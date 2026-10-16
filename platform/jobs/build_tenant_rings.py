"""Build tenant-scoped ring artifacts through the existing research CLI.

Each run uses only edges incident to its tenant and passes an explicit tenant ID
to ``ringshield run``. The CLI's run log is retained beside every output ring file.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from ringshield.aggregators.cc import SELECT_COL, threshold_for_pct  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402


class TenantRingBuildError(ValueError):
    """Raised when input data or a tenant-scoped run is invalid."""


def _score_run_log(scores_path: Path, config: dict) -> tuple[dict, float]:
    log_path = Path(str(scores_path) + ".log.json")
    if not log_path.is_file():
        raise TenantRingBuildError(f"scored-edge run log is required: {log_path}")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TenantRingBuildError(f"invalid scored-edge run log: {log_path}") from exc
    if log.get("split") != "test":
        raise TenantRingBuildError("tenant runs accept only score files whose sibling log declares split=test")
    if (log.get("model_id") != config["active_model_id"]
            or int(log.get("seed", -1)) != int(config["active_seed"])):
        raise TenantRingBuildError("scored-edge log does not match the active model/seed in platform config")
    rule = log.get("seed_rule") or {}
    source = str(config.get("seed_score_cutoff_source", ""))
    source_path, separator, source_key = source.rpartition(":")
    expected_source_path = Path(source_path)
    if not expected_source_path.is_absolute():
        expected_source_path = REPO_ROOT / expected_source_path
    if (not separator or source_key != "seed_rule.q"
            or expected_source_path.resolve() != log_path.resolve()):
        raise TenantRingBuildError("seed cutoff source must identify this score log's seed_rule.q")
    cutoff = float(config["seed_score_cutoff"])
    if not math.isclose(float(rule.get("q", float("nan"))), cutoff, rel_tol=0, abs_tol=1e-12):
        raise TenantRingBuildError("configured seed_score_cutoff does not match its recorded source log")
    return log, cutoff


def seed_fraction_for_cutoff(scores: np.ndarray, cutoff: float) -> float:
    """Invert NumPy's linear percentile to reproduce the configured fixed-cut seed mask."""
    values = np.sort(np.asarray(scores, dtype=float)[np.isfinite(scores)])
    if not len(values):
        raise TenantRingBuildError("no finite detector scores are available for seed selection")
    if cutoff > values[-1]:
        # The fixed pooled threshold is above every visible score: no seeds are selected.
        # The CLI has no absolute-cutoff flag, but pct=0 gives the same empty seed mask.
        return 0.0
    if cutoff < values[0]:
        raise TenantRingBuildError(
            f"fixed seed cutoff {cutoff} is outside tenant score range [{values[0]}, {values[-1]}]"
        )
    if len(values) == 1:
        if cutoff != values[0]:
            raise TenantRingBuildError("fixed seed cutoff cannot be represented by this tenant's scores")
        return 0.0
    right = bisect.bisect_left(values.tolist(), cutoff)
    if right < len(values) and values[right] == cutoff:
        rank = float(right)
    else:
        left = right - 1
        rank = left + (cutoff - float(values[left])) / (float(values[right]) - float(values[left]))
    pct = 100.0 * (1.0 - rank / (len(values) - 1))
    actual = threshold_for_pct(values, pct)
    if not np.array_equal(values > actual, values > cutoff):
        raise TenantRingBuildError(
            f"CLI percentile cannot reproduce the fixed seed mask (q={actual}, cutoff={cutoff})"
        )
    return pct


def build_edge_subset(scores_path: Path, tenant_id: int, output_path: Path,
                      score_by_id: dict[int, tuple] | None = None) -> int:
    """Write the edge IDs visible to one bank: either endpoint belongs to it."""
    if not scores_path.is_file():
        raise TenantRingBuildError(f"scored-edge file not found: {scores_path}")
    parquet = pq.ParquetFile(scores_path)
    columns = set(parquet.schema_arrow.names)
    required = {"edge_id", "from_bank", "to_bank"}
    missing = sorted(required - columns)
    if missing:
        raise TenantRingBuildError(f"scored-edge file is missing columns: {missing}")
    if {"true_label", "account_number", "from_account_number", "to_account_number"} & columns:
        raise TenantRingBuildError("labels and account numbers are forbidden in tenant ring inputs")

    edge_ids: list[int] = []
    columns_to_read = ["edge_id", "from_bank", "to_bank"]
    if score_by_id is not None:
        if SELECT_COL not in columns:
            raise TenantRingBuildError(f"scored-edge file is missing detector score column {SELECT_COL}")
        columns_to_read.append(SELECT_COL)
    for batch in parquet.iter_batches(columns=columns_to_read, batch_size=100_000):
        values = batch.to_pydict()
        scores = values.get(SELECT_COL, [None] * len(values["edge_id"]))
        for edge_id, from_bank, to_bank, score in zip(
            values["edge_id"], values["from_bank"], values["to_bank"], scores,
        ):
            if int(from_bank) == tenant_id or int(to_bank) == tenant_id:
                edge_ids.append(int(edge_id))
                if score_by_id is not None:
                    score_by_id[int(edge_id)] = (
                        float(score) if score is not None else float("nan"), int(from_bank), int(to_bank),
                    )
    if not edge_ids:
        raise TenantRingBuildError(f"tenant {tenant_id} has no visible scored edges")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({"edge_id": pa.array(edge_ids, type=pa.int64())})
    pq.write_table(table, output_path, compression="zstd")
    return len(edge_ids)


def _load_model(model_dir: Path) -> dict:
    path = model_dir / "model.json"
    if not path.is_file():
        raise TenantRingBuildError(f"model directory is missing model.json: {model_dir}")
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TenantRingBuildError(f"could not read model metadata: {path}") from exc
    if model.get("aggregator") != "full":
        raise TenantRingBuildError("tenant ring builder currently requires a full-aggregator model")
    if model.get("model_id") is None or model.get("seed") is None:
        raise TenantRingBuildError("model metadata must declare model_id and seed")
    if not (model_dir / "policy" / "policy.txt").is_file():
        raise TenantRingBuildError("full-aggregator model is missing policy/policy.txt")
    if not (model_dir / "affinity" / "affinity.txt").is_file():
        raise TenantRingBuildError("full-aggregator model is missing affinity/affinity.txt")
    return model


def validate_ring_visibility(row: dict, tenant_id: int, subset_ids: set[int], score_by_id: dict[int, tuple]):
    for column in ("member_edges", "seed_edges", "expanded_edges"):
        edge_ids = set(map(int, row.get(column) or []))
        if not edge_ids.issubset(subset_ids):
            raise TenantRingBuildError(f"tenant {tenant_id}: {column} contains edges outside its input subset")
        if any(tenant_id not in score_by_id[edge_id][1:] for edge_id in edge_ids):
            raise TenantRingBuildError(f"tenant {tenant_id}: {column} contains a non-visible edge")


def build_tenant_rings(
    *,
    scores_path: Path,
    model_dir: Path,
    gfp_path: Path,
    embeddings_path: Path,
    tenant_ids: list[int],
    output_dir: Path,
    config: dict | None = None,
) -> list[dict]:
    scores_path = scores_path.resolve()
    model_dir = model_dir.resolve()
    gfp_path = gfp_path.resolve()
    embeddings_path = embeddings_path.resolve()
    output_dir = output_dir.resolve()
    if not tenant_ids or len(tenant_ids) != len(set(tenant_ids)):
        raise TenantRingBuildError("provide one or more distinct --tenant-id values")
    for path, name in ((gfp_path, "GFP features"), (embeddings_path, "embeddings")):
        if not path.is_file():
            raise TenantRingBuildError(f"{name} file not found: {path}")
    config = config or load_platform_config()
    model = _load_model(model_dir)
    if (model["model_id"] != config["active_model_id"]
            or int(model["seed"]) != int(config["active_seed"])):
        raise TenantRingBuildError("model directory does not match active_model_id/active_seed in platform config")
    score_log, cutoff = _score_run_log(scores_path, config)
    if config.get("seed_score_column") != SELECT_COL:
        raise TenantRingBuildError(f"seed_score_column must match the research CLI selection column {SELECT_COL}")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for tenant_id in tenant_ids:
        subset_path = output_dir / f"tenant_{tenant_id}_edge_ids.parquet"
        rings_path = output_dir / f"tenant_{tenant_id}_rings.parquet"
        score_by_id: dict[int, tuple] = {}
        n_subset = build_edge_subset(scores_path, tenant_id, subset_path, score_by_id)
        subset_ids = set(map(int, pq.read_table(subset_path, columns=["edge_id"])["edge_id"].to_pylist()))
        seed_pct = seed_fraction_for_cutoff(
            np.asarray([score_by_id[edge_id][0] for edge_id in sorted(subset_ids)], dtype=float), cutoff,
        )
        expected_seeds = sum(score_by_id[edge_id][0] > cutoff for edge_id in subset_ids)
        command = [
            sys.executable, "-m", "ringshield", "run",
            "--scores", str(scores_path),
            "--edge-subset", str(subset_path),
            "--tenant-id", str(tenant_id),
            "--model-dir", str(model_dir),
            "--aggregator", "full",
            "--seed-frac-pct", format(seed_pct, ".16g"),
            "--gfp", str(gfp_path),
            "--embeddings", str(embeddings_path),
            "--out", str(rings_path),
        ]
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        log_path = Path(str(rings_path) + ".log.json")
        if not rings_path.is_file() or not log_path.is_file():
            raise TenantRingBuildError(f"tenant {tenant_id}: research CLI did not produce rings and a run log")
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TenantRingBuildError(f"tenant {tenant_id}: invalid rings run log") from exc
        expected_rule = f"explicit tenant_id={tenant_id}"
        if (log.get("edge_subset") != str(subset_path)
                or not str(log.get("tenant_rule", "")).startswith(expected_rule)
                or log.get("n_edges_used") != n_subset
                or log.get("aggregator") != "full"):
            raise TenantRingBuildError(f"tenant {tenant_id}: research CLI log failed tenant-scope validation")
        logged_model = log.get("model") or {}
        if (logged_model.get("model_id") != model["model_id"]
                or int(logged_model.get("seed", -1)) != int(model["seed"])
                or logged_model.get("aggregator") != "full"):
            raise TenantRingBuildError(f"tenant {tenant_id}: run log model provenance does not match model.json")
        quantile = log.get("quantile_cut") or {}
        cli_q = float(quantile.get("q", float("nan")))
        expected_mask = {
            edge_id for edge_id in subset_ids if score_by_id[edge_id][0] > cutoff
        }
        cli_mask = {
            edge_id for edge_id in subset_ids if score_by_id[edge_id][0] > cli_q
        }
        if cli_mask != expected_mask or int(quantile.get("n_seeds", -1)) != expected_seeds:
            raise TenantRingBuildError(f"tenant {tenant_id}: research CLI did not apply the fixed configured cutoff")
        log["split"] = "test"
        log["platform_config"] = {
            "path": str(config.get("_path", "platform/config.yaml")),
            "active_model_id": config["active_model_id"],
            "active_seed": int(config["active_seed"]),
            "seed_score_cutoff": cutoff,
            "seed_score_cutoff_source": config["seed_score_cutoff_source"],
            "seed_score_column": SELECT_COL,
            "effective_seed_frac_pct": seed_pct,
            "cli_quantile_q": cli_q,
            "n_seeds": expected_seeds,
            "tenant_assignment_deviation": (
                "Tenant-scoped runs stamp the requested tenant_id explicitly. This differs "
                "from contract/schema.py's sender bank of earliest seed edge, because the same "
                "cross-bank transaction and tenant-visible ring may be copied to both endpoint banks."
            ),
        }
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
        rings = pq.read_table(rings_path, columns=["tenant_id", "member_edges", "seed_edges", "expanded_edges"])
        if any(int(value) != tenant_id for value in rings["tenant_id"].to_pylist()):
            raise TenantRingBuildError(f"tenant {tenant_id}: output rings contain another tenant ID")
        for row in rings.to_pylist():
            validate_ring_visibility(row, tenant_id, subset_ids, score_by_id)
        results.append({
            "tenant_id": tenant_id,
            "visible_edges": n_subset,
            "rings": rings.num_rows,
            "seed_edges": expected_seeds,
            "rings_path": str(rings_path),
            "rings_log_path": str(log_path),
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--gfp", type=Path)
    parser.add_argument("--embeddings", type=Path)
    parser.add_argument("--tenant-id", required=True, action="append", type=int,
                        help="bank code; repeat to build multiple independent tenant runs")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_platform_config(str(args.config) if args.config else None)
        scores = args.scores or configured_path(config, "scored_edges")
        model_dir = args.model_dir or configured_path(config, "model_dir")
        gfp = args.gfp or configured_path(config, "gfp")
        embeddings = args.embeddings or configured_path(config, "embeddings")
        results = build_tenant_rings(
            scores_path=scores,
            model_dir=model_dir,
            gfp_path=gfp,
            embeddings_path=embeddings,
            tenant_ids=args.tenant_id,
            output_dir=args.output_dir,
            config=config,
        )
    except (TenantRingBuildError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
