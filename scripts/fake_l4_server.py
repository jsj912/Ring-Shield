"""Local DEMO STUB L4 regeneration service; it does not produce research output."""

from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import sys
from threading import Event
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = REPO_ROOT / "platform"
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.explanation_validation import normalize_regenerated_row  # noqa: E402
from settings import load_platform_config  # noqa: E402


def _response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def create_server(*, port: int, token: str, config: dict[str, Any],
                  explainer_version: str = "0.5.0-review") -> HTTPServer:
    if not 0 <= int(port) <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if not token:
        raise RuntimeError("RINGSHIELD_XAI_TOKEN is required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                _response(self, 200, {"status": "ok", "service": "DEMO STUB L4"})
            else:
                _response(self, 404, {"message": "not found"})

        def do_POST(self) -> None:
            if self.path != "/regenerate":
                _response(self, 404, {"message": "not found"})
                return
            authorization = self.headers.get("Authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
            if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                _response(self, 401, {"message": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1_000_000:
                    raise ValueError
                request = json.loads(self.rfile.read(length))
                tenant_id = request["tenant_id"]
                ring_id = request["ring_id"]
                excluded_members = request["excluded_members"]
                excluded_edges = request["excluded_edges"]
                if (not isinstance(tenant_id, int) or isinstance(tenant_id, bool)
                        or not isinstance(ring_id, str)
                        or not isinstance(excluded_members, list)
                        or not isinstance(excluded_edges, list)):
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                _response(self, 400, {"message": "invalid regeneration request"})
                return

            provenance = {
                "scope": "tenant", "tenant_id": tenant_id,
                "feature_scope": "tenant_view",
                "fx_rates_sha256": config.get("fx_rates_sha256"),
                "rings_schema_version": (config.get("l4") or {}).get("rings_schema_version"),
                "explainer_version": explainer_version, "regenerated": True,
                "excluded_members": excluded_members, "excluded_edges": excluded_edges,
            }
            row = {
                "tenant_id": tenant_id, "ring_id": ring_id,
                "explainer_version": explainer_version,
                "edge_weights": [], "account_weights": [], "feature_weights": [],
                "narrative": "DEMO STUB explanation; this is not real research output.",
                "evidence_summary": {"source": "DEMO STUB"}, "latency_ms": 1,
                "provenance": provenance,
            }
            try:
                normalize_regenerated_row(
                    row, tenant_id=tenant_id, ring_id=ring_id,
                    excluded_members=excluded_members, excluded_edges=excluded_edges,
                    config=config,
                )
            except Exception:
                _response(self, 400, {"message": "generated demo response failed validation"})
                return
            _response(self, 200, row)

        def log_message(self, _format: str, *_args: Any) -> None:
            # Request paths, headers, bodies, and tokens are intentionally not logged.
            return

    return HTTPServer(("127.0.0.1", int(port)), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("RINGSHIELD_FAKE_L4_PORT", "8765")))
    parser.add_argument("--port-file", type=Path)
    parser.add_argument("--explainer-version", default="0.5.0-review")
    args = parser.parse_args(argv)
    token = os.environ.get("RINGSHIELD_XAI_TOKEN", "")
    config = load_platform_config()
    server = create_server(port=args.port, token=token, config=config,
                           explainer_version=args.explainer_version)
    stopping = Event()

    def request_stop(_signum, _frame):
        stopping.set()

    old_int = signal.signal(signal.SIGINT, request_stop)
    old_term = signal.signal(signal.SIGTERM, request_stop)
    server.timeout = 0.25
    try:
        if args.port_file:
            args.port_file.write_text(str(server.server_port), encoding="ascii")
        print(f"DEMO STUB L4 listening on 127.0.0.1:{server.server_port}", flush=True)
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
