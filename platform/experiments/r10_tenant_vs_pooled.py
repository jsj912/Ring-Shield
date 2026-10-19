"""Compare tenant ring runs with pooled runs on the same per-bank truth subset."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import tempfile
from string import Formatter

import pyarrow.parquet as pq
from sqlalchemy import select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from adapters import research_cli
from adapters.experiment_metrics import bootstrap_ring_metrics
from adapters.ground_truth import load_window_truth
from db.models import Tenant
from db.session import db_session
from experiments.common import ExperimentInputError, sha256_file, write_csv_and_markdown, write_run_manifest
from jobs.build_tenant_rings import build_tenant_rings
from settings import configured_path, load_platform_config


def _loaded_tenants() -> list[int]:
    with db_session(tenant_id=-1, role="admin") as session:
        return list(session.scalars(select(Tenant.tenant_id).where(
            Tenant.tenant_id > 0, Tenant.is_loaded.is_(True),
        ).order_by(Tenant.tenant_id)))


def _truth_bank_ids(truth: dict, account_map: Path) -> tuple[dict[int | str, set[int]], dict[int, int]]:
    names = set(pq.ParquetFile(account_map).schema_arrow.names)
    if not {"account_id", "bank_code"} <= names:
        raise ExperimentInputError(f"account map must include account_id and bank_code: {account_map}")
    table = pq.read_table(account_map, columns=["account_id", "bank_code"])
    account_banks = {int(account): int(bank) for account, bank in
                     zip(table["account_id"].to_pylist(), table["bank_code"].to_pylist())}
    ring_banks = {
        ring_id: {account_banks[account] for account in members if account in account_banks}
        for ring_id, members in truth.items()
    }
    return ring_banks, account_banks


def _members(rings_path: Path) -> list[set[int]]:
    table = pq.read_table(rings_path, columns=["members"])
    return [set(map(int, members or [])) for members in table["members"].to_pylist()]


def tenant_truth_ids(ring_banks: dict, tenant_id: int) -> list[int]:
    """Truth rings with at least one member account owned by this bank."""
    return sorted(int(ring_id) for ring_id, banks in ring_banks.items() if tenant_id in banks)


def _exact_int(value, *, field: str, minimum: int, maximum: int | None = None) -> int:
    """Validate JSON/CLI integer fields without bool or lossy numeric coercion."""
    if type(value) is not int:
        raise ExperimentInputError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ExperimentInputError(f"{field} must be in the range {bound}")
    return value


def _score_cutoff(value) -> float:
    """Validate score_raw's predicted-probability cutoff against its [0, 1] contract."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentInputError("score run log seed_rule.q must be a finite number in [0, 1]")
    try:
        cutoff = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ExperimentInputError(
            "score run log seed_rule.q must be a finite number in [0, 1]"
        ) from exc
    if not math.isfinite(cutoff) or not 0.0 <= cutoff <= 1.0:
        raise ExperimentInputError("score run log seed_rule.q must be a finite number in [0, 1]")
    return cutoff


def _score_log(path: Path, *, model_id: str, seed: int,
               tenant_id: int | None = None) -> tuple[dict, Path, float]:
    expected_seed = _exact_int(seed, field="requested seed", minimum=1, maximum=5)
    log_path = Path(str(path) + ".log.json")
    if not path.is_file() or not log_path.is_file():
        raise ExperimentInputError(f"score parquet and sibling run log are required: {path}")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentInputError(f"invalid score run log: {log_path}") from exc
    if not isinstance(log, dict):
        raise ExperimentInputError(f"invalid score run log: expected an object in {log_path}")
    try:
        seed_rule = log["seed_rule"]
        if not isinstance(seed_rule, dict):
            raise TypeError("seed_rule must be an object")
        cutoff = _score_cutoff(seed_rule["q"])
        log_seed = _exact_int(log["seed"], field="score run log seed", minimum=1, maximum=5)
    except (KeyError, TypeError) as exc:
        raise ExperimentInputError(f"invalid score run log fields: {log_path}") from exc
    if (log.get("split") != "test" or log.get("model_id") != model_id
            or log_seed != expected_seed):
        raise ExperimentInputError(
            f"score run log must declare split=test and match {model_id} seed {seed}: {log_path}"
        )
    if tenant_id is not None:
        try:
            expected_tenant_id = _exact_int(tenant_id, field="requested tenant_id", minimum=1)
            logged_tenant_id = _exact_int(
                log["tenant_id"], field="score run log tenant_id", minimum=1,
            )
        except (KeyError, ExperimentInputError) as exc:
            raise ExperimentInputError(
                f"tenant-visible score log must declare an integer tenant_id={tenant_id}"
            ) from exc
        if logged_tenant_id != expected_tenant_id:
            raise ExperimentInputError(
                f"tenant-visible score log must declare tenant_id={tenant_id}: {log_path}"
            )
    return log, log_path, cutoff


def _validate_format_template(template: str, *, allowed: set[str],
                              required: set[str], name: str) -> None:
    fields = set()
    try:
        parsed = Formatter().parse(template)
        for _literal, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if field_name not in allowed:
                raise ExperimentInputError(
                    f"{name} has unsupported field {field_name!r}"
                )
            if conversion is not None or format_spec:
                raise ExperimentInputError(
                    f"{name} does not allow conversions or format specifications"
                )
            fields.add(field_name)
    except ValueError as exc:
        raise ExperimentInputError(f"{name} is malformed") from exc
    missing = sorted(required - fields)
    if missing:
        raise ExperimentInputError(
            f"{name} must include " + ", ".join(missing)
        )


def _validate_visible_template(template: str) -> None:
    required = {"tenant_id", "model_id", "seed"}
    _validate_format_template(
        template, allowed=required, required=required,
        name="r10.tenant_visible_scores_template",
    )


def _format_visible_template(template: str, *, tenant_id: int | str,
                             model_id: str, seed: int) -> str:
    _validate_visible_template(template)
    try:
        return template.format(tenant_id=tenant_id, model_id=model_id, seed=seed)
    except (IndexError, KeyError, ValueError, AttributeError) as exc:
        raise ExperimentInputError("r10.tenant_visible_scores_template could not be formatted") from exc


def _candidate_seed_inputs(config: dict, requested_seeds: list[int] | None,
                           score_source: str | None = None) -> list[dict]:
    model_id = str(config["active_model_id"])
    r10_config = config.get("r10") or {}
    score_source = score_source or r10_config.get("tenant_score_source")
    if score_source not in {"pooled", "tenant_visible"}:
        raise ExperimentInputError(
            "R10 tenant score source is unresolved; configure r10.tenant_score_source as "
            "'pooled' or 'tenant_visible', or pass --tenant-score-source"
        )
    pooled_template = str(r10_config.get(
        "pooled_scores_template", "contract/out/scored_edges_{model_id}_{seed}.parquet"))
    _validate_format_template(
        pooled_template, allowed={"model_id", "seed"}, required={"model_id", "seed"},
        name="r10.pooled_scores_template",
    )
    visible_template = r10_config.get("tenant_visible_scores_template")
    if score_source == "tenant_visible" and not visible_template:
        raise ExperimentInputError(
            "r10.tenant_visible_scores_template is required when tenant_score_source is tenant_visible"
        )
    if score_source == "tenant_visible":
        _validate_visible_template(str(visible_template))
    seed_values = requested_seeds or list(range(1, 6))
    seed_values = [
        _exact_int(seed, field="R10 seed", minimum=1, maximum=5) for seed in seed_values
    ]
    gfp_path = configured_path(config, "gfp")
    candidates = []
    missing: list[str] = []
    for seed in seed_values:
        try:
            pooled_relative = pooled_template.format(model_id=model_id, seed=seed)
        except (IndexError, KeyError, ValueError, AttributeError) as exc:
            raise ExperimentInputError("r10.pooled_scores_template could not be formatted") from exc
        pooled_scores = REPO_ROOT / pooled_relative
        model_dir = REPO_ROOT / "models" / "artifacts" / f"full_{model_id}_seed{seed}"
        embeddings = REPO_ROOT / "experiments" / f"R1_{model_id}" / f"embeddings_test_seed{seed}.parquet"
        absent = [str(path) for path in (pooled_scores, model_dir / "model.json", gfp_path, embeddings)
                  if not path.exists()]
        if absent:
            missing.extend(absent)
            continue
        _, pooled_log_path, pooled_cutoff = _score_log(
            pooled_scores, model_id=model_id, seed=seed)
        visible_path = (Path(str(visible_template)) if Path(str(visible_template)).is_absolute()
                        else REPO_ROOT / str(visible_template)) if visible_template else None
        candidates.append({"seed": seed, "score_source": score_source,
                           "visible_scores_template": visible_path,
                           "pooled_scores": pooled_scores,
                           "pooled_log_path": pooled_log_path, "pooled_cutoff": pooled_cutoff,
                           "model_id": model_id, "model_dir": model_dir,
                           "embeddings": embeddings, "gfp": gfp_path})
    if not candidates:
        missing_text = "\n".join(f"- {path}" for path in sorted(set(missing)))
        raise ExperimentInputError(f"no detector seed has all required R10 inputs; missing files:\n{missing_text}")
    return candidates


def _tenant_score_path(inputs: dict, tenant_id: int) -> Path:
    if inputs["score_source"] == "pooled":
        return inputs["pooled_scores"]
    tenant_id = _exact_int(tenant_id, field="requested tenant_id", minimum=1)
    template = str(inputs["visible_scores_template"])
    return Path(_format_visible_template(
        template, tenant_id=tenant_id, model_id=str(inputs["model_id"]), seed=inputs["seed"],
    ))


def _score_cutoff_source(log_path: Path) -> str:
    try:
        location = log_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        location = str(log_path.resolve())
    return f"{location}:seed_rule.q"


def run_experiment(*, truth_path: Path, account_map: Path | None = None,
                   seeds: list[int] | None = None,
                   tenant_score_source: str | None = None) -> dict:
    config = load_platform_config()
    # Validate source, templates, seeds, and candidate input logs before touching
    # the database or reading the experiment truth.
    seed_inputs = _candidate_seed_inputs(config, seeds, tenant_score_source)
    truth_path = truth_path.resolve()
    account_map = (account_map or configured_path(config, "account_map")).resolve()
    for path in (truth_path, account_map):
        if not path.is_file():
            raise ExperimentInputError(f"required experiment input is unavailable: {path}")
    tenants = _loaded_tenants()
    if not tenants:
        raise ExperimentInputError("no loaded tenants are available in the platform database")
    truth = load_window_truth(truth_path, window_name="whole", scope="test_visible")
    ring_banks, account_banks = _truth_bank_ids(truth, account_map)
    all_rows = []
    input_paths = [truth_path, account_map]
    output_root = REPO_ROOT / "results" / "platform" / "r10"

    for inputs in seed_inputs:
        seed = inputs["seed"]
        seed_config = dict(config)
        seed_config.update({
            "active_seed": seed, "model_dir": str(inputs["model_dir"]),
            "embeddings": str(inputs["embeddings"]),
        })
        seed_dir = output_root / f"seed_{seed}"
        if inputs["score_source"] == "pooled":
            tenant_scores_by_id = {tenant: (inputs["pooled_scores"], inputs["pooled_log_path"],
                                           inputs["pooled_cutoff"]) for tenant in tenants}
        else:
            tenant_scores_by_id = {}
            for tenant in tenants:
                tenant_scores = _tenant_score_path(inputs, tenant)
                _, tenant_log_path, tenant_cutoff = _score_log(
                    tenant_scores, model_id=str(config["active_model_id"]), seed=seed,
                    tenant_id=tenant)
                tenant_scores_by_id[tenant] = (tenant_scores, tenant_log_path, tenant_cutoff)
                input_paths.append(tenant_scores)
                input_paths.append(tenant_log_path)
        tenant_runs = []
        for tenant in tenants:
            tenant_scores, tenant_log_path, tenant_cutoff = tenant_scores_by_id[tenant]
            tenant_config = dict(seed_config)
            tenant_config.update({
                "scored_edges": str(tenant_scores),
                "seed_score_cutoff": tenant_cutoff,
                "seed_score_cutoff_source": _score_cutoff_source(tenant_log_path),
            })
            tenant_runs.extend(build_tenant_rings(
                scores_path=tenant_scores, model_dir=inputs["model_dir"],
                gfp_path=inputs["gfp"], embeddings_path=inputs["embeddings"],
                tenant_ids=[tenant], output_dir=seed_dir / "tenant-runs", config=tenant_config,
            ))
        pooled_path = seed_dir / "pooled-rings.parquet"
        pooled_result = research_cli.run_rings(
            scores=inputs["pooled_scores"], model_dir=inputs["model_dir"], aggregator="full",
            gfp=inputs["gfp"], embeddings=inputs["embeddings"], out=pooled_path,
        )
        input_paths.extend([inputs["pooled_scores"], inputs["gfp"], inputs["embeddings"]])
        input_paths.append(inputs["model_dir"] / "model.json")
        tenant_rows = []
        for run in tenant_runs:
            tenant_id = int(run["tenant_id"])
            truth_ids = tenant_truth_ids(ring_banks, tenant_id)
            subset_truth = {ring_id: truth[ring_id] for ring_id in truth
                            if int(ring_id) in set(truth_ids)}
            subset_banks = {ring_id: ring_banks[ring_id] for ring_id in subset_truth}
            with tempfile.TemporaryDirectory(prefix="ringshield-r10-") as temp_dir:
                manifest = Path(temp_dir) / "truth-subset.json"
                manifest.write_text(json.dumps({"truth_ring_ids": truth_ids}), encoding="utf-8")
                pooled_eval = research_cli.eval_rings(
                    rings=pooled_result.rings_path, truth=truth_path, holdout=manifest,
                    window="test", scope="test_visible", out=Path(temp_dir) / "pooled-metrics.json",
                )
                tenant_eval = research_cli.eval_rings(
                    rings=Path(run["rings_path"]), truth=truth_path, holdout=manifest,
                    window="test", scope="test_visible", out=Path(temp_dir) / "tenant-metrics.json",
                )
            tenant_members = _members(Path(run["rings_path"]))
            pooled_members = _members(pooled_result.rings_path)
            bank_count = [len(subset_banks[ring_id]) for ring_id in subset_truth]
            cross_bank_fraction = sum(count > 1 for count in bank_count) / len(bank_count) if bank_count else 0.0
            row = {
                "seed": seed, "tenant_id": tenant_id,
                "n_truth_rings": len(subset_truth),
                "tenant_ring_recall": tenant_eval.metrics["ring_recall"],
                "tenant_ring_recall_ci_low": None,
                "tenant_ring_recall_ci_high": None,
                "tenant_member_coverage": tenant_eval.metrics["member_coverage"],
                "tenant_member_coverage_ci_low": None,
                "tenant_member_coverage_ci_high": None,
                "pooled_ring_recall": pooled_eval.metrics["ring_recall"],
                "pooled_ring_recall_ci_low": None,
                "pooled_ring_recall_ci_high": None,
                "pooled_member_coverage": pooled_eval.metrics["member_coverage"],
                "pooled_member_coverage_ci_low": None,
                "pooled_member_coverage_ci_high": None,
                "tenant_truth_cross_bank_fraction": cross_bank_fraction,
                "tenant_truth_mean_banks_per_ring": (sum(bank_count) / len(bank_count) if bank_count else 0.0),
                "tenant_rings": int(run["rings"]), "pooled_rings": pooled_result.ring_count,
            }
            for prefix, predicted in (("tenant", tenant_members), ("pooled", pooled_members)):
                confidence = bootstrap_ring_metrics(
                    predicted, subset_truth,
                    seed=seed * 1_000_003 + tenant_id, resamples=1000,
                )
                row[f"{prefix}_ring_recall_ci_low"] = confidence["ring_recall"]["low"]
                row[f"{prefix}_ring_recall_ci_high"] = confidence["ring_recall"]["high"]
                row[f"{prefix}_member_coverage_ci_low"] = confidence["member_coverage"]["low"]
                row[f"{prefix}_member_coverage_ci_high"] = confidence["member_coverage"]["high"]
            tenant_rows.append(row)
        all_rows.extend(tenant_rows)
        seed_rows = [row for row in tenant_rows if row["n_truth_rings"] > 0]
        if seed_rows:
            mean_row = {"seed": seed, "tenant_id": "MEAN", "n_truth_rings": sum(row["n_truth_rings"] for row in seed_rows)}
            metric_columns = [key for key in seed_rows[0] if key not in {"seed", "tenant_id", "n_truth_rings"}]
            mean_row.update({key: sum(float(row[key]) for row in seed_rows) / len(seed_rows)
                             for key in metric_columns})
            all_rows.append(mean_row)
        input_paths.append(inputs["pooled_log_path"])

    cross_counts = [len(banks) for banks in ring_banks.values()]
    global_stats = {
        "truth_ring_count": len(truth),
        "cross_bank_truth_fraction": sum(count > 1 for count in cross_counts) / len(cross_counts) if cross_counts else 0.0,
        "mean_banks_per_truth_ring": sum(cross_counts) / len(cross_counts) if cross_counts else 0.0,
    }
    for row in all_rows:
        row.update(global_stats)
    csv_path = output_root / "r10_table.csv"
    md_path = output_root / "r10_table.md"
    write_csv_and_markdown(all_rows, csv_path, md_path)
    run_path = write_run_manifest(output_root, experiment="r10_tenant_vs_pooled",
                                  config=config, inputs=input_paths,
                                  details={"n_seeds": len(seed_inputs),
                                           "seeds": [item["seed"] for item in seed_inputs],
                                           "tenant_ids": tenants, "metrics": global_stats,
                                           "tenant_score_source": inputs["score_source"]})
    return {"n_seeds": len(seed_inputs), "tenant_ids": tenants,
            "csv": str(csv_path), "markdown": str(md_path), "run_json": str(run_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--account-map", type=Path)
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--tenant-score-source", choices=("pooled", "tenant_visible"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(truth_path=args.truth,
                                        account_map=args.account_map, seeds=args.seed,
                                        tenant_score_source=args.tenant_score_source), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"R10 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
