# Archived — custom Tableau MCP fork (retired)

These files are the **original custom Python MCP server** for Play 1. They are kept for
reference only and are **no longer the product**.

Play 1 pivoted to **wrap the official Tableau MCP server** (`ghcr.io/tableau/tableau-mcp`)
behind a thin auth sidecar, rather than maintain a fork. The official image ships HTTP
transport, Direct-Trust JWT impersonation, tool curation, result limits, and a far larger,
Tableau-supported tool set — our hand-built equivalents were a subset.

For the current solution see the Play 1 README and:

- `../deploy/azure/` — the Azure landing zone (official image + sidecar).
- `../sidecar/` — the auth sidecar that adds the Microsoft glue (x-api-key, Entra→Tableau RLS).
- `../deploy/copilot-studio/` — Copilot Studio wiring.

| File | Was |
|------|-----|
| `server.py` | The custom MCP server (3 tools: list/schema/query, + parked Pulse wrappers). |
| `Dockerfile` | Image build for the fork (was published by the retired `build-mcp-image.yml`). |
| `requirements.txt` | Python deps for the fork. |
| `.env.example` | Env template for the fork. |

Nothing here is built or deployed by current workflows.
