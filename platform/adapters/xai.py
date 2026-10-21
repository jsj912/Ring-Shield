"""HTTP adapter for the separately hosted L4 explanation service."""

from __future__ import annotations

import os
from typing import Any

import httpx

from settings import load_platform_config


class XaiError(RuntimeError):
    """Base class for safe L4 service failures."""

    code = "xai_error"
    safe_message = "L4 explanation service request failed"


class XaiNotConfiguredError(XaiError):
    code = "not_configured"
    safe_message = "L4 explanation regeneration is not configured"


class XaiConnectionError(XaiError):
    code = "connection_failed"
    safe_message = "L4 explanation service is unavailable"


class XaiTimeoutError(XaiError):
    code = "timeout"
    safe_message = "L4 explanation service timed out"


class XaiRingNotFoundError(XaiError):
    code = "ring_not_found"
    safe_message = "L4 could not find the ring"


class XaiInvalidEditError(XaiError):
    code = "invalid_edit"

    def __init__(self, safe_message: str):
        self.safe_message = safe_message
        super().__init__(safe_message)


class XaiUnexpectedStatusError(XaiError):
    code = "unexpected_status"


class XaiInvalidResponseError(XaiError):
    code = "invalid_response"
    safe_message = "L4 returned an invalid response"


def _settings(config: dict[str, Any] | None) -> tuple[str | None, int]:
    root = config if config is not None else load_platform_config()
    l4 = root.get("l4")
    if not isinstance(l4, dict):
        raise XaiNotConfiguredError()
    url = l4.get("regenerate_url")
    timeout = l4.get("regenerate_timeout_seconds", 120)
    if url is None:
        raise XaiNotConfiguredError()
    if not isinstance(url, str) or not url.strip() or not isinstance(timeout, int):
        raise XaiNotConfiguredError()
    return url.rstrip("/"), timeout


def _client_request(client: httpx.Client, method: str, url: str,
                    *, timeout_seconds: int, token: str, json_body: dict | None = None):
    timeout = httpx.Timeout(timeout_seconds, connect=3.0)
    return client.request(
        method, url, headers={"Authorization": f"Bearer {token}"},
        json=json_body, timeout=timeout,
    )


def _decode_response(response: httpx.Response, token: str) -> dict[str, Any]:
    if response.status_code == 404:
        raise XaiRingNotFoundError()
    if response.status_code == 422:
        try:
            body = response.json()
        except (ValueError, httpx.DecodingError):
            body = {}
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            message = "L4 rejected the requested ring edit"
        if token in message:
            message = "L4 rejected the requested ring edit"
        raise XaiInvalidEditError(message.strip()[:300])
    if response.status_code != 200:
        raise XaiUnexpectedStatusError(f"L4 returned HTTP {response.status_code}")
    try:
        value = response.json()
    except (ValueError, httpx.DecodingError) as exc:
        raise XaiInvalidResponseError() from None
    if not isinstance(value, dict):
        raise XaiInvalidResponseError()
    return value


def _request(method: str, endpoint: str, *, config: dict[str, Any] | None,
             client: httpx.Client | None, body: dict | None = None) -> dict[str, Any]:
    url, timeout = _settings(config)
    token = os.environ.get("RINGSHIELD_XAI_TOKEN")
    if not token:
        raise XaiNotConfiguredError()
    owned = client is None
    active_client = client or httpx.Client()
    try:
        response = _client_request(active_client, method, f"{url}/{endpoint}",
                                   timeout_seconds=timeout, token=token, json_body=body)
        return _decode_response(response, token)
    except httpx.TimeoutException:
        raise XaiTimeoutError() from None
    except httpx.RequestError:
        raise XaiConnectionError() from None
    finally:
        if owned:
            active_client.close()


def regenerate(tenant_id: int, ring_id: str, excluded_members: list[int],
               excluded_edges: list[int], *, config: dict[str, Any] | None = None,
               client: httpx.Client | None = None) -> dict[str, Any]:
    """Request one corrected-ring explanation using the L4 HTTP contract."""
    return _request("POST", "regenerate", config=config, client=client, body={
        "tenant_id": int(tenant_id), "ring_id": ring_id,
        "excluded_members": excluded_members, "excluded_edges": excluded_edges,
    })


def health(*, config: dict[str, Any] | None = None,
           client: httpx.Client | None = None) -> dict[str, Any]:
    """Read the L4 service health payload."""
    return _request("GET", "health", config=config, client=client)
