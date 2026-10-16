"""Load verified L4 explanation parquet output into tenant-scoped storage.

The adjacent run log is part of the handoff contract. A batch is accepted only
when every explained ring reproduced the shipped full-ring output.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from db.models import Explanation, Ring as PlatformRing  # noqa: E402
from db.session import loader_db_session  # noqa: E402
from settings import load_platform_config  # noqa: E402

REQUIRED_COLUMNS = {
    "ring_id", "tenant_id", "edge_weights", "account_weights", "feature_weights",
    "topology_type", "topology_prob", "narrative", "evidence_summary", "latency_ms",
    "provenance",
}
FORBIDDEN_COLUMNS = {"account_number", "from_account_number", "to_account_number", "true_label"}


class ExplanationLoadError(ValueError):
    """Raised when an explanation handoff is malformed or not reproducible."""


def _finite_json(value: Any, *, path: str) -> Any:
    """Convert Arrow values to JSON-safe Python values, rejecting nonfinite numbers."""
    if value is None:
        return None
    if hasattr(value, "as_py"):
        value = value.as_py()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, list, tuple, dict)):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _finite_json(item, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def _json_object(value: Any, *, field: str, ring_id: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ExplanationLoadError(f"{ring_id}: {field} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ExplanationLoadError(f"{ring_id}: {field} must be a JSON object")
    return _finite_json(value, path=field)


def read_handoff(parquet_path: Path, log_path: Path, rings_log_path: Path) -> tuple[list[dict], dict]:
    for source_path in (parquet_path, log_path, rings_log_path):
        lowered = str(source_path).replace("\\", "/").lower()
        if any(part.startswith("labels_") for part in Path(lowered).parts) or "ground_truth" in lowered:
            raise ExplanationLoadError(f"label/ground-truth paths are forbidden: {source_path}")
    if not parquet_path.is_file():
        raise ExplanationLoadError(f"explanation parquet not found: {parquet_path}")
    if not log_path.is_file():
        raise ExplanationLoadError(f"L4 run log not found: {log_path}")
    if not rings_log_path.is_file():
        raise ExplanationLoadError(f"source rings run log not found: {rings_log_path}")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
        rings_log = json.loads(rings_log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExplanationLoadError("could not read L4 or source rings run log") from exc
    expected_log_path = Path(str(parquet_path) + ".log.json")
    if expected_log_path.resolve() != log_path.resolve():
        raise ExplanationLoadError("L4 run log must be the sibling .log.json for the supplied parquet")
    if log.get("split") != "test":
        raise ExplanationLoadError("L4 run log must declare split=test")
    if rings_log.get("split") != "test":
        raise ExplanationLoadError("source tenant rings log must declare split=test")

    parquet = pq.ParquetFile(parquet_path)
    names = set(parquet.schema_arrow.names)
    forbidden = sorted(names & FORBIDDEN_COLUMNS)
    missing = sorted(REQUIRED_COLUMNS - names)
    if forbidden:
        raise ExplanationLoadError(f"sensitive/label columns are forbidden: {forbidden}")
    if missing:
        raise ExplanationLoadError(f"explanation file is missing columns: {missing}")

    provenance = log.get("provenance") or {}
    n_rows = parquet.metadata.num_rows
    if n_rows == 0:
        raise ExplanationLoadError("explanation parquet is empty")
    if log.get("n_explained") != n_rows or log.get("n_rings") != n_rows:
        raise ExplanationLoadError("run log counts do not match the explanation row count")
    if log.get("n_reproduces_shipped_ring") != n_rows or log.get("not_reproduced"):
        raise ExplanationLoadError("L4 run contains rings that do not reproduce the shipped ring output")
    if provenance.get("rings_schema_version") != 2:
        raise ExplanationLoadError("L4 run must use rings schema version 2")
    if provenance.get("aggregator_id") != "full":
        raise ExplanationLoadError("only full-aggregator explanation runs can be loaded for tenants")
    if log.get("policy") != "converted":
        raise ExplanationLoadError("L4 run currency policy must be 'converted'")
    if (rings_log.get("command") != "run" or not rings_log.get("edge_subset")
            or not str(rings_log.get("tenant_rule", "")).startswith("explicit tenant_id=")):
        raise ExplanationLoadError(
            "source rings must come from a tenant-scoped run with an explicit tenant_id"
        )
    source_rings = (log.get("inputs") or {}).get("rings")
    output_rings = rings_log.get("out")
    if (not source_rings or not output_rings
            or Path(str(source_rings)).name.lower() != Path(str(output_rings)).name.lower()):
        raise ExplanationLoadError("L4 run log does not point to the supplied tenant rings artifact")
    ring_model = rings_log.get("model") or {}
    config = load_platform_config()
    if (ring_model.get("aggregator") != provenance.get("aggregator_id")
            or ring_model.get("model_id") != provenance.get("model_id")
            or ring_model.get("seed") != provenance.get("seed")):
        raise ExplanationLoadError("L4 and tenant rings run provenance do not match")
    if (ring_model.get("model_id") != config["active_model_id"]
            or int(ring_model.get("seed", -1)) != int(config["active_seed"])):
        raise ExplanationLoadError("L4 handoff does not match active_model_id/active_seed in platform config")
    version = log.get("explainer_version")
    if not isinstance(version, str) or not version.strip():
        raise ExplanationLoadError("run log is missing explainer_version")

    rows: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for raw in parquet.iter_batches(batch_size=2_000):
        for source in raw.to_pylist():
            ring_id = str(source["ring_id"])
            tenant_id = int(source["tenant_id"])
            identity = tenant_id, ring_id
            if identity in seen:
                raise ExplanationLoadError(f"duplicate explanation key: {identity}")
            seen.add(identity)
            row_provenance = _json_object(source["provenance"], field="provenance", ring_id=ring_id)
            expected = (provenance.get("aggregator_id"), provenance.get("model_id"),
                        provenance.get("seed"), version)
            actual = (row_provenance.get("aggregator_id"), row_provenance.get("model_id"),
                      row_provenance.get("seed"), row_provenance.get("explainer_version"))
            if actual != expected:
                raise ExplanationLoadError(f"{ring_id}: row provenance does not match the run log")
            loo = row_provenance.get("loo") or {}
            if loo.get("reproduces_shipped_ring") is not True:
                raise ExplanationLoadError(f"{ring_id}: row provenance does not confirm ring reproduction")
            if row_provenance.get("rings_schema_version") != 2:
                raise ExplanationLoadError(f"{ring_id}: row provenance does not declare rings schema version 2")
            edges = _finite_json(source["edge_weights"], path=f"{ring_id}.edge_weights") or []
            accounts = _finite_json(source["account_weights"], path=f"{ring_id}.account_weights") or []
            features = _finite_json(source["feature_weights"], path=f"{ring_id}.feature_weights") or []
            if not all(isinstance(part, list) for part in (edges, accounts, features)):
                raise ExplanationLoadError(f"{ring_id}: weight columns must be lists")
            if any(not isinstance(item, dict) for item in features):
                raise ExplanationLoadError(f"{ring_id}: feature_weights entries must be objects")
            for field, items, id_key in (("edge_weights", edges, "edge_id"),
                                         ("account_weights", accounts, "account_id")):
                for item in items:
                    if not isinstance(item, dict) or item.get(id_key) is None:
                        raise ExplanationLoadError(f"{ring_id}: {field} entries need {id_key}")
                    try:
                        item[id_key] = int(item[id_key])
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise ExplanationLoadError(f"{ring_id}: {field} contains an invalid {id_key}") from exc
            evidence = _json_object(source["evidence_summary"], field="evidence_summary", ring_id=ring_id)
            try:
                latency_ms = int(source["latency_ms"])
                topology_prob = float(source["topology_prob"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ExplanationLoadError(f"{ring_id}: invalid latency or topology probability") from exc
            if latency_ms < 0:
                raise ExplanationLoadError(f"{ring_id}: latency_ms cannot be negative")
            if not math.isfinite(topology_prob) or not 0 <= topology_prob <= 1:
                raise ExplanationLoadError(f"{ring_id}: topology_prob must be finite and between 0 and 1")
            rows.append({
                "tenant_id": tenant_id,
                "ring_id": ring_id,
                "explainer_version": version,
                "edge_weights": edges,
                "account_weights": accounts,
                "feature_weights": features,
                "narrative": str(source["narrative"] or ""),
                "evidence_summary": evidence,
                "latency_ms": latency_ms,
                "provenance": row_provenance,
                "_source_topology_type": str(source["topology_type"] or "UNKNOWN"),
            })
    if len(rows) != n_rows:
        raise ExplanationLoadError("could not read all explanation rows")
    return rows, log


def load_explanations(parquet_path: Path, log_path: Path, rings_log_path: Path) -> dict[str, int]:
    rows, _log = read_handoff(parquet_path, log_path, rings_log_path)
    counts: defaultdict[str, int] = defaultdict(int)
    with loader_db_session() as session:
        for row in rows:
            ring = session.get(PlatformRing, {
                "tenant_id": row["tenant_id"], "ring_id": row["ring_id"],
            })
            if ring is None or ring.scope != "tenant":
                raise ExplanationLoadError(
                    f"{row['ring_id']}: matching tenant ring must be loaded before explanations"
                )
            provenance = row["provenance"]
            if (ring.aggregator_id, ring.model_id, ring.seed) != (
                provenance["aggregator_id"], provenance["model_id"], provenance["seed"],
            ):
                raise ExplanationLoadError(f"{row['ring_id']}: row does not match loaded ring metadata")
            if row["_source_topology_type"] != ring.topology_type:
                raise ExplanationLoadError(f"{row['ring_id']}: explanation topology does not match loaded ring")
            member_accounts = set(map(int, ring.member_accounts or []))
            member_edges = set(map(int, ring.member_edges or []))
            invalid_edges = [item["edge_id"] for item in row["edge_weights"]
                             if item["edge_id"] not in member_edges]
            invalid_accounts = [item["account_id"] for item in row["account_weights"]
                                if item["account_id"] not in member_accounts]
            if invalid_edges or invalid_accounts:
                raise ExplanationLoadError(
                    f"{row['ring_id']}: explanation weights reference nonmember edges/accounts"
                )
            if any(item.get("top_edge_id") is not None
                   and int(item["top_edge_id"]) not in member_edges
                   for item in row["feature_weights"]):
                raise ExplanationLoadError(f"{row['ring_id']}: feature weight references a nonmember edge")
            values = {key: value for key, value in row.items() if not key.startswith("_")}
            stmt = insert(Explanation).values(values)
            result = session.execute(stmt.on_conflict_do_update(
                index_elements=[Explanation.tenant_id, Explanation.ring_id, Explanation.explainer_version],
                set_={key: getattr(stmt.excluded, key) for key in (
                    "edge_weights", "account_weights", "feature_weights", "narrative",
                    "evidence_summary", "latency_ms", "provenance",
                )},
            ))
            counts["explanations_loaded"] += result.rowcount or 0
    counts["rows_validated"] = len(rows)
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explanations", required=True, type=Path)
    parser.add_argument("--run-log", required=True, type=Path)
    parser.add_argument("--rings-log", required=True, type=Path,
                        help="run log beside the tenant-scoped rings parquet used by L4")
    args = parser.parse_args(argv)
    try:
        print(load_explanations(args.explanations, args.run_log, args.rings_log))
    except (ExplanationLoadError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
