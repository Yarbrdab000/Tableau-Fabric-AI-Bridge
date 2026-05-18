# Tableau + Microsoft Fabric AI Bridge

> **"You don't have to migrate your data to modernize it."**

This repository contains a collection of plays that bridge existing Tableau investments
with the Microsoft AI and Fabric ecosystem. The philosophy across all plays is the same:
meet customers where their data already lives, add AI on top, and let the ceiling sell
the modernization.

These are **"AI on top of legacy" plays — not migration plays.**

---

## Repository Structure

```
tableau-fabric-ai-bridge/
├── README.md
└── play1/
    ├── Tableau_VDS_Bridge.ipynb    # Fabric notebook — the implementation
    └── Play1_Runbook.docx          # Full technical runbook
```

---

## Plays

| Play | What it does | Status |
|------|-------------|--------|
| **Play 1** | Pull governed Tableau data sources into Fabric Lakehouse via VDS API | ✅ Complete |
| **Play 2** | Connect a Fabric Data Agent to Tableau via the Tableau MCP Server | 🔄 In progress |
| **Play 3** | Surface Tableau metadata and lineage inside OneLake Catalog | 📋 Planned |

---

# Play 1 — Tableau VDS → Fabric Lakehouse

## What This Play Does

Tableau's VizQL Data Service (VDS) is a REST API that lets you query published Tableau
data sources programmatically — returning JSON data without needing to render a
visualization. This play uses VDS to pull governed Tableau data into a Microsoft Fabric
Lakehouse as a Delta table.

The key architectural insight: **Tableau has likely become a de facto semantic layer in
your customer's environment.** Teams have spent years curating data sources, defining
metrics, certifying dashboards, and establishing governance. This play treats those
Tableau data sources as a governed system of record and extends their reach into Fabric —
without touching or replacing them.

**What we are NOT doing:**
- Replatforming the data model
- Reimplementing business logic
- Disrupting upstream pipelines or existing Tableau workflows

**What we ARE doing:**
- Accessing curated data programmatically via a supported REST API
- Landing it in Fabric where it can power AI, semantic models, and downstream analytics
- Preserving all existing Tableau governance and ownership

---

## Architecture

```
Tableau Cloud / Tableau Server
  └── Published Data Source (governed, certified)
          │
          │  VizQL Data Service REST API
          │  POST /api/v1/vizql-data-service/query-datasource
          │  Auth: Personal Access Token (PAT)
          ▼
Microsoft Fabric — PySpark Notebook
  └── pandas DataFrame → spark.createDataFrame()
          │
          │  Delta write with overwriteSchema
          ▼
Fabric Lakehouse (Delta table)
  ├── SQL Analytics Endpoint  →  T-SQL queries
  ├── Power BI                →  Semantic model / reports
  └── Fabric Data Agent       →  Natural language (Play 2)
```

---

## Prerequisites

Before you start, make sure you have:

| Requirement | Notes |
|-------------|-------|
| Tableau Cloud **or** Tableau Server 2025.1+ (Or Tableau Cloud Trial Site) | VDS is not available on earlier Tableau Server versions |
| **Creator license** on the Tableau site | Required for VDS API access — Viewer/Explorer licenses will not work |
| A **published data source** in Tableau | The data source must be published to the site, not just embedded in a workbook |
| **API Access** enabled on the data source | Check in Tableau: Data Source → More actions → Edit Connection → API Access |
| Azure Key Vault | For secure credential storage — do not hardcode PAT secrets |
| Microsoft Fabric workspace | With a Lakehouse item created |

---

## One-Time Setup

### Step 1 — Generate a Personal Access Token in Tableau

A PAT is how the notebook authenticates to Tableau. It's scoped to your user account
and can be revoked at any time without changing your password.

1. Log into Tableau Cloud or Tableau Server
2. Click your **avatar** (top right) → **My Account Settings**
3. Scroll to **Personal Access Tokens** → **Create**
4. Give it a descriptive name (e.g. `Fabric-Bridge-Prod`)
5. **Copy the secret immediately** — it is only shown once and cannot be retrieved later

**Also note down:**
- Your **pod** — the first part of your Tableau Cloud URL (e.g. `10ay.online.tableau.com`)
- Your **site contentUrl** — the slug in the URL after `/site/` (e.g. `mycompany`)

> **🔄 Adapting for your environment:** Every Tableau Cloud site has a different pod and
> contentUrl. Tableau Server customers use their server hostname instead of a pod.
> These values go into `POD` and `SITE` in the notebook config cell.

---

### Step 2 — Store the PAT in Azure Key Vault

Never hardcode a PAT secret in a notebook. Use Key Vault so the credential is:
- Not visible in source control
- Centrally managed and rotatable
- Auditable

**Create the Key Vault:**
1. Go to [portal.azure.com](https://portal.azure.com) → search **Key Vault** → **Create**
2. Choose your subscription and resource group
3. Give it a name (e.g. `my-tableau-kv`)
4. On the **Access configuration** tab → set Permission model to **Azure role-based access control (RBAC)**
5. Review + Create

**Add the PAT as a secret:**
1. Open your Key Vault → **Secrets** → **Generate/Import**
2. Name: `tableau-pat-secret` (or any name — just remember it)
3. Value: paste your PAT secret
4. Create

**Grant yourself access to manage secrets:**
1. Key Vault → **Access control (IAM)** → **Add role assignment**
2. Role: **Key Vault Secrets Officer**
3. Assign to: your user account

> **🔄 Adapting for your environment:** The Key Vault name and secret name are entirely
> up to you. Update the `notebookutils.credentials.getSecret()` call in Cell 1 of the
> notebook to match whatever you named them.

---

### Step 3 — Grant Fabric Workspace Access to Key Vault

The Fabric notebook runs under a managed identity — that identity needs permission to
read the secret at runtime.

**Find your Fabric workspace managed identity Object ID:**
1. Open your Fabric workspace
2. **Workspace Settings** → **Workspace identity** → copy the **ID** value

**Grant access via Azure CLI** (the portal picker may not show managed identities in
some enterprise environments — CLI bypasses this):

```bash
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee-object-id <workspace-identity-object-id> \
  --assignee-principal-type ServicePrincipal \
  --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.KeyVault/vaults/<keyvault-name>
```

You can run this from **Azure Cloud Shell** (`>_` button in portal.azure.com) — no
local CLI installation needed.

> **🔄 Adapting for your environment:** Replace all four placeholder values with your
> own. The workspace identity Object ID is unique to each Fabric workspace. If you're
> running this in a different workspace, you need a new role assignment for that
> workspace's identity.

---

### Step 4 — Create a Lakehouse in Fabric

1. In your Fabric workspace → **New** → **Lakehouse**
2. Give it a name (e.g. `my_lakehouse`)
3. Once created, open the notebook → **Explorer pane** (left rail) → **Add lakehouse**
4. Select the Lakehouse you just created

> **🔄 Adapting for your environment:** The Lakehouse name feeds into `TABLE_NAME` in
> the notebook config. You can use an existing Lakehouse — just make sure it's attached
> to the notebook before running.

---

## Configuring the Notebook

Open `Tableau_VDS_Bridge.ipynb` and fill in **Cell 1 — Configuration**:

```python
PAT_NAME          = ""    # Your PAT name (e.g. "Fabric-Bridge-Prod")
POD               = ""    # Your Tableau pod (e.g. "10ay.online.tableau.com")
                          # Tableau Server: use your server hostname
SITE              = ""    # Your site contentUrl slug
                          # Tableau Server default site: use ""
DATASOURCE_SEARCH = ""    # Partial name match for your data source
                          # e.g. "sales" will match "Sales Summary" or "Sales Pipeline"
TABLE_NAME        = ""    # Name for the Delta table in your Lakehouse
                          # e.g. "sales_data" or "crm_opportunities"

PAT_SECRET = notebookutils.credentials.getSecret(
    "https://<your-keyvault-name>.vault.azure.net/",
    "<your-secret-name>"
)
```

> **🔄 Adapting for your environment:** These are the only values that change between
> environments or data sources. Everything else in the notebook is portable.

---

## Understanding the Field Query (Cell 5)

This is the cell most likely to need customization for your specific data source.

The notebook queries Tableau by specifying field captions — the exact names of fields
as they appear in the Tableau data source. **Run Cell 4 first** to see a full list of
available fields before editing Cell 5.

```python
query_fields = [
    {"fieldCaption": "Order ID"},       # Raw dimension — returns as-is
    {"fieldCaption": "Sales"},          # Raw measure — returns row-level value
    {"fieldCaption": "Profit Ratio"},   # Calculated field — Tableau computes it
]
```

**Adapting for your data source:**

| Scenario | What to change |
|----------|---------------|
| Different data source | Update `DATASOURCE_SEARCH` in Cell 1, run Cell 4 to see fields, update `query_fields` in Cell 5 |
| Want aggregated data | Add `"function": "SUM"` to measure fields (e.g. `{"fieldCaption": "Sales", "function": "SUM"}`) |
| Want filtered data | Add a `"filters"` block to the query body in Cell 5 |
| Data source has joined tables | Only include fields from the **primary** table — fields from secondary tables trigger inner joins and silently reduce row count |
| Field name has changed in Tableau | Re-run Cell 4 to get the updated field list, update Cell 5 to match |

**Supported aggregation functions:** `SUM`, `AVG`, `COUNT`, `COUNTD`, `MIN`, `MAX`,
`MEDIAN`, `STDEV`, and date truncations like `TRUNC_MONTH`, `TRUNC_YEAR`.

**Adding filters example:**

```python
"filters": [
    {
        "field": {"fieldCaption": "Region"},
        "filterType": "SET",
        "values": ["West", "East"],
        "exclude": False
    },
    {
        "field": {"fieldCaption": "Order Date"},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": "2023-01-01",
        "maxDate": "2023-12-31"
    }
]
```

---

## Running the Notebook

Run all cells **top to bottom** in order:

| Cell | What it does | What can go wrong |
|------|-------------|-------------------|
| **Cell 1** — Configuration | Loads variables, retrieves PAT from Key Vault | Key Vault access not configured → re-check Step 3 |
| **Cell 2** — Authenticate | Gets session token from Tableau REST API | Wrong POD/SITE/PAT → check your Tableau URL and credentials |
| **Cell 3** — Discover | Finds data source by name, resolves LUID | Name doesn't match → check `DATASOURCE_SEARCH`, verify data source is published |
| **Cell 4** — Metadata | Reads full field schema | Use this output to verify field names before editing Cell 5 |
| **Cell 5** — Query | Pulls full dataset via VDS API | 401/404 → re-run Cell 2 first; wrong field names → check Cell 4 output |
| **Cell 6** — Sanitize | Cleans column names for Delta compatibility | Automatic — no action needed |
| **Cell 7** — Write | Writes Delta table, verifies row count | Lakehouse not attached → add it in Explorer pane |

> **Tip:** If you get a 401 or 404 error on Cell 5 or later, **re-run Cell 2** to
> refresh the session token. Tokens can expire if too much time passes between cells,
> or if another session opened with the same PAT.

---

## Scheduling the Pipeline

To keep your Delta table fresh on a schedule:

1. In your Fabric workspace → **New** → **Data pipeline**
2. Add a **Notebook activity** to the pipeline canvas
3. In the **Settings** tab → select `Tableau VDS Bridge` from the notebook dropdown
4. Set your schedule under the **Schedule** tab (daily, hourly, etc.)

The pipeline runs under the Fabric workspace managed identity, which already has Key
Vault access from Step 3 — no additional credential configuration needed.

> **🔄 Adapting for your environment:** Consider your VDS rate limits when choosing
> a schedule frequency. Each Creator license on the Tableau site adds 100 queries/hour
> to the site-wide cap.

---

## Known Gotchas

### Fields from secondary/joined tables cause silent inner joins

If your Tableau data source has multiple logical tables (e.g. Orders joined to Returns,
or Accounts joined to Opportunities), including a field from a secondary table in your
query causes VDS to perform an inner join. This **silently reduces your row count** with
no error or warning.

**How to identify this:** Compare the row count in your VDS result against the row count
shown in the Tableau data source editor. If they don't match, a secondary table field is
likely causing a join.

**Fix:** Remove fields from secondary tables from your `query_fields` list in Cell 5.
If you need those fields, consider separate queries per table and joining in Fabric.

---

### Session token expires mid-session

Tableau session tokens can be invalidated if too much time passes between the auth call
(Cell 2) and later API calls, or if another process authenticates with the same PAT.

**Fix:** Re-run Cell 2 to get a fresh token, then continue from where you left off.
You do not need to restart from Cell 1.

---

### Schema mismatch on overwrite

If you change the field list in Cell 5 between runs, the Delta table schema will differ
from the existing table. Delta rejects this by default.

**Fix:** The notebook already handles this with `.option("overwriteSchema", "true")`.
If you add this notebook to a production pipeline and want to protect against accidental
schema changes, remove that option and handle schema migration explicitly.

---

### VDS rate limits

VDS queries count against a site-wide rate limit: 100 queries/hour per Creator license
assigned to the site. A site with 10 Creator licenses has a cap of 1,000 queries/hour.

**Design implication:** Don't make many small VDS calls. Pull the data you need in one
well-designed query and do aggregation/filtering downstream in Fabric.

---

### Tableau Server version requirement

VDS is only available on Tableau Server **2025.1 or later**. Customers on earlier
versions need to upgrade before this play is possible.

---

## What's Next

Once your Tableau data is in the Fabric Lakehouse as a Delta table, you can:

- **Query it with T-SQL** via the SQL Analytics Endpoint (no setup needed — it's automatic)
- **Connect Power BI** via a Fabric semantic model on top of the Delta table
- **Wire up a Fabric Data Agent** to answer natural language questions over the data (**Play 2**)
- **Schedule the notebook** via a Data Factory pipeline to keep data fresh

---

## Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `401 Unauthorized` on auth | Wrong PAT name, secret, or site | Double-check `PAT_NAME`, `SITE`, and the secret value in Key Vault |
| `404 Not Found` on VDS call | Session token expired | Re-run Cell 2 |
| `400 Bad Request` on VDS call | Invalid field caption | Re-run Cell 4 and verify field names exactly match |
| Row count lower than expected | Secondary table field causing inner join | Remove joined-table fields from Cell 5 |
| `AnalysisException: Schema mismatch` | Field list changed since last run | Already handled by `overwriteSchema: true` — if still failing, check for type changes |
| Key Vault access denied | Managed identity not assigned Secrets User role | Re-run Step 3 CLI command |
| `No data source matching X found` | Data source name mismatch or not published | Check `DATASOURCE_SEARCH` value and verify data source is published to the site |

---

*Part of the Tableau + Microsoft Fabric AI Bridge project.*
*Play 2 (Fabric Data Agent → Tableau via MCP) and Play 3 (Tableau Metadata → OneLake Catalog) coming soon.*
