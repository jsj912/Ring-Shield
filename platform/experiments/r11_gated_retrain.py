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
import subprocess
import sys
import time
from uuid import uuid4

import pandas as pd
import pyarrow.parquet as pq

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
DAY9 = (777_610, 864_009)    # test day 9 in loader seconds: the day the retrained model would serve


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


def _serving(tenant_id: int, components: list[str]) -> list[ModelVersion]:
    """The promoted version of each retrained component, i.e. what serves the next cycle."""
    return sorted((row for row in _version_snapshot(tenant_id).values()
                   if row.component in components and row.promoted),
                  key=lambda row: (row.component, row.model_version_id))


def _version_label(rows: list[ModelVersion]) -> str:
    return "; ".join(f"{row.component} #{row.model_version_id} {row.version_tag}" for row in rows) or "base (no rows yet)"


def _restricted(rings_path: Path, edges: pd.DataFrame, lo: int, hi: int) -> list[set]:
    """Predicted member sets inside [lo, hi]: endpoints of in-window member edges."""
    window = edges[(edges["timestamp"] >= lo) & (edges["timestamp"] <= hi)]
    out = []
    for member_edges in pq.read_table(rings_path, columns=["member_edges"])["member_edges"].to_pylist():
        keep = [edge for edge in member_edges if edge in window.index]
        if keep:
            out.append(set(window.loc[keep, "from_id"]) | set(window.loc[keep, "to_id"]))
    return out


def day9_metrics(rings_path: Path, *, tenant_id: int, config: dict, truth_path: Path) -> dict:
    """Descriptive ring metrics on test day 9 for one ring set: test_visible truth rings in scope of
    day 9 with a scored member whose home bank is the tenant (R10's pairing rule), Jaccard 0.5."""
    from evaluation.ring_metrics import evaluate_rings
    from ringshield.truth import load_ground_truth
    lo, hi = DAY9
    truth, _ = load_ground_truth(truth_path, lo, hi, "test_visible", verbose=False)
    banks = pd.read_parquet(REPO_ROOT / config["account_map"]).set_index("account_id")["bank_code"]
    truth = {rid: members for rid, members in truth.items()
             if any(int(banks.get(account, -1)) == tenant_id for account in members)}
    edges = pd.read_parquet(REPO_ROOT / config["scored_edges"],
                            columns=["edge_id", "from_id", "to_id", "timestamp"]).set_index("edge_id")
    metrics = evaluate_rings(_restricted(rings_path, edges, lo, hi), truth, 0.5)
    return {"ring_precision": round(metrics.ring_precision, 4), "ring_recall": round(metrics.ring_recall, 4),
            "ring_f1": round(metrics.ring_f1, 4), "member_coverage": round(metrics.member_coverage, 4),
            "n_predicted": metrics.n_predicted, "n_truth": metrics.n_truth, "n_matched": metrics.n_matched}


def serving_rings(promoted: list[ModelVersion], *, tenant_id: int, base_rings: Path, build_config: Path,
                  run_dir: Path) -> tuple[Path | None, str]:
    """The serving model's rings for the tenant: the base rings if nothing was promoted, the
    promoted candidate's rings if one was, and none if two were (no combined artifact exists)."""
    if not promoted:
        return base_rings, "nothing promoted: the serving model is the old model"
    if len(promoted) > 1:
        return None, "two components promoted separately; no combined artifact to build rings from"
    out_dir = run_dir / "serving_rings"
    command = [sys.executable, str(PLATFORM_ROOT / "jobs" / "build_tenant_rings.py"),
               "--config", str(build_config), "--model-dir", str(promoted[0].artifact_path),
               "--tenant-id", str(tenant_id), "--output-dir", str(out_dir)]
    subprocess.run(command, cwd=REPO_ROOT, check=True, stdout=subprocess.DEVNULL)
    return out_dir / f"tenant_{tenant_id}_rings.parquet", f"promoted {promoted[0].component} #{promoted[0].model_version_id}"


def models_screen_json(tenant_id: int, config: dict, cycles: list[dict], run_id: str | None) -> dict:
    """The Models screen's shapes (api/schemas.py ModelVersionPage, RetrainRunPage), field names
    unchanged, plus the per-cycle rows."""
    versions = sorted(_version_snapshot(tenant_id).values(), key=lambda row: row.model_version_id, reverse=True)
    items = [{"model_version_id": row.model_version_id, "component": row.component, "version_tag": row.version_tag,
              "trained_at": row.trained_at.isoformat(), "train_label_count": row.train_label_count,
              "holdout_ring_f1": row.holdout_ring_f1, "promoted": bool(row.promoted), "shared": row.tenant_id is None,
              "gate_reason": row.gate_reason, "retrain_run_id": row.retrain_run_id} for row in versions]
    runs = []
    if run_id is not None:
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            run = session.scalar(select(RetrainRun).where(RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id))
        runs.append({"run_id": run.run_id, "status": run.status,
                     "started_at": run.started_at.isoformat() if run.started_at else None,
                     "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                     "model_version_id": run.model_version_id,
                     "candidates": [{"model_version_id": item["model_version_id"], "component": item["component"],
                                     "holdout_ring_f1": item["holdout_ring_f1"], "promoted": item["promoted"],
                                     "gate_reason": item["gate_reason"]}
                                    for item in items if item["retrain_run_id"] == run_id]})
    return {"label": "R11, simulated verdicts; a demonstration, not an effectiveness experiment",
            "model_versions": {"items": items, "next_before_id": None,
                               "active_model_id": config["active_model_id"], "active_seed": int(config["active_seed"])},
            "retrain_runs": {"items": runs}, "cycles": cycles}


def day9_report(*, tenant_id: int, config: dict, retrain: dict, truth_path: Path, retrain_run_id: str | None,
                output_dir: Path) -> dict:
    """Day 9, descriptive only: the old model's rings against the rings of the model serving cycles 7-12."""
    import yaml
    from experiments.r11_seed_config import config_path as build_config_path, tenant_build_config
    seed = int(config["active_seed"])
    base_rings = REPO_ROOT / str(retrain["label_rings_template"]).format(
        tenant_id=tenant_id, model_id=config["active_model_id"], seed=seed)
    build_config = build_config_path(seed, tenant_id)
    if not build_config.is_file():
        build_config.parent.mkdir(parents=True, exist_ok=True)
        build_config.write_text(yaml.safe_dump(tenant_build_config(seed, tenant_id, config), sort_keys=False),
                                encoding="utf-8")
    promoted_rows = [row for row in _version_snapshot(tenant_id).values()
                     if row.retrain_run_id == retrain_run_id and row.promoted]
    serving_path, serving_note = serving_rings(promoted_rows, tenant_id=tenant_id, base_rings=base_rings,
                                               build_config=build_config, run_dir=output_dir)
    candidates = [row for row in _version_snapshot(tenant_id).values()
                  if row.retrain_run_id == retrain_run_id and row.gate_reason != "initial holdout baseline"]
    if not promoted_rows:
        serving_note = ("no candidate was trained (no new verdicts before the retrain)" if not candidates
                        else "the gate refused every candidate") + "; the serving model is the old model"
    return {"window": {"loader_seconds": list(DAY9), "scope": "test_visible", "jaccard": 0.5,
                       "truth": f"in-scope rings with a scored member whose home bank is {tenant_id}"},
            "old_model": day9_metrics(base_rings, tenant_id=tenant_id, config=config, truth_path=truth_path),
            "serving_model": (day9_metrics(serving_path, tenant_id=tenant_id, config=config, truth_path=truth_path)
                              if serving_path is not None else None),
            "serving_note": serving_note, "label": "descriptive only"}


def cycle_intervals(cycles: int = CYCLES, hours: int = CYCLE_HOURS) -> list[tuple[int, int]]:
    """[start, end) of each cycle in loader seconds: the primary window cut into equal slices."""
    window = truth_window_info(TRUTH_WINDOW)
    start, end = int(window["start"]), int(window["end"]) + 1
    step = hours * 3_600
    if cycles * step != end - start:
        raise ValueError(f"{cycles} cycles of {hours} h do not tile the {TRUTH_WINDOW} window")
    return [(start + index * step, start + (index + 1) * step) for index in range(cycles)]


def run_experiment(*, tenant_id: int, accuracy: float, cycles: int = CYCLES, out_root: Path | None = None) -> dict:
    """R11 as amended (docs/R11.md): 12 four-hour cycles over test days 8-9, every open ring of the
    tenant reviewed in its cycle, one gated retrain after cycle 6, and a no-retrain control."""
    started = time.monotonic()
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
    output_dir = (out_root or REPO_ROOT / "results" / "platform" / "r11") / f"accuracy_{accuracy:.2f}"
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
    base_label = f"base {Path(paths['base_model_dir']).name}"
    holdout_serving = baseline_control
    retrain_run_id = None

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
            run_id = retrain_run_id = f"r11-{uuid4().hex}"
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
        holdout_before = holdout_serving
        holdout_serving = sum(current_scores) / len(current_scores) if current_scores else baseline_control
        serving = _serving(tenant_id, retrain["components"])
        cycle_rows.append({
            "accuracy": accuracy, "cycle": cycle,
            "hours": f"{(start - window_start) // 3_600}-{(end - window_start) // 3_600}",
            "open_rings": simulation["open_rings"],
            "simulated_verdicts": simulation["simulated"],
            "retrain_status": run_status,
            # Before the first retrain records anything, the base model (the control) is serving.
            "holdout_ring_f1": sum(current_scores) / len(current_scores) if current_scores else baseline_control,
            "no_retrain_control_holdout_ring_f1": baseline_control,
            "retrain": "y" if cycle == RETRAIN_AFTER_CYCLE else "n",
            "gate_decision": ("—" if cycle != RETRAIN_AFTER_CYCLE else
                              f"retrain run {run_status}: {candidates or 'no candidate'}" if run_status != "succeeded" else
                              "promoted" if promoted and not refused else "refused" if refused and not promoted
                              else f"{promoted} promoted, {refused} refused" if promoted or refused else "no candidate"),
            "holdout_before": holdout_before, "holdout_after": holdout_serving,
            "serving_model": _version_label([row for row in serving if row.gate_reason != "initial holdout baseline"])
            if any(row.gate_reason != "initial holdout baseline" for row in serving) else base_label,
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
    seed = int(config["active_seed"])
    day9 = day9_report(tenant_id=tenant_id, config=config, retrain=retrain, truth_path=truth_path,
                       retrain_run_id=retrain_run_id, output_dir=output_dir)
    wall_seconds = round(time.monotonic() - started, 1)
    models_path = output_dir / "models.json"
    models_path.write_text(json.dumps(models_screen_json(tenant_id, config, cycle_rows, retrain_run_id) |
                                      {"day9": day9, "wall_seconds": wall_seconds}, indent=2, default=str),
                           encoding="utf-8")
    input_paths = [truth_path, paths["holdout_manifest"], paths["holdout_sha256_file"],
                   paths["val_scored_edges"], paths["val_gfp"], paths["val_embeddings"],
                   paths["base_model_dir"] / "model.json"]
    run_json = write_run_manifest(
        output_dir, experiment="r11_gated_retrain", config=config, inputs=input_paths,
        details={"tenant_id": tenant_id, "accuracy": accuracy, "cycles": cycles,
                 "cycle_hours": CYCLE_HOURS, "truth_window": TRUTH_WINDOW,
                 "review_fraction": REVIEW_FRACTION, "retrain_after_cycle": RETRAIN_AFTER_CYCLE,
                 "components": list(retrain["components"]), "typing": "not refit; R5 head fixed",
                 "retrained_false": saw_retrained_false, "detector_seed": seed, "day9": day9,
                 "wall_seconds": wall_seconds, "models_screen_json": str(models_path.relative_to(REPO_ROOT)),
                 "no_retrain_control": "static initial promoted holdout F1; no train job is run for this lane"},
    )
    return {"csv": str(csv_path), "markdown": str(md_path), "run_json": str(run_json),
            "models_json": str(models_path), "wall_seconds": wall_seconds, "day9": day9,
            "retrained_false": saw_retrained_false, "disclaimer": disclaimer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--accuracy", type=float, required=True, choices=(0.90, 0.70))
    parser.add_argument("--cycles", type=int, default=CYCLES)
    parser.add_argument("--out-root", type=Path,
                        help="outputs go to OUT_ROOT/accuracy_<a>/ (the five-seed run uses one root per seed)")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(tenant_id=args.tenant_id, accuracy=args.accuracy,
                                        cycles=args.cycles,
                                        out_root=args.out_root.resolve() if args.out_root else None), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"R11 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
