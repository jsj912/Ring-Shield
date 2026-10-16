"""Idempotently load contract parquets into tenant-isolated PostgreSQL tables.

Visibility comes from either endpoint bank, never from scored_edges.tenant_id.
Ground-truth files are intentionally not accepted by this command.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402
from db.models import Account, EdgeScore, Ring as PlatformRing, Tenant, Transaction  # noqa: E402
from db.session import loader_db_session  # noqa: E402
from settings import load_platform_config  # noqa: E402

BATCH_SIZE = 10_000
FORBIDDEN_COLUMNS = {"account_number", "from_account_number", "to_account_number", "true_label"}


class ContractLoadError(ValueError):
    pass


def _python_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "as_py"):
        value = value.as_py()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, list, tuple, dict)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _python_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_python_value(v) for v in value]
    return value


def _check_file(path: Path, required: Iterable[str]) -> tuple[pq.ParquetFile, dict]:
    lowered_path = str(path).replace("\\", "/").lower()
    if any(part.startswith("labels_") for part in Path(lowered_path).parts) or "ground_truth" in lowered_path:
        raise ContractLoadError(f"label/ground-truth paths are forbidden: {path}")
    if not path.is_file():
        raise ContractLoadError(f"contract file not found: {path}")
    log_path = Path(str(path) + ".log.json")
    if not log_path.is_file():
        raise ContractLoadError(f"run log is required beside contract file: {log_path}")
    try:
        run_log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractLoadError(f"invalid contract run log: {log_path}") from exc
    if run_log.get("split") != "test":
        raise ContractLoadError(f"{path}: sibling run log must declare split=test")
    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    forbidden = sorted(names & FORBIDDEN_COLUMNS)
    missing = sorted(set(required) - names)
    if forbidden:
        raise ContractLoadError(f"{path}: sensitive/label columns are forbidden: {forbidden}")
    if missing:
        raise ContractLoadError(f"{path}: missing contract columns: {missing}")
    return parquet, run_log


def _account_upserts(session, accounts: dict[tuple[int, int], tuple[int, int, int]]) -> None:
    if not accounts:
        return
    values = [
        {"tenant_id": tenant, "account_id": account, "bank_code": bank,
         "first_seen": first_seen, "last_seen": last_seen}
        for (tenant, account), (bank, first_seen, last_seen) in accounts.items()
    ]
    stmt = insert(Account).values(values)
    session.execute(stmt.on_conflict_do_update(
        index_elements=[Account.tenant_id, Account.account_id],
        set_={
            "bank_code": stmt.excluded.bank_code,
            "first_seen": func.least(Account.first_seen, stmt.excluded.first_seen),
            "last_seen": func.greatest(Account.last_seen, stmt.excluded.last_seen),
        },
    ))


def load_edges(path: Path, *, scope: str, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    parquet, run_log = _check_file(path, SCORED_EDGES_ORDER)
    if "tenant_id" not in parquet.schema_arrow.names:
        raise ContractLoadError(f"{path}: scored_edges requires tenant_id in its contract")

    counts = defaultdict(int)
    with loader_db_session() as session:
        if scope == "pooled":
            tenant_ids = {-1}
            if session.get(Tenant, -1) is None:
                raise ContractLoadError("reserved pooled tenant is missing; apply the platform migration")
        else:
            tenant_ids = set(session.scalars(select(Tenant.tenant_id).where(Tenant.is_loaded.is_(True))))
            if not tenant_ids:
                raise ContractLoadError("no tenants are marked is_loaded; provision the selected tenant registry first")

        for record_batch in parquet.iter_batches(batch_size=batch_size):
            transaction_rows: list[dict] = []
            edge_score_rows: list[dict] = []
            account_stats: dict[tuple[int, int], tuple[int, int, int]] = {}
            for source in record_batch.to_pylist():
                if (run_log.get("model_id") is not None
                        and str(source.get("model_id")) != str(run_log["model_id"])):
                    raise ContractLoadError("scored-edge row model_id does not match its sibling run log")
                if (run_log.get("seed") is not None
                        and int(source.get("seed", -1)) != int(run_log["seed"])):
                    raise ContractLoadError("scored-edge row seed does not match its sibling run log")
                from_bank = int(source["from_bank"])
                to_bank = int(source["to_bank"])
                timestamp = int(source["timestamp"])
                visible_tenants = ({-1} if scope == "pooled" else ({from_bank, to_bank} & tenant_ids))
                for tenant_id in visible_tenants:
                    row = {key: _python_value(value) for key, value in source.items()}
                    row["tenant_id"] = tenant_id
                    transaction_rows.append({
                        "tenant_id": tenant_id,
                        "edge_id": int(source["edge_id"]),
                        "from_id": int(source["from_id"]),
                        "to_id": int(source["to_id"]),
                        "from_bank": from_bank,
                        "to_bank": to_bank,
                        "timestamp": timestamp,
                        "amount_sent": _python_value(source.get("amount_sent")),
                        "amount_received": _python_value(source.get("amount_received")),
                        "currency_sent": _python_value(source.get("currency_sent")),
                        "currency_received": _python_value(source.get("currency_received")),
                        "payment_format": _python_value(source.get("payment_format")),
                        "payload": {key: value for key, value in row.items()
                                    if key not in {"score_raw", "score_calibrated", "is_seed", "model_id", "seed"}},
                    })
                    edge_score_rows.append({
                        "tenant_id": tenant_id,
                        "edge_id": int(source["edge_id"]),
                        "model_id": str(source["model_id"]),
                        "seed": int(source["seed"]),
                        "score_raw": _python_value(source.get("score_raw")),
                        "score_calibrated": _python_value(source.get("score_calibrated")),
                        "is_seed": _python_value(source.get("is_seed")),
                        "payload": {"selection_column": "score_raw"},
                    })
                    for account_id, bank_code in ((int(source["from_id"]), from_bank),
                                                  (int(source["to_id"]), to_bank)):
                        key = (tenant_id, account_id)
                        prior = account_stats.get(key)
                        if prior is None:
                            account_stats[key] = (bank_code, timestamp, timestamp)
                        else:
                            account_stats[key] = (bank_code, min(prior[1], timestamp),
                                                  max(prior[2], timestamp))

            if transaction_rows:
                stmt = insert(Transaction).values(transaction_rows)
                update_columns = {
                    col: getattr(stmt.excluded, col)
                    for col in ("from_id", "to_id", "from_bank", "to_bank", "timestamp",
                                "amount_sent", "amount_received", "currency_sent", "currency_received",
                                "payment_format", "payload")
                }
                session.execute(stmt.on_conflict_do_update(
                    index_elements=[Transaction.tenant_id, Transaction.edge_id], set_=update_columns,
                ))
                score_stmt = insert(EdgeScore).values(edge_score_rows)
                session.execute(score_stmt.on_conflict_do_update(
                    index_elements=[EdgeScore.tenant_id, EdgeScore.edge_id, EdgeScore.model_id, EdgeScore.seed],
                    set_={key: getattr(score_stmt.excluded, key) for key in (
                        "score_raw", "score_calibrated", "is_seed", "payload",
                    )},
                ))
                _account_upserts(session, account_stats)
                counts["visible_edge_rows"] += len(transaction_rows)
                counts["edge_score_rows"] += len(edge_score_rows)
                counts["unique_source_edges"] += len(record_batch)
                counts["account_tenant_rows"] += len(account_stats)
    return dict(counts)


def _ring_metadata(session, tenant_id: int, ring_row: dict, config: dict) -> tuple[str, int]:
    seed_edges = [int(edge_id) for edge_id in (ring_row.get("seed_edges") or [])]
    if not seed_edges:
        raise ContractLoadError(f"{ring_row['ring_id']}: ring has no seed_edges")
    metadata = set(session.execute(
        select(EdgeScore.model_id, EdgeScore.seed)
        .where(EdgeScore.tenant_id == tenant_id, EdgeScore.edge_id.in_(seed_edges),
               EdgeScore.model_id == config["active_model_id"],
               EdgeScore.seed == int(config["active_seed"]))
    ).all())
    if len(metadata) != 1:
        raise ContractLoadError(
            f"{ring_row['ring_id']}: seed edges are missing or span multiple detector model/seed pairs"
        )
    model_id, seed = next(iter(metadata))
    return str(model_id), int(seed)


def load_rings(path: Path, *, scope: str) -> dict[str, int]:
    parquet, _run_log = _check_file(path, RINGS_ORDER)
    config = load_platform_config()
    counts = defaultdict(int)
    seen_ring_ids: set[tuple[int, str]] = set()
    with loader_db_session() as session:
        loaded_tenants = set(session.scalars(select(Tenant.tenant_id).where(Tenant.is_loaded.is_(True))))
        for record_batch in parquet.iter_batches(batch_size=2_000):
            for raw in record_batch.to_pylist():
                row = {key: _python_value(value) for key, value in raw.items()}
                source_tenant_id = int(row["tenant_id"])
                tenant_id = -1 if scope == "pooled" else source_tenant_id
                row["tenant_id"] = tenant_id
                identity = (tenant_id, str(row["ring_id"]))
                if identity in seen_ring_ids:
                    raise ContractLoadError(f"duplicate ring key in input: {identity}")
                seen_ring_ids.add(identity)
                if scope == "tenant" and tenant_id not in loaded_tenants:
                    raise ContractLoadError(
                        f"{row['ring_id']}: tenant_id {tenant_id} is not marked is_loaded; "
                        "tenant ring files must come from a run with --tenant-id"
                    )
                member_edges = [int(edge_id) for edge_id in (row.get("member_edges") or [])]
                if not member_edges:
                    raise ContractLoadError(f"{row['ring_id']}: ring has no member_edges")
                if len(member_edges) != len(set(member_edges)):
                    raise ContractLoadError(f"{row['ring_id']}: member_edges contains duplicates")
                seed_edges = [int(edge_id) for edge_id in (row.get("seed_edges") or [])]
                expanded_edges = [int(edge_id) for edge_id in (row.get("expanded_edges") or [])]
                if not set(seed_edges) <= set(member_edges):
                    raise ContractLoadError(f"{row['ring_id']}: seed_edges must be a subset of member_edges")
                if not set(expanded_edges) <= set(member_edges):
                    raise ContractLoadError(f"{row['ring_id']}: expanded_edges must be a subset of member_edges")
                if set(seed_edges) & set(expanded_edges):
                    raise ContractLoadError(f"{row['ring_id']}: seed and expanded edges must be disjoint")
                visible = set(session.scalars(
                    select(Transaction.edge_id).where(
                        Transaction.tenant_id == tenant_id,
                        Transaction.edge_id.in_(member_edges),
                    )
                ))
                if visible != set(member_edges):
                    missing = sorted(set(member_edges) - visible)
                    raise ContractLoadError(
                        f"{row['ring_id']}: member edges are not all visible to tenant {tenant_id}: {missing[:8]}"
                    )
                bank_pairs = session.execute(
                    select(Transaction.from_bank, Transaction.to_bank).where(
                        Transaction.tenant_id == tenant_id,
                        Transaction.edge_id.in_(member_edges),
                    )
                ).all()
                member_banks = {int(bank) for pair in bank_pairs for bank in pair}
                counterparties = member_banks - ({tenant_id} if scope == "tenant" else set())
                row["cross_bank"] = len(member_banks) > 1
                row["counterparty_banks"] = [f"Bank {bank}" for bank in sorted(counterparties)]
                currency_rows = session.execute(
                    select(Transaction.currency_sent, Transaction.currency_received).where(
                        Transaction.tenant_id == tenant_id, Transaction.edge_id.in_(member_edges),
                    )
                ).all()
                currencies = {int(currency) for pair in currency_rows for currency in pair if currency is not None}
                row["n_currencies"] = len(currencies) or None
                if len(currencies) > 1:
                    row["total_amount"] = None
                    row["total_currency"] = None
                model_id, seed = _ring_metadata(session, tenant_id, row, config)
                if (model_id, seed) != (config["active_model_id"], int(config["active_seed"])):
                    raise ContractLoadError(
                        f"{row['ring_id']}: ring does not match active_model_id/active_seed in platform config"
                    )
                values = {
                    "tenant_id": tenant_id,
                    "ring_id": str(row["ring_id"]),
                    "model_id": model_id,
                    "aggregator_id": str(row["aggregator_id"]),
                    "seed": seed,
                    "scope": scope,
                    "member_accounts": [int(v) for v in row.get("members", [])],
                    "member_edges": member_edges,
                    "seed_edges": seed_edges,
                    "expanded_edges": expanded_edges,
                    "confidence": float(row["confidence"]),
                    "conservation_closure": row.get("conservation_closure"),
                    "topology_type": str(row.get("topology_type") or "UNKNOWN"),
                    "topology_probs": [float(v) for v in (row.get("topology_probs") or [])],
                    "start_time": int(row["start_time"]),
                    "end_time": int(row["end_time"]),
                    "payload": {**row, "scope": scope},
                }
                if len(values["topology_probs"]) != 8:
                    raise ContractLoadError(f"{row['ring_id']}: topology_probs must contain eight values")
                stmt = insert(PlatformRing).values(values)
                updates = {k: getattr(stmt.excluded, k) for k in (
                    "model_id", "aggregator_id", "seed", "scope", "member_accounts", "member_edges",
                    "seed_edges", "expanded_edges", "confidence", "conservation_closure", "topology_type",
                    "topology_probs", "start_time", "end_time", "payload",
                )}
                result = session.execute(stmt.on_conflict_do_update(
                    index_elements=[PlatformRing.tenant_id, PlatformRing.ring_id],
                    set_=updates,
                    where=PlatformRing.status == "open",
                ))
                counts["rings_loaded"] += result.rowcount or 0
                counts["rings_preserved_after_verdict"] += 0 if result.rowcount else 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored-edges", required=True, type=Path)
    parser.add_argument("--rings", type=Path)
    parser.add_argument("--scope", choices=("tenant", "pooled"), default="tenant",
                        help="tenant copies visible edges per loaded bank; pooled stores a full graph under internal tenant -1")
    args = parser.parse_args(argv)
    try:
        result = {"edges": load_edges(args.scored_edges, scope=args.scope)}
        if args.rings:
            result["rings"] = load_rings(args.rings, scope=args.scope)
    except (ContractLoadError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
