# Tableau MCP Auth Sidecar

A small reverse proxy that sits in front of the **official** Tableau MCP server
(`ghcr.io/tableau/tableau-mcp`) to add the Microsoft-environment glue the official image
doesn't ship:

1. **Caller auth** — a shared `x-api-key` (simple, for Copilot Studio custom connectors and
   quick demos) and/or a Microsoft **Entra** identity that an upstream gateway (Azure
   Container Apps **Easy Auth**, or **APIM**) has already validated.
2. **Entra → Tableau identity passthrough (the hero)** — maps the caller's Entra UPN to a
   Tableau username, signs a Connected App (Direct Trust) JWT as that user, exchanges it for
   a Tableau session token, and injects it as `X-Tableau-Auth` so **Tableau row-level
   security applies per signed-in M365 user**.

The official image is left completely unmodified. The sidecar is the only public ingress;
the official server runs internal-only.

```
 Copilot Studio / M365 / Foundry
        │  (x-api-key  or  Entra OAuth)
        ▼
 Easy Auth / APIM  ── validates Entra, sets X-MS-CLIENT-PRINCIPAL
        ▼
 sidecar (this)   ── caller auth + Entra→Tableau mapping + X-Tableau-Auth injection
        ▼  localhost only
 official tableau-mcp (TRANSPORT=http, DANGEROUSLY_DISABLE_OAUTH=true,
                       ENABLE_PASSTHROUGH_AUTH=true)
        ▼
 Tableau Cloud / Server  (REST + Metadata + VizQL Data Service + Pulse)
```

## Identity modes (mutually exclusive, chosen at startup)

| `IDENTITY_MODE`   | Behavior                                                                 | Per-user RLS |
|-------------------|--------------------------------------------------------------------------|--------------|
| `service_account` | All calls run as the official server's own Tableau credentials. Sidecar just proxies. | No |
| `passthrough`     | Map Entra UPN → Tableau user, inject `X-Tableau-Auth`. Requires Easy Auth/APIM in front. | Yes |

`ON_UNRESOLVED_IDENTITY=deny` (the only supported value): if a caller's UPN can't be mapped
to a Tableau user, or the per-user sign-in fails, the request is **denied** — it never falls
back to a privileged service account.

## UPN → Tableau username mapping (`UPN_MAPPING_MODE`)

- `direct` — UPN is the Tableau username (common when both are the email).
- `transform` — swap the domain (`UPN_DOMAIN_FROM` → `UPN_DOMAIN_TO`); other domains are denied.
- `explicit` — look up an explicit map from `UPN_MAP_JSON` or `UPN_MAP_PATH` (case-insensitive).

SCIM is **not** required — it just keeps `direct` matches in sync automatically.

## Security model

- The sidecar **strips** all client-supplied identity headers (`X-Tableau-Auth`,
  `X-MS-CLIENT-PRINCIPAL*`, etc.) before forwarding. It trusts `X-MS-CLIENT-PRINCIPAL*`
  only when `TRUST_EASY_AUTH=true`, i.e. when a platform gateway sets them authentically.
- The official server must have **no public ingress** (internal-only). The sidecar is the
  complete auth boundary, which is why `DANGEROUSLY_DISABLE_OAUTH=true` is safe.
- Per-user Tableau session tokens are cached **in memory only**, keyed by the full identity
  tuple (server, site, mapped username, tenant, object id, mode, connected-app id) — never by
  UPN alone — and are never logged. A stale-token `401/403` evicts and re-signs-in once.

## Key environment variables

See [`deploy/local/.env.example`](../deploy/local/.env.example). Highlights:

| Var | Purpose |
|-----|---------|
| `UPSTREAM_MCP_URL` | Official server MCP URL (e.g. `http://localhost:8000/mcp`). |
| `ALLOW_API_KEY` / `SIDECAR_API_KEY` | Enable + set the shared caller key. |
| `TRUST_EASY_AUTH` | Trust platform-set Entra headers (required for passthrough). |
| `IDENTITY_MODE` | `service_account` or `passthrough`. |
| `TABLEAU_SERVER` / `TABLEAU_SITE` | Tableau pod + site content URL. |
| `TABLEAU_CONNECTED_APP_CLIENT_ID` / `_SECRET_ID` / `_SECRET_VALUE` | Direct Trust Connected App. |
| `UPN_MAPPING_MODE` + `UPN_DOMAIN_FROM`/`_TO` or `UPN_MAP_JSON`/`_PATH` | Identity mapping. |
| `TOKEN_CACHE_TTL_S` | Per-user session-token cache TTL (default 1800). |

## Run locally

Full stack (needs Docker), from `Play1/deploy/local/`:

```bash
cp .env.example .env   # fill in Tableau Connected App values
docker compose up --build
curl -s localhost:9000/healthz
```

Tests (no Docker needed), from `Play1/sidecar/`:

```bash
python -m venv .venv && . .venv/Scripts/activate    # or bin/activate on *nix
pip install -r requirements.txt pytest
python -m pytest tests -q
```

## Files

- `config.py` — env config + startup validation (hard-separates the two identity modes).
- `identity.py` — Entra extraction, UPN mapping, Connected App JWT, per-user sign-in, token cache.
- `proxy.py` — Starlette streaming reverse proxy (`/healthz`, `/mcp`).
- `tests/` — offline unit + integration tests against an in-process mock upstream.
