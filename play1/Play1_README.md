# Play 1 — Foundry Agent → Tableau VDS via Logic App

> **"Your Tableau data, answered in natural language — no migration required."**

This play connects an Azure AI Foundry agent (GPT-4o) to a published Tableau data source via the VizQL Data Service (VDS) API. Business users ask questions in plain English. The agent queries live Tableau data in real time and returns a natural language answer.

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
| `template.json` | ARM template — deploys the Logic App to Azure |
| `main.bicep` | Bicep equivalent of the ARM template |
| `openapi_spec.json` | OpenAPI spec — paste into Foundry as the tool definition |
| `agent_instructions.md` | Foundry agent instructions — paste into the Instructions field |

---

## Prerequisites

Before starting, you need:

- **Tableau Cloud or Tableau Server 2025.1+** with at least one Creator license
- A **published data source** on your Tableau site
- An **Azure subscription** with permission to create Logic Apps and Key Vaults
- An **Azure AI Foundry project** with GPT-4o deployed
- A **Tableau Personal Access Token (PAT)** — generate one in your Tableau account settings

> 🔄 **Adapting for your environment:** This play was built and tested against Tableau Cloud. If you are using Tableau Server, the API endpoints are the same but replace `YOUR_TABLEAU_POD` with your server hostname (e.g. `tableau.yourcompany.com`).

---

## Step 1 — Store Your PAT Secret in Azure Key Vault

Your Tableau PAT secret must be stored in Azure Key Vault. The Logic App retrieves it at runtime via managed identity — it is never hardcoded anywhere.

**If you already have a Key Vault:**
1. Go to your Key Vault → **Secrets** → **Generate/Import**
2. Name: choose a name (e.g. `tableau-pat-secret`) — note this for later
3. Value: paste your Tableau PAT secret
4. Click **Create**

**If you need to create a Key Vault:**
1. portal.azure.com → **Key Vaults** → **Create**
2. Choose your subscription, resource group, and region
3. Permission model: **Azure role-based access control (RBAC)**
4. Create, then add the secret as above

> 🔄 **Adapting for your environment:** Note your Key Vault name, resource group, subscription ID, and secret name — you will need all four in Step 2.

---

## Step 2 — Deploy the Logic App

The Logic App handles all Tableau authentication and API calls. Deploy it using the provided ARM template or Bicep file.

### Option A — Deploy via Azure Portal (recommended for first-time setup)

1. portal.azure.com → search **Deploy a custom template** → **Build your own template in the editor**
2. Paste the contents of `template.json` → **Save**
3. Fill in the parameters:

| Parameter | What to enter |
|-----------|--------------|
| `tableau_pod` | Your Tableau Cloud pod e.g. `10ay.online.tableau.com` |
| `tableau_site` | Your site contentUrl slug e.g. `mycompany` (find it in your Tableau URL) |
| `tableau_pat_name` | Your PAT name exactly as it appears in Tableau account settings |
| `tableau_datasource_luid` | The LUID of your target data source (see Finding Your Datasource LUID below) |
| `keyvault_secret_name` | The name of the secret you created in Step 1 |
| `connections_keyvault_externalid` | Resource ID of your Key Vault API connection (see note below) |
| `keyvault_managed_api_location` | Managed API ID for Key Vault in your region (see note below) |

4. Click **Review + create** → **Create**

### Option B — Deploy via Azure CLI

```bash
az deployment group create \
  --resource-group YOUR_RESOURCE_GROUP \
  --template-file template.json \
  --parameters tableau_pod=YOUR_POD \
               tableau_site=YOUR_SITE \
               tableau_pat_name=YOUR_PAT_NAME \
               tableau_datasource_luid=YOUR_LUID \
               keyvault_secret_name=YOUR_SECRET_NAME \
               connections_keyvault_externalid=YOUR_KV_CONNECTION_ID \
               keyvault_managed_api_location=YOUR_KV_MANAGED_API_ID
```

> 🔄 **Finding the Key Vault connection parameters:** After deploying, if the Key Vault connection parameters are unclear, you can create a Key Vault API connection manually in the portal (Logic Apps → API Connections → Add → Key Vault) and then copy its resource ID from the Properties blade.

---

## Step 3 — Enable Managed Identity on the Logic App

The Logic App uses a system-assigned managed identity to authenticate to Key Vault without storing credentials.

1. Go to your deployed Logic App → **Settings** → **Identity**
2. Under **System assigned** → toggle **Status** to **On** → **Save**
3. Copy the **Object (principal) ID** that appears — you need it for Step 4

---

## Step 4 — Grant the Logic App Access to Key Vault

1. Go to your Key Vault → **Access control (IAM)** → **Add role assignment**
2. Role: **Key Vault Secrets User**
3. Assign access to: **Managed identity**
4. Select your Logic App by name
5. **Review + assign**

### Fix Key Vault Networking

By default Key Vault may block external requests. You need to allow trusted Microsoft services:

1. Key Vault → **Settings** → **Networking**
2. Check **Allow trusted Microsoft services to bypass this firewall**
3. **Save**

> ⚠️ **Known limitation:** On some configurations the trusted services bypass is insufficient for Consumption Logic Apps using the Key Vault connector. If the Logic App still fails to retrieve the secret, temporarily set **Allow public access from all networks** to unblock the demo. For production deployments use Logic Apps Standard, which supports Key Vault references natively via app settings without this networking constraint.

---

## Step 5 — Get Your Logic App Trigger URL

1. Go to your Logic App → **Overview** → **Trigger history** or open the designer
2. Click the **When an HTTP request is received** trigger
3. Copy the **HTTP POST URL** — this is your Logic App trigger URL

It will look like:
```
https://prod-XX.westus2.logic.azure.com:443/workflows/YOUR_WORKFLOW_ID/triggers/When_an_HTTP_request_is_received/paths/invoke?api-version=2016-10-01&sp=...&sv=1.0&sig=YOUR_SIG
```

---

## Step 6 — Configure the OpenAPI Spec

Open `openapi_spec.json` and replace the two placeholder values:

```json
"servers": [
  {
    "url": "YOUR_LOGIC_APP_TRIGGER_URL"  ← paste your full trigger URL here
  }
],
```

And in the `sig` parameter default:
```json
{
  "name": "sig",
  "schema": {
    "default": "YOUR_LOGIC_APP_SIG"  ← paste just the sig value here
  }
}
```

> 🔄 **Adapting for your environment:** The `sig` value is the SAS token at the end of your trigger URL (everything after `sig=`). The other query parameters (`api-version`, `sp`, `sv`) are standard and don't need to change.

---

## Step 7 — Update the Agent Instructions

Open `agent_instructions.md` and update the field list to match your actual data source. The current instructions reference Superstore fields — replace them with the fields from your published data source.

To find your available fields:
1. Open your data source in Tableau
2. Go to the data source editor — all field names listed there are valid `fieldCaption` values for VDS queries
3. Note which fields are dimensions (no aggregation needed) and which are measures (require SUM, AVG, etc.)

> 🔄 **Adapting for your environment:** Field captions must exactly match what appears in Tableau. Case and spacing matter. `Sub-Category` is not the same as `Sub Category`.

---

## Step 8 — Create the Foundry Agent

1. Go to [ai.azure.com](https://ai.azure.com) → your project → **Agents** → **New agent**
2. Model: **GPT-4o** (recommended — GPT-4o mini may struggle with complex query construction)
3. Name it something descriptive e.g. `tableau-vds-agent`
4. Paste the contents of `agent_instructions.md` into the **Instructions** field
5. Under **Tools** → **Add** → **Custom** → **OpenAPI**
6. Paste the updated contents of `openapi_spec.json`
7. Authentication: **Anonymous** (the Logic App SAS token handles security)
8. **Save**

---

## Step 9 — Test

Ask the agent a natural language question about your data. Good starter questions:

- *"What were total sales by category?"*
- *"How many unique orders were placed in [State]?"*
- *"What was the percent difference in sales between last year and this year?"*
- *"Show me profit by region for Q1"*

If it works, you should get a natural language answer with specific numbers within 10-15 seconds.

---

## Finding Your Datasource LUID

The LUID (Locally Unique Identifier) is the unique ID of your published data source. You need it to tell VDS which data source to query.

**Option A — Via Tableau REST API:**
```
GET https://YOUR_POD/api/3.24/auth/signin  (authenticate first)
GET https://YOUR_POD/api/3.24/sites/YOUR_SITE_ID/datasources
```
The response includes a `datasource` array — each item has an `id` field. That is the LUID.

**Option B — Via Tableau Cloud UI:**
1. Go to your Tableau Cloud site → **Explore** → find your data source
2. Click on it → the URL contains the LUID:
   `https://YOUR_POD/datasources/YOUR_LUID/...`

**Option C — Via the Play 3 notebook** (if you have Play 3 set up):
The data source discovery cell prints the LUID of every data source on your site.

---

## Known Limitations and Gotchas

### Foundry agent response size limit
The Foundry agent has a maximum payload size for tool responses. Raw row-level queries against large data sources will exceed this limit. Always use aggregation functions (SUM, AVG, COUNT, COUNTD) on measures and date truncation (YEAR, QUARTER, MONTH) on date fields. The agent instructions enforce this, but be aware of it if you modify the instructions.

### Tableau relationship-based data sources
Tableau data sources built with the modern relationship model (introduced in Tableau 2020.2, now the default) keep logical tables separate and resolve joins at query time. When VDS queries a field from a related table, it performs a join at that moment — rows without a match are silently dropped, which can affect aggregate totals.

**Before connecting any data source to this play:**
- Check the data model in Tableau's data source editor
- If the source uses relationships (multiple logical tables connected by lines), treat each logical table as independent
- Either query only fields from the primary table, or create a dedicated published data source that pre-flattens the tables you need via a traditional join

> This is not a limitation specific to this play — it affects any tool built on VDS, including the official Tableau MCP Server. Understanding the data model is a prerequisite for building AI interfaces over Tableau data sources.

### High cardinality dimensions
Dimensions with many unique values (Order ID, Customer Name, Product Name, exact dates) will produce large result sets that may exceed Foundry's response limit. The agent instructions restrict Order ID to COUNTD only and require date truncation. If you add new fields to the instructions, apply the same judgment.

### Key Vault networking on Consumption Logic Apps
See Step 4 note above. Logic Apps Standard resolves this cleanly via app settings.

### Tableau Server version requirement
VDS requires Tableau Server 2025.1 or later. Customers on earlier versions need to upgrade before this play is possible.

### PAT expiry
Tableau PATs expire after a configurable period (default 15 days on Tableau Cloud). When your PAT expires, update the secret value in Key Vault — the Logic App will pick up the new value automatically on the next run. No Logic App changes needed.

---

## Production Hardening Notes

This play is designed as a demo asset. For production deployment consider:

- **Logic Apps Standard** — supports Key Vault references natively, eliminates the networking complexity
- **Private endpoints** on Key Vault — removes the need for public network access
- **JWT authentication** instead of PAT — better for service account flows, supports more granular scoping
- **Error handling in the Logic App** — add failure branches to handle Tableau auth failures, VDS errors, and Key Vault access failures gracefully
- **Rate limiting awareness** — VDS queries count against a site-wide cap of 100 queries/hour per Creator license. High-frequency agent usage in a multi-user deployment needs to account for this

---

## Deployment Checklist

- [ ] PAT secret stored in Key Vault
- [ ] Logic App deployed from ARM template
- [ ] Managed identity enabled on Logic App
- [ ] Key Vault Secrets User role assigned to Logic App managed identity
- [ ] Key Vault networking allows Logic App access
- [ ] Logic App trigger URL copied
- [ ] `openapi_spec.json` updated with trigger URL and sig
- [ ] `agent_instructions.md` updated with your data source fields
- [ ] Foundry agent created with GPT-4o
- [ ] Instructions pasted into agent
- [ ] OpenAPI tool added to agent
- [ ] Test query returns correct results

---

*Part of the Tableau + Microsoft Fabric AI Bridge project.*  
*Play 2 (Tableau Metadata → Fabric Lakehouse), Play 3 (Tableau VDS → Fabric Lakehouse), and Play 4 (Semantic Model Generator) also available.*
