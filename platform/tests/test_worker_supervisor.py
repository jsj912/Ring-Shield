from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs import worker_supervisor as supervisor  # noqa: E402


class _Results:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Session:
    def __init__(self, tenant_ids, contexts):
        self.tenant_ids = tenant_ids
        self.contexts = contexts
        self.statements = []

    def scalars(self, statement):
        sql = str(statement.compile())
        self.statements.append(sql)
        if "FROM tenants" in sql:
            return _Results(self.tenant_ids)
        if "FROM explanation_jobs" in sql:
            return _Results(["210." + "a" * 32] if self.contexts[-1] == 210 else [])
        if "FROM retrain_runs" in sql:
            return _Results(["run-210"] if self.contexts[-1] == 210 else [])
        raise AssertionError(sql)


def test_collect_pending_work_uses_tenant_context_and_queued_filters(monkeypatch):
    contexts = []
    sessions = []

    @contextmanager
    def fake_loader_session(*, tenant_id=None):
        contexts.append(tenant_id)
        session = _Session([210, 220], contexts)
        sessions.append(session)
        yield session

    monkeypatch.setattr(supervisor, "loader_db_session", fake_loader_session)

    work = supervisor.collect_pending_work()

    assert [(item.kind, item.tenant_id, item.job_id) for item in work] == [
        ("explanation", 210, "210." + "a" * 32),
        ("retrain", 210, "run-210"),
    ]
    assert contexts == [None, 210, 220]
    statements = [statement for session in sessions for statement in session.statements]
    assert any("explanation_jobs.tenant_id =" in sql
               and "explanation_jobs.status =" in sql for sql in statements)
    assert any("retrain_runs.tenant_id =" in sql
               and "retrain_runs.status =" in sql for sql in statements)
    assert any("tenants.is_loaded IS true" in sql for sql in statements)


def test_supervisor_launches_each_kind_with_expected_arguments_and_limit(capsys):
    work = [
        supervisor._item("explanation", 210, "210." + "a" * 32),
        supervisor._item("retrain", 220, "run-220"),
        supervisor._item("explanation", 220, "220." + "b" * 32),
    ]
    launched = []

    class Child:
        def poll(self):
            return 0

    def fake_popen(argv, **options):
        launched.append((argv, options))
        return Child()

    supervisor.run_supervisor(
        once=True, max_concurrent=2, pending_work=lambda: work,
        popen=fake_popen, sleep=lambda _seconds: None,
    )

    assert len(launched) == 2
    assert launched[0][0] == list(work[0].argv)
    assert launched[1][0] == list(work[1].argv)
    assert launched[0][0][-3:] == ["-m", "jobs.regenerate_worker", work[0].job_id]
    assert launched[1][0][-4:] == [
        "-m", "jobs.retrain_worker", "220", "run-220",
    ]
    assert all("env" in options for _argv, options in launched)
    assert '"outcome":"succeeded"' in capsys.readouterr().out


def test_supervisor_does_not_launch_the_same_job_twice_and_stops_gracefully(tmp_path):
    work = supervisor._item("explanation", 210, "210." + "c" * 32)
    stop_file = tmp_path / "stop"
    scans = 0
    launches = []

    class Child:
        poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            return None if self.poll_calls == 1 else 0

    def pending():
        nonlocal scans
        scans += 1
        if scans == 2:
            stop_file.write_text("stop", encoding="utf-8")
        return [work]

    supervisor.run_supervisor(
        poll_seconds=0.001, stop_file=str(stop_file), pending_work=pending,
        popen=lambda argv, **_options: launches.append(argv) or Child(),
        sleep=lambda _seconds: None,
    )

    assert len(launches) == 1


def test_supervisor_survives_failed_child_and_never_logs_environment_secrets(
        monkeypatch, capsys):
    secret = "supervisor-secret-not-for-logs"
    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", secret)
    work = supervisor._item("retrain", 210, "run-failing")
    launches = []

    class FailedChild:
        def poll(self):
            return 9

    supervisor.run_supervisor(
        once=True, pending_work=lambda: [work],
        popen=lambda argv, **options: launches.append((argv, options)) or FailedChild(),
        sleep=lambda _seconds: None,
    )

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    assert events[-1]["outcome"] == "failed"
    assert events[-1]["job_id"] == "run-failing"
    assert launches[0][1]["env"]["RINGSHIELD_XAI_TOKEN"] == secret
    assert secret not in output


def test_supervisor_logs_launch_failure_and_continues(capsys):
    work = supervisor._item("explanation", 210, "210." + "d" * 32)

    def failed_start(_argv, **_options):
        raise OSError("sensitive connection detail")

    supervisor.run_supervisor(
        once=True, pending_work=lambda: [work], popen=failed_start,
        sleep=lambda _seconds: None,
    )

    output = capsys.readouterr().out
    assert '"outcome":"launch_failed"' in output
    assert "sensitive connection detail" not in output
