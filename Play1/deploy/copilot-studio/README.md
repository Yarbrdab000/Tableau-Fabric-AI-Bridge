# Wire the Tableau MCP server into Microsoft Copilot Studio

This connects your deployed MCP server (an Azure Container App) to a Copilot Studio
agent so business users can ask natural-language questions about your Tableau
datasources. Tools are discovered automatically over MCP — you do **not** define
each action by hand.

You need two values from the Deploy-to-Azure step:

| Value | Where it came from |
| --- | --- |
| **MCP endpoint** | the `mcpEndpoint` output, e.g. `https://<app>.<region>.azurecontainerapps.io/mcp` |
| **MCP Api Key** | the `mcpApiKey` you set when deploying (the shared secret callers must send) |

There are two supported paths. **Option A (custom connector)** is the most reliable
and is what `mcp-connector.swagger.yaml` in this folder is for. **Option B** uses
Copilot Studio's built-in "Add a tool" MCP flow if your tenant has it.

---

## Prerequisites

- A Copilot Studio agent (or create one at <https://copilotstudio.microsoft.com>).
- **Generative orchestration must be ON** for the agent
  (Agent → **Settings** → **Generative AI** → *Orchestration* = generative). MCP tools
  are ignored under classic orchestration.

---

## Option A — Import the custom connector (recommended)

1. Open the swagger file in this folder: **`mcp-connector.swagger.yaml`**.
2. Edit one line — set `host:` to **your** Container App FQDN (the `mcpEndpoint`
   without `https://` and without the trailing `/mcp`). For example, for
   `https://tableau-mcp.graysea-5a3f72c8.westus3.azurecontainerapps.io/mcp`, the host is
   `tableau-mcp.graysea-5a3f72c8.westus3.azurecontainerapps.io`. (It is already set to
   the current test deployment.)
3. Go to **Power Apps** → <https://make.powerapps.com> → pick the same environment your
   agent uses → **More** → **Discover all** → **Custom connectors**
   (or **Solutions** → your solution → **New** → **Automation** → **Custom connector**).
4. Choose **New custom connector** → **Import an OpenAPI file** → upload the edited
   `mcp-connector.swagger.yaml` → name it `Tableau MCP` → **Continue**.
5. On the **Security** tab confirm: **API Key**, parameter label `x-api-key`,
   parameter name `x-api-key`, location **Header**. → **Create connector**.
6. Click **Test** (or **+ New connection**). When prompted for the API key, paste your
   **MCP Api Key**. (Listed under *Connections* afterward.)

Then add it to the agent:

7. In Copilot Studio open your agent → **Tools** (or **Actions**) → **+ Add a tool**.
8. Find **Tableau MCP** (Model Context Protocol) → **Add to agent**. Copilot connects to
   the server and lists the three tools (`list_datasources`, `get_datasource_schema`,
   `query_datasource`).

---

## Option B — Built-in MCP tool (if available in your tenant)

1. Copilot Studio → your agent → **Tools** → **+ Add a tool** →
   **New tool** → **Model Context Protocol**.
2. Server name: `Tableau MCP`. Server URL: your **MCP endpoint** (ends in `/mcp`).
   Transport: **Streamable HTTP**.
3. Authentication: **API key** → Header name `x-api-key` → value = your **MCP Api Key**.
   (If only `Authorization` is offered, use value `Bearer <your MCP Api Key>`.)
4. **Create** → **Add to agent**.

---

## Test it

In the agent's **Test** pane, ask things like:

- "What Tableau datasources can you see?"  → calls `list_datasources`.
- "What fields are in the Superstore datasource?"  → calls `get_datasource_schema`.
- "What were the top 3 regions by total sales?"  → calls `query_datasource`
  (you should get West / East / Central).

The agent should call the tools and answer from live Tableau data.

---

## Notes & troubleshooting

- **Tools don't appear / agent won't call them:** confirm generative orchestration is ON
  and the connection's API key matches the deployed `mcpApiKey`.
- **401 from the server:** the API key is wrong or not being sent in `x-api-key`.
- **Cold start:** the Container App scales to zero; the first request after idle can take
  a few seconds while a replica spins up. Subsequent calls are fast.
- **Access model:** the server queries Tableau as the single configured service account
  (`TABLEAU_JWT_USERNAME`). All agent users see what that account can see — scope it with
  least privilege. See `../../docs/customer-setup-guide.md`.
- **Security:** anyone with the endpoint URL **and** the API key can query. Treat the key
  as a secret; rotate it by updating the `mcp-api-key` Container App secret and the
  connector connection. For stronger auth, put Microsoft Entra in front (see the setup
  guide).
