"""PostgreSQL acceptance for tenant-bound L6 retraining and writer-role limits."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import re
import sys
from uuid import uuid4

import pytest
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters.research_cli import EvalResult, RingRunResult, TrainResult
from db.session import get_engine, get_loader_engine, loader_db_session
from jobs.retrain import run_retrain_job
from tenant_row_cleanup import delete_tenant_rows_added_since, snapshot_tenant_row_keys


TENANT_A = 210
TENANT_B = 220
PROTECTED_TABLES = ("verdicts", "rings", "users", "explanations")


def _delete_stale_owned_retrain_rows(engine) -> None:
    """Remove rows from interrupted runs of this acceptance before seeding baselines."""
    owned_model_sql = """
        SELECT model_version_id FROM model_versions
        WHERE tenant_id IN (210, 220) AND component = 'expansion'
          AND ((version_tag LIKE 'retrain-test-%'
                AND trained_at = TIMESTAMPTZ '2000-01-01 00:00:00+00')
               OR artifact_path LIKE '%/out/retrain/%/expansion-candidate')
    """
    with engine.begin() as connection:
        connection.execute(text(f"""
            DELETE FROM retrain_runs
            WHERE tenant_id IN (210, 220)
              AND (run_id LIKE 'fixture-retrain-%' OR run_id LIKE '%-rt'
                   OR model_version_id IN ({owned_model_sql}))
        """))
        connection.execute(text(f"""
            DELETE FROM model_versions
            WHERE tenant_id IN (210, 220) AND model_version_id IN ({owned_model_sql})
        """))


def _delete_current_retrain_rows(engine, *, run_id, baseline_ids, test_started_at, candidate_path):
    fixture_run_ids = (f"fixture-retrain-{run_id}-{TENANT_A}",
                       f"fixture-retrain-{run_id}-{TENANT_B}")
    with engine.begin() as connection:
        run_prefix = f"{run_id}%"
        connection.execute(text("""
            DELETE FROM audit_log
            WHERE tenant_id IN (:tenant_a, :tenant_b) AND at >= :started_at
              AND (object_id LIKE :run_prefix OR details->>'run_id' LIKE :run_prefix)
        """), {"tenant_a": TENANT_A, "tenant_b": TENANT_B,
              "started_at": test_started_at, "run_prefix": run_prefix})
        connection.execute(text("""
            DELETE FROM retrain_runs
            WHERE tenant_id IN (:tenant_a, :tenant_b)
              AND (run_id = :run_id OR run_id IN (:fixture_a, :fixture_b)
                   OR model_version_id IN (:base_a, :base_b)
                   OR model_version_id IN (
                       SELECT model_version_id FROM model_versions
                       WHERE tenant_id IN (:tenant_a, :tenant_b)
                         AND component = 'expansion' AND trained_at >= :started_at
                         AND artifact_path = :candidate_path))
        """), {
            "tenant_a": TENANT_A, "tenant_b": TENANT_B,
            "run_id": run_id, "fixture_a": fixture_run_ids[0], "fixture_b": fixture_run_ids[1],
            "base_a": baseline_ids.get(TENANT_A, -1), "base_b": baseline_ids.get(TENANT_B, -1),
            "started_at": test_started_at, "candidate_path": str(candidate_path),
        })
        connection.execute(text("""
            DELETE FROM model_versions
            WHERE tenant_id IN (:tenant_a, :tenant_b) AND component = 'expansion'
              AND (model_version_id IN (:base_a, :base_b)
                   OR (trained_at >= :started_at AND artifact_path = :candidate_path))
        """), {
            "tenant_a": TENANT_A, "tenant_b": TENANT_B,
            "base_a": baseline_ids.get(TENANT_A, -1), "base_b": baseline_ids.get(TENANT_B, -1),
            "started_at": test_started_at, "candidate_path": str(candidate_path),
        })


def _snapshot(engine, table: str, tenant_id: int) -> list[str]:
    quoted_table = engine.dialect.identifier_preparer.quote(table)
    with engine.connect() as connection:
        return list(connection.execute(text(
            f"SELECT row_to_json(row_data)::text FROM ("
            f"SELECT * FROM public.{quoted_table} WHERE tenant_id = :tenant_id) row_data "
            "ORDER BY row_to_json(row_data)::text"
        ), {"tenant_id": tenant_id}).scalars())


@pytest.mark.parametrize(("candidate_f1", "promoted"), [(0.95, True), (0.45, False)])
def test_retrain_job_is_tenant_bound_and_loader_cannot_write_verdicts(
        monkeypatch, tmp_path, candidate_f1, promoted, register_db_test_ids):
    admin_url = os.environ["RINGSHIELD_TEST_ADMIN_URL"]
    admin = create_engine(admin_url)
    test_started_at = datetime.now(timezone.utc)
    run_id = f"{uuid4().hex}-rt"
    register_db_test_ids(run_id, f"fixture-retrain-{run_id}", f"retrain-test-{run_id}",
                         f"v2-{run_id[:8]}")
    log_path = PLATFORM_ROOT / "out" / "retrain" / f"{run_id}.log"
    candidate_path = log_path.parent / run_id / "expansion-candidate"
    version_tags = (f"retrain-test-{run_id}-a", f"retrain-test-{run_id}-b")
    baseline_ids = {}
    app_engine = get_engine()
    loader_engine = get_loader_engine()
    observed_statements: list[tuple[str, object]] = []

    def record_dml(_conn, _cursor, statement, _parameters, _context, _many):
        observed_statements.append((statement, _parameters))

    event.listen(app_engine, "before_cursor_execute", record_dml)
    event.listen(loader_engine, "before_cursor_execute", record_dml)
    baseline_row_keys = None
    try:
        _delete_stale_owned_retrain_rows(admin)
        baseline_row_keys = snapshot_tenant_row_keys(admin, (TENANT_A, TENANT_B))
        with admin.connect() as connection:
            tenant_tables = tuple(connection.execute(text("""
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'tenant_id'
                GROUP BY table_name ORDER BY table_name
            """)).scalars())
        assert tenant_tables, "acceptance database has no tenant-scoped tables"
        with admin.begin() as connection:
            version_ids = {}
            for tenant_id, tag in zip((TENANT_A, TENANT_B), version_tags):
                version_ids[tenant_id] = connection.execute(text("""
                    INSERT INTO model_versions
                      (tenant_id, component, version_tag, trained_at, train_label_count,
                       holdout_ring_f1, promoted)
                    VALUES (:tenant_id, 'expansion', :tag, '2000-01-01T00:00:00Z', 0, 0.5, true)
                    RETURNING model_version_id
                """), {"tenant_id": tenant_id, "tag": tag}).scalar_one()
                baseline_ids[tenant_id] = version_ids[tenant_id]
                connection.execute(text("""
                    INSERT INTO retrain_runs (run_id, tenant_id, triggered_by, status, model_version_id)
                    VALUES (:run_id, :tenant_id, 'supervisor', 'completed', :version_id)
                """), {"run_id": f"fixture-retrain-{run_id}-{tenant_id}",
                      "tenant_id": tenant_id, "version_id": version_ids[tenant_id]})
            connection.execute(text("""
                INSERT INTO retrain_runs (run_id, tenant_id, triggered_by, status)
                VALUES (:run_id, :tenant_id, 'supervisor', 'running')
            """), {"run_id": run_id, "tenant_id": TENANT_A})

        before_b = {table: _snapshot(admin, table, TENANT_B) for table in tenant_tables}
        before_a_protected = {table: _snapshot(admin, table, TENANT_A) for table in PROTECTED_TABLES}
        before_a_versions = _snapshot(admin, "model_versions", TENANT_A)

        base_dir = tmp_path / "base-model"
        base_dir.mkdir()
        paths = {"base_model_dir": base_dir}
        paths.update({key: base_dir / f"{key}.parquet" for key in
                      ("val_scored_edges", "val_gfp", "val_embeddings", "truth_parquet",
                       "holdout_manifest")})
        fixture_dir = PLATFORM_ROOT / "tests" / "fixtures"
        paths["holdout_manifest"] = fixture_dir / "holdout_manifest_fixture.json"
        paths["holdout_sha256_file"] = fixture_dir / "holdout_manifest_fixture.sha256"
        pq.write_table(pa.table({"edge_id": pa.array([], type=pa.int64())}),
                       paths["val_scored_edges"])
        config = {"active_model_id": "demo-model", "active_seed": 7}
        l6 = {"retrain": {"components": ["expansion"], "min_new_labels": 1,
                          "epsilon": 0.01, "eval_window": "val", "eval_scope": "test_visible"}}
        monkeypatch.setattr("jobs.retrain.load_platform_config", lambda: config)
        monkeypatch.setattr("jobs.retrain.load_l6_config", lambda _config: l6)
        monkeypatch.setattr("jobs.retrain._validate_inputs", lambda _l6, _config: paths)
        monkeypatch.setattr("jobs.retrain._run_log_path", lambda _run_id: log_path)
        refresh_steps = []

        def successful_refresh(**kwargs):
            refresh_steps.append(kwargs)
            refreshed_rings = tmp_path / f"refreshed-{kwargs['model_version_id']}.parquet"
            pq.write_table(pa.table({
                "tenant_id": pa.array([TENANT_A], type=pa.int64()),
                "ring_id": pa.array(["refreshed-demo-cycle"]),
            }), refreshed_rings)
            return refreshed_rings

        monkeypatch.setattr("jobs.retrain._run_ring_refresh_process", successful_refresh)

        class FakeCLI:
            def train(self, **kwargs):
                version = {
                    "version": 2,
                    "retrained": True,
                    "training_labels": {"rings": ["demo-cycle"]},
                }
                kwargs["out_dir"].mkdir(parents=True, exist_ok=True)
                (kwargs["out_dir"] / "version.json").write_text(
                    __import__("json").dumps(version), encoding="utf-8",
                )
                return TrainResult(model_dir=kwargs["out_dir"], version=version, retrained=True)

            def run_rings(self, **kwargs):
                pq.write_table(pa.table({
                    "ring_id": pa.array(["demo-cycle", "new-candidate-ring"]),
                }), kwargs["out"])
                return RingRunResult(rings_path=kwargs["out"], run_log={"command": "run"}, ring_count=1)

            def eval_rings(self, **kwargs):
                return EvalResult(metrics_path=kwargs["out"], metrics={"ring_f1": candidate_f1},
                                  ring_f1=candidate_f1)

        run_retrain_job(TENANT_A, run_id, cli=FakeCLI())
        assert len(refresh_steps) == int(promoted)
        if promoted:
            assert refresh_steps[0]["tenant_id"] == TENANT_A
            assert refresh_steps[0]["run_id"] == (
                f"{run_id}-v{refresh_steps[0]['model_version_id']}"
            )

        after_b = {table: _snapshot(admin, table, TENANT_B) for table in tenant_tables}
        after_a_protected = {table: _snapshot(admin, table, TENANT_A) for table in PROTECTED_TABLES}
        assert after_b == before_b, "tenant B rows changed during tenant A retraining"
        assert after_a_protected == before_a_protected, "retraining wrote protected tenant A tables"
        inserts_to_protected = [statement for statement, _ in observed_statements
                                if re.search(r"\bINSERT\s+INTO\s+(?:public\.)?\"?"
                                             r"(?:verdicts|rings|users|explanations)\b",
                                             statement, re.I)]
        assert inserts_to_protected == [], inserts_to_protected

        def parameters_contain(value, expected: int) -> bool:
            if isinstance(value, dict):
                return any(parameters_contain(item, expected) for item in value.values())
            if isinstance(value, (tuple, list)):
                return any(parameters_contain(item, expected) for item in value)
            return value == expected

        tenant_queries = [
            (statement, parameters)
            for statement, parameters in observed_statements
            if re.search(r"\b(?:model_versions|retrain_runs|verdicts|rings|transactions)\b",
                         statement, re.I)
        ]
        assert tenant_queries, "retraining issued no observable tenant-table queries"
        for statement, parameters in tenant_queries:
            assert "tenant_id" in statement.lower(), statement
            assert parameters_contain(parameters, TENANT_A), (statement, parameters)
            assert not parameters_contain(parameters, TENANT_B), (statement, parameters)

        after_a_versions = _snapshot(admin, "model_versions", TENANT_A)
        assert len(after_a_versions) == len(before_a_versions) + 1
        with admin.connect() as connection:
            state = connection.execute(text(
                "SELECT status FROM retrain_runs WHERE tenant_id = :tenant_id AND run_id = :run_id"
            ), {"tenant_id": TENANT_A, "run_id": run_id}).scalar_one()
            versions = connection.execute(text("""
                SELECT version_tag, promoted, gate_reason FROM model_versions
                WHERE tenant_id = :tenant_id AND component = 'expansion'
                ORDER BY model_version_id
            """), {"tenant_id": TENANT_A}).all()
        assert state == "succeeded"
        assert versions[-1].version_tag.startswith("v2-")
        assert versions[-1].promoted is promoted
        assert versions[0].promoted is (not promoted)
        if not promoted:
            assert versions[-1].gate_reason
        with app_engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == "ringshield_api"
        with loader_db_session(tenant_id=TENANT_A) as session:
            assert session.execute(text("SELECT current_user")).scalar_one() == "ringshield_loader"

        with pytest.raises(DBAPIError):
            with loader_db_session(tenant_id=TENANT_A) as session:
                session.execute(text("""
                    INSERT INTO verdicts
                      (tenant_id, ring_id, user_id, verdict, corrected_members, corrected_edges, is_simulated)
                    VALUES (:tenant_id, 'demo-cycle', 1, 'confirm', ARRAY[]::bigint[], ARRAY[]::bigint[], false)
                """), {"tenant_id": TENANT_A})
    finally:
        event.remove(app_engine, "before_cursor_execute", record_dml)
        event.remove(loader_engine, "before_cursor_execute", record_dml)
        try:
            _delete_current_retrain_rows(
                admin, run_id=run_id, baseline_ids=baseline_ids,
                test_started_at=test_started_at, candidate_path=candidate_path,
            )
        finally:
            try:
                if baseline_row_keys is not None:
                    delete_tenant_rows_added_since(
                        admin, baseline_row_keys, (TENANT_A, TENANT_B),
                        exclude_tables={"retrain_runs", "model_versions"},
                    )
            finally:
                log_path.unlink(missing_ok=True)
                shutil.rmtree(log_path.parent / run_id, ignore_errors=True)
                admin.dispose()
