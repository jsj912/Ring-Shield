"""Lossless transaction payload round-trip against the CI PostgreSQL roles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.load_contract import load_edges  # noqa: E402


def test_unknown_scored_edge_fields_round_trip_through_transaction_payload(
        tmp_path, repo_platform_config, register_db_test_ids):
    fixture_dir = Path(os.environ["RINGSHIELD_TEST_FIXTURE_DIR"])
    source_path = fixture_dir / "scored_edges.parquet"
    source = pq.read_table(source_path)
    row = next(item for item in source.to_pylist()
               if item["from_bank"] == 210 or item["to_bank"] == 210)
    run_log = json.loads(Path(str(source_path) + ".log.json").read_text(encoding="utf-8"))
    edge_id = 980_000_000 + uuid4().int % 10_000_000
    from_id = 980_000_000 + uuid4().int % 10_000_000
    to_id = from_id + 1
    marker = {"origin": "roundtrip-test", "nested": {"revision": 7}}
    row.update(edge_id=edge_id, from_id=from_id, to_id=to_id,
               platform_future_field=marker)
    path = tmp_path / "scored_edges_extra_column.parquet"
    pq.write_table(pa.Table.from_pylist([row]), path)
    Path(str(path) + ".log.json").write_text(json.dumps(run_log), encoding="utf-8")
    register_db_test_ids(str(edge_id), "platform_future_field_roundtrip")
    test_started_at = datetime.now(timezone.utc)

    load_edges(path, scope="tenant", tenant_id=210)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin.connect() as connection:
            payload = connection.execute(text("""
                SELECT payload FROM transactions
                WHERE tenant_id = 210 AND edge_id = :edge_id
            """), {"edge_id": edge_id}).scalar_one()
            assert payload["platform_future_field"] == marker
    finally:
        admin.dispose()
        cleanup_engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
        try:
            with cleanup_engine.begin() as connection:
                connection.execute(text("""
                    DELETE FROM audit_log
                    WHERE tenant_id = 210 AND action = 'contract.load_completed'
                      AND at >= :started_at
                """), {"started_at": test_started_at})
                connection.execute(text("DELETE FROM edge_scores WHERE tenant_id=210 AND edge_id=:id"),
                                   {"id": edge_id})
                connection.execute(text("DELETE FROM transactions WHERE tenant_id=210 AND edge_id=:id"),
                                   {"id": edge_id})
                connection.execute(text("DELETE FROM accounts WHERE tenant_id=210 AND account_id IN (:a,:b)"),
                                   {"a": from_id, "b": to_id})
        finally:
            cleanup_engine.dispose()
