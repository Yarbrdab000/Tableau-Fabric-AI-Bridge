# Tableau + Microsoft Fabric AI Bridge

Tableau has an enormous installed base. Most enterprise customers running Tableau today aren't going anywhere fast — the switching costs are real, the workflows are embedded, and the politics are complicated. This repo is built around that reality.

> **Start here:** Download [`Setup/setup_reference.html`](Setup/setup_reference.html), open it in your browser, and fill in your values as you go. Every notebook Cell 1 maps directly to fields in that reference. Keep it open on a second monitor throughout setup.

**Two motions, one toolkit:**

**Motion 1 — The AI-on-top play.** For customers who aren't ready to migrate, this gives them Microsoft AI capabilities on top of their existing Tableau investment — natural language queries, governed data in Fabric, Copilot-ready semantic models — without touching a single Tableau workbook. The ceiling sells the migration; you don't have to.

**Motion 2 — The migration accelerator.** For customers who are ready to move, Plays 2–4 automate the hardest part: reconstructing every Tableau datasource as a Power BI semantic model. Point it at a Tableau environment, run the pipeline, and every published datasource lands in Fabric as a working semantic model with correct schema, data types, and DirectLake connectivity. What used to take weeks of manual SE work runs overnight.

Critically — you don't have to migrate everything at once. Built-in filter and batch controls let you scope the pipeline to a single datasource, a specific project, or any subset of the Tableau estate. Start with one business unit, validate, then expand. The customer stays in control of the pace.

**The insight that makes both motions work:** you don't have to choose. Start with Motion 1 to prove value on day one. The same pipeline that powers the AI layer is already doing the migration work in the background. When the customer is ready, the migration is mostly done — and they already know it works.

---

## The Pipeline

```
Tableau Cloud / Server
        │
        ├── Play 2 ──► Metadata_Lakehouse
        │               tableau_datasources     ← what datasources exist
        │               tableau_fields          ← schema, types, roles, formulas
        │               tableau_lineage         ← upstream tables, downstream workbooks
        │               tableau_workbooks       ← workbook inventory
        │
        ├── Play 3 ──► h1_ultrastore
        │               {datasource}_{table}    ← one Delta table per upstream source
        │
        ├── Play 4 ──► Fabric Workspace
        │               {Datasource Name}       ← one semantic model per datasource
        │               DirectLake → h1_ultrastore
        │
        └── Play 5 ──► Fabric Workspace
                        Tableau Migration Assessment  ← estate KPI model + dashboard
                        DirectLake → Metadata_Lakehouse
```

**Run order: Play 2 → Play 3 → Play 4** (Play 5 runs straight off Play 2)

Play 2 builds the manifest. Play 3 lands the data. Play 4 builds the models. Play 5
assesses the estate for migration.

---

## Plays

### [Play 1 — Tableau MCP Server on Azure](Play1/Play1_README.md)
A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a live Tableau datasource as agent tools (`list_datasources`, `get_datasource_schema`, `query_datasource`). One-click deploys to Azure Container Apps and plugs into Microsoft Copilot Studio, M365 Copilot, or Azure AI Foundry. Business users ask questions in plain English and get answers backed by governed Tableau data — no data movement, no migration required.

**Use case:** Immediate AI value on existing Tableau investments, wired into the Microsoft Copilot ecosystem. No Fabric lakehouse required to get started. Works standalone against any published Tableau datasource.

**Input:** Tableau published datasource (live, via VDS API)
**Output:** MCP endpoint consumable by Copilot Studio / M365 Copilot / Foundry agents

---

### [Play 1 (no MCP) — Foundry Agent via Logic App](Play1_no_MCP/Play1_no_MCP_README.md)
The same natural-language-over-Tableau outcome without MCP: connects an Azure AI Foundry agent to a live Tableau datasource through a Logic App that handles Tableau authentication at query time. Useful when MCP isn't available in the target environment.

**Use case:** Immediate AI value on existing Tableau investments using a plain Foundry agent + Logic App. No Fabric lakehouse required. Works standalone against any published Tableau datasource.

**Input:** Tableau published datasource (live, via VDS API)
**Output:** Natural language interface over Tableau data

---

### [Play 2 — Tableau Metadata Bridge](Play2/Play2_README.md)
Pulls the complete field schema, lineage, and governance metadata from the Tableau Metadata API and lands it in a Fabric Lakehouse. This is the control plane for the migration pipeline — every downstream play reads from it.

**Use case:** Tableau estate inventory. Know exactly what datasources exist, what fields they have, what workbooks depend on them, and what upstream databases they connect to — all queryable from Fabric.

**Input:** Tableau Metadata API
**Output:** Four Delta tables in `Metadata_Lakehouse`

---

### [Play 3 — VizQL Data Service Bridge](Play3/Play3_README.md)
Uses Tableau's VizQL Data Service API to pull the actual data from every published Tableau datasource into Fabric as Delta tables. Metadata-driven — no hardcoded field lists, no manual configuration per datasource.

**Use case:** Land the full Tableau data estate in OneLake. Works against extracts and live connections. Scales to hundreds of datasources with configurable batch controls.

**Input:** Play 2 metadata + Tableau VDS API
**Output:** `{datasource}_{table}` Delta tables in `h1_ultrastore`

---

### [Play 4 — Semantic Model Generator](Play4/Play4_README.md)
Automatically generates and deploys a Power BI semantic model for every Tableau datasource — correct tables, correct columns, correct data types, calculated field stubs, DirectLake connectivity. Deployed directly to the Fabric workspace via REST API. No manual steps.

**Use case:** This is the migration accelerator. A Tableau environment with 500 datasources becomes 500 Fabric semantic models overnight — with relationships auto-mapped where Tableau exposes the join keys. The customer validates, reviews any ambiguous relationships, translates calculated fields — and the migration is done.

**Input:** Play 2 metadata + Play 3 Delta tables
**Output:** Deployed semantic models in Fabric workspace — one per Tableau datasource

---

### [Play 5 — Migration Assessment](Play5/Play5_README.md)
Builds a single estate **migration-assessment** semantic model over the Play 2 metadata — datasource and workbook counts, connection diversity, flat-file/one-off risk, datasource reuse, calculated-field complexity, certification coverage, and stale content — plus a deployable four-page Power BI dashboard template. Runs straight off Play 2; no Play 3/4 dependency.

**Use case:** The "should we migrate, and what will it cost?" lens. Point it at a customer's Tableau estate and the dashboard quantifies migration scope on day one — before anyone commits to moving anything.

**Input:** Play 2 metadata
**Output:** `Tableau Migration Assessment` semantic model (DirectLake → Metadata_Lakehouse) + dashboard template

---

## Why This Approach Works

Traditional Tableau migration conversations stall for three reasons: cost, risk, and politics. The customer doesn't know how long it will take, what will break, or how to get sign-off to rebuild 500 reports.

This toolkit changes the conversation:

- **Cost** — the pipeline runs overnight, not over months. The SE cost is setup and validation, not rebuild.
- **Risk** — semantic models are generated from the actual Tableau schema, not manually reconstructed. What's in Tableau is what's in Fabric.
- **Politics** — you don't ask for migration sign-off. You show up with the migration already done and ask if they want to keep going.

For customers who genuinely won't migrate, Play 1 delivers immediate AI value on their existing investment — and keeps Microsoft in the account while the conversation continues.

---

## Prerequisites

| Requirement | Notes |
|------------|-------|
| Tableau Cloud or Server 2025.1+ | VDS API required for Plays 3 and 4. Metadata API available from 2024.2+ |
| Creator license on Tableau site | VDS rate limit: 100 calls/hour per Creator license (capacity-based) |
| Tableau PAT | Store in Azure Key Vault — must belong to a user with **Site Administrator** role. A Creator-level PAT will return a partial inventory (only datasources that user can access). |
| Azure Key Vault | Managed identity access from Fabric workspace |
| Microsoft Fabric workspace | F-SKU capacity recommended for DirectLake |
| Fabric admin: "Service principals can use Fabric APIs" | Required for Play 4 deployment |

---

## Fabric Lakehouse Architecture

Two lakehouses, deliberately separate:

| Lakehouse | Purpose | Used by |
|-----------|---------|---------|
| `Metadata_Lakehouse` | Governance and catalog layer — Tableau estate inventory | Play 2 (write), Play 3 (read), Play 4 (read) |
| `h1_ultrastore` | Data layer — actual datasource data, DirectLake source | Play 3 (write), Play 4 semantic models (DirectLake read) |

The separation matters at scale. A customer with 500 datasources generates thousands of Delta tables in `h1_ultrastore`. Keeping governance metadata in its own lakehouse means clean separation between the catalog and the data, separate SQL analytics endpoints, and no interference between metadata queries and data queries.

---

## Quick Start

**Step 0 — Setup reference (do this first)**
Download [`Setup/setup_reference.html`](Setup/setup_reference.html) and open it in your browser. Fill in values as you collect them — it saves automatically and keeps everything in one place.

1. Create `Metadata_Lakehouse` and `h1_ultrastore` in your Fabric workspace
2. Store your Tableau PAT in Azure Key Vault — PAT must belong to a **Site Administrator**
3. Grant the Fabric workspace managed identity **Key Vault Secrets User** on the Key Vault
4. Enable **"Service principals can use Fabric APIs"** in Fabric Admin Portal
5. Run Play 2 → Play 3 → Play 4

For the AI-only motion (no data movement): deploy Play 1 (MCP server) or Play 1 (no MCP) standalone — no Fabric lakehouse required.

---

## Phased Migration

For large Tableau environments, Plays 3 and 4 support filtering so you can migrate one project or set of datasources at a time rather than the full estate in one shot.

**Play 3 — filter controls in Cell 1:**
```python
DATASOURCE_FILTER = ["Finance Datasource", "Sales Datasource"]  # specific datasources
PROJECT_FILTER    = ["Finance"]                                  # entire project at once
BATCH_SIZE        = 10    # max datasources per run
BATCH_OFFSET      = 0     # increment to process next chunk
```

**Play 4 — filter controls in Cell 1:**
```python
DATASOURCE_FILTER = ["Finance Datasource"]  # only generate models for these
OVERWRITE         = False                   # skip models that already exist
```

**Recommended phased approach:**
1. Run Play 2 once — full estate inventory (fast, metadata only)
2. Run Play 3 with `PROJECT_FILTER = ["Finance"]` — land one business unit's data
3. Run Play 4 with the same filter — deploy semantic models for that unit
4. Validate with the customer, then repeat for the next project

Play 2 always runs against the full environment — it's the manifest, not the migration. The scoping happens in Plays 3 and 4.

---

## Known Limitations

- **VDS requires Tableau 2025.1+** — older Tableau Server versions are not supported for Plays 3 and 4
- **Relationships** — Play 4 auto-maps relationships it can infer from Tableau's hidden disambiguated join keys (with many-to-one direction inferred from landed Delta cardinality); ambiguous or unkeyed relationships still need manual review
- **DAX translation** — calculated fields are stubbed with the original Tableau formula preserved; DAX translation is a manual step
- **Hidden join key fields** — some hidden fields have different names in VDS vs the Metadata API; Play 3 handles this via retry logic and logs any dropped fields
- **DirectLake on trial capacity** — may fall back to DirectQuery on small F-SKUs; behaves correctly on production capacity
- **Row Level Security (RLS)** — VDS respects Tableau RLS. Data landed in the Lakehouse reflects only what the PAT user is permitted to see. For complete data, use a Site Admin PAT or disable RLS on the datasource before running. Migrating RLS rules to Fabric row-level security is a separate post-migration step.

---

## Repo Structure

```
/
├── README.md
├── Setup/
│   ├── Setup_README.md
│   └── setup_reference.html        ← open this first
├── Play1/                          ← MCP server (Azure)
│   ├── Play1_README.md
│   ├── server.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── deploy/
│   │   ├── azure/                  ← Bicep + one-click ARM template
│   │   └── copilot-studio/         ← custom connector swagger + guide
│   └── docs/
│       └── customer-setup-guide.md
├── Play1_no_MCP/                   ← Foundry agent + Logic App
│   ├── Play1_no_MCP_README.md
│   ├── Play1_Agent_Instructions_Generator.ipynb
│   ├── openapi_spec.json
│   ├── deploy_logicapp.bicep
│   └── deploy_connection.bicep
├── Play2/
│   ├── Play2_README.md
│   └── Play2_Tableau_Metadata_Bridge.ipynb
├── Play3/
│   ├── Play3_README.md
│   └── Play3_Tableau_VDS_Bridge.ipynb
├── Play4/
│   ├── Play4_README.md
│   └── Play4_Tableau_Semantic_Model_Generator.ipynb
└── Play5/
    ├── Play5_README.md
    ├── Play5_Migration_Assessment.ipynb
    └── dashboard/
        ├── README.md
        └── kpi_catalog.json
```
