"""PostgreSQL acceptance for safe tenant ring refreshes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs import load_contract, refresh_rings

TENANT_A = 210
TENANT_B = 220


def _ring_json(engine, tenant_id: int, ring_id: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT row_to_json(r)::text FROM rings AS r
            WHERE r.tenant_id = :tenant_id AND r.ring_id = :ring_id
        """), {"tenant_id": tenant_id, "ring_id": ring_id}).scalar_one_or_none()


def _tenant_ring_rows(engine, tenant_id: int) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(text("""
            SELECT row_to_json(r)::text FROM rings AS r
            WHERE r.tenant_id = :tenant_id ORDER BY r.ring_id
        """), {"tenant_id": tenant_id}).scalars())


def _tenant_table_rows(engine, table: str, tenant_id: int) -> list[str]:
    quoted_table = engine.dialect.identifier_preparer.quote(table)
    with engine.connect() as connection:
        return list(connection.execute(text(
            f"SELECT row_to_json(row_data)::text FROM ("
            f"SELECT * FROM public.{quoted_table} WHERE tenant_id = :tenant_id) row_data "
            "ORDER BY row_to_json(row_data)::text"
        ), {"tenant_id": tenant_id}).scalars())


def test_refresh_updates_open_preserves_verdict_rings_and_isolates_tenant_rows(
        monkeypatch, tmp_path, register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    run_id = uuid4().hex
    open_ring_id = f"refresh-open-{run_id}"
    model_version_tag = f"v2-refresh-{run_id[:8]}"
    register_db_test_ids(run_id, open_ring_id, model_version_tag,
                         f"full-demo-model-7-v2-refresh-{run_id[:8]}-")
    model_dir = tmp_path / "promoted-model"
    model_dir.mkdir()
    model_version_id = None
    created_ring_ids: list[str] = []
    fixture_dir = Path(os.environ["RINGSHIELD_TEST_FIXTURE_DIR"])

    try:
        with admin.begin() as connection:
            model_version_id = connection.execute(text("""
                INSERT INTO model_versions
                  (tenant_id, component, version_tag, trained_at, train_label_count,
                   holdout_ring_f1, promoted, artifact_path)
                VALUES (:tenant_id, 'typing', :tag, now(), 0, 0.95, true, :artifact_path)
                RETURNING model_version_id
            """), {"tenant_id": TENANT_A, "tag": model_version_tag,
                  "artifact_path": str(model_dir)}).scalar_one()
            connection.execute(text("""
                INSERT INTO rings
                  (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
                   member_accounts, member_edges, seed_edges, expanded_edges,
                   confidence, conservation_closure, topology_type, topology_probs,
                   start_time, end_time, status, payload)
                SELECT tenant_id, :ring_id, model_id, aggregator_id, seed, scope,
                       ARRAY[101, 102]::bigint[], ARRAY[2]::bigint[], ARRAY[2]::bigint[],
                       ARRAY[]::bigint[], 0.25, conservation_closure, topology_type,
                       topology_probs, start_time, end_time, 'open', payload
                FROM rings WHERE tenant_id = :tenant_id AND ring_id = 'demo-cycle'
            """), {"tenant_id": TENANT_A, "ring_id": open_ring_id})

        # The fixture verdict ring may have an open status; the verdict itself is
        # the protected signal and must keep it out of roll-forward matching.
        with admin.connect() as connection:
            verdict_ring_ids = set(connection.execute(text(
                "SELECT DISTINCT ring_id FROM verdicts WHERE tenant_id = :tenant_id"
            ), {"tenant_id": TENANT_A}).scalars())
        assert "demo-cycle" in verdict_ring_ids
        before_verdict_rings = {ring_id: _ring_json(admin, TENANT_A, ring_id)
                                for ring_id in verdict_ring_ids}
        with admin.connect() as connection:
            tenant_tables = tuple(connection.execute(text("""
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'tenant_id'
                GROUP BY table_name ORDER BY table_name
            """)).scalars())
        before_tenant_b = {
            table: _tenant_table_rows(admin, table, TENANT_B) for table in tenant_tables
        }
        before_tenant_a = {
            json.loads(row)["ring_id"]: row for row in _tenant_ring_rows(admin, TENANT_A)
        }
        before_ids = set(before_tenant_a)
        before_open = json.loads(_ring_json(admin, TENANT_A, open_ring_id))

        config = {
            "active_model_id": "demo-model",
            "active_seed": 7,
            "scored_edges": str(fixture_dir / "scored_edges.parquet"),
            "gfp": str(fixture_dir / "gfp.parquet"),
            "embeddings": str(fixture_dir / "embeddings.parquet"),
        }
        source = pq.read_table(fixture_dir / "rings.parquet")
        original = next(row for row in source.to_pylist() if row["tenant_id"] == TENANT_A)
        open_candidate = dict(original)
        open_candidate.update({
            "ring_id": "candidate-open",
            "members": [101, 102],
            "n_members": 2,
            "member_edges": [2],
            "seed_edges": [2],
            "expanded_edges": [],
            "confidence": 0.99,
        })
        verdict_candidate = dict(original)
        verdict_candidate["ring_id"] = "demo-cycle"
        verdict_candidate["confidence"] = 0.88

        monkeypatch.setattr(refresh_rings, "load_platform_config", lambda: config)
        monkeypatch.setattr(load_contract, "load_platform_config", lambda: config)
        monkeypatch.setattr(refresh_rings, "PLATFORM_ROOT", tmp_path / "platform")

        def fake_builder(**kwargs):
            assert kwargs["tenant_ids"] == [TENANT_A]
            assert kwargs["model_dir"] == model_dir
            kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
            rings_path = kwargs["output_dir"] / "tenant-210-rings.parquet"
            pq.write_table(pa.Table.from_pylist(
                [open_candidate, verdict_candidate], schema=source.schema,
            ), rings_path)
            Path(str(rings_path) + ".log.json").write_text(
                json.dumps({"split": "test"}), encoding="utf-8",
            )
            return [{"tenant_id": TENANT_A, "rings_path": rings_path}]

        monkeypatch.setattr(refresh_rings, "build_tenant_rings", fake_builder)
        result = refresh_rings.refresh_tenant_rings(TENANT_A, model_version_id, run_id)

        assert result["rings_loaded"] == 2  # one in-place update and one new ring, via RETURNING
        after_tenant_b = {
            table: _tenant_table_rows(admin, table, TENANT_B) for table in tenant_tables
        }
        assert after_tenant_b == before_tenant_b
        after_verdict_rings = {ring_id: _ring_json(admin, TENANT_A, ring_id)
                               for ring_id in verdict_ring_ids}
        assert after_verdict_rings == before_verdict_rings

        after_open = json.loads(_ring_json(admin, TENANT_A, open_ring_id))
        assert after_open["ring_id"] == open_ring_id
        assert after_open["confidence"] == 0.99
        assert after_open["member_accounts"] == [101, 102]
        old_members = set(before_open["member_accounts"])
        new_members = set(after_open["member_accounts"])
        assert len(old_members & new_members) / len(old_members | new_members) >= 0.5

        after_rows = _tenant_ring_rows(admin, TENANT_A)
        after_tenant_a = {json.loads(row)["ring_id"]: row for row in after_rows}
        after_ids = set(after_tenant_a)
        assert before_ids <= after_ids
        for ring_id in before_ids - {open_ring_id}:
            assert after_tenant_a[ring_id] == before_tenant_a[ring_id], (
                f"existing ring identity {ring_id} was reused or modified"
            )
        created_ring_ids = sorted(after_ids - before_ids)
        assert len(created_ring_ids) == 1
        new_ring_id = created_ring_ids[0]
        assert new_ring_id.startswith(f"full-demo-model-7-v2-refresh-{run_id[:8]}-")
        assert new_ring_id not in before_ids
        assert _ring_json(admin, TENANT_A, new_ring_id) is not None
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM audit_log
                WHERE tenant_id = :tenant_id AND object_id = :run_id
            """), {"tenant_id": TENANT_A, "run_id": run_id})
            connection.execute(text("""
                DELETE FROM rings WHERE tenant_id = :tenant_id
                  AND ring_id LIKE :generated_prefix
            """), {"tenant_id": TENANT_A,
                  "generated_prefix": f"full-demo-model-7-v2-refresh-{run_id[:8]}-%"})
            connection.execute(text("DELETE FROM rings WHERE tenant_id = :tenant_id AND ring_id = :ring_id"),
                               {"tenant_id": TENANT_A, "ring_id": open_ring_id})
            if model_version_id is not None:
                connection.execute(text("DELETE FROM model_versions WHERE tenant_id = :tenant_id AND model_version_id = :id"),
                                   {"tenant_id": TENANT_A, "id": model_version_id})
        admin.dispose()
