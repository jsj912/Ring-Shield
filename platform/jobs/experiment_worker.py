"""Run an allow-listed platform experiment as a separate process."""

from __future__ import annotations

import json
import sys
import re
import csv
import math
from datetime import datetime, timezone
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from api.request_context import log_event  # noqa: E402


def _state_path(job_id: str) -> Path:
    if len(job_id) != 32 or not job_id.isalnum():
        raise ValueError("invalid experiment job ID")
    return PLATFORM_ROOT / "out" / "experiments" / f"{job_id}.json"


def _write_state(path: Path, value: dict) -> None:
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


R10_SCRIPT = REPO_ROOT / "evaluation" / "r10_registered.py"
R10_RESULT = REPO_ROOT / "results" / "tables" / "r10_registered.json"
R10_POST_HOC = REPO_ROOT / "experiments" / "R10" / "results.json"
R10_POST_HOC_LABEL = "post-hoc, descriptive"
_R10_ROWS = ("primary", "pooled_scores", "budget_matched", "robustness")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def r10_registered_results(path: Path = None, post_hoc_path: Path = None) -> dict:
    """The registered R10 result (docs/TENANT_SIZES.md) as the administrator view reads it: the
    pooled-across-tenants rows with CIs, the descriptive per-tenant rows and the cross-bank
    summary. Only aggregate recalls and counts; no ring ids, accounts or patterns. The post-hoc
    extras ride along under "post_hoc" when they exist (the repo's file unless `path` is given)."""
    payload = json.loads((path or R10_RESULT).read_text(encoding="utf-8"))
    rows = {}
    for name in _R10_ROWS:
        row = payload["rows"][name]
        intervals = {}
        for part in ("tenant", "pooled", "difference"):
            interval = row[part]
            if not all(_finite(interval[key]) for key in ("value", "low", "high")):
                raise ValueError("R10 result contains an invalid metric")
            intervals[part] = {key: interval[key] for key in ("value", "low", "high")}
        rows[name] = {"tenants": [int(t) for t in row["tenants"]], "n_pairs": int(row["n_pairs"]),
                      "n_rings": int(row["n_rings"]), **intervals}
    per_tenant = []
    for item in payload["per_tenant"]:
        if item["row"] not in rows or not all(_finite(item[k]) for k in ("tenant_recall", "pooled_recall")):
            raise ValueError("R10 result contains an invalid per-tenant row")
        per_tenant.append({key: item[key] for key in ("row", "tenant_id", "n_rings",
                                                      "tenant_recall", "pooled_recall")})
    result = {
        "created_utc": payload["created_utc"], "seeds": payload["seeds"],
        "window_days": payload["window"]["days"], "scope": payload["scope"],
        "jaccard": payload["jaccard"], "n_boot": payload["n_boot"],
        "n_in_scope_rings": payload["n_in_scope_rings"], "cross_bank_rings": payload["cross_bank_rings"],
        "cross_bank_fraction": payload["cross_bank_fraction"],
        "mean_banks_per_ring": payload["mean_banks_per_ring"],
        "rows": rows, "per_tenant": per_tenant,
    }
    if post_hoc_path is not None or path is None:
        post_hoc = r10_post_hoc_results(post_hoc_path)
        if post_hoc is not None:
            result["post_hoc"] = post_hoc
    return result


def _post_hoc_interval(part: dict) -> dict:
    if not all(_finite(part[key]) for key in ("value", "low", "high")) or not isinstance(part["n"], int):
        raise ValueError("R10 post-hoc result contains an invalid metric")
    return {key: part[key] for key in ("value", "low", "high", "n")}


def r10_post_hoc_results(path: Path = None) -> dict | None:
    """The R10 extras computed after the registered result (evaluation/r10_posthoc.py), labelled
    post-hoc and descriptive: member coverage, (a) vs (b), and per-tenant counts of in-scope rings
    with a visible laundering edge. None when they have not been computed. Aggregates only."""
    path = path or R10_POST_HOC
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("label") != R10_POST_HOC_LABEL:
        raise ValueError("R10 post-hoc result is not labelled post-hoc, descriptive")
    coverage = {name: {side: _post_hoc_interval(payload["rows"][name][f"member_coverage_{side}"])
                       for side in ("tenant", "pooled")} for name in _R10_ROWS}
    ab = payload["rows"]["a_vs_b"]
    per_tenant = []
    for item in payload["per_tenant"]:
        values = {side: item[f"member_coverage_{side}"] for side in ("tenant", "pooled")}
        if item["row"] not in _R10_ROWS or not all(v is None or _finite(v) for v in values.values()):
            raise ValueError("R10 post-hoc result contains an invalid per-tenant row")
        per_tenant.append({"row": item["row"], "tenant_id": int(item["tenant_id"]),
                           "member_coverage_tenant": values["tenant"], "member_coverage_pooled": values["pooled"],
                           "n_matched_tenant": int(item["n_matched_tenant"]),
                           "n_matched_pooled": int(item["n_matched_pooled"])})
    visible = [{"tenant_id": int(item["tenant_id"]), "sets": [str(s) for s in item["sets"]],
                "in_scope_rings_with_visible_laundering_edge": int(item["in_scope_rings_with_visible_laundering_edge"]),
                "tenant_ring_pairs": int(item["tenant_ring_pairs"])} for item in payload["visible_laundering"]]
    return {
        "label": R10_POST_HOC_LABEL, "created_utc": payload["created_utc"],
        "registered_commit": payload["registered_result"]["commit"],
        "registered_reproduced": bool(payload["registered_result"]["reproduced"]),
        "ring_sets_reused": int(payload["ring_sets"]["n"]),
        "ring_sets_manifest_sha256": str(payload["ring_sets"]["manifest_sha256"]),
        "member_coverage": coverage,
        "a_vs_b": {"tenants": [int(t) for t in ab["tenants"]], "n_pairs": int(ab["n_pairs"]),
                   "n_rings": int(ab["n_rings"]), "a": _post_hoc_interval(ab["a"]),
                   "b": _post_hoc_interval(ab["b"]), "difference": _post_hoc_interval(ab["difference"])},
        "per_tenant": per_tenant, "visible_laundering": visible,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "r10":
        raise SystemExit("usage: python -m jobs.experiment_worker r10 JOB_ID")
    job_id = args[1]
    state_path = _state_path(job_id)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("experiment job state is missing or invalid") from exc
    state.update(status="running", message=None)
    _write_state(state_path, state)
    log_event("experiment.started", status="running", job_id=job_id)
    try:
        import subprocess

        # The registered R10 (evaluation/r10_registered.py); ring sets are cached, so a rerun
        # recomputes the bootstrap from the cached runs.
        subprocess.run([sys.executable, str(R10_SCRIPT)], cwd=str(REPO_ROOT), check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        clean_result = r10_registered_results()
        state.update(status="succeeded", results=clean_result)
        _write_state(state_path, state)
        log_event("experiment.finished", status="succeeded", job_id=job_id)
    except Exception as exc:
        message = str(exc)
        message = re.sub(r"(?i)\b[A-Z]:\\(?:[^\\\s]+\\)*[^\\\s]*", "<local-file>", message)
        message = re.sub(r"(?<![\w])/(?:[^/\s]+/)*[^/\s]+", "<local-file>", message)
        state.update(status="failed", message=f"{type(exc).__name__}: {message}")
        _write_state(state_path, state)
        log_event("experiment.finished", status="failed", job_id=job_id)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
