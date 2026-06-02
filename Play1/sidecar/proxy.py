"""Sidecar reverse proxy: the public ingress in front of the official Tableau MCP server.

Responsibilities (see config.py for the why):
  * Authenticate the caller (x-api-key fallback and/or Entra identity via Easy Auth/APIM).
  * In passthrough mode, resolve the caller's Entra UPN to a Tableau session token and
    inject it as ``X-Tableau-Auth`` so per-user RLS applies. Fail closed if unresolved.
  * Stream-proxy MCP-over-HTTP (Streamable HTTP / SSE) to the upstream official server,
    stripping spoofable identity headers and hop-by-hop headers in both directions.

The upstream official server is expected to run with TRANSPORT=http,
DANGEROUSLY_DISABLE_OAUTH=true and (for passthrough) ENABLE_PASSTHROUGH_AUTH=true, bound
to localhost / the container-internal network only. This sidecar is the complete auth
boundary, so the official server MUST NOT have public ingress.
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Optional, Tuple

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from config import (
    HOP_BY_HOP_HEADERS,
    SPOOFABLE_INBOUND_HEADERS,
    SidecarConfig,
    load_config,
)
from identity import (
    CallerIdentity,
    IdentityError,
    TokenCache,
    UpstreamAuthError,
    extract_caller_identity,
    resolve_tableau_token,
    tableau_signin_as,
)

logger = logging.getLogger("tableau-mcp-sidecar")

MAX_REQUEST_BYTES = 4 * 1024 * 1024  # 4 MiB cap on inbound MCP request bodies.

# Response headers we must not copy back verbatim from the upstream — the ASGI server
# manages framing/length itself, and hop-by-hop headers are connection-scoped.
_RESPONSE_HEADER_DENYLIST = set(HOP_BY_HOP_HEADERS) | {"content-length", "content-encoding"}


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse({"error": "unauthorized", "error_description": detail}, status_code=401)


def _forbidden(detail: str) -> JSONResponse:
    return JSONResponse({"error": "forbidden", "error_description": detail}, status_code=403)


def _check_api_key(request: Request, config: SidecarConfig) -> bool:
    if not (config.allow_api_key and config.api_key):
        return False
    presented = request.headers.get("x-api-key")
    if not presented:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
    if not presented:
        return False
    return hmac.compare_digest(presented, config.api_key)


def _read_caller_identity(request: Request, config: SidecarConfig) -> Optional[CallerIdentity]:
    """Read the Entra identity from platform-set headers, only if we trust Easy Auth/APIM.

    When trust_easy_auth is true, the gateway in front of the sidecar authenticates the
    user and sets the X-MS-CLIENT-PRINCIPAL* headers authentically (a client cannot forge
    them because the platform overwrites them). When false, we never read identity.
    """
    if not config.trust_easy_auth:
        return None
    return extract_caller_identity(request.headers)


def _build_upstream_headers(request: Request, tableau_token: Optional[str]) -> dict:
    """Copy inbound headers minus spoofable identity + hop-by-hop + host/length, then add
    the trusted X-Tableau-Auth (passthrough only)."""
    drop = set(SPOOFABLE_INBOUND_HEADERS) | set(HOP_BY_HOP_HEADERS) | {
        "host",
        "content-length",
        "x-api-key",
        "authorization",
    }
    headers = {k: v for k, v in request.headers.items() if k.lower() not in drop}
    if tableau_token:
        headers["X-Tableau-Auth"] = tableau_token
    return headers


def create_app(config: Optional[SidecarConfig] = None) -> Starlette:
    config = config or load_config()
    cache = TokenCache(config.token_cache_ttl_s)

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", **config.public_diagnostics()})

    async def proxy(request: Request) -> StreamingResponse | JSONResponse:
        client: httpx.AsyncClient = request.app.state.http_client

        # 1. Authenticate the caller.
        caller = _read_caller_identity(request, config)
        api_ok = _check_api_key(request, config)
        easy_ok = config.trust_easy_auth and caller is not None
        if not (api_ok or easy_ok):
            return _unauthorized("Provide a valid x-api-key or an Entra identity.")

        # 2. Resolve the Tableau identity to act as (passthrough only).
        tableau_token: Optional[str] = None
        used_cache_key: Optional[Tuple] = None
        if config.is_passthrough:
            if caller is None:
                return _forbidden("Passthrough mode requires an authenticated Entra identity.")
            try:
                tableau_token, used_cache_key = await resolve_tableau_token(
                    client, config, caller, cache
                )
            except IdentityError as exc:
                logger.info("Identity not resolvable (fail-closed): %s", exc)
                return _forbidden(str(exc))
            except UpstreamAuthError as exc:
                logger.warning("Tableau per-user sign-in failed: %s", exc)
                return _forbidden("Could not establish a Tableau session for this user.")

        # 3. Read + size-cap the request body.
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse(
                {"error": "payload_too_large"}, status_code=413
            )

        # 4. Build the upstream URL (preserve subpath beneath /mcp + query string).
        upstream_url = _resolve_upstream_url(request, config)

        async def send(token: Optional[str]) -> httpx.Response:
            upstream_headers = _build_upstream_headers(request, token)
            upstream_req = client.build_request(
                request.method, upstream_url, headers=upstream_headers, content=body
            )
            return await client.send(upstream_req, stream=True)

        # 5. Send; on a stale-token 401/403 (passthrough, cached), re-sign-in once.
        upstream = await send(tableau_token)
        if (
            config.is_passthrough
            and used_cache_key is not None
            and upstream.status_code in (401, 403)
        ):
            await upstream.aclose()
            cache.evict(used_cache_key)
            try:
                tableau_username_token = await tableau_signin_as(
                    client, config, _username_for(used_cache_key)
                )
            except UpstreamAuthError as exc:
                logger.warning("Re-sign-in failed: %s", exc)
                return _forbidden("Could not refresh the Tableau session for this user.")
            cache.set(used_cache_key, tableau_username_token)
            upstream = await send(tableau_username_token)

        # 6. Stream the response back, dropping framing/hop-by-hop headers.
        response_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _RESPONSE_HEADER_DENYLIST
        }

        async def body_iterator():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            body_iterator(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # No read timeout so long-lived SSE streams are not killed; bounded connect/write.
        timeout = httpx.Timeout(connect=10.0, write=30.0, pool=10.0, read=None)
        app.state.http_client = httpx.AsyncClient(timeout=timeout)
        logger.info("Sidecar started: %s", config.public_diagnostics())
        try:
            yield
        finally:
            await app.state.http_client.aclose()

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/mcp", proxy, methods=["GET", "POST", "DELETE"]),
        Route("/mcp/{path:path}", proxy, methods=["GET", "POST", "DELETE"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.config = config
    app.state.token_cache = cache
    return app


def _resolve_upstream_url(request: Request, config: SidecarConfig) -> str:
    base = config.upstream_mcp_url.rstrip("/")
    extra = request.path_params.get("path")
    url = f"{base}/{extra}" if extra else base
    query = request.url.query
    if query:
        url = f"{url}?{query}"
    return url


def _username_for(cache_key: Tuple) -> str:
    # cache_key = (server, site, mapped_username, tenant, oid, mode, client_id)
    return cache_key[2]


# Run with: uvicorn --factory proxy:create_app --host 0.0.0.0 --port $PORT
