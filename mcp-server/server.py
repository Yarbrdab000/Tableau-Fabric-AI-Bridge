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
  * list_pulse_metrics     -> curated Tableau Pulse metrics (KPIs) on the site
  * get_pulse_metric_insight -> Tableau's AI-generated narrative for a Pulse metric
                              (value, period-over-period change, trends, top contributors)
  * ask_pulse              -> natural-language question about a Pulse metric (AI brief)

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

import json
import os
import re
import atexit
import html
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
    PulseUnavailable,
    build_schema_profile,
    connect_from_env,
    pulse_default_metric,
    assemble_pulse_bundle_request,
    assemble_pulse_metric_group_context,
)

from mcp.server.fastmcp import FastMCP  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

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


class QueryField(BaseModel):
    """One column in a VizQL Data Service query (a dimension, measure, calc, or bin)."""

    model_config = ConfigDict(extra="allow")  # pass through any VDS property not named here

    fieldCaption: str = Field(
        description="Exact field caption as shown by get_datasource_schema, e.g. 'Sales' "
        "or 'Region'. Required."
    )
    function: Optional[str] = Field(
        default=None,
        description="Aggregation for a measure: SUM, AVG, MEDIAN, COUNT, COUNTD, MIN, MAX, "
        "STDEV, VAR, or a date part/trunc like YEAR, QUARTER, MONTH, WEEK, DAY, "
        "TRUNC_YEAR, TRUNC_QUARTER, TRUNC_MONTH, TRUNC_WEEK, TRUNC_DAY. Omit for a "
        "plain dimension (which groups the result).",
    )
    calculation: Optional[str] = Field(
        default=None,
        description="Inline calculation expression for a calculated field, e.g. "
        "'[Profit]/[Sales]'. Provide with a fieldCaption that names the result.",
    )
    binSize: Optional[float] = Field(
        default=None, description="Bucket size to bin a numeric field into ranges."
    )
    sortDirection: Optional[str] = Field(
        default=None, description="Sort order for this field: 'ASC' or 'DESC'."
    )
    sortPriority: Optional[int] = Field(
        default=None,
        description="Sort key order when sorting by multiple fields; 1 = primary sort key.",
    )
    fieldAlias: Optional[str] = Field(
        default=None, description="Rename the output column."
    )
    maxDecimalPlaces: Optional[int] = Field(
        default=None, description="Round numeric output to this many decimal places."
    )


class QueryFilter(BaseModel):
    """One filter in a VizQL Data Service query. Extra keys depend on filterType."""

    model_config = ConfigDict(extra="allow")  # carry filterType-specific keys verbatim

    filterType: str = Field(
        description="Filter kind: 'SET' (keep/exclude specific values via 'values' + "
        "optional 'exclude'), 'MATCH' (text 'contains'/'startsWith'/'endsWith'), "
        "'QUANTITATIVE_NUMERICAL' ('quantitativeFilterType' RANGE|MIN|MAX|ONLY_NULL|"
        "ONLY_NON_NULL with 'min'/'max'), 'QUANTITATIVE_DATE' (same with 'minDate'/"
        "'maxDate' as ISO yyyy-mm-dd), 'DATE' (relative: 'periodType' e.g. MONTHS, "
        "'dateRangeType' e.g. LASTN, 'rangeN'), or 'TOP' ('howMany', 'direction' "
        "TOP|BOTTOM, 'fieldToMeasure')."
    )
    field: Dict[str, Any] = Field(
        description="The field this filter targets, e.g. {'fieldCaption': 'Region'}. "
        "For a TOP filter this is the dimension being ranked (e.g. Region); the "
        "measure to rank by goes in 'fieldToMeasure'."
    )


@mcp.tool()
def query_datasource(
    datasource: str,
    fields: List[QueryField],
    filters: Optional[List[QueryFilter]] = None,
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
      * TOP                    {"filterType":"TOP","field":{"fieldCaption":"Region"},
                                "howMany":5,"direction":"TOP",
                                "fieldToMeasure":{"fieldCaption":"Sales","function":"SUM"}}
                                ("field" = the dimension to rank; "fieldToMeasure" = the
                                measure to rank it by)

    Best practices: prefer aggregation over row-level data; use a TOP filter for
    "top N" questions; keep results small.

    Superlatives ("highest", "most", "lowest", "largest", "best", "top"): rank the
    data — do NOT just set row_limit to 1. To get the single highest/lowest, sort the
    relevant measure (sortDirection DESC for highest / ASC for lowest, sortPriority 1)
    AND apply a TOP filter (direction TOP for highest / BOTTOM for lowest, howMany 1),
    then read the first row. Setting row_limit=1 without sorting returns an ARBITRARY
    row, not the maximum, and will give a wrong answer.

    Args:
        datasource: The datasource name or LUID.
        fields: The VDS query fields (non-empty list, see above).
        filters: Optional VDS filters (see above).
        row_limit: Max number of rows to return (default 100; capped at the server's
            limit). This only truncates the result set — it does NOT sort or rank.
            Never use row_limit=1 to answer "highest/lowest/most" questions; sort the
            measure and use a TOP filter instead (see Superlatives above).
        disaggregate: Return row-level data instead of aggregates (disabled unless the
            host allows it; use sparingly).
    """
    if not fields:
        return json.dumps(
            {"error": "`fields` must be a non-empty list. Call get_datasource_schema first."}
        )

    # Models accept extra keys (extra="allow"); model_dump preserves them while dropping
    # unset optionals so the VDS payload stays clean.
    query: Dict[str, Any] = {
        "fields": [f.model_dump(exclude_none=True) for f in fields]
    }
    if filters:
        query["filters"] = [f.model_dump(exclude_none=True) for f in filters]

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
# Tableau Pulse tools — curated metrics + AI-generated insight narratives.
# Pulse insight endpoints need the full metric definition in the request body; these
# tools assemble that server-side so the agent only supplies a metric name + question.
# --------------------------------------------------------------------------------------
_PULSE_LANGUAGE = os.environ.get("PULSE_LANGUAGE", "LANGUAGE_EN_US")
_PULSE_LOCALE = os.environ.get("PULSE_LOCALE", "LOCALE_EN_US")
_PULSE_TIME_ZONE = os.environ.get("PULSE_TIME_ZONE", "UTC")
_PULSE_BUNDLE_TYPES = ("ban", "springboard", "basic", "detail")

_PULSE_SCOPES_HINT = (
    "Tableau Pulse scopes were not granted at sign-in. Ensure Pulse is enabled on the "
    "site and the Connected App allows these scopes: "
    "tableau:insight_definitions_metrics:read, tableau:insight_metrics:read, "
    "tableau:metric_subscriptions:read, tableau:insights:read, tableau:insight_brief:create."
)


def _pulse_scopes_error(client) -> Optional[str]:
    """Return a JSON error string if Pulse scopes were not granted at sign-in, else None."""
    if not getattr(client, "pulse_scopes_granted", True):
        return json.dumps({"error": _PULSE_SCOPES_HINT})
    return None


def _html_to_text(markup: str) -> str:
    """Flatten Pulse HTML insight markup to plain text for chat surfaces."""
    if not markup:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", markup)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Pulse insight briefs embed citation tokens like "[[1]](id|id)" — drop them.
    text = re.sub(r"\[\[\d+\]\]\([^)]*\)", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _distill_bundle(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the human-readable narrative out of a Pulse insight-bundle response."""
    result = (resp or {}).get("bundle_response", {}).get("result", {}) or {}
    insights: List[Dict[str, Any]] = []
    for group in result.get("insight_groups", []) or []:
        for summary in group.get("summaries", []) or []:
            text = _html_to_text((summary.get("result") or {}).get("markup", ""))
            if text:
                insights.append({"type": group.get("type", "summary"), "text": text})
        for item in group.get("insights", []) or []:
            res = item.get("result") or {}
            text = _html_to_text(res.get("markup") or res.get("content") or "")
            if text:
                insights.append({
                    "type": item.get("insight_type", group.get("type", "insight")),
                    "question": res.get("question"),
                    "text": text,
                })
    return {
        "characterization": result.get("characterization", ""),
        "has_errors": bool(result.get("has_errors", False)),
        "insights": insights,
    }


@mcp.tool()
def list_pulse_metrics() -> str:
    """List the Tableau Pulse metrics published on the configured site.

    Tableau Pulse metrics are curated KPIs (e.g. "Sales", "Profit Ratio") that Tableau
    tracks and auto-analyzes. Call this first to discover what metrics exist, then pass a
    metric name to get_pulse_metric_insight (for a trend/contributor summary) or to
    ask_pulse (to ask a natural-language question about it).

    Returns a JSON array of {name, description, definition_id, default_metric_id,
    datasource_luid, measure, aggregation, time_dimension}.
    """
    def _do(client):
        scope_err = _pulse_scopes_error(client)
        if scope_err:
            return scope_err
        definitions = client.pulse_list_all_definitions()
        out = []
        for d in definitions:
            md = d.get("metadata", {}) or {}
            spec = d.get("specification", {}) or {}
            basic = spec.get("basic_specification", {}) or {}
            measure = basic.get("measure", {}) or {}
            metric = pulse_default_metric(d) or {}
            out.append({
                "name": md.get("name"),
                "description": md.get("description"),
                "definition_id": md.get("id"),
                "default_metric_id": metric.get("id"),
                "datasource_luid": (spec.get("datasource", {}) or {}).get("id"),
                "measure": measure.get("field"),
                "aggregation": measure.get("aggregation"),
                "time_dimension": (basic.get("time_dimension", {}) or {}).get("field"),
            })
        return json.dumps({"pulse_metrics": out, "count": len(out)}, indent=2)

    return _execute(_do)


@mcp.tool()
def get_pulse_metric_insight(metric: str, bundle_type: str = "ban") -> str:
    """Get Tableau Pulse's AI-generated insight narrative for a metric.

    Returns Tableau's own analysis of the metric's current value — period-over-period
    change, trends, anomalies, and top contributing dimensions — as plain text. Use this
    when the user asks how a tracked metric is doing (e.g. "how are sales trending?",
    "what's driving the change in profit?"). Discover metric names with list_pulse_metrics.

    Args:
        metric: The Pulse metric name (e.g. "Sales") or its definition/metric ID.
        bundle_type: Depth of analysis:
            * "ban" (default) — current value, period-over-period change, and the top
              insight per filterable dimension.
            * "springboard" — current value + change + the single highest-ranked insight.
            * "basic" — like springboard, focused on low-cardinality dimensions.
            * "detail" — full breakdown: performance over time, highs/lows/trends, top
              contributors per dimension, and follow-up insights.
    """
    def _do(client):
        scope_err = _pulse_scopes_error(client)
        if scope_err:
            return scope_err
        definition, m = client.pulse_resolve_metric(metric)
        if definition is None or m is None:
            return json.dumps({
                "error": f"No Pulse metric found matching '{metric}'. "
                         "Call list_pulse_metrics to see available metrics."
            })
        # Insight bundles require a basic_specification metric; viz-state-defined
        # metrics aren't supported here — steer the agent to ask_pulse instead.
        spec = definition.get("specification", {}) or {}
        if not spec.get("basic_specification"):
            return json.dumps({
                "error": f"The Pulse metric '{metric}' is not defined with a basic "
                         "specification, so an insight bundle can't be generated. Use "
                         "ask_pulse to ask a question about it instead.",
                "metric": {"name": (definition.get("metadata", {}) or {}).get("name"),
                           "definition_id": (definition.get("metadata", {}) or {}).get("id")},
            })
        bt = (bundle_type or "ban").lower()
        if bt not in _PULSE_BUNDLE_TYPES:
            bt = "ban"
        request = assemble_pulse_bundle_request(
            definition, m,
            time_zone=_PULSE_TIME_ZONE,
            language=_PULSE_LANGUAGE,
            locale=_PULSE_LOCALE,
        )
        resp = client.pulse_generate_insight_bundle(request, bt)
        md = definition.get("metadata", {}) or {}
        result = {
            "metric": {"name": md.get("name"), "definition_id": md.get("id"),
                       "metric_id": m.get("id")},
            "bundle_type": bt,
        }
        result.update(_distill_bundle(resp))
        return json.dumps(result, indent=2, default=str)

    return _execute(_do)


@mcp.tool()
def ask_pulse(question: str, metric: str, action_type: str = "ANSWER") -> str:
    """Ask a natural-language question about a Tableau Pulse metric (AI insight brief).

    Tableau answers conversationally using the metric's underlying data — e.g. "why did
    sales drop last month?", "summarize what I should know about profit", "what should I
    focus on to grow revenue?". Returns Tableau's answer plus suggested follow-up
    questions. Discover metric names with list_pulse_metrics.

    Args:
        question: The user's natural-language question about the metric.
        metric: The Pulse metric name (e.g. "Sales") or its definition/metric ID.
        action_type: The kind of response: "ANSWER" (default, answer a specific
            question), "SUMMARIZE" (summarize key changes), or "ADVISE" (recommend
            actions).
    """
    def _do(client):
        scope_err = _pulse_scopes_error(client)
        if scope_err:
            return scope_err
        definition, m = client.pulse_resolve_metric(metric)
        if definition is None or m is None:
            return json.dumps({
                "error": f"No Pulse metric found matching '{metric}'. "
                         "Call list_pulse_metrics to see available metrics."
            })
        action = (action_type or "ANSWER").upper().replace("ACTION_TYPE_", "")
        if action not in ("ANSWER", "SUMMARIZE", "ADVISE"):
            action = "ANSWER"
        context = assemble_pulse_metric_group_context(definition, m)
        brief_request = {
            "language": _PULSE_LANGUAGE,
            "locale": _PULSE_LOCALE,
            "time_zone": _PULSE_TIME_ZONE,
            "messages": [{
                "action_type": f"ACTION_TYPE_{action}",
                "content": question,
                "role": "ROLE_USER",
                "metric_group_context": [context],
                "metric_group_context_resolved": True,
            }],
        }
        resp = client.pulse_generate_insight_brief(brief_request)
        md = definition.get("metadata", {}) or {}
        follow_ups = [
            f.get("content") for f in (resp.get("follow_up_questions", []) or [])
            if f.get("content")
        ]
        return json.dumps({
            "metric": {"name": md.get("name"), "definition_id": md.get("id"),
                       "metric_id": m.get("id")},
            "question": question,
            "answer": _html_to_text(resp.get("markup", "")),
            "not_enough_information": bool(resp.get("not_enough_information", False)),
            "follow_up_questions": follow_ups,
        }, indent=2, default=str)

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
