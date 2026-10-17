"""Run ten simulated feedback/retraining cycles for one accuracy condition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters import research_cli
from adapters.ground_truth import load_window_truth
from db.models import ModelVersion, RetrainRun, User
from db.session import db_session
from experiments.common import ExperimentInputError, write_csv_and_markdown, write_run_manifest
from jobs.retrain import _evaluate, _validate_inputs, run_retrain_job
from jobs.simulate_verdicts import simulate_cycle
from api.identity import Principal
from settings import load_l6_config, load_platform_config


def retrained_false_disclaimer(cycles: list[dict]) -> str:
    if any(int(row["retrained_false_count"]) > 0 for row in cycles):
        return "Retraining was not real in this run; no improvement is claimed."
    return ""


def _tenant_actor(tenant_id: int) -> Principal:
    with db_session(tenant_id=tenant_id, role="analyst") as session:
        user = session.execute(select(User.user_id, User.email).where(
            User.tenant_id == tenant_id,
            User.email == f"simulated.analyst@tenant{tenant_id}.local",
            User.role == "analyst", User.disabled.is_(False),
        )).one_or_none()
    if user is None:
        raise ExperimentInputError(f"simulated analyst is not seeded for tenant {tenant_id}")
    return Principal(user_id=user.user_id, tenant_id=tenant_id,
                     role="analyst", email=user.email)


def _baseline_f1(tenant_id: int, components: list[str]) -> float | None:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        rows = list(session.scalars(select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.component.in_(components), ModelVersion.promoted.is_(True),
        )))
    values = [float(row.holdout_ring_f1) for row in rows if row.holdout_ring_f1 is not None]
    return sum(values) / len(values) if values else None


def _version_snapshot(tenant_id: int) -> dict[int, ModelVersion]:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        return {row.model_version_id: row for row in session.scalars(select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
        ))}


def _run_status(tenant_id: int, run_id: str) -> str:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        row = session.scalar(select(RetrainRun).where(
            RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
        ))
    if row is None:
        raise RuntimeError(f"retrain run {run_id} disappeared")
    return row.status


def run_experiment(*, tenant_id: int, accuracy: float, cycles: int = 10) -> dict:
    if accuracy not in (0.90, 0.70):
        raise ValueError("R11 supports accuracy 0.90 or 0.70")
    if cycles != 10:
        raise ValueError("R11 uses exactly 10 cycles")
    config = load_platform_config()
    l6 = load_l6_config(config)
    paths = _validate_inputs(l6, config)
    truth_path = paths.get("truth_parquet")
    if truth_path is None or not truth_path.is_file():
        raise ExperimentInputError("platform config l6.retrain.truth_parquet is missing or unavailable")
    # Fail before any simulated verdict is written if the selected test window
    # or ground truth cannot be loaded.
    load_window_truth(truth_path, window_name="whole", scope="test_visible")
    actor = _tenant_actor(tenant_id)
    simulator = l6["simulator"]
    retrain = l6["retrain"]
    baseline_control = _baseline_f1(tenant_id, retrain["components"])
    output_dir = REPO_ROOT / "results" / "platform" / "r11" / f"accuracy_{accuracy:.2f}"
    if baseline_control is None:
        baseline_scores = [
            _evaluate(
                research_cli, model_dir=paths["base_model_dir"], paths=paths,
                l6=l6, run_dir=output_dir / "no-retrain-control", label=component,
            ) for component in retrain["components"]
        ]
        baseline_control = sum(baseline_scores) / len(baseline_scores)
    cycle_rows = []
    saw_retrained_false = False

    for offset in range(cycles):
        cycle_day = 8 + offset
        simulation = simulate_cycle(
            tenant_id=tenant_id, cycle_day=cycle_day, actor=actor,
            truth_path=truth_path, seed=int(simulator["seed"]), accuracy=accuracy,
            review_fraction=float(simulator["review_fraction"]),
            match_jaccard=float(simulator["match_jaccard"]),
            full_confirm_jaccard=float(simulator["full_confirm_jaccard"]),
            cycle_days=1, truth_window="whole",
        )
        before = _version_snapshot(tenant_id)
        run_id = f"r11-{uuid4().hex}"
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            session.add(RetrainRun(
                run_id=run_id, tenant_id=tenant_id, triggered_by="supervisor",
                started_at=datetime.now(timezone.utc), status="running",
                log_path=f"platform/out/retrain/{run_id}.log",
            ))
        run_retrain_job(tenant_id, run_id)
        run_status = _run_status(tenant_id, run_id)
        after = _version_snapshot(tenant_id)
        created = [row for version_id, row in after.items() if version_id not in before]
        promoted = sum(bool(row.promoted) for row in created)
        refused = sum(not bool(row.promoted) for row in created)
        false_retrain = sum(
            str(row.gate_reason or "").startswith("train CLI reported retrained=false")
            for row in created
        )
        saw_retrained_false = saw_retrained_false or bool(false_retrain)
        current_scores = [float(row.holdout_ring_f1) for row in after.values()
                          if row.component in retrain["components"]
                          and row.promoted and row.holdout_ring_f1 is not None]
        cycle_rows.append({
            "accuracy": accuracy, "cycle": offset + 1, "cycle_day": cycle_day,
            "open_rings": simulation["open_rings"],
            "simulated_verdicts": simulation["simulated"],
            "retrain_status": run_status,
            "holdout_ring_f1": sum(current_scores) / len(current_scores) if current_scores else None,
            "no_retrain_control_holdout_ring_f1": baseline_control,
            "promotions": promoted, "refusals": refused,
            "retrained_false_count": false_retrain,
            "run_id": run_id,
        })

    csv_path = output_dir / "cycles.csv"
    md_path = output_dir / "cycles.md"
    write_csv_and_markdown(cycle_rows, csv_path, md_path)
    disclaimer = retrained_false_disclaimer(cycle_rows)
    if disclaimer:
        existing = md_path.read_text(encoding="utf-8")
        md_path.write_text(disclaimer + "\n\n" + existing, encoding="utf-8")
    input_paths = [truth_path, paths["holdout_manifest"], paths["holdout_sha256_file"],
                   paths["val_scored_edges"], paths["val_gfp"], paths["val_embeddings"],
                   paths["base_model_dir"] / "model.json"]
    run_json = write_run_manifest(
        output_dir, experiment="r11_gated_retrain", config=config, inputs=input_paths,
        details={"tenant_id": tenant_id, "accuracy": accuracy, "cycles": cycles,
                 "retrained_false": saw_retrained_false,
                 "no_retrain_control": "static initial promoted holdout F1; no train job is run for this lane"},
    )
    return {"csv": str(csv_path), "markdown": str(md_path), "run_json": str(run_json),
            "retrained_false": saw_retrained_false, "disclaimer": disclaimer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--accuracy", type=float, required=True, choices=(0.90, 0.70))
    parser.add_argument("--cycles", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(tenant_id=args.tenant_id, accuracy=args.accuracy,
                                        cycles=args.cycles), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"R11 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
