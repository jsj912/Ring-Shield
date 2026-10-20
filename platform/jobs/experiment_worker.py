"""Run an allow-listed platform experiment as a separate process."""

from __future__ import annotations

import json
import sys
import re
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
        from experiments.r10_tenant_vs_pooled import run_experiment
        from settings import configured_path, load_platform_config

        config = load_platform_config()
        truth_value = config["l6"]["retrain"].get("truth_parquet")
        if not truth_value:
            raise RuntimeError("platform config requires l6.retrain.truth_parquet; path is unavailable")
        truth_path = Path(truth_value)
        if not truth_path.is_absolute():
            truth_path = REPO_ROOT / truth_path
        result = run_experiment(
            truth_path=truth_path,
            account_map=configured_path(config, "account_map"),
        )
        clean_result = {key: Path(value).resolve().relative_to(REPO_ROOT).as_posix()
                        for key, value in result.items() if key in {"csv", "markdown", "run_json"}}
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
