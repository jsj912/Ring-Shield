"""Inject a held-out pattern shift and report detector/retraining response."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml
from sqlalchemy import func, select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from adapters import research_cli
from adapters.ground_truth import load_window_truth_details
from api.identity import Principal
from db.models import Ring, Transaction, User
from db.session import db_session
from experiments.common import ExperimentInputError, write_csv_and_markdown, write_run_manifest
from jobs import load_contract
from jobs.build_tenant_rings import build_tenant_rings
from jobs.drift_monitor import DriftStream, daily_statistics, persist_events, read_daily_scores
from jobs.retrain import run_retrain_job
from jobs.simulate_verdicts import simulate_cycle
from settings import configured_path, load_platform_config

DAY_ZERO = 10
SECONDS_PER_DAY = 86_400
FIRST_TEST_DAY = 8
LAST_TEST_DAY = 17
PATTERN_NAMES = {"BIPARTITE", "CYCLE", "FAN_IN", "FAN_OUT", "SCATTER_GATHER", "STACK"}


def _ring_members(path: Path) -> list[set[int]]:
    table = pq.read_table(path, columns=["members"])
    return [set(map(int, values or [])) for values in table["members"].to_pylist()]


def _score_log(path: Path) -> dict:
    log_path = Path(str(path) + ".log.json")
    try:
        return json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentInputError(f"scored-edge run log is missing or invalid: {log_path}") from exc


def prepare_shifted_scores(*, scores_path: Path, truth_path: Path, pattern: str,
                           output_dir: Path) -> dict:
    """Remove first-half target-pattern edges, then move those same rows to half two."""
    if pattern not in PATTERN_NAMES:
        raise ValueError(f"unsupported R12 pattern {pattern!r}")
    truth, patterns, truth_rows = load_window_truth_details(
        truth_path, window_name="whole", scope="test_visible",
    )
    pattern_ids = {ring_id for ring_id, name in patterns.items() if str(name).upper() == pattern}
    if not pattern_ids:
        raise ExperimentInputError(f"configured R12 pattern has no truth rings in test window: {pattern}")
    required = {"from_id", "to_id", "timestamp_int", "pattern_type", "ring_id"}
    if not required <= set(truth_rows.columns):
        raise ExperimentInputError(f"truth adapter omitted transaction fields required for R12 pattern {pattern}")

    try:
        scores = pd.read_parquet(scores_path)
    except (OSError, ValueError) as exc:
        raise ExperimentInputError(f"test scored-edge file is unavailable: {scores_path}") from exc
    if not {"edge_id", "from_id", "to_id", "timestamp"} <= set(scores.columns):
        raise ExperimentInputError("R12 scored edges require edge_id/from_id/to_id/timestamp columns")
    split_midpoint = DAY_ZERO + ((FIRST_TEST_DAY + LAST_TEST_DAY + 1) // 2) * SECONDS_PER_DAY
    truth_rows = truth_rows.loc[
        truth_rows["ring_id"].isin(pattern_ids)
        & (truth_rows["timestamp_int"] < split_midpoint)
    ]

    available: dict[tuple[int, int, int], list[int]] = {}
    for row_index, row in scores[["from_id", "to_id", "timestamp"]].iterrows():
        key = (int(row.from_id), int(row.to_id), int(row.timestamp))
        available.setdefault(key, []).append(int(row_index))
    selected_rows: list[int] = []
    for row in truth_rows.itertuples(index=False):
        key = (int(row.from_id), int(row.to_id), int(row.timestamp_int))
        matches = available.get(key)
        if matches:
            selected_rows.append(matches.pop(0))
    selected_rows = sorted(set(selected_rows))
    if not selected_rows:
        raise ExperimentInputError(
            "R12 could not match first-half truth transactions to scored-edge rows by endpoints and timestamp"
        )

    before = scores.drop(index=selected_rows).reset_index(drop=True)
    reinserted = scores.loc[selected_rows].copy()
    reinserted["timestamp"] = reinserted["timestamp"].astype("int64") + 5 * SECONDS_PER_DAY
    after = pd.concat([before, reinserted], ignore_index=True).sort_values(
        ["timestamp", "edge_id"], kind="stable",
    ).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    before_path = output_dir / "scores_before_insertion.parquet"
    after_path = output_dir / "scores_after_insertion.parquet"
    before.to_parquet(before_path, index=False)
    after.to_parquet(after_path, index=False)
    source_log = _score_log(scores_path)
    for path, stage in ((before_path, "before_insertion"), (after_path, "after_insertion")):
        log = deepcopy(source_log)
        log["created_utc"] = datetime.now(timezone.utc).isoformat()
        log["inputs"]["r12_shift"] = {
            "stage": stage, "pattern": pattern, "moved_edge_rows": len(selected_rows),
            "source_log": str(Path(str(scores_path) + ".log.json").name),
        }
        Path(str(path) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return {"pattern_ids": pattern_ids, "moved_edge_rows": len(selected_rows),
            "before_path": before_path, "after_path": after_path,
            "truth": truth, "patterns": patterns}


def _fixture_dry_report(config: dict, *, pattern: str) -> dict:
    output_dir = REPO_ROOT / "results" / "platform" / "r12" / "dry_fixture"
    insertion_day = 8 + 128
    daily = [(8 + index, 0.0 if index < 128 else 1.0,
              0.0 if index < 128 else 1.0) for index in range(256)]
    stream = DriftStream(delta=float(config["l6"]["drift"]["delta"]), tenant_id=-99)
    events = [event for point in daily for event in stream.update(*point)]
    mean_events = [event for event in events if event["monitor"] == "adwin_score_mean"]
    detected_day = ((int(mean_events[0]["window_end"].timestamp()) - DAY_ZERO)
                    // SECONDS_PER_DAY - 1) if mean_events else None
    delay = detected_day - insertion_day if detected_day is not None else None
    truth = {1: {11, 12}}
    before = {"ring_recall": 0.0, "member_coverage": 0.0}
    after = {"ring_recall": 1.0, "member_coverage": 1.0}
    rows = [
        {"lane": "no_retrain_control", "recall_before_insertion": before["ring_recall"],
         "recall_after_insertion_without_retrain": after["ring_recall"],
         "recall_after_gated_retrain": None,
         "control_note": "fixture only; gated retrain was not executed"},
        {"lane": "gated_retrain", "recall_before_insertion": before["ring_recall"],
         "recall_after_insertion_without_retrain": after["ring_recall"],
         "recall_after_gated_retrain": None,
         "control_note": "fixture only; no supplied held-out model"},
    ]
    csv_path = output_dir / "recall.csv"
    md_path = output_dir / "recall.md"
    write_csv_and_markdown(rows, csv_path, md_path)
    report_header = (
        f"DRY RUN FIXTURE ONLY for pattern {pattern}. No real detector, analyst, or retrain ran.\n"
        "drift was injected, not observed.\n\n"
        f"Fixture insertion day: {insertion_day}; ADWIN mean detection day: {detected_day}; "
        f"detection delay (simulated days): {delay}. The final recall column is null because "
        "the gated retrain was not executed in dry mode.\n\n"
    )
    md_path.write_text(report_header + md_path.read_text(encoding="utf-8"), encoding="utf-8")
    run_path = write_run_manifest(
        output_dir, experiment="r12_injected_shift", config=config,
        inputs=[Path(__file__)],
        details={"dry_run": True, "fixture_only": True, "pattern": pattern,
                 "insertion_day": insertion_day, "detection_day": detected_day,
                 "detection_delay_simulated_days": delay,
                 "n_events": len(events), "n_truth_fixture_rings": len(truth),
                 "statement": "drift was injected, not observed"},
    )
    return {"dry_run": True, "csv": str(csv_path), "markdown": str(md_path),
            "run_json": str(run_path), "detection_delay_simulated_days": delay}


def _tenant_is_empty(tenant_id: int) -> None:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        edge_count = session.scalar(select(func.count()).select_from(Transaction).where(
            Transaction.tenant_id == tenant_id,
        ))
        ring_count = session.scalar(select(func.count()).select_from(Ring).where(
            Ring.tenant_id == tenant_id,
        ))
    if edge_count or ring_count:
        raise ExperimentInputError(
            "real R12 requires a dedicated loaded tenant with no transactions or rings; "
            "use a disposable database/tenant"
        )


def _actor(tenant_id: int) -> Principal:
    with db_session(tenant_id=tenant_id, role="analyst") as session:
        row = session.execute(select(User.user_id, User.email).where(
            User.tenant_id == tenant_id,
            User.email == f"simulated.analyst@tenant{tenant_id}.local",
            User.role == "analyst", User.disabled.is_(False),
        )).one_or_none()
    if row is None:
        raise ExperimentInputError(f"simulated analyst is not seeded for tenant {tenant_id}")
    return Principal(user_id=row.user_id, tenant_id=tenant_id, role="analyst", email=row.email)


def _event_rings_for_day(tenant_id: int, day: int) -> set[str]:
    start = DAY_ZERO + int(day) * SECONDS_PER_DAY
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        return set(session.scalars(select(Ring.ring_id).where(
            Ring.tenant_id == tenant_id, Ring.scope == "tenant", Ring.status == "open",
            Ring.start_time >= start, Ring.start_time < start + SECONDS_PER_DAY,
        )))


def _eval_pattern(rings_path: Path, truth_path: Path, pattern_ids: set,
                  output_path: Path) -> dict:
    manifest = output_path.with_suffix(".holdout.json")
    manifest.write_text(json.dumps({"truth_ring_ids": sorted(map(int, pattern_ids))}), encoding="utf-8")
    result = research_cli.eval_rings(
        rings=rings_path, truth=truth_path, holdout=manifest, window="whole",
        scope="test_visible", out=output_path,
    )
    return {"ring_recall": result.metrics["ring_recall"],
            "member_coverage": result.metrics["member_coverage"]}


def _real_replay(*, tenant_id: int, config: dict, pattern: str) -> dict:
    r12_config = config.get("r12") or {}
    model_dir_value = r12_config.get("model_dir")
    if not model_dir_value:
        raise ExperimentInputError("platform config r12.model_dir is required for real mode")
    model_dir = Path(model_dir_value)
    if not model_dir.is_absolute():
        model_dir = REPO_ROOT / model_dir
    if not model_dir.is_dir():
        raise ExperimentInputError(f"configured r12.model_dir is unavailable: {model_dir}")
    truth_value = config.get("l6", {}).get("retrain", {}).get("truth_parquet")
    if not truth_value:
        raise ExperimentInputError("platform config l6.retrain.truth_parquet is unavailable")
    truth_path = Path(truth_value)
    if not truth_path.is_absolute():
        truth_path = REPO_ROOT / truth_path
    if not truth_path.is_file():
        raise ExperimentInputError(f"configured R12 truth parquet is unavailable: {truth_path}")
    scores_path = Path(config["scored_edges"])
    if not scores_path.is_absolute():
        scores_path = REPO_ROOT / scores_path
    for key in ("gfp", "embeddings"):
        value = Path(config[key])
        if not value.is_absolute():
            value = REPO_ROOT / value
        if not value.is_file():
            raise ExperimentInputError(f"configured R12 {key} input is unavailable: {value}")
    _tenant_is_empty(tenant_id)
    run_id = uuid4().hex
    output_dir = REPO_ROOT / "results" / "platform" / "r12" / run_id
    shift = prepare_shifted_scores(scores_path=scores_path, truth_path=truth_path,
                                   pattern=pattern, output_dir=output_dir)
    score_log = _score_log(shift["after_path"])
    dynamic_config = deepcopy(config)
    dynamic_config.pop("_path", None)
    dynamic_config.update({
        "active_seed": int(score_log["seed"]), "model_dir": str(model_dir),
        "scored_edges": str(shift["after_path"]),
        "seed_score_cutoff": float(score_log["seed_rule"]["q"]),
        "seed_score_cutoff_source": (
            f"{shift['after_path'].relative_to(REPO_ROOT).as_posix()}.log.json:seed_rule.q"
        ),
    })
    dynamic_config["gfp"] = str(configured_path(config, "gfp"))
    dynamic_config["embeddings"] = str(configured_path(config, "embeddings"))
    dynamic_config["l6"]["retrain"]["base_model_dir"] = str(model_dir)
    runtime_config = output_dir / "platform-r12.yaml"
    runtime_config.write_text(yaml.safe_dump(dynamic_config, sort_keys=False), encoding="utf-8")
    old_config_env = os.environ.get("RINGSHIELD_PLATFORM_CONFIG")
    os.environ["RINGSHIELD_PLATFORM_CONFIG"] = str(runtime_config)
    from settings import load_platform_config as load_config, load_l6_config
    load_config.cache_clear()
    try:
        _tenant_is_empty(tenant_id)
        before_config = deepcopy(dynamic_config)
        before_config["scored_edges"] = str(shift["before_path"])
        before_config["seed_score_cutoff_source"] = (
            f"{shift['before_path'].relative_to(REPO_ROOT).as_posix()}.log.json:seed_rule.q"
        )
        before_build = build_tenant_rings(
            scores_path=shift["before_path"], model_dir=model_dir,
            gfp_path=Path(before_config["gfp"]), embeddings_path=Path(before_config["embeddings"]),
            tenant_ids=[tenant_id], output_dir=output_dir / "before", config=before_config,
        )[0]
        after_build = build_tenant_rings(
            scores_path=shift["after_path"], model_dir=model_dir,
            gfp_path=Path(dynamic_config["gfp"]), embeddings_path=Path(dynamic_config["embeddings"]),
            tenant_ids=[tenant_id], output_dir=output_dir / "after", config=dynamic_config,
        )[0]
        before_metrics = _eval_pattern(Path(before_build["rings_path"]), truth_path,
                                       shift["pattern_ids"], output_dir / "before-metrics.json")
        after_metrics = _eval_pattern(Path(after_build["rings_path"]), truth_path,
                                      shift["pattern_ids"], output_dir / "after-metrics.json")
        load_contract.load_edges(shift["after_path"], scope="tenant", tenant_id=tenant_id)
        load_contract.load_rings(Path(after_build["rings_path"]), scope="tenant", tenant_id=tenant_id)

        from settings import load_l6_config as load_current_l6
        l6 = load_current_l6(load_config())
        daily = read_daily_scores(tenant_id, model_id=dynamic_config["active_model_id"],
                                  seed=int(dynamic_config["active_seed"]))
        stream = DriftStream(delta=float(l6["drift"]["delta"]), tenant_id=tenant_id)
        detections = []
        for point in daily:
            for event in stream.update(*point):
                persist_events(tenant_id, [event])
                detections.append(event)
        actor = _actor(tenant_id)
        reviewed = 0
        for day in sorted({(int(event["window_end"].timestamp()) - DAY_ZERO) // SECONDS_PER_DAY - 1
                           for event in detections}):
            ring_ids = _event_rings_for_day(tenant_id, day)
            if not ring_ids:
                continue
            result = simulate_cycle(
                tenant_id=tenant_id, cycle_day=day, actor=actor, truth_path=truth_path,
                seed=int(l6["simulator"]["seed"]), accuracy=float(l6["simulator"]["accuracy"]),
                review_fraction=float(l6["simulator"]["review_fraction"]),
                match_jaccard=float(l6["simulator"]["match_jaccard"]),
                full_confirm_jaccard=float(l6["simulator"]["full_confirm_jaccard"]),
                cycle_days=1, truth_window="whole", ring_ids=ring_ids,
            )
            reviewed += result["simulated"]

        run_id = f"r12-{run_id}"
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            from db.models import RetrainRun
            session.add(RetrainRun(
                run_id=run_id, tenant_id=tenant_id, triggered_by="supervisor",
                started_at=datetime.now(timezone.utc), status="running",
                log_path=f"platform/out/retrain/{run_id}.log",
            ))
        run_retrain_job(tenant_id, run_id)
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            retrain_state = session.scalar(select(RetrainRun).where(
                RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
            ))
        if retrain_state is None:
            raise RuntimeError("R12 gated retrain run disappeared")
        after_retrain_path = Path(after_build["rings_path"])
        if retrain_state.model_version_id is not None:
            refresh_path = (PLATFORM_ROOT / "out" / "ring-refresh" / run_id
                            / str(tenant_id) / f"tenant_{tenant_id}_rings.parquet")
            if refresh_path.is_file():
                after_retrain_path = refresh_path
        after_retrain_metrics = _eval_pattern(
            after_retrain_path, truth_path, shift["pattern_ids"], output_dir / "after-retrain-metrics.json",
        )
        report_rows = [
            {"lane": "no_retrain_control", "recall_before_insertion": before_metrics["ring_recall"],
             "recall_after_insertion_without_retrain": after_metrics["ring_recall"],
             "recall_after_gated_retrain": after_metrics["ring_recall"]},
            {"lane": "gated_retrain", "recall_before_insertion": before_metrics["ring_recall"],
             "recall_after_insertion_without_retrain": after_metrics["ring_recall"],
             "recall_after_gated_retrain": after_retrain_metrics["ring_recall"]},
        ]
        csv_path, md_path = output_dir / "recall.csv", output_dir / "recall.md"
        write_csv_and_markdown(report_rows, csv_path, md_path)
        delay = None
        if detections:
            earliest = min(event["window_end"] for event in detections)
            detection_day = (int(earliest.timestamp()) - DAY_ZERO) // SECONDS_PER_DAY - 1
            delay = detection_day - (FIRST_TEST_DAY + 5)
        md_path.write_text(
            "drift was injected, not observed.\n\n"
            f"Pattern: {pattern}; moved transaction rows: {shift['moved_edge_rows']}; "
            f"detection delay: {delay} simulated days; analyst-reviewed rings: {reviewed}; "
            f"gated retrain status: {retrain_state.status}.\n\n"
            + md_path.read_text(encoding="utf-8"), encoding="utf-8",
        )
        inputs = [truth_path, scores_path, Path(str(scores_path) + ".log.json"),
                  Path(dynamic_config["gfp"]), Path(dynamic_config["embeddings"]),
                  model_dir / "model.json", l6["paths"]["holdout_manifest"],
                  l6["paths"]["holdout_sha256_file"], l6["paths"]["val_scored_edges"],
                  l6["paths"]["val_gfp"], l6["paths"]["val_embeddings"]]
        run_json = write_run_manifest(
            output_dir, experiment="r12_injected_shift", config=config, inputs=inputs,
            details={"dry_run": False, "pattern": pattern,
                     "moved_edge_rows": shift["moved_edge_rows"],
                     "detection_delay_simulated_days": delay,
                     "reviewed_rings": reviewed, "retrain_status": retrain_state.status,
                     "statement": "drift was injected, not observed"},
        )
        return {"dry_run": False, "csv": str(csv_path), "markdown": str(md_path),
                "run_json": str(run_json), "detection_delay_simulated_days": delay,
                "retrain_status": retrain_state.status}
    finally:
        load_config.cache_clear()
        if old_config_env is None:
            os.environ.pop("RINGSHIELD_PLATFORM_CONFIG", None)
        else:
            os.environ["RINGSHIELD_PLATFORM_CONFIG"] = old_config_env
        load_config.cache_clear()


def run_experiment(*, tenant_id: int | None = None, dry: bool = False,
                   pattern: str | None = None) -> dict:
    config = load_platform_config()
    selected_pattern = str(pattern or (config.get("r12") or {}).get("pattern", "BIPARTITE")).upper()
    model_dir_value = (config.get("r12") or {}).get("model_dir")
    model_path = Path(model_dir_value) if model_dir_value else None
    if model_path is not None and not model_path.is_absolute():
        model_path = REPO_ROOT / model_path
    if dry or model_path is None or not model_path.is_dir():
        return _fixture_dry_report(config, pattern=selected_pattern)
    if tenant_id is None:
        raise ExperimentInputError("real R12 mode requires --tenant-id for its disposable loaded tenant")
    return _real_replay(tenant_id=tenant_id, config=config, pattern=selected_pattern)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int)
    parser.add_argument("--pattern")
    parser.add_argument("--dry", action="store_true",
                        help="write clearly labeled fixture output without research data or database writes")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(tenant_id=args.tenant_id, dry=args.dry,
                                        pattern=args.pattern), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"R12 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
