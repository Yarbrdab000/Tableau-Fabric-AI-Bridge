# Tableau + Microsoft Fabric AI Bridge

A collection of notebooks and tools that bridge existing Tableau investments with the Microsoft Fabric and AI ecosystem — without replacing or migrating anything in the Tableau environment.

**Philosophy:** Meet customers where their data already lives. Add AI and Fabric on top. Let the ceiling sell the modernization.

---

## The Pipeline

```
Tableau Cloud / Server
        │
        ├── Play 2 ──► Metadata_Lakehouse
        │               tableau_datasources
        │               tableau_fields          ← schema, types, roles, formulas
        │               tableau_lineage         ← upstream tables, downstream workbooks
        │               tableau_workbooks
        │
        ├── Play 3 ──► h1_ultrastore
        │               {datasource}_{table}    ← one Delta table per upstream source
        │
        └── Play 4 ──► Fabric Workspace
                        {Datasource Name}       ← one semantic model per datasource
                        DirectLake → h1_ultrastore
```

**Run order: Play 2 → Play 3 → Play 4**

Play 2 builds the manifest. Play 3 lands the data. Play 4 builds the models.

---

## Plays

### [Play 1 — Fabric Data Agent → Tableau via MCP](Play1/Play1_README.md)
Connects a Fabric Data Agent to Tableau published datasources via the official Tableau MCP Server. Enables natural language queries over governed Tableau data without moving anything. Uses Azure AI Foundry + Logic Apps.

**Input:** Tableau published datasource (live, via MCP)
**Output:** Natural language interface over Tableau data

### [Play 2 — Tableau Metadata Bridge](Play2/Play2_README.md)
Pulls governance metadata from the Tableau Metadata API (GraphQL) and lands it in Fabric as four Delta tables. This is the control plane for the entire pipeline — field schemas, data types, lineage, and workbook inventory.

**Input:** Tableau Metadata API
**Output:** Four Delta tables in `Metadata_Lakehouse`

### [Play 3 — VizQL Data Service Bridge](Play3/Play3_README.md)
Uses Tableau's VizQL Data Service (VDS) REST API to pull published Tableau datasources into Fabric as Delta tables. Queries each upstream table independently to avoid cross-table joins. Metadata-driven — no hardcoded field lists.

**Input:** Play 2 metadata tables
**Output:** `{datasource}_{table}` Delta tables in `h1_ultrastore`

### [Play 4 — Semantic Model Generator](Play4/Play4_README.md)
Reads Play 2 metadata and Play 3 Delta tables, generates a TMDL-format Power BI semantic model for each Tableau datasource, and deploys it directly to the Fabric workspace via the Fabric REST API. DirectLake connection to `h1_ultrastore` out of the box.

**Input:** Play 2 metadata + Play 3 Delta tables
**Output:** Deployed semantic models in Fabric workspace

---

## Prerequisites

| Requirement | Notes |
|------------|-------|
| Tableau Cloud or Server 2025.1+ | VDS API required for Play 3. Metadata API available from 2024.2+ |
| Creator license on Tableau site | VDS rate limit: 100 calls/hour per Creator license (capacity-based) |
| Tableau PAT | Store in Azure Key Vault |
| Azure Key Vault | Managed identity access from Fabric workspace |
| Microsoft Fabric workspace | F-SKU capacity recommended for DirectLake |
| Fabric admin: "Service principals can use Fabric APIs" | Required for Play 4 deployment |

---

## Fabric Lakehouse Architecture

Two lakehouses, deliberately separate:

| Lakehouse | Purpose | Used by |
|-----------|---------|---------|
| `Metadata_Lakehouse` | Governance and catalog layer — small, stable, high read | Play 2 (write), Play 3 (read), Play 4 (read) |
| `h1_ultrastore` | Data layer — large, frequently refreshed | Play 3 (write), Play 4 semantic models (DirectLake read) |

---

## Quick Start

1. Create `Metadata_Lakehouse` and `h1_ultrastore` in your Fabric workspace
2. Store your Tableau PAT in Azure Key Vault
3. Grant the Fabric workspace managed identity **Key Vault Secrets User** on the Key Vault
4. Enable **"Service principals can use Fabric APIs"** in Fabric Admin Portal
5. Run Play 2 → Play 3 → Play 4

---

## Known Limitations

- **VDS requires Tableau 2025.1+** — older Tableau Server versions are not supported for Play 3 and Play 4
- **Relationships not generated** — Play 4 generates tables and columns; relationships are configured by the customer
- **DAX translation** — calculated fields are stubbed with the original Tableau formula; DAX translation is manual
- **Hidden join key fields** — some hidden fields have different names in VDS vs the Metadata API; Play 3 handles this via retry logic and logs any dropped fields
- **DirectLake on trial capacity** — may fall back to DirectQuery; behaves correctly on F-SKU

---

## Repo Structure

```
/
├── README.md
├── Play1/
│   ├── Play1_README.md
│   ├── agent_instructions.md
│   ├── openapi_spec.json
│   ├── template.json
│   └── main.bicep
├── Play2/
│   ├── Play2_README.md
│   └── Tableau_Metadata_Bridge.ipynb
├── Play3/
│   ├── Play3_README.md
│   └── Tableau_VDS_Bridge_V2.ipynb
└── Play4/
    ├── Play4_README.md
    └── Tableau_Semantic_Model_Generator.ipynb
```
