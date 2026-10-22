"""Week 9: the L4 regeneration service for the platform (Kashish's contract).

    set RINGSHIELD_XAI_TOKEN=<token>
    python -m explainability.serve --tenants 12,20 --data-root <Ring-Shield checkout> --port 8765

The platform never imports research code; it calls this local HTTP service when an analyst records a partial verdict.

  GET  /health        no token. {"status": "ok", "tenants_ready": [12, 20], "explainer_version": "..."}
  POST /regenerate    "Authorization: Bearer <token>". Body {"tenant_id", "ring_id", "excluded_members": [...],
                      "excluded_edges": [...]} -> one explanation row as a JSON object: the explanations parquet
                      columns, `evidence_summary` and `provenance` as JSON strings, NaN as null, plus a top-level
                      `explainer_version` (the platform's validator needs it; equal to the provenance one).
  errors              401 {"error": "Unauthorized"}; 400 {"error": "BadRequest", "message"}; 404 {"error":
                      "RingNotFound"} (also for a tenant this service does not serve); 422 {"error": "InvalidEdit",
                      "message"} for nothing excluded, an id not in the ring, fewer than two accounts or no seed /
                      expanded transaction left; 500 {"error": "InternalError"} with no detail.

Rules: listens on 127.0.0.1 only; refuses to start without RINGSHIELD_XAI_TOKEN; compares the token in constant time;
never logs the token, request bodies or explanation text (one line per request: method, path, status, milliseconds).
Requests are handled one at a time (the tenant explainers are shared state; a regenerate takes about half a second).
Every tenant is loaded before the port opens, so /health answers only once all tenants are ready.

--data-root must be the Ring-Shield checkout this code runs from: the research code (ringshield/) finds its data
relative to its own folder, so a separate data folder would be only half used. The service refuses any other path.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from explainability import contract_io

TOKEN_ENV = "RINGSHIELD_XAI_TOKEN"
MAX_BODY = 1_000_000


class BadRequest(ValueError):
    pass


def _id_list(body: dict, key: str) -> list[int]:
    v = body.get(key)
    if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        raise BadRequest(f"{key} must be a list of integer ids")
    return sorted(set(v))


def parse_request(raw: bytes) -> dict:
    """The /regenerate body -> {tenant_id, ring_id, excluded_members, excluded_edges}; BadRequest if malformed."""
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BadRequest("the body is not JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("the body must be a JSON object")
    tenant, ring = body.get("tenant_id"), body.get("ring_id")
    if not isinstance(tenant, int) or isinstance(tenant, bool):
        raise BadRequest("tenant_id must be an integer")
    if not isinstance(ring, str) or not ring:
        raise BadRequest("ring_id must be a non-empty string")
    return {"tenant_id": tenant, "ring_id": ring, "excluded_members": _id_list(body, "excluded_members"),
            "excluded_edges": _id_list(body, "excluded_edges")}


def regenerate_row(explainers: dict, req: dict) -> dict:
    """One explanation row for the platform: the tenant's regenerate, plus the top-level explainer_version."""
    from explainability.api import RingNotFound
    te = explainers.get(req["tenant_id"])
    if te is None:
        raise RingNotFound(f"no ring {req['ring_id']!r} for tenant {req['tenant_id']}")
    row = te.regenerate(req["ring_id"], req["tenant_id"], excluded_members=req["excluded_members"],
                        excluded_edges=req["excluded_edges"])
    row["explainer_version"] = json.loads(row["provenance"])["explainer_version"]
    return row


def make_server(explainers: dict, token: str, port: int = 0, explainer_version: str = "",
                log=sys.stderr) -> HTTPServer:
    """The HTTP server over already-built tenant explainers {tenant_id: TenantExplainer}."""
    from explainability.api import InvalidEdit, RingNotFound
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} is not set")
    expected = token.encode("utf-8")
    ready = sorted(explainers)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
            self._status = status

        def _authorised(self) -> bool:
            h = self.headers.get("Authorization", "")
            given = h[len("Bearer "):].encode("utf-8") if h.startswith("Bearer ") else b""
            return hmac.compare_digest(given, expected)

        def do_GET(self) -> None:
            self._t0 = time.perf_counter()
            if self.path == "/health":
                self._send(200, {"status": "ok", "tenants_ready": ready, "explainer_version": explainer_version})
            else:
                self._send(404, {"error": "NotFound"})

        def do_POST(self) -> None:
            self._t0 = time.perf_counter()
            if self.path != "/regenerate":
                self._send(404, {"error": "NotFound"})
                return
            if not self._authorised():
                self._send(401, {"error": "Unauthorized"})
                return
            try:
                n = int(self.headers.get("Content-Length", ""))
                if not 0 < n <= MAX_BODY:
                    raise ValueError
                req = parse_request(self.rfile.read(n))
            except ValueError as e:                    # BadRequest is a ValueError too
                self._send(400, {"error": "BadRequest", "message": str(e) if isinstance(e, BadRequest)
                                 else "Content-Length must be between 1 and 1,000,000"})
                return
            try:
                row = regenerate_row(explainers, req)
            except RingNotFound:
                self._send(404, {"error": "RingNotFound"})
                return
            except InvalidEdit as e:
                self._send(422, {"error": "InvalidEdit", "message": str(e)})
                return
            except Exception as e:                     # no detail to the caller; the type only in our log
                print(f"regenerate failed: {type(e).__name__}", file=log, flush=True)
                self._send(500, {"error": "InternalError"})
                return
            self._send(200, row)

        def log_request(self, code="-", size="-") -> None:   # called by send_response: say nothing yet
            pass

        def log_message(self, format, *args) -> None:        # no paths with bodies, headers or tokens
            pass

        def finish(self) -> None:
            super().finish()
            if hasattr(self, "_status"):
                ms = (time.perf_counter() - self._t0) * 1000
                print(f"{self.command} {self.path.split('?')[0]} {self._status} {ms:.0f} ms", file=log, flush=True)

    return HTTPServer(("127.0.0.1", int(port)), Handler)


def check_data_root(data_root) -> Path:
    root = Path(data_root).resolve()
    if root != contract_io.REPO_ROOT.resolve():
        raise SystemExit(f"--data-root must be the Ring-Shield checkout this code runs from "
                         f"({contract_io.REPO_ROOT.resolve()}); got {root}. The research code finds its data relative "
                         f"to its own folder, so run the service from the checkout that holds the data.")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenants", required=True, help="comma-separated bank ids, e.g. 12,20")
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--port-file", default=None, help="write the bound port here once ready (for tests, port 0)")
    a = ap.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print(f"{TOKEN_ENV} is not set; refusing to start", file=sys.stderr)
        return 2
    try:
        tenants = sorted({int(t) for t in a.tenants.split(",") if t.strip()})
    except ValueError:
        print("--tenants must be comma-separated integers", file=sys.stderr)
        return 2
    check_data_root(a.data_root)
    from explainability.tenant import TenantExplainer
    cfg = contract_io.load_config()
    unknown = sorted(set(tenants) - set(cfg["tenants"]["banks"]))
    if not tenants or unknown:
        print(f"no tenant inputs configured for {unknown or tenants}; configured: {cfg['tenants']['banks']}",
              file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    explainers = {}
    for t in tenants:
        explainers[t] = TenantExplainer(cfg, t)
        print(f"tenant {t} loaded ({len(explainers[t].rings)} rings)", file=sys.stderr, flush=True)
    server = make_server(explainers, token, a.port, cfg["explainer_version"])
    port = server.server_address[1]
    if a.port_file:
        Path(a.port_file).write_text(str(port), encoding="ascii")
    print(f"L4 service ready on 127.0.0.1:{port}: tenants {tenants}, explainer {cfg['explainer_version']}, "
          f"start-up {time.perf_counter() - t0:.1f} s", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
