"""Load verified L4 explanation parquet output into tenant-scoped storage.

The adjacent run log is part of the handoff contract. A batch is accepted only
when every explained ring reproduced the shipped full-ring output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from db.models import Explanation, Ring as PlatformRing  # noqa: E402
from db.session import loader_db_session  # noqa: E402
from settings import load_platform_config  # noqa: E402
from contract.schema import RINGS_ORDER  # noqa: E402
from audit import add_audit_event  # noqa: E402

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rings_schema_version(path: Path) -> int:
    """Identify the supported source ring layout from its parquet columns."""
    try:
        columns = pq.ParquetFile(path).schema_arrow.names
    except Exception as exc:
        raise ExplanationLoadError("source tenant rings parquet has an unreadable schema") from exc
    if columns == RINGS_ORDER:
        return 1
    if len(columns) == 30 and len(set(columns)) == 30:
        return 2
    raise ExplanationLoadError(
        "source tenant rings parquet columns do not match schema version 1 "
        "(the exact 22 contract columns) or schema version 2 (the 30-column layout)"
    )


def _forbidden_path(value: Any) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            found = _forbidden_path(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _forbidden_path(item)
            if found:
                return found
    elif isinstance(value, str):
        lowered = value.replace("\\", "/").lower()
        if "ground_truth" in lowered or any(
                part.startswith("labels_") for part in Path(lowered).parts):
            return value
    return None


def _tenant_from_rule(value: Any) -> int | None:
    match = re.match(r"^explicit tenant_id=(\d+)(?:\s|$)", str(value or ""))
    return int(match.group(1)) if match else None


def read_handoff(parquet_path: Path, log_path: Path, rings_log_path: Path) -> tuple[list[dict], dict]:
    for source_path in (parquet_path, log_path, rings_log_path):
        if _forbidden_path(str(source_path)):
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
    forbidden_input = _forbidden_path((log, rings_log))
    if forbidden_input:
        raise ExplanationLoadError(f"label/ground-truth paths are forbidden: {forbidden_input}")
    expected_log_path = Path(str(parquet_path) + ".log.json")
    if expected_log_path.resolve() != log_path.resolve():
        raise ExplanationLoadError("L4 run log must be the sibling .log.json for the supplied parquet")
    if rings_log.get("split") != "test":
        raise ExplanationLoadError("source tenant rings log must declare split=test")
    if log.get("scope") != "tenant":
        raise ExplanationLoadError("L4 run log must declare scope=tenant")
    tenant_id = log.get("tenant_id")
    try:
        tenant_id = int(tenant_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExplanationLoadError("L4 run log must declare an integer tenant_id") from exc
    if log.get("feature_scope") != "tenant_view":
        raise ExplanationLoadError("L4 feature_scope must be tenant_view")

    parquet = pq.ParquetFile(parquet_path)
    names = set(parquet.schema_arrow.names)
    forbidden = sorted(names & FORBIDDEN_COLUMNS)
    missing = sorted(REQUIRED_COLUMNS - names)
    if forbidden:
        raise ExplanationLoadError(f"sensitive/label columns are forbidden: {forbidden}")
    if missing:
        raise ExplanationLoadError(f"explanation file is missing columns: {missing}")

    n_rows = parquet.metadata.num_rows
    if n_rows == 0:
        raise ExplanationLoadError("explanation parquet is empty")
    if log.get("n_explained") != n_rows or log.get("n_rings") != n_rows:
        raise ExplanationLoadError("run log counts do not match the explanation row count")
    if (log.get("n_reproduces_shipped_ring") != log.get("n_rings")
            or log.get("n_rings") != n_rows or log.get("not_reproduced") != []):
        raise ExplanationLoadError("L4 run contains rings that do not reproduce the shipped ring output")
    if (rings_log.get("command") != "run" or not rings_log.get("edge_subset")
            or _tenant_from_rule(rings_log.get("tenant_rule")) is None):
        raise ExplanationLoadError(
            "source rings must come from a tenant-scoped run with an explicit tenant_id"
        )
    output_rings = rings_log.get("out")
    if not output_rings:
        raise ExplanationLoadError("source rings log is missing its out artifact")
    rings_path = rings_log_path.parent / Path(str(output_rings)).name
    if not rings_path.is_file():
        raise ExplanationLoadError("source tenant rings parquet named by its log was not found beside the log")
    try:
        expected_rings_sha = (log.get("input_sha256") or {}).get("rings", {}).get("sha256")
    except AttributeError:
        expected_rings_sha = None
    if not isinstance(expected_rings_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_rings_sha):
        raise ExplanationLoadError("L4 run log is missing input_sha256.rings.sha256")
    if _sha256(rings_path).lower() != expected_rings_sha.lower():
        raise ExplanationLoadError("tenant rings artifact SHA-256 does not match L4 input_sha256.rings")
    source_rings_schema_version = _rings_schema_version(rings_path)
    rings_tenant_id = _tenant_from_rule(rings_log.get("tenant_rule"))
    if rings_tenant_id != tenant_id:
        raise ExplanationLoadError("tenant mismatch between L4 log and source rings log")
    ring_model = rings_log.get("model") or {}
    config = load_platform_config()
    configured_rings_schema_version = config["l4"]["rings_schema_version"]
    if source_rings_schema_version != configured_rings_schema_version:
        raise ExplanationLoadError(
            f"source tenant rings schema version {source_rings_schema_version} does not match "
            f"configured l4.rings_schema_version {configured_rings_schema_version}"
        )
    expected_fx_hash = config.get("fx_rates_sha256")
    if not isinstance(expected_fx_hash, str) or not expected_fx_hash:
        raise ExplanationLoadError("platform config is missing fx_rates_sha256")
    if log.get("fx_rates_sha256") != expected_fx_hash:
        raise ExplanationLoadError("L4 log fx_rates_sha256 does not match platform config")
    if (ring_model.get("model_id") != config["active_model_id"]
            or int(ring_model.get("seed", -1)) != int(config["active_seed"])):
        raise ExplanationLoadError("L4 handoff does not match active_model_id/active_seed in platform config")
    version = log.get("explainer_version")
    if not isinstance(version, str) or not version.strip():
        raise ExplanationLoadError("run log is missing explainer_version")

    rows: list[dict] = []
    seen: set[tuple[int, str]] = set()
    shared_provenance: dict[str, Any] | None = None
    shared_fields = ("aggregator_id", "model_id", "seed", "rings_schema_version",
                     "currency_policy", "explainer_version", "scope", "tenant_id",
                     "feature_scope", "fx_rates_sha256")
    for raw in parquet.iter_batches(batch_size=2_000):
        for source in raw.to_pylist():
            ring_id = str(source["ring_id"])
            tenant_id = int(source["tenant_id"])
            if tenant_id != int(log["tenant_id"]):
                raise ExplanationLoadError(f"{ring_id}: tenant_id does not match L4 log tenant")
            identity = tenant_id, ring_id
            if identity in seen:
                raise ExplanationLoadError(f"duplicate explanation key: {identity}")
            seen.add(identity)
            row_provenance = _json_object(source["provenance"], field="provenance", ring_id=ring_id)
            forbidden_provenance = _forbidden_path(row_provenance)
            if forbidden_provenance:
                raise ExplanationLoadError(
                    f"label/ground-truth paths are forbidden: {forbidden_provenance}"
                )
            row_rings_schema_version = row_provenance.get("rings_schema_version")
            if (not isinstance(row_rings_schema_version, int)
                    or isinstance(row_rings_schema_version, bool)
                    or row_rings_schema_version != source_rings_schema_version):
                raise ExplanationLoadError(
                    f"{ring_id}: explanation row declares rings schema version "
                    f"{row_rings_schema_version!r}, but source tenant rings are version "
                    f"{source_rings_schema_version} (configured version "
                    f"{configured_rings_schema_version})"
                )
            if shared_provenance is None:
                shared_provenance = {key: row_provenance.get(key) for key in shared_fields}
            elif any(row_provenance.get(key) != shared_provenance[key] for key in shared_fields):
                raise ExplanationLoadError(f"{ring_id}: row provenance differs across explanation rows")
            if row_provenance.get("explainer_version") != version:
                raise ExplanationLoadError(f"{ring_id}: row explainer_version does not match the run log")
            if row_provenance.get("scope") != "tenant":
                raise ExplanationLoadError(f"{ring_id}: row provenance scope must be tenant")
            if row_provenance.get("tenant_id") != int(log["tenant_id"]):
                raise ExplanationLoadError(f"{ring_id}: row tenant_id does not match L4 log tenant")
            if row_provenance.get("feature_scope") != "tenant_view":
                raise ExplanationLoadError(f"{ring_id}: row feature_scope must be tenant_view")
            if row_provenance.get("fx_rates_sha256") != expected_fx_hash:
                raise ExplanationLoadError(f"{ring_id}: row fx_rates_sha256 does not match platform config")
            if row_provenance.get("currency_policy") != "converted":
                raise ExplanationLoadError(f"{ring_id}: currency_policy must be converted")
            if row_provenance.get("aggregator_id") != "full":
                raise ExplanationLoadError("only full-aggregator explanation runs can be loaded for tenants")
            if (ring_model.get("aggregator") != row_provenance.get("aggregator_id")
                    or ring_model.get("model_id") != row_provenance.get("model_id")
                    or ring_model.get("seed") != row_provenance.get("seed")):
                raise ExplanationLoadError("L4 and tenant rings run provenance do not match")
            loo = row_provenance.get("loo") or {}
            if loo.get("reproduces_shipped_ring") is not True:
                raise ExplanationLoadError(f"{ring_id}: row provenance does not confirm ring reproduction")
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
            except (TypeError, ValueError, OverflowError) as exc:
                raise ExplanationLoadError(f"{ring_id}: invalid latency") from exc
            if latency_ms < 0:
                raise ExplanationLoadError(f"{ring_id}: latency_ms cannot be negative")
            topology_type = str(source["topology_type"] or "UNKNOWN").strip().upper()
            raw_topology_prob = source["topology_prob"]
            if raw_topology_prob is None:
                topology_prob = None
            else:
                try:
                    topology_prob = float(raw_topology_prob)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ExplanationLoadError(f"{ring_id}: invalid topology_prob") from exc
            if topology_prob is not None and math.isinf(topology_prob):
                raise ExplanationLoadError(f"{ring_id}: topology_prob must not be infinite")
            if topology_prob is not None and math.isnan(topology_prob):
                if topology_type != "UNKNOWN":
                    raise ExplanationLoadError(
                        f"{ring_id}: topology_prob may be NaN only when topology_type is UNKNOWN"
                    )
                topology_prob = None
            elif topology_prob is None and topology_type != "UNKNOWN":
                raise ExplanationLoadError(
                    f"{ring_id}: topology_prob may be null only when topology_type is UNKNOWN"
                )
            elif topology_prob is not None and not 0 <= topology_prob <= 1:
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
                "fx_rates_sha256": expected_fx_hash,
                "_source_topology_type": None if topology_type == "UNKNOWN" else topology_type,
            })
    if shared_provenance is None:
        raise ExplanationLoadError("explanation parquet is empty")
    if (ring_model.get("aggregator") != shared_provenance["aggregator_id"]
            or ring_model.get("model_id") != shared_provenance["model_id"]
            or ring_model.get("seed") != shared_provenance["seed"]):
        raise ExplanationLoadError("L4 and tenant rings run provenance do not match")
    if shared_provenance["tenant_id"] != int(log["tenant_id"]):
        raise ExplanationLoadError("row tenant_id does not match L4 log tenant")
    if len(rows) != n_rows:
        raise ExplanationLoadError("could not read all explanation rows")
    return rows, log


def load_explanations(parquet_path: Path, log_path: Path, rings_log_path: Path) -> dict[str, int]:
    rows, _log = read_handoff(parquet_path, log_path, rings_log_path)
    counts: defaultdict[str, int] = defaultdict(int)
    tenant_ids = {row["tenant_id"] for row in rows}
    load_run_id = uuid4().hex
    if len(tenant_ids) != 1:
        raise ExplanationLoadError("one tenant-scoped explanation handoff must contain exactly one tenant")
    with loader_db_session(tenant_id=next(iter(tenant_ids))) as session:
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
            if (row["_source_topology_type"] is not None
                    and row["_source_topology_type"] != ring.topology_type):
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
                    "fx_rates_sha256",
                )},
            ).returning(Explanation.ring_id))
            if result.first() is None:
                raise ExplanationLoadError(f"{row['ring_id']}: explanation was not written")
            counts["explanations_loaded"] += 1
        add_audit_event(session, tenant_id=next(iter(tenant_ids)), actor="loader",
                        action="explanations.load_completed", entity_type="explanation_load",
                        entity_id=load_run_id,
                        details={"run_id": load_run_id,
                                                 "explanations_loaded": counts["explanations_loaded"],
                                                 "rows_validated": len(rows)})
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
