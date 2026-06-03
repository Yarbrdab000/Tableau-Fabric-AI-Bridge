"""Shared test fixtures: configs + an in-process mock that stands in for BOTH the official
MCP upstream and Tableau REST sign-in (routed by path via httpx ASGITransport)."""

import itertools

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from config import DEFAULT_JWT_SCOPES, SidecarConfig


def make_config(**overrides) -> SidecarConfig:
    base = dict(
        port=9000,
        upstream_mcp_url="http://upstream/mcp",
        upstream_request_timeout_s=600.0,
        allow_api_key=True,
        api_key="test-key",
        trust_easy_auth=False,
        identity_mode="service_account",
        on_unresolved_identity="deny",
        tableau_server="http://tableau",
        tableau_site="",
        tableau_rest_version="3.21",
        connected_app_client_id="cid",
        connected_app_secret_id="sid",
        connected_app_secret_value="secret",
        jwt_scopes=list(DEFAULT_JWT_SCOPES),
        upn_mapping_mode="direct",
        upn_domain_from=None,
        upn_domain_to=None,
        upn_explicit_map={},
        entra_tenant_id="tenant-1",
        token_cache_ttl_s=1800,
    )
    base.update(overrides)
    return SidecarConfig(**base)


class MockUpstream:
    """Records the last /mcp request and can be told to fail the next N /mcp calls with 401
    (to exercise the sidecar's cache-evict + re-sign-in retry)."""

    def __init__(self) -> None:
        self.last_headers: dict = {}
        self.last_body: bytes = b""
        self.signin_count = 0
        self._fail_next = 0
        self._token_seq = itertools.count(1)
        self.app = Starlette(
            routes=[
                Route("/mcp", self._mcp, methods=["GET", "POST", "DELETE"]),
                Route("/api/{ver}/auth/signin", self._signin, methods=["POST"]),
                Route("/sse", self._sse, methods=["GET"]),
            ]
        )

    def fail_next_mcp(self, n: int) -> None:
        self._fail_next = n

    async def _mcp(self, request: Request):
        self.last_headers = {k.lower(): v for k, v in request.headers.items()}
        self.last_body = await request.body()
        if self._fail_next > 0:
            self._fail_next -= 1
            return JSONResponse({"error": "expired"}, status_code=401)
        return JSONResponse(
            {
                "ok": True,
                "method": request.method,
                "x_tableau_auth": request.headers.get("x-tableau-auth"),
                "saw_spoof": request.headers.get("x-ms-client-principal-name"),
            },
            headers={"Mcp-Session-Id": "sess-123"},
        )

    async def _signin(self, request: Request):
        self.signin_count += 1
        token = f"tabtoken-{next(self._token_seq)}"
        return JSONResponse(
            {"credentials": {"token": token, "site": {"id": "site-1"}, "user": {"id": "u1"}}}
        )

    async def _sse(self, request: Request):
        async def gen():
            yield b"data: one\n\n"
            yield b"data: two\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Mcp-Session-Id": "sess-sse"})


@pytest.fixture
def mock_upstream() -> MockUpstream:
    return MockUpstream()


@pytest.fixture
def mock_client(mock_upstream: MockUpstream) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=mock_upstream.app)
    return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(connect=5, read=None, write=5, pool=5))
