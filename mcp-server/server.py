#!/usr/bin/env python3
"""Tableau-Fabric-AI-Bridge MCP server.

Exposes the repo's live-tested Tableau capabilities as Model Context Protocol (MCP)
tools so an AI agent — Microsoft Copilot Studio / M365 Copilot, GitHub Copilot, Claude
Desktop, etc. — can inventory and query published Tableau datasources in natural
language. It is a thin wrapper around the proven skill scripts (one source of truth):

  * list_datasources       -> published datasources on the site (name, luid, project)
  * get_datasource_schema  -> field-level schema (captions, data types, roles, folders,
                              calculated-field formulas) so the agent learns exact field
                              names before querying
  * query_datasource       -> run a structured VizQL Data Service query (aggregations,
                              filters, sorting, top-N) and return rows

Transports (set MCP_TRANSPORT):
  * "stdio" (default) — for local dev in GitHub Copilot / VS Code / Claude Desktop.
  * "http"            — Streamable HTTP on /mcp for hosted use (Copilot Studio). Listens
                        on 0.0.0.0:$PORT (default 8000). If MCP_API_KEY is set, every
                        request must send `Authorization: Bearer <key>` (or `x-api-key`).

Tableau connection + auth reuse the same environment variables as the skill scripts:
  TABLEAU_SERVER, TABLEAU_SITE, TABLEAU_AUTH (pat|jwt, default jwt for hosted),
  PAT: TABLEAU_PAT_NAME, TABLEAU_PAT_VALUE
  JWT (Connected App Direct Trust): TABLEAU_CONNECTED_APP_CLIENT_ID,
       TABLEAU_CONNECTED_APP_SECRET_ID, TABLEAU_CONNECTED_APP_SECRET_VALUE,
       TABLEAU_JWT_USERNAME (the Tableau user to act as; a Site Admin bypasses RLS).

Read-only: the server never modifies Tableau. It keeps one warm sign-in per worker
process (refreshed on a TTL or auth failure) and signs out on shutdown.
"""

from __future__ import annotations

import json
import os
import re
import atexit
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# --------------------------------------------------------------------------------------
# Import the single source of truth: the live-tested skill client/auth/VDS plumbing.
# In the container the scripts are copied next to this file (see Dockerfile); for local
# dev we fall back to the in-repo skill path.
# --------------------------------------------------------------------------------------
def _locate_scripts_dir() -> Path:
    override = os.environ.get("TABLEAU_SCRIPTS_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates.append(here / "tableau_scripts")  # container layout
    candidates.append(
        here.parent / ".github" / "skills" / "tableau-datasource-profiler" / "scripts"
    )  # in-repo layout
    for c in candidates:
        if (c / "profile_datasource.py").exists():
            return c
    raise RuntimeError(
        "Could not locate the Tableau skill scripts (profile_datasource.py). "
        "Set TABLEAU_SCRIPTS_DIR to the directory containing it."
    )


sys.path.insert(0, str(_locate_scripts_dir()))

from profile_datasource import (  # noqa: E402
    TableauError,
    VDSRateLimit,
    build_schema_profile,
    connect_from_env,
)

from mcp.server.fastmcp import FastMCP  # noqa: E402

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _auth_mode() -> str:
    # Hosted deployments use a Connected App (JWT) by default; PAT for quick local dev.
    return (os.environ.get("TABLEAU_AUTH", "jwt") or "jwt").lower()


# --- Cached Tableau session -----------------------------------------------------------
# Tableau caps both sign-ins and VDS calls, and a single Copilot question may invoke
# several tools. Rather than sign in/out on every call, we keep one warm session per
# worker process and reuse it for a TTL (well under Tableau's token lifetime), refreshing
# on expiry or an auth failure. The token is just a header value, so sharing it across
# the threadpool that runs sync MCP tools is safe; sign-in is guarded by a lock.
_SESSION_TTL = int(os.environ.get("TABLEAU_SESSION_TTL", "540"))  # seconds (~9 min)
_conn_lock = threading.Lock()
_conn: Dict[str, Any] = {"client": None, "expires": 0.0}


def _get_client():
    now = time.time()
    with _conn_lock:
        client = _conn["client"]
        if client is not None and client.token and now < _conn["expires"]:
            return client
        rest_version = os.environ.get("TABLEAU_REST_VERSION", "3.24")
        client = connect_from_env(rest_version=rest_version, auth=_auth_mode())
        _conn["client"] = client
        _conn["expires"] = now + _SESSION_TTL
        return client


def _invalidate() -> None:
    with _conn_lock:
        client = _conn["client"]
        _conn["client"] = None
        _conn["expires"] = 0.0
    if client is not None:
        try:
            client.sign_out()
        except Exception:
            pass


def _is_auth_error(msg: str) -> bool:
    return ("Sign-in" in msg) or ("Not signed in" in msg) or ("(401" in msg)


def _execute(fn: "Callable[[Any], str]") -> str:
    """Run fn(client) with the cached session; refresh once on auth failure."""
    for attempt in (1, 2):
        try:
            client = _get_client()
        except TableauError as exc:
            return json.dumps({"error": f"Tableau connection failed: {exc}"})
        try:
            return fn(client)
        except VDSRateLimit as exc:
            return json.dumps({"error": str(exc), "retryable": True})
        except TableauError as exc:
            msg = str(exc)
            if attempt == 1 and _is_auth_error(msg):
                _invalidate()
                continue
            return json.dumps({"error": msg})
    return json.dumps({"error": "Unexpected error executing Tableau request."})


atexit.register(_invalidate)


def _resolve_luid(client, datasource: str) -> tuple:
    """Accept a datasource name OR a LUID; return (luid, display_name)."""
    if _UUID_RE.match(datasource.strip()):
        return datasource.strip(), datasource.strip()
    return client.resolve_datasource_luid(datasource)


# --------------------------------------------------------------------------------------
# MCP server + tools
# --------------------------------------------------------------------------------------
_PORT = int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000")))

# Guardrails against runaway result sizes / data exfiltration.
_MAX_ROW_LIMIT = int(os.environ.get("MCP_MAX_ROW_LIMIT", "1000"))
_ALLOW_DISAGGREGATE = (
    os.environ.get("MCP_ALLOW_DISAGGREGATE", "false").lower() in ("1", "true", "yes")
)

mcp = FastMCP(
    "tableau-fabric-bridge",
    host="0.0.0.0",
    port=_PORT,
    stateless_http=True,
    streamable_http_path="/mcp",
)


@mcp.tool()
def list_datasources() -> str:
    """List the published Tableau datasources available on the configured site.

    Returns a JSON array of {name, luid, project}. Call this first when the user
    refers to data without naming an exact datasource, so you can pick the right one
    to pass to get_datasource_schema or query_datasource.
    """
    def _do(client):
        items = client.list_datasources()
        return json.dumps({"datasources": items, "count": len(items)}, indent=2)

    return _execute(_do)


@mcp.tool()
def get_datasource_schema(datasource: str) -> str:
    """Get the field-level schema of a published datasource (by name or LUID).

    Use this BEFORE query_datasource to discover exact field captions, data types,
    roles (dimension/measure), folders, and calculated-field formulas. Returns JSON.

    Args:
        datasource: The published datasource name (e.g. "Superstore Datasource") or its LUID.
    """
    def _do(client):
        luid, name = _resolve_luid(client, datasource)
        page_size = int(os.environ.get("TABLEAU_PAGE_SIZE", "200"))
        profile = build_schema_profile(client, luid, page_size)
        profile.setdefault("datasource", {})
        profile["datasource"]["name"] = name
        profile["datasource"]["luid"] = luid
        return json.dumps(profile, indent=2, default=str)

    return _execute(_do)


@mcp.tool()
def query_datasource(
    datasource: str,
    fields: List[Dict[str, Any]],
    filters: Optional[List[Dict[str, Any]]] = None,
    row_limit: int = 100,
    disaggregate: bool = False,
) -> str:
    """Answer a business question by running a VizQL Data Service query on a datasource.

    You translate the user's natural-language question into a structured query: a list
    of `fields` (and optional `filters`). The server executes it read-only and returns
    rows as JSON. Discover exact field captions first with get_datasource_schema.

    Field kinds (each item in `fields`):
      * dimension  -> {"fieldCaption": "Region"}                      (groups the result)
      * measure    -> {"fieldCaption": "Sales", "function": "SUM"}    (aggregates; also
                       AVG, MEDIAN, COUNT, COUNTD, MIN, MAX, STDEV, VAR, YEAR, QUARTER,
                       MONTH, WEEK, DAY, TRUNC_YEAR/QUARTER/MONTH/WEEK/DAY)
      * calculated -> {"fieldCaption": "Margin", "calculation": "[Profit]/[Sales]"}
      * bin        -> {"fieldCaption": "Sales", "binSize": 100}
      Optional on any field: fieldAlias, maxDecimalPlaces, sortDirection (ASC|DESC),
      sortPriority (1 = primary sort key).

    Filter kinds (each item in `filters`, all take "field": {"fieldCaption": "..."}):
      * SET                    {"filterType":"SET","values":[...],"exclude":false}
      * MATCH                  {"filterType":"MATCH","contains":"..."}  (or startsWith/endsWith)
      * QUANTITATIVE_NUMERICAL {"filterType":"QUANTITATIVE_NUMERICAL",
                                "quantitativeFilterType":"RANGE","min":0,"max":100}
                                (also MIN, MAX, ONLY_NULL, ONLY_NON_NULL)
      * QUANTITATIVE_DATE      same as above with "minDate"/"maxDate" as ISO yyyy-mm-dd
      * DATE (relative)        {"filterType":"DATE","periodType":"MONTHS",
                                "dateRangeType":"LASTN","rangeN":3}
      * TOP                    {"filterType":"TOP","howMany":5,"direction":"TOP",
                                "fieldToMeasure":{"fieldCaption":"Sales","function":"SUM"}}

    Best practices: prefer aggregation over row-level data; use a TOP filter for
    "top N" questions; keep results small.

    Args:
        datasource: The datasource name or LUID.
        fields: The VDS query fields (non-empty list, see above).
        filters: Optional VDS filters (see above).
        row_limit: Max rows to return (default 100; capped at the server's limit).
        disaggregate: Return row-level data instead of aggregates (disabled unless the
            host allows it; use sparingly).
    """
    if not isinstance(fields, list) or not fields:
        return json.dumps(
            {"error": "`fields` must be a non-empty list. Call get_datasource_schema first."}
        )

    query: Dict[str, Any] = {"fields": fields}
    if filters:
        query["filters"] = filters

    # Clamp the row limit: unlimited (<=0) or oversized values fall back to the cap.
    if not isinstance(row_limit, int) or row_limit <= 0 or row_limit > _MAX_ROW_LIMIT:
        effective_limit = _MAX_ROW_LIMIT
    else:
        effective_limit = row_limit
    options: Dict[str, Any] = {"returnFormat": "OBJECTS", "rowLimit": effective_limit}

    notes: List[str] = []
    if disaggregate:
        if _ALLOW_DISAGGREGATE:
            options["disaggregate"] = True
        else:
            notes.append(
                "disaggregate was ignored: row-level extraction is disabled on this "
                "server (set MCP_ALLOW_DISAGGREGATE=true to enable)."
            )

    def _do(client):
        luid, name = _resolve_luid(client, datasource)
        rows = client.vds_query(luid, query, options)
        if rows is None:
            return json.dumps({
                "error": "VizQL Data Service is not available on this site "
                         "(requires Tableau 2025.1+ with VDS enabled).",
                "datasource": {"name": name, "luid": luid},
            })
        result: Dict[str, Any] = {
            "datasource": {"name": name, "luid": luid},
            "row_count": len(rows),
            "rows": rows,
        }
        if notes:
            result["notes"] = notes
        return json.dumps(result, indent=2, default=str)

    return _execute(_do)


# --------------------------------------------------------------------------------------
# HTTP transport wiring (Streamable HTTP for Copilot Studio / hosted use)
# --------------------------------------------------------------------------------------
def _build_http_app():
    """Return the Streamable HTTP ASGI app with a health route and optional API key."""
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    api_key = os.environ.get("MCP_API_KEY", "").strip()

    async def health_route(_request):
        return JSONResponse({"status": "ok", "service": "tableau-fabric-bridge"})

    inner = mcp.streamable_http_app()
    inner.routes.append(Route("/healthz", health_route, methods=["GET"]))

    if not api_key:
        sys.stderr.write(
            "WARNING: MCP_API_KEY is not set — the /mcp endpoint is unauthenticated. "
            "Set MCP_API_KEY or enable Microsoft Entra authentication on the host "
            "before exposing this publicly.\n"
        )
        return inner

    class _ApiKeyMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            if scope.get("path", "") == "/healthz":
                await self.app(scope, receive, send)
                return
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            presented = headers.get("x-api-key", "")
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                presented = auth[7:].strip()
            if presented != api_key:
                resp = Response("Unauthorized", status_code=401)
                await resp(scope, receive, send)
                return
            await self.app(scope, receive, send)

    return _ApiKeyMiddleware(inner)


def main() -> int:
    transport = (os.environ.get("MCP_TRANSPORT", "stdio") or "stdio").lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        import uvicorn

        app = _build_http_app()
        sys.stderr.write(
            f"Starting Tableau-Fabric-AI-Bridge MCP (Streamable HTTP) on "
            f"0.0.0.0:{_PORT}{mcp.settings.streamable_http_path}\n"
        )
        uvicorn.run(
            app, host="0.0.0.0", port=_PORT,
            log_level=os.environ.get("LOG_LEVEL", "info"),
        )
        return 0
    # Default: stdio for local dev.
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
