# Play 1 — Foundry Agent → Tableau VDS via Logic App

> **"Your Tableau data, answered in natural language — no migration required."**

This play connects an Azure AI Foundry agent (GPT-4o) to a published Tableau datasource via the VizQL Data Service (VDS) API. Business users ask questions in plain English. The agent queries live Tableau data in real time and returns a natural language answer.

**This is not a data pipeline.** No data is copied, ingested, or replicated. The agent talks directly to Tableau at query time.

---

## Architecture

```
User (natural language question)
        ↓
Azure AI Foundry Agent (GPT-4o)
        ↓  OpenAPI tool call
Azure Logic App (Consumption)
        ↓  GET secret
Azure Key Vault (PAT secret)
        ↓  POST /auth/signin
Tableau REST API (session token)
        ↓  POST /vizql-data-service/query-datasource
Tableau VizQL Data Service
        ↓  aggregated JSON results
Azure AI Foundry Agent
        ↓
User (natural language answer)
```

---

## Files in This Folder

| File | Purpose |
|------|---------|
| `deploy_logicapp.bicep` | Step 1 — deploys the Logic App with managed identity enabled |
| `deploy_connection.bicep` | Step 2 — deploys the Key Vault connection and full Logic App workflow |
| `openapi_spec.json` | OpenAPI spec — paste into Foundry as the tool definition |
| `agent_instructions.md` | Foundry agent instructions — paste into the Instructions field |
| `Play1_Agent_Instructions_Generator.ipynb` | Utility notebook — auto-generates agent instructions from your datasource |

---

## Prerequisites

Before starting, you need:

- **Tableau Cloud or Tableau Server 2025.1+** with at least one Creator license
- A **published datasource** on your Tableau site
- An **Azure subscription** with permission to create Logic Apps and Key Vaults
- An **Azure AI Foundry project** with GPT-4o deployed
- A **Tableau Personal Access Token (PAT)** — generate one in your Tableau account settings. Set the expiration to the maximum allowed value (up to 1 year) to avoid the Logic App silently failing mid-demo when the PAT expires
- The **Setup Reference** filled in: open `Setup/setup_reference.html` and have it ready

> 🔄 **Adapting for your environment:** This play was built and tested against Tableau Cloud. For Tableau Server, replace `YOUR_TABLEAU_POD` with your server hostname e.g. `tableau.yourcompany.com`.

---

## Step 1 — Create Your Key Vault and Store the PAT Secret

Your Tableau PAT secret must be stored in Azure Key Vault. The Logic App retrieves it at runtime via managed identity — it is never hardcoded anywhere.

1. portal.azure.com → **Key Vaults** → **Create**
2. Choose your subscription, resource group, and region — **use the same region for everything in this play**
3. Permission model: **Azure role-based access control (RBAC)**
4. **Create**
5. Once created → **Secrets** → **Generate/Import**

> ⚠️ **RBAC propagation:** After creating a new Key Vault you may see "The operation is not allowed by RBAC" when navigating to Secrets. Wait 2-3 minutes and refresh — this is normal and resolves on its own.

6. Name: your secret name e.g. `tableau-pat-secret` — note this for the deploy command
7. Value: paste your Tableau PAT secret
8. **Create**

**Set Key Vault networking:**
1. Key Vault → **Networking**
2. Check **Allow trusted Microsoft services to bypass this firewall**
3. **Save**

> ⚠️ **Known limitation:** On some Consumption Logic App configurations the trusted services bypass is insufficient. If the Logic App fails to retrieve the secret at runtime, set **Allow public access from all networks** temporarily. For production, use Logic Apps Standard which handles Key Vault references natively.

---

## Step 2 — Deploy the Logic App

The deployment uses two Bicep files run in sequence. The full command sequence is auto-generated in `Setup/setup_reference.html` — fill in all your values there first and copy the generated command block.

**Before running:**
1. Open [Azure Cloud Shell](https://portal.azure.com/#cloudshell) in your browser
2. Upload both `deploy_logicapp.bicep` and `deploy_connection.bicep` via **Manage files → Upload**
3. Copy the full deploy sequence from the Setup Reference and paste it into Cloud Shell

**What the command sequence does:**
1. Deploys the Logic App with managed identity enabled
2. Automatically grants the Logic App **Key Vault Secrets User** role on your Key Vault
3. Waits 3 minutes for RBAC to propagate
4. **During the wait (important):** go to Azure Portal → **API Connections** → find `keyvault-{your-region}` → **General** → **Edit API connection** → **Authorize** → **Save**
5. Deploys the Key Vault connection and full Logic App workflow

> ⚠️ **Expected behavior:** The first deployment will show a `WorkflowManagedIdentityConfigurationInvalid` error before the role assignment is granted — this is normal and expected. The sequence handles this automatically.

> ⚠️ **Rerunning:** The command sequence is safe to rerun. `RoleAssignmentExists` errors are suppressed automatically.

> ⚠️ **Subscription ID:** Use the GUID format (e.g. `f108977f-bc85-4ab6-a29e-ee78a8b03fa8`) not the display name when filling in the Setup Reference.

---

## Step 3 — Get Your Logic App Trigger URL

1. Go to your Logic App in the Azure Portal
2. Open the **designer**
3. Click the **When an HTTP request is received** trigger
4. Copy the **HTTP POST URL**

It will look like:
```
https://prod-XX.westus3.logic.azure.com:443/workflows/YOUR_WORKFLOW_ID/triggers/When_an_HTTP_request_is_received/paths/invoke?api-version=2016-10-01&sp=...&sv=1.0&sig=YOUR_SIG
```

Save this in the **Logic App trigger URL** field in the Setup Reference.

---

## Step 4 — Configure the OpenAPI Spec

Open `openapi_spec.json` and replace the two placeholder values:

```json
"servers": [
  {
    "url": "YOUR_LOGIC_APP_TRIGGER_URL"
  }
],
```

And in the `sig` parameter default:
```json
{
  "name": "sig",
  "schema": {
    "default": "YOUR_LOGIC_APP_SIG"
  }
}
```

> The `sig` value is everything after `sig=` in your trigger URL. The other query parameters (`api-version`, `sp`, `sv`) are standard — do not change them.

---

## Step 5 — Generate Agent Instructions

Use `Play1_Agent_Instructions_Generator.ipynb` to auto-generate the agent instructions from your Tableau datasource. No Fabric lakehouse required.

1. Open the notebook in Fabric (or any Jupyter environment)
2. Fill in Cell 1:
   - `PAT_NAME` — your PAT name
   - `PAT_SECRET` — your PAT secret value
   - `POD` — your Tableau Cloud pod e.g. `10ay.online.tableau.com`
   - `SITE` — your site contentUrl slug
   - `DATASOURCE_LUID` — your datasource LUID (numeric ID from the Tableau Cloud URL)
   - `DATASOURCE_NAME` — display name for the datasource
3. Run all cells
4. Copy everything between the dividers in the Cell 4 output

> **Finding your datasource LUID:** Open the datasource in Tableau Cloud — the LUID is the numeric ID in the URL e.g. `114001783`. It is **not** a UUID format.

If you prefer to edit manually, open `agent_instructions.md` and update the field list to match your datasource. Field captions must exactly match what appears in Tableau — `Sub-Category` is not the same as `Sub Category`.

---

## Step 6 — Create the Foundry Agent

1. Go to [ai.azure.com](https://ai.azure.com) → your project → **Agents** → **New agent**
2. Model: **GPT-4o** (GPT-4o mini may struggle with complex query construction)
3. Name: e.g. `tableau-vds-agent`
4. Paste the Cell 4 output from the instructions generator into the **Instructions** field
5. **Tools** → **Add** → **Custom** → **OpenAPI**
6. Paste the updated contents of `openapi_spec.json`
7. Authentication: **Anonymous** (the Logic App SAS token handles security)
8. **Save**

---

## Step 7 — Test

Ask the agent a natural language question about your data:

- *"What were total sales by category?"*
- *"How many unique orders were placed in California?"*
- *"Show me profit by region for Q1"*
- *"What was the top performing sub-category last year?"*

You should get a natural language answer with specific numbers within 10-15 seconds.

---

## Finding Your Datasource LUID

| Method | How |
|--------|-----|
| Tableau Cloud UI | Open the datasource → the numeric ID in the URL is the LUID e.g. `114001783` |
| Instructions Generator notebook | Run `Play1_Agent_Instructions_Generator.ipynb` — it discovers all datasources and prints their LUIDs |
| Tableau REST API | `GET /api/3.24/sites/{siteId}/datasources` — each item has an `id` field |

---

## Known Limitations

**Foundry agent response size limit**
Always use aggregation functions (SUM, AVG, COUNT, COUNTD) on measures and date truncation (YEAR, QUARTER, MONTH) on dates. Raw row-level queries will exceed the payload limit. The generated agent instructions enforce this automatically.

**Tableau relationship-based datasources**
VDS performs joins at query time when fields from multiple logical tables are requested. Rows without a match are silently dropped, which can affect aggregate totals. Query fields from one logical table at a time, or create a pre-flattened published datasource.

**High cardinality dimensions**
Dimensions with many unique values (Order ID as a dimension, exact dates, Customer Name) produce large result sets. The instructions restrict these by default — apply the same judgment if you add fields.

**PAT expiry**
PATs expire after a configurable period. Set expiration to the maximum when generating. When a PAT expires, update the secret value in Key Vault — the Logic App picks it up automatically on the next run, no redeployment needed.

**Tableau Server version**
VDS requires Tableau Server 2025.1 or later.

---

## Production Hardening Notes

- **Logic Apps Standard** — supports Key Vault references natively, eliminates the networking complexity
- **Private endpoints** on Key Vault — removes the need for public network access
- **Error handling** — add failure branches to the Logic App for Tableau auth failures, VDS errors, and Key Vault access failures
- **Rate limiting** — VDS queries count against a site-wide cap of 100 calls/hour per Creator license

---

## Deployment Checklist

- [ ] Key Vault created with PAT secret stored
- [ ] Key Vault networking set to allow trusted Microsoft services
- [ ] Both Bicep files uploaded to Cloud Shell
- [ ] Full deploy sequence run successfully
- [ ] API connection authorized in portal during the sleep window
- [ ] Logic App trigger URL copied and saved in Setup Reference
- [ ] `openapi_spec.json` updated with trigger URL and sig
- [ ] Instructions generator notebook run — output copied
- [ ] Foundry agent created with GPT-4o
- [ ] Instructions pasted into agent
- [ ] OpenAPI tool added to agent
- [ ] Test query returns correct results

---

*Part of the Tableau + Microsoft Fabric AI Bridge project.*
*Play 2 (Tableau Metadata → Fabric Lakehouse), Play 3 (Tableau VDS → Fabric Lakehouse), and Play 4 (Semantic Model Generator) also available.*
