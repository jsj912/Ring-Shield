"""A stand-in for the RingShield API that serves the fixtures folder (NFR-D55).

It answers the routes the dashboard calls with the API's own field names and status codes,
including 401 for a bad or missing token and 403 when a bank user asks for another tenant.
It is test scaffolding for the API, not part of the dashboard's logic: anything it selects or
pages here, the real API does server-side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

FIXTURE_TOKEN_PREFIX = "fixture-token-"


class FixtureAPI:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.users = self._load("users.json")
        self.tenants = self._load("tenants.json")
        self.rings = {}
        for path in sorted((self.root / "rings").glob("*.json")):
            ring = json.loads(path.read_text(encoding="utf-8"))
            self.rings[(ring["tenant_id"], ring["summary"]["ring_id"])] = ring
        self.request_count = 0
        self.models = {k: v for k, v in self._load("models.json", {}).items() if not k.startswith("_")}
        self.retrain_polls: dict[str, int] = {}
        self.r10_jobs: dict[str, int] = {}
        self.jobs: dict[str, dict] = {}          # regeneration jobs started by partial verdicts
        self.verdict_posts = 0

    def _load(self, name: str, default=None):
        path = self.root / name
        if not path.is_file():
            return default if default is not None else []
        return json.loads(path.read_text(encoding="utf-8"))

    def _response(self, status: int, payload=None) -> httpx.Response:
        self.request_count += 1
        request_id = f"fixture-{self.request_count:05d}"
        if isinstance(payload, dict) and status >= 400:
            payload = {**payload, "request_id": request_id}
        return httpx.Response(status, json=payload, headers={"X-Request-ID": request_id},
                              request=httpx.Request("GET", "http://fixture.local"))

    def _error(self, status: int, error: str, message: str) -> httpx.Response:
        """The API's error body: error_code, message, request_id (platform/api/errors.py)."""
        code = {401: "AUTHENTICATION_REQUIRED", 403: "NOT_PERMITTED", 404: "NOT_FOUND",
                422: "VALIDATION_ERROR"}.get(status, "REQUEST_FAILED")
        return self._response(status, {"error_code": code, "message": message})

    def _session_user(self, headers: dict) -> dict | None:
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if not token.startswith(FIXTURE_TOKEN_PREFIX):
            return None
        user_id = token.removeprefix(FIXTURE_TOKEN_PREFIX)
        return next((u for u in self.users if str(u["user_id"]) == user_id), None)

    def handle(self, method: str, path: str, *, headers: dict | None = None,
               body: dict | None = None, params=None) -> httpx.Response:
        method = method.upper()
        if method == "POST" and path == "/auth/login":
            return self._login(body or {})
        user = self._session_user(headers or {})
        if user is None:
            return self._error(401, "Unauthorized", "Authentication required")
        tenant_match = re.match(r"^/tenants/(\d+)(/.*)?$", path)
        if tenant_match and user["role"] != "admin" and int(tenant_match.group(1)) != user["tenant_id"]:
            return self._error(403, "Forbidden", "Not permitted")
        if path.startswith("/admin/") and user["role"] != "admin":
            return self._error(403, "Forbidden", "Not permitted")
        if method == "GET" and path == "/admin/tenants":
            return self._response(200, self.tenants)
        if path.startswith("/admin/experiments/tenant-vs-pooled"):
            return self._r10(method, path)
        if tenant_match:
            tenant_id, rest = int(tenant_match.group(1)), tenant_match.group(2) or ""
            if method == "GET" and rest == "/rings":
                return self._ring_page(tenant_id, _param_dict(params))
            if rest == "/models" or rest.startswith("/retrain"):
                return self._models(tenant_id, method, rest, user)
            if method == "GET" and rest == "/verdicts":
                return self._verdict_page(tenant_id, _param_dict(params))
            if method == "POST":
                return self._post(tenant_id, rest, user, body or {})
            job_match = re.match(r"^/rings/([^/]+)/explanation/jobs/([^/]+)$", rest)
            if method == "GET" and job_match:
                return self._job(tenant_id, job_match.group(1), job_match.group(2))
            ring_match = re.match(r"^/rings/([^/]+)(/subgraph|/evidence|/explanation|/verdicts)?$", rest)
            if method == "GET" and ring_match:
                ring = self.rings.get((tenant_id, ring_match.group(1)))
                if ring is None:
                    return self._error(404, "NotFound", "Ring not found")
                part = ring_match.group(2)
                if part == "/verdicts":
                    return self._response(200, {"items": ring.get("verdicts", []), "next_before_id": None})
                body = {None: ring["detail"], "/subgraph": ring.get("subgraph"),
                        "/evidence": ring.get("evidence"), "/explanation": ring.get("explanation")}[part]
                if body is None:
                    return self._error(404, "NotFound", "Not found")
                return self._response(200, body)
        return self._error(404, "NotFound", f"No fixture for {method} {path}")

    def _ring_page(self, tenant_id: int, params: dict) -> httpx.Response:
        """The API's GET /tenants/{t}/rings over the fixtures: filters, sort, cursor and counts."""
        tenant_rings = [ring["summary"] for (tenant, _), ring in self.rings.items() if tenant == tenant_id]
        statuses = params.get("status") or ["open"]
        types = params.get("topology_type") or []
        min_conf = float(_one(params, "min_conf") or 0)
        cross_only = (_one(params, "cross_bank_only") or "false") == "true"
        after, before = _one(params, "start_after"), _one(params, "start_before")
        query = (_one(params, "q") or "").strip()
        rows = [r for r in tenant_rings
                if r["status"] in statuses and (not types or r["topology_type"] in types)
                and r["confidence"] >= min_conf and (not cross_only or r["cross_bank"])
                and (not after or r["start_time"] >= after[:19]) and (not before or r["start_time"] <= before[:19])
                and (not query or query == r["ring_id"]
                     or query in {str(a) for a in self.rings[(tenant_id, r["ring_id"])]["detail"]["member_accounts"]})]
        sort = _one(params, "sort") or "confidence"
        key = {"confidence": "confidence", "total_amount": "total_amount", "start_time": "start_time",
               "members": "n_members"}.get(sort, "confidence")
        rows.sort(key=lambda r: (r[key] is None, r[key] or 0, r["ring_id"]),
                  reverse=(_one(params, "order") or "desc") == "desc")
        offset = int(_one(params, "cursor") or 0)
        limit = int(_one(params, "limit") or 50)
        page = rows[offset:offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(rows) else None
        return self._response(200, {"items": page, "next_cursor": next_cursor, "total": len(rows),
                                     "tenant_total": len(tenant_rings)})

    def _r10(self, method: str, path: str) -> httpx.Response:
        """The admin R10 routes: the latest registered result, and a run that finishes on its
        second poll with the same result (admin.py, jobs/experiment_worker.py)."""
        result = {k: v for k, v in self._load("r10_result.json", {}).items() if not k.startswith("_")}
        if method == "GET" and path.endswith("/latest"):
            return self._response(200, {"results": result}) if result else self._error(404, "NotFound", "No R10 result")
        if method == "POST":
            job_id = f"{len(self.r10_jobs) + 1:032d}"
            self.r10_jobs[job_id] = 0
            return self._response(202, {"job_id": job_id, "status": "queued", "message": None, "results": None})
        job_id = path.rsplit("/", 1)[-1]
        if job_id not in self.r10_jobs:
            return self._error(404, "NotFound", "Experiment job not found")
        self.r10_jobs[job_id] += 1
        if self.r10_jobs[job_id] < 2:
            return self._response(200, {"job_id": job_id, "status": "running", "message": None, "results": None})
        return self._response(200, {"job_id": job_id, "status": "succeeded", "message": None, "results": result})

    def _models(self, tenant_id: int, method: str, rest: str, user: dict) -> httpx.Response:
        """GET /models, and the supervisor-only retrain routes (operations.py)."""
        store = self.models.setdefault(str(tenant_id), {"versions": [], "runs": []})
        if rest == "/models" and method == "GET":
            items = [{k: v for k, v in item.items()} for item in store["versions"]]
            return self._response(200, {"items": items, "next_before_id": None,
                                         "active_model_id": "gine_causal", "active_seed": 1})
        if user["role"] != "supervisor":
            return self._error(403, "Forbidden", "Only a tenant supervisor can access retraining")
        if rest == "/retrain" and method == "POST":
            run_id = f"fixture-run-{len(store['runs']) + 1}"
            store["runs"].insert(0, {"run_id": run_id, "status": "running", "started_at": "2026-10-24T12:00:00Z",
                                     "finished_at": None, "model_version_id": None,
                                     "log_lines": ["labels: 7 verdicts"]})
            return self._response(202, {"run_id": run_id})
        run_match = re.match(r"^/retrain/([^/]+)$", rest)
        if method == "GET" and run_match:
            run = next((r for r in store["runs"] if r["run_id"] == run_match.group(1)), None)
            if run is None:
                return self._error(404, "NotFound", "Retrain run not found")
            if run["status"] == "running":
                self._advance_run(store, run)
            return self._response(200, {**{k: run[k] for k in ("run_id", "status", "model_version_id",
                                                                "log_lines")},
                                        "candidates": self._candidates(store, run["run_id"])})
        if method == "GET" and rest == "/retrain":
            return self._response(200, {"items": [
                {**{k: run[k] for k in ("run_id", "status", "started_at", "finished_at", "model_version_id")},
                 "candidates": self._candidates(store, run["run_id"])} for run in store["runs"]]})
        return self._error(404, "NotFound", f"No fixture for {method} {rest}")

    def _advance_run(self, store: dict, run: dict) -> None:
        """Polls move a new run along: the first poll adds a log line, the second finishes it with
        both candidates refused by the gate, as R11 found."""
        polls = self.retrain_polls[run["run_id"]] = self.retrain_polls.get(run["run_id"], 0) + 1
        if polls == 1:
            run["log_lines"].append("expansion: training")
            return
        next_id = max((v["model_version_id"] for v in store["versions"]), default=0) + 1
        for offset, (component, f1) in enumerate((("expansion", 0.6601), ("affinity", 0.6574))):
            reason = f"holdout ring_f1 {f1:.4f} < current 0.6883 - 0.005"
            store["versions"].insert(0, {
                "model_version_id": next_id + offset, "component": component,
                "version_tag": f"v0.3.1-{run['run_id'][-8:]}", "trained_at": "2026-10-24T12:20:00Z",
                "train_label_count": 7, "holdout_ring_f1": f1, "promoted": False, "shared": False,
                "gate_reason": reason, "retrain_run_id": run["run_id"]})
            run["log_lines"].append(f"{component}: {reason}")
        run.update(status="succeeded", finished_at="2026-10-24T12:30:00Z")

    @staticmethod
    def _candidates(store: dict, run_id: str) -> list[dict]:
        return [{k: v[k] for k in ("model_version_id", "component", "holdout_ring_f1", "promoted", "gate_reason")}
                for v in sorted(store["versions"], key=lambda v: v["model_version_id"])
                if v.get("retrain_run_id") == run_id]

    def _verdict_page(self, tenant_id: int, params: dict) -> httpx.Response:
        """GET /tenants/{t}/verdicts: filters, newest first, counts, analysts and an offset cursor."""
        every = [v for (tenant, _), ring in self.rings.items() if tenant == tenant_id for v in ring["verdicts"]]
        kinds = params.get("verdict") or []
        analyst = _one(params, "analyst_id")
        simulated = _one(params, "simulated")
        since, until = _one(params, "since"), _one(params, "until")
        rows = [v for v in every
                if (not kinds or v["verdict"] in kinds)
                and (analyst is None or str(v["user_id"]) == analyst)
                and (simulated is None or v["is_simulated"] == (simulated == "true"))
                and (not since or v["created_at"][:19] >= since[:19])
                and (not until or v["created_at"][:19] <= until[:19])]
        rows.sort(key=lambda v: (v["created_at"], v["verdict_id"]), reverse=True)
        offset, limit = int(_one(params, "cursor") or 0), int(_one(params, "limit") or 50)
        page = rows[offset:offset + limit]
        return self._response(200, {
            "items": [{"verdict_id": v["verdict_id"], "ring_id": v["ring_id"], "verdict": v["verdict"],
                       "analyst_id": v["user_id"], "analyst_label": f"Analyst {v['user_id']}",
                       "is_simulated": v["is_simulated"],
                       "note_excerpt": v["note"][:160] if v["note"] else None,
                       "created_at": v["created_at"]} for v in page],
            "next_cursor": str(offset + limit) if offset + limit < len(rows) else None,
            "total": len(rows),
            "counts": {name: sum(1 for v in rows if v["verdict"] == kind)
                       for name, kind in (("confirmed", "confirm"), ("rejected", "reject"),
                                          ("partial", "partial"))},
            "analysts": [{"analyst_id": uid, "analyst_label": f"Analyst {uid}"}
                         for uid in sorted({v["user_id"] for v in every})],
        })

    def _post(self, tenant_id: int, rest: str, user: dict, body: dict) -> httpx.Response:
        """POST verdicts and regenerate, as platform/api/routers/verdicts.py answers them."""
        match = re.match(r"^/rings/([^/]+)/(verdicts|explanation/regenerate)$", rest)
        ring = self.rings.get((tenant_id, match.group(1))) if match else None
        if ring is None:
            return self._error(404, "NotFound", "Ring not found")
        if user["role"] not in {"analyst", "supervisor"}:
            return self._error(403, "Forbidden", "Not permitted")
        if match.group(2) == "explanation/regenerate":
            verdict = next((v for v in ring["verdicts"] if v["verdict_id"] == body.get("verdict_id")), None)
            if verdict is None or verdict["verdict"] != "partial":
                return self._error(422, "Invalid", "A partial verdict is required")
            job = self._start_job(tenant_id, ring, verdict)
            return self._response(202, {k: job[k] for k in ("job_id", "status", "result_revision",
                                                             "error", "created_at", "finished_at")})
        self.verdict_posts += 1
        kind = body.get("verdict")
        if kind not in {"confirm", "reject", "partial"}:
            return self._error(422, "Invalid", "verdict must be confirm, reject or partial")
        if kind == "partial" and not (body.get("note") or "").strip():
            return self._error(422, "Invalid", "A note is required for a partial verdict")
        if kind == "partial" and not body.get("corrected_members"):
            return self._error(422, "Invalid", "At least one corrected member must remain")
        if ring["summary"]["status"] != "open":
            return self._error(409, "Conflict", "This ring already has a verdict")
        verdict = {
            "verdict_id": 900000 + self.verdict_posts, "ring_id": ring["summary"]["ring_id"],
            "user_id": user["user_id"], "user_name": user["email"], "verdict": kind,
            "corrected_members": body.get("corrected_members") or [],
            "corrected_edges": body.get("corrected_edges") or [],
            "note": body.get("note"), "is_simulated": False, "created_at": "2022-09-10T12:00:00Z",
        }
        ring["verdicts"].insert(0, verdict)
        status = {"confirm": "confirmed", "reject": "rejected", "partial": "partial"}[kind]
        ring["summary"]["status"] = ring["detail"]["status"] = status
        regeneration = None
        if kind == "partial":
            regeneration = {"status": "queued", "job_id": self._start_job(tenant_id, ring, verdict)["job_id"]}
        return self._response(201, {**verdict, "regeneration": regeneration})

    def _start_job(self, tenant_id: int, ring: dict, verdict: dict) -> dict:
        job = {"job_id": f"fixture-job-{len(self.jobs) + 1}", "status": "queued", "result_revision": None,
               "error": None, "created_at": "2022-09-10T12:00:00Z", "finished_at": None,
               "tenant_id": tenant_id, "ring_id": ring["summary"]["ring_id"], "verdict": verdict}
        self.jobs[job["job_id"]] = job
        return job

    def _job(self, tenant_id: int, ring_id: str, job_id: str) -> httpx.Response:
        """The first poll finds the job finished: the explanation and subgraph are regenerated
        over the corrected members, as the L4 worker writes a new revision."""
        job = self.jobs.get(job_id)
        if job is None or (job["tenant_id"], job["ring_id"]) != (tenant_id, ring_id):
            return self._error(404, "NotFound", "Job not found")
        if job["status"] == "queued":
            self._regenerate(self.rings[(tenant_id, ring_id)], job["verdict"])
            job.update(status="succeeded", finished_at="2022-09-10T12:00:05Z",
                       result_revision=self.rings[(tenant_id, ring_id)]["explanation"]["revision"])
        return self._response(200, {k: job[k] for k in ("job_id", "status", "result_revision",
                                                         "error", "created_at", "finished_at")})

    @staticmethod
    def _regenerate(ring: dict, verdict: dict) -> None:
        members = set(verdict["corrected_members"])
        edges = set(verdict["corrected_edges"])
        explanation = ring["explanation"]
        explanation.update(
            revision=explanation["revision"] + 1, regenerated=True,
            narrative=f"Regenerated after the analyst's correction. {explanation['narrative']}",
            account_weights=[a for a in explanation["account_weights"] if a["account_id"] in members],
            edge_weights=[e for e in explanation["edge_weights"] if e["edge_id"] in edges])
        subgraph = ring.get("subgraph")
        if subgraph:
            subgraph["nodes"] = [n for n in subgraph["nodes"] if n["account_id"] in members]
            subgraph["edges"] = [e for e in subgraph["edges"] if e["edge_id"] in edges
                                 and e["from_id"] in members and e["to_id"] in members]
            subgraph["n_accounts"] = len(subgraph["nodes"])

    def _login(self, body: dict) -> httpx.Response:
        user = next((u for u in self.users if u["email"] == body.get("email")
                     and u["password"] == body.get("password")), None)
        if user is None:
            # one generic answer whether the email or the password was wrong (FR-D02)
            return self._error(401, "Unauthorized", "Incorrect email or password")
        return self._response(200, {
            "user_id": user["user_id"], "tenant_id": user["tenant_id"],
            "tenant_name": user["tenant_name"], "role": user["role"],
            "token": f"{FIXTURE_TOKEN_PREFIX}{user['user_id']}",
            "expires_at": "2099-01-01T00:00:00Z",
        })


def _param_dict(params) -> dict[str, list[str]]:
    """httpx-style params (a dict or a list of pairs) as {name: [values]}."""
    out: dict[str, list[str]] = {}
    items = params.items() if isinstance(params, dict) else (params or [])
    for name, value in items:
        out.setdefault(name, []).extend(value if isinstance(value, list) else [value])
    return out


def _one(params: dict, name: str):
    values = params.get(name) or []
    return values[0] if values else None
