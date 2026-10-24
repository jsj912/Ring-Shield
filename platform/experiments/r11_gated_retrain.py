"""R11: twelve simulated feedback cycles and one gated retrain for one accuracy condition.

A demonstration that the feedback loop works end to end, not an effectiveness experiment: one
bank produces a handful of rings in 48 h and its verdicts are ~0.06 % of the expansion training
rows. Amendments to spec v1.1 are recorded in docs/R11.md.
"""

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
sys.path.insert(1, str(REPO_ROOT))

from adapters import research_cli
from adapters.ground_truth import load_window_truth, truth_window_info
from db.models import ModelVersion, RetrainRun, User
from db.session import db_session
from experiments.common import ExperimentInputError, write_csv_and_markdown, write_run_manifest
from jobs.retrain import _evaluate, _validate_inputs, run_retrain_job
from jobs.simulate_verdicts import DAY_ZERO_TIMESTAMP, simulate_cycle
from api.identity import Principal
from settings import load_l6_config, load_platform_config

TRUTH_WINDOW = "primary"     # test days 8-9; days 0-7 are train and validation and are never replayed
CYCLES = 12
CYCLE_HOURS = 4
REVIEW_FRACTION = 1.0        # every open ring of the tenant is reviewed in its cycle
RETRAIN_AFTER_CYCLE = 6      # end of day 8; the result serves cycles 7-12


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


def cycle_intervals(cycles: int = CYCLES, hours: int = CYCLE_HOURS) -> list[tuple[int, int]]:
    """[start, end) of each cycle in loader seconds: the primary window cut into equal slices."""
    window = truth_window_info(TRUTH_WINDOW)
    start, end = int(window["start"]), int(window["end"]) + 1
    step = hours * 3_600
    if cycles * step != end - start:
        raise ValueError(f"{cycles} cycles of {hours} h do not tile the {TRUTH_WINDOW} window")
    return [(start + index * step, start + (index + 1) * step) for index in range(cycles)]


def run_experiment(*, tenant_id: int, accuracy: float, cycles: int = CYCLES) -> dict:
    """R11 as amended (docs/R11.md): 12 four-hour cycles over test days 8-9, every open ring of the
    tenant reviewed in its cycle, one gated retrain after cycle 6, and a no-retrain control."""
    if accuracy not in (0.90, 0.70):
        raise ValueError("R11 supports accuracy 0.90 or 0.70")
    if cycles != CYCLES:
        raise ValueError(f"R11 uses exactly {CYCLES} cycles")
    intervals = cycle_intervals(cycles)
    config = load_platform_config()
    l6 = load_l6_config(config)
    paths = _validate_inputs(l6, config)
    truth_path = paths.get("truth_parquet")
    if truth_path is None or not truth_path.is_file():
        raise ExperimentInputError("platform config l6.retrain.truth_parquet is missing or unavailable")
    # Fail before any simulated verdict is written if the selected test window
    # or ground truth cannot be loaded.
    load_window_truth(truth_path, window_name=TRUTH_WINDOW, scope="test_visible")
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

    window_start = intervals[0][0]
    for offset, (start, end) in enumerate(intervals):
        cycle = offset + 1
        simulation = simulate_cycle(
            tenant_id=tenant_id, cycle_day=(start - DAY_ZERO_TIMESTAMP) // 86_400, actor=actor,
            truth_path=truth_path, seed=int(simulator["seed"]), accuracy=accuracy,
            review_fraction=REVIEW_FRACTION,
            match_jaccard=float(simulator["match_jaccard"]),
            full_confirm_jaccard=float(simulator["full_confirm_jaccard"]),
            truth_window=TRUTH_WINDOW, interval=(start, end),
        )
        run_id, run_status, promoted, refused, false_retrain, candidates = None, "not run", 0, 0, 0, ""
        if cycle == RETRAIN_AFTER_CYCLE:
            before = _version_snapshot(tenant_id)
            run_id = f"r11-{uuid4().hex}"
            with db_session(tenant_id=tenant_id, role="supervisor") as session:
                session.add(RetrainRun(
                    run_id=run_id, tenant_id=tenant_id, triggered_by="supervisor",
                    started_at=datetime.now(timezone.utc), status="running",
                    log_path=f"platform/out/retrain/{run_id}.log",
                ))
            # Exactly one retrain, on whatever day 8 produced: no minimum label count.
            run_retrain_job(tenant_id, run_id, min_new_labels=1)
            run_status = _run_status(tenant_id, run_id)
            after = _version_snapshot(tenant_id)
            # The first retrain also records each component's base model as the starting baseline;
            # those rows are not retrain outcomes.
            created = [row for version_id, row in after.items() if version_id not in before
                       and row.gate_reason != "initial holdout baseline"]
            candidates = "; ".join(
                f"{row.component} {'n/a' if row.holdout_ring_f1 is None else f'{float(row.holdout_ring_f1):.4f}'} "
                f"{'promoted' if row.promoted else 'refused'}" for row in created)
            promoted = sum(bool(row.promoted) for row in created)
            refused = sum(not bool(row.promoted) for row in created)
            false_retrain = sum(
                str(row.gate_reason or "").startswith("train CLI reported retrained=false")
                for row in created
            )
            saw_retrained_false = saw_retrained_false or bool(false_retrain)
        current_scores = [float(row.holdout_ring_f1) for row in _version_snapshot(tenant_id).values()
                          if row.component in retrain["components"]
                          and row.promoted and row.holdout_ring_f1 is not None]
        cycle_rows.append({
            "accuracy": accuracy, "cycle": cycle,
            "hours": f"{(start - window_start) // 3_600}-{(end - window_start) // 3_600}",
            "open_rings": simulation["open_rings"],
            "simulated_verdicts": simulation["simulated"],
            "retrain_status": run_status,
            # Before the first retrain records anything, the base model (the control) is serving.
            "holdout_ring_f1": sum(current_scores) / len(current_scores) if current_scores else baseline_control,
            "no_retrain_control_holdout_ring_f1": baseline_control,
            "candidates": candidates, "promotions": promoted, "refusals": refused,
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
                 "cycle_hours": CYCLE_HOURS, "truth_window": TRUTH_WINDOW,
                 "review_fraction": REVIEW_FRACTION, "retrain_after_cycle": RETRAIN_AFTER_CYCLE,
                 "components": list(retrain["components"]), "typing": "not refit; R5 head fixed",
                 "retrained_false": saw_retrained_false,
                 "no_retrain_control": "static initial promoted holdout F1; no train job is run for this lane"},
    )
    return {"csv": str(csv_path), "markdown": str(md_path), "run_json": str(run_json),
            "retrained_false": saw_retrained_false, "disclaimer": disclaimer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--accuracy", type=float, required=True, choices=(0.90, 0.70))
    parser.add_argument("--cycles", type=int, default=CYCLES)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(tenant_id=args.tenant_id, accuracy=args.accuracy,
                                        cycles=args.cycles), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"R11 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
