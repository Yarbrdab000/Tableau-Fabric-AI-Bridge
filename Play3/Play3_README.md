# Play 3 — Tableau Metadata → Fabric Lakehouse + Data Agent

> **"A unified governance view across your entire BI estate — without moving a single asset."**

This play pulls governance metadata from the Tableau Metadata API (GraphQL) and lands it
in a Microsoft Fabric Lakehouse as four Delta tables. A Fabric semantic model sits on top
of those tables, enabling a Fabric Data Agent to answer natural language governance
questions across your Tableau environment.

**This is a governance and discoverability play.** No Tableau data is moved or replicated.
Only metadata is extracted — schema definitions, field-level lineage, ownership,
certification status, and workbook dependencies.

---

## What This Play Does

Tableau environments contain a significant amount of valuable governance metadata that is
typically siloed inside Tableau itself. This play extracts that metadata and makes it
queryable in Fabric — enabling questions like:

- *"Which database tables are used by Tableau data sources?"*
- *"What data sources are certified and who owns them?"*
- *"Which workbooks depend on a specific data source?"*
- *"What calculated fields exist across all my data sources and what are their formulas?"*
- *"Which workbooks would be affected if the Orders table changed?"*

When combined with Phase 2 (Power BI Scanner API — coming soon), the agent can answer
cross-platform questions like:

- *"Which upstream database tables are shared between Tableau and Power BI?"*
- *"Where do we have duplicate coverage across both platforms?"*

---

## Architecture

```
Tableau Metadata API (GraphQL)
        ↓  Single paginated query per object type
Microsoft Fabric Notebook (PySpark)
        ↓  Parse and flatten
Four Delta Tables in Fabric Lakehouse
        ↓
Fabric Semantic Model (DirectQuery)
        ↓
Fabric Data Agent (natural language governance queries)
```

---

## Files in This Folder

| File | Purpose |
|------|---------|
| `Tableau_Metadata_Bridge.ipynb` | Fabric notebook — pulls metadata and writes Delta tables |
| `semantic_model.tmdl` | TMDL definition of the semantic model built on top of the Delta tables |
| `Play3_README.md` | This file |

> **Data Agent setup:** The Fabric Data Agent is created manually in the Fabric UI on top
> of the semantic model. See Step 5 below for setup instructions.

---

## Delta Tables

| Table | Grain | Key Contents |
|-------|-------|-------------|
| `tableau_datasources` | One row per published data source | Name, owner, project, certification status, connection type, field count, downstream workbook count |
| `tableau_fields` | One row per field per data source | Field name, type (ColumnField/CalculatedField/etc.), data type, role (dimension/measure), formula, hidden status |
| `tableau_lineage` | One row per relationship | Upstream database tables → datasource, datasource → downstream workbooks |
| `tableau_workbooks` | One row per workbook | Name, owner, project, sheet count, sheet names, connected published datasources |

---

## Prerequisites

- Tableau Cloud or Tableau Server 2025.1+
- Creator license on the Tableau site
- Azure Key Vault with Tableau PAT secret stored (same setup as Play 1)
- Microsoft Fabric workspace with a Lakehouse created for metadata
- Fabric workspace managed identity with Key Vault Secrets User role

> 🔄 **Adapting for your environment:** If you completed Play 1, you already have the
> Key Vault and managed identity configured. The same PAT and Key Vault secret work
> for this notebook — no additional Azure setup required.

---

## Step 1 — Create a Metadata Lakehouse

Create a dedicated Lakehouse for metadata tables to keep them separate from your
operational data (Play 1 Delta tables).

1. In your Fabric workspace → **New** → **Lakehouse**
2. Name it something like `Metadata_Lakehouse`
3. Open the notebook → **Explorer pane** (left rail) → **Add lakehouse** → select your
   new Metadata Lakehouse

> 🔄 **Adapting for your environment:** You can use an existing Lakehouse if you prefer.
> The four metadata tables won't conflict with Play 1 tables as long as the names don't
> overlap.

---

## Step 2 — Configure and Run the Notebook

Open `Tableau_Metadata_Bridge.ipynb` and fill in **Cell 1 — Configuration**:

```python
PAT_NAME        = ""    # Your PAT name (same as Play 1)
POD             = ""    # Your Tableau pod e.g. 10ay.online.tableau.com
SITE            = ""    # Your site contentUrl slug
KV_URL          = "https://<your-keyvault-name>.vault.azure.net/"
KV_SECRET_NAME  = "<your-secret-name>"

DS_TABLE        = "tableau_datasources"
FIELDS_TABLE    = "tableau_fields"
LINEAGE_TABLE   = "tableau_lineage"
WORKBOOKS_TABLE = "tableau_workbooks"
```

Then run all cells top to bottom:

| Cell | What it does |
|------|-------------|
| Cell 1 — Configuration | Loads variables, retrieves PAT from Key Vault |
| Cell 2 — Authenticate | Gets session token from Tableau REST API |
| Cell 3 — Query Metadata API | Sends GraphQL queries for datasources and workbooks (paginated) |
| Cell 4 — Parse datasources | Flattens datasource metadata to DataFrame |
| Cell 5 — Parse fields | Flattens field-level metadata to DataFrame |
| Cell 6 — Parse lineage | Builds upstream/downstream relationship rows |
| Cell 7 — Parse workbooks | Flattens workbook metadata to DataFrame |
| Cell 8 — Write Delta tables | Writes all four tables to Lakehouse |
| Cell 9 — Verify | Spot-check queries to confirm data landed correctly |

---

## Step 3 — Create the Semantic Model

Create a semantic model in Fabric on top of the four Delta tables.

1. In your Fabric workspace → **New** → **Semantic model**
2. Select your Metadata Lakehouse as the source
3. Add all four tables: `tableau_datasources`, `tableau_fields`, `tableau_lineage`,
   `tableau_workbooks`
4. Define the following relationships:

| From | To | On |
|------|----|----|
| `tableau_fields.datasource_id` | `tableau_datasources.datasource_id` | Many → One |
| `tableau_lineage.datasource_id` | `tableau_datasources.datasource_id` | Many → One |
| `tableau_workbooks.name` | `tableau_lineage.related_asset_name` | Many → One |

> 🔄 **Adapting for your environment:** The `semantic_model.tmdl` file in this folder
> contains the full model definition. To use it, open the semantic model in Power BI
> Desktop, then update the connection string in the expression source to point to your
> own Fabric workspace:
> ```
> AnalysisServices.Database("powerbi://api.powerbi.com/v1.0/myorg/YOUR_WORKSPACE_NAME",
> "YOUR_SEMANTIC_MODEL_NAME")
> ```
> Replace `YOUR_WORKSPACE_NAME` and `YOUR_SEMANTIC_MODEL_NAME` with your values.

---

## Step 4 — Create the Fabric Data Agent

1. In your Fabric workspace → **New** → **Data agent** (or search for it)
2. Select your semantic model as the data source
3. Add all four tables
4. In the agent instructions, paste the following:

```
You are a governance agent with access to Tableau metadata. You can answer questions
about published data sources, their fields, lineage, and downstream workbook dependencies.

Available tables:
- tableau_datasources: Published data sources with owner, certification, connection info
- tableau_fields: All fields per data source including calculated field formulas
- tableau_lineage: Upstream database tables and downstream workbook relationships
- tableau_workbooks: Workbooks with sheet counts and datasource connections

When asked about lineage, use the relationship_type column to distinguish between
'upstream_table' (database tables feeding a datasource) and 'downstream_workbook'
(workbooks consuming a datasource).

Always include specific names, counts, and owners in your answers where available.
```

5. Test with governance questions like:
   - *"Which data sources have the most fields?"*
   - *"What calculated fields exist and what are their formulas?"*
   - *"Which workbooks have the most sheets?"*
   - *"What database tables does the Superstore data source connect to?"*

---

## Step 5 — Schedule the Notebook

To keep metadata fresh, schedule the notebook to run periodically.

1. In your Fabric workspace → **New** → **Data pipeline**
2. Add a **Notebook activity** → select `Tableau_Metadata_Bridge`
3. Set a schedule — daily is usually sufficient for governance metadata

The pipeline runs under the Fabric workspace managed identity, which already has Key
Vault access — no additional credential configuration needed.

---

## Known Limitations

### certificationStatus and certifiedBy require Data Management add-on
These fields are not included in the notebook. If your Tableau environment has the
Data Management add-on licensed, add `certificationStatus` and `certifiedBy` back to
the GraphQL query in Cell 3 and the parse step in Cell 4. The `isCertified` boolean
is included and works without the add-on.

### workbook_owner and workbook_project may be null on trial environments
Workbooks owned by "Tableau System Account" (the default on Tableau Cloud trials) may
not return owner or project information through the Metadata API. On production
environments with user-published content these fields populate correctly.

### Downstream workbook relationships require user-published content
The Metadata API does not surface downstream workbook relationships for system-provisioned
content. Create and publish workbooks under your own user account to see lineage
relationships populate in `tableau_lineage`.

### Semantic model connection string is environment-specific
The `semantic_model.tmdl` file contains a hardcoded connection string pointing to the
original Fabric workspace. Update the connection string to match your environment before
importing.

---

## Phase 2 — Coming Soon

Phase 2 adds a Power BI Scanner API notebook that pulls semantic model lineage from
Fabric itself — upstream database tables, datasource connections, workspace and owner
metadata — and lands it in a `fabric_semantic_model_lineage` table in the same Lakehouse.

With both tables present, the Data Agent can answer true cross-platform governance
questions:

- *"Which database tables are used in both Tableau and Power BI?"*
- *"Where do we have redundant coverage across both platforms?"*
- *"Which teams have the same upstream data in both tools?"*

This creates a unified governance view across the entire BI estate without requiring
either platform to change.

---

*Part of the Tableau + Microsoft Fabric AI Bridge project.*
*Play 1 (Tableau VDS → Fabric Lakehouse) and Play 2 (Foundry Agent → Tableau via Logic App) also available.*
