# Customer Setup Guide — Natural-language Tableau in Microsoft Copilot

This guide takes you from nothing to **asking questions about your Tableau data inside
Microsoft Copilot**, by deploying the Tableau-Fabric-AI-Bridge MCP server into **your own
Azure subscription**. End to end it takes about **10–15 minutes**. You don't write any
code, and you don't run any servers yourself beyond clicking *Deploy*.

**What you'll need**
- A Tableau Cloud (or Server) site where you're a **Site Administrator**.
- An **Azure subscription** (any tier) and permission to create resources.
- A **Microsoft Copilot Studio** environment (or M365 Copilot with agent extensibility).

---

## Overview

```
[1] Create a Tableau Connected App   ->  gives the server permission to read your data
[2] Click "Deploy to Azure"          ->  stands up the MCP endpoint (HTTPS) in your tenant
[3] Add the endpoint to Copilot      ->  your users can now ask questions in Copilot
```

---

## Step 1 — Create a Tableau Connected App (one time, ~3 min)

This is how the server is allowed to query Tableau on your behalf, without storing
anyone's password. The server uses **one Tableau service account** (it does not map each
Copilot user to a Tableau identity), so choose that account deliberately in Step 2.

1. In Tableau Cloud, go to **Settings → Connected Apps**.
2. Click **New Connected App → Direct Trust**.
3. Give it a name (e.g. `Copilot MCP Bridge`) and select a project/level. Click **Create**.
4. Set the connected app to **Enabled**.
5. Under **Scopes**, enable:
   - `tableau:content:read`
   - `tableau:viz_data_service:read`
6. Click **Generate New Secret**. Copy these four values — you'll paste them in Step 2:
   - **Client ID**
   - **Secret ID**
   - **Secret Value** (shown once)
   - Your Tableau **site content URL** (the slug in your site's URL,
     e.g. `https://10ay.online.tableau.com/#/site/`**`acme-analytics`**)

> **Choose the service account deliberately** (`TABLEAU_JWT_USERNAME`). Every Copilot
> user's questions run as this one Tableau account. Use a **least-privilege user or
> group** that can see only the datasources you want this agent to expose. A **Site
> Admin** bypasses row-level security and sees all data — convenient for a demo, but a
> poor production default. For different audiences, deploy separate instances with
> different service accounts.

---

## Step 2 — Deploy to Azure (one click, ~5 min)

1. Click the **Deploy to Azure** button (in the
   [MCP server README](../README.md), or the link your vendor gave you).
2. In the portal form, choose your **Subscription**, **Resource group**, and **Region**.
3. Fill in the fields:

   | Field | Value |
   |-------|-------|
   | **Tableau Server** | Your pod URL, e.g. `https://10ay.online.tableau.com` |
   | **Tableau Site** | Your site content URL (slug) from Step 1 |
   | **Tableau Auth** | `jwt` |
   | **Connected App Client Id / Secret Id / Secret Value** | from Step 1 |
   | **Jwt Username** | a Tableau Site Admin email |
   | **Mcp Api Key** | invent a long random string (e.g. a GUID). You'll paste this into Copilot in Step 3. |

4. Click **Review + create → Create**. Wait for the deployment to finish.
5. Open the deployment's **Outputs**. Copy **`mcpEndpoint`** — it looks like
   `https://tableau-mcp.<region>.azurecontainerapps.io/mcp`.

> **Cost:** the server scales to zero when idle, so you typically pay only a few
> dollars a month (or less) for occasional use.

Quick check: open **`healthUrl`** from the outputs in a browser — it should return
`{"status":"ok"}`.

---

## Step 3 — Add the endpoint to Microsoft Copilot Studio (~3 min)

1. In **Copilot Studio**, open your agent (or create one) and make sure
   **generative orchestration** is turned on (required for MCP).
2. Go to **Tools → Add a tool → New tool → Model Context Protocol**.
3. Enter:
   - **Server URL**: the `mcpEndpoint` from Step 2.
   - **Authentication**: **API key**. Choose **Header**, header name **`x-api-key`**, and
     value = your **MCP Api Key** from Step 2. (Advanced alternative: header
     `Authorization` with value `Bearer <your MCP Api Key>`.)
4. Save. Copilot Studio connects and automatically discovers the three tools
   (`list_datasources`, `get_datasource_schema`, `query_datasource`).
5. Add the tools to your agent.

You're done. Try asking your agent:

> *"What were total sales by region in the Superstore datasource?"*
> *"Show me the top 5 states by profit."*

The agent will list datasources, read the schema, and run the query — answering in plain
language with live Tableau numbers.

---

## Optional — Harden with Microsoft Entra (recommended for production)

The API key already restricts who can call the endpoint. For an additional, identity-based
layer, enable **built-in authentication** on the Container App:

1. In the Azure portal, open your Container App → **Authentication**.
2. **Add identity provider → Microsoft**, accept the defaults to create an app
   registration, and set **Restrict access: Require authentication**.
3. Configure your Copilot Studio connector to use **OAuth 2.0 (Microsoft Entra)** instead
   of (or in addition to) the API key.

This ensures only authenticated callers in your tenant can reach the server.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `healthUrl` doesn't respond immediately | Scale-to-zero cold start — retry after ~15s. |
| Copilot can't connect | Re-check the `Authorization: Bearer <key>` header matches `Mcp Api Key`. |
| `VizQL Data Service is not available` | Your site needs Tableau **2025.1+ with VDS enabled**. |
| `VDS rate limit hit (429)` | VizQL Data Service allows ~100 calls/hour per Creator; retry shortly. |
| Empty/partial query results | The service account's row-level security may limit rows. Check that `Jwt Username` can see the data (without over-privileging it). |
| Sign-in fails | Verify the Connected App is **Enabled** and the secret value was copied correctly. |

---

## For vendors — publish the container image once

Customers click *Deploy to Azure*, which pulls a prebuilt public image. To produce it:

1. Merge this repo to `main`. The GitHub Action
   `.github/workflows/build-mcp-image.yml` builds and pushes
   `ghcr.io/<owner>/tableau-fabric-ai-bridge-mcp:latest` (no local Docker needed).
2. In your repo's **Packages**, open the image and set its visibility to **Public**
   (so the deploy button can pull it without registry credentials).
3. Share the **Deploy to Azure** button / link with your customers.

Prefer the CLI? Use [`deploy/azure/deploy.ps1`](../deploy/azure/deploy.ps1) after `az login`.
