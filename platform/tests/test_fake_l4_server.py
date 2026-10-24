from __future__ import annotations

import json
from pathlib import Path
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.explanation_validation import normalize_regenerated_row  # noqa: E402
from settings import load_platform_config  # noqa: E402
from scripts.fake_l4_server import create_server  # noqa: E402


def test_fake_l4_ephemeral_server_health_auth_and_shared_validation(repo_platform_config):
    config = load_platform_config()
    token = "demo-test-token"
    server = create_server(port=0, token=token, config=config)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    request_body = {
        "tenant_id": 210, "ring_id": "fake-l4-ring",
        "excluded_members": [21], "excluded_edges": [17],
    }
    try:
        assert server.server_address[0] == "127.0.0.1"
        with urlopen(f"{base_url}/health", timeout=2) as response:
            health = json.loads(response.read())
        assert health == {"status": "ok", "service": "DEMO STUB L4"}

        for authorization in (None, "Bearer wrong-token"):
            headers = {"Content-Type": "application/json"}
            if authorization:
                headers["Authorization"] = authorization
            request = Request(f"{base_url}/regenerate", data=json.dumps(request_body).encode(),
                              headers=headers, method="POST")
            try:
                urlopen(request, timeout=2)
                raise AssertionError("unauthorized fake L4 request unexpectedly succeeded")
            except HTTPError as exc:
                assert exc.code == 401

        request = Request(
            f"{base_url}/regenerate", data=json.dumps(request_body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            row = json.loads(response.read())
        normalized = normalize_regenerated_row(
            row, tenant_id=210, ring_id="fake-l4-ring", excluded_members=[21],
            excluded_edges=[17], config=config,
        )
        assert "DEMO STUB" in normalized["narrative"]
        assert "not real research output" in normalized["narrative"]
        assert normalized["provenance"]["regenerated"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
