"""Integration tests for the streaming proxy against an in-process mock upstream.

Covers caller auth, header stripping (anti-spoof), X-Tableau-Auth injection, per-user
sign-in + caching, fail-closed behavior, cache-evict-retry, and SSE pass-through.
"""

import base64
import json

import pytest
from starlette.testclient import TestClient

from proxy import create_app
from conftest import make_config


def _client_with_mock(cfg, mock_client):
    app = create_app(cfg)
    tc = TestClient(app)
    tc.__enter__()  # runs startup (creates a real client we immediately replace)
    app.state.http_client = mock_client
    return app, tc


def _easy_auth_headers(upn="alice@contoso.com", oid="oid-1", tid="tenant-1"):
    payload = {"claims": [
        {"typ": "preferred_username", "val": upn},
        {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": oid},
        {"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": tid},
    ]}
    blob = base64.b64encode(json.dumps(payload).encode()).decode()
    return {"x-ms-client-principal": blob, "x-ms-client-principal-name": upn,
            "x-ms-client-principal-id": oid}


def test_healthz_no_auth(mock_client):
    cfg = make_config()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        r = tc.get("/healthz")
        assert r.status_code == 200
        assert r.json()["identity_mode"] == "service_account"
    finally:
        tc.__exit__(None, None, None)


def test_service_account_requires_api_key(mock_client):
    cfg = make_config()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        assert tc.post("/mcp", json={"jsonrpc": "2.0"}).status_code == 401
    finally:
        tc.__exit__(None, None, None)


def test_service_account_proxies_and_strips_spoof(mock_client, mock_upstream):
    cfg = make_config()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        r = tc.post(
            "/mcp",
            headers={"x-api-key": "test-key", "x-ms-client-principal-name": "attacker@evil.com"},
            json={"jsonrpc": "2.0", "method": "tools/list"},
        )
        assert r.status_code == 200
        # No identity injected in service-account mode...
        assert r.json()["x_tableau_auth"] is None
        # ...and the client-supplied (spoofed) Entra header never reached the upstream.
        assert mock_upstream.last_headers.get("x-ms-client-principal-name") is None
        assert r.headers.get("mcp-session-id") == "sess-123"
    finally:
        tc.__exit__(None, None, None)


def _passthrough_cfg():
    return make_config(identity_mode="passthrough", trust_easy_auth=True, upn_mapping_mode="direct")


def test_passthrough_injects_token_and_caches(mock_client, mock_upstream):
    cfg = _passthrough_cfg()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        r1 = tc.post("/mcp", headers=_easy_auth_headers(), json={"m": 1})
        assert r1.status_code == 200
        assert r1.json()["x_tableau_auth"] == "tabtoken-1"
        assert mock_upstream.signin_count == 1
        # Second call for same identity reuses the cached Tableau token (no new sign-in).
        r2 = tc.post("/mcp", headers=_easy_auth_headers(), json={"m": 2})
        assert r2.status_code == 200
        assert mock_upstream.signin_count == 1
    finally:
        tc.__exit__(None, None, None)


def test_passthrough_requires_identity(mock_client):
    cfg = _passthrough_cfg()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        # Valid api-key but NO Entra identity -> cannot resolve a user -> fail closed.
        r = tc.post("/mcp", headers={"x-api-key": "test-key"}, json={"m": 1})
        assert r.status_code == 403
    finally:
        tc.__exit__(None, None, None)


def test_passthrough_unmapped_upn_fails_closed(mock_client, mock_upstream):
    cfg = make_config(
        identity_mode="passthrough", trust_easy_auth=True, upn_mapping_mode="transform",
        upn_domain_from="contoso.com", upn_domain_to="t.example.com",
    )
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        r = tc.post("/mcp", headers=_easy_auth_headers(upn="eve@evil.com"), json={"m": 1})
        assert r.status_code == 403
        assert mock_upstream.last_body == b""  # never forwarded
        assert mock_upstream.signin_count == 0
    finally:
        tc.__exit__(None, None, None)


def test_passthrough_stale_token_evict_and_retry(mock_client, mock_upstream):
    cfg = _passthrough_cfg()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        mock_upstream.fail_next_mcp(1)  # first /mcp returns 401 (stale token)
        r = tc.post("/mcp", headers=_easy_auth_headers(), json={"m": 1})
        assert r.status_code == 200
        assert r.json()["x_tableau_auth"] == "tabtoken-2"  # re-signed-in
        assert mock_upstream.signin_count == 2
    finally:
        tc.__exit__(None, None, None)


def test_sse_streaming_passthrough(mock_client, mock_upstream):
    cfg = make_config(upstream_mcp_url="http://upstream/sse")
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        r = tc.get("/mcp", headers={"x-api-key": "test-key"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "data: one" in r.text and "data: two" in r.text
        assert r.headers.get("mcp-session-id") == "sess-sse"
    finally:
        tc.__exit__(None, None, None)


def test_unknown_path_404(mock_client):
    cfg = make_config()
    app, tc = _client_with_mock(cfg, mock_client)
    try:
        assert tc.post("/admin", json={}).status_code == 404
    finally:
        tc.__exit__(None, None, None)
