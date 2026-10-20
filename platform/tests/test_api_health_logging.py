from __future__ import annotations

import json
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token, decode_access_token  # noqa: E402
from api.main import app  # noqa: E402
from api.request_context import RequestContextMiddleware  # noqa: E402
from api.errors import install_error_handlers  # noqa: E402


def test_health_is_unauthenticated_safe_and_reports_components(monkeypatch, tmp_path, repo_platform_config):
    from api import main

    monkeypatch.setattr(main, "check_database", lambda: None)
    monkeypatch.setenv("RINGSHIELD_ARTIFACT_DIR", str(tmp_path))
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "file_store": "ok"}
    assert "authorization" not in response.text.lower()
    assert str(tmp_path) not in response.text


def test_health_database_failure_is_safe_503(monkeypatch, tmp_path, repo_platform_config):
    from api import main

    def fail():
        raise OSError("private host and password")

    monkeypatch.setattr(main, "check_database", fail)
    monkeypatch.setenv("RINGSHIELD_ARTIFACT_DIR", str(tmp_path))
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["message"] == "Database unavailable"
    assert "private" not in response.text
    assert "request_id" in response.json()


def test_structured_request_log_uses_verified_claims_and_omits_secrets(monkeypatch, capsys):
    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    principal = Principal(user_id=37, tenant_id=210, role="analyst", email="private@example.test")
    token, _ = create_access_token(principal)
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)

    @test_app.post("/items/{item_id}")
    async def item(item_id: int, request: Request):
        request.state.principal = decode_access_token(request.headers["authorization"].split()[1])
        await request.body()
        return {"ok": True}

    response = TestClient(test_app).post(
        "/items/22?query-secret=hidden", headers={"Authorization": f"Bearer {token}"},
        json={"password": "body-secret"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    log_line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(log_line)
    assert record["event"] == "http.request.completed"
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert record["tenant_id"] == 210 and record["user_id"] == 37
    assert record["route"] == "/items/{item_id}"
    assert record["method"] == "POST" and record["status"] == 200
    assert isinstance(record["duration_ms"], (int, float))
    assert "Bearer " not in log_line and token not in log_line
    assert "body-secret" not in log_line and "query-secret" not in log_line
    assert "private@example.test" not in log_line


def test_unhandled_error_log_is_correlated_and_contains_no_exception_text(monkeypatch, capsys):
    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    token, _ = create_access_token(
        Principal(user_id=41, tenant_id=210, role="analyst", email="person@example.test")
    )
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    install_error_handlers(test_app)

    @test_app.get("/failure/{record_id}")
    async def failure(record_id: int, request: Request):
        request.state.principal = decode_access_token(request.headers["authorization"].split()[1])
        raise RuntimeError("C:\\private\\secret-file and private-message")

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/failure/8", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 500
    assert "private" not in response.text
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    error_line = next(line for line in lines if line["event"] == "http.request.unhandled_error")
    assert error_line["tenant_id"] == 210
    assert error_line["request_id"] == response.headers["X-Request-ID"]
    assert all("private" not in json.dumps(line) and "secret-file" not in json.dumps(line)
               for line in lines)
