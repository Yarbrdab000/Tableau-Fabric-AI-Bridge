# Play 4 — Semantic Model Generator

> Part of the [Tableau + Microsoft Fabric AI Bridge](../README.md) project.

## What This Does

Reads the datasource and field metadata from Play 2 and generates a fully structured Power BI semantic model for each Tableau datasource — deployed directly to the Fabric workspace via the Fabric REST API.

Each generated semantic model:
- Has one table per upstream source table, pointing at the Play 3 Delta tables via DirectLake
- Has all columns with correct data types and `summarizeBy` settings derived from Tableau field roles
- Has cross-table relationships auto-inferred from Tableau's hidden join keys — many-to-one direction determined from the landed Delta cardinality and emitted as `relationships.tmdl`
- Has a `_Measures` table with DAX measure stubs for every Tableau calculated field (original Tableau formula preserved as an annotation)
- Is immediately queryable in Fabric — no manual steps required

**This is the migration accelerator.** Point it at a customer's Tableau environment, run the full pipeline, and every published datasource becomes a working Fabric semantic model — before the customer has committed to migrating anything.

---

## Prerequisites

- Play 2 has been run — `Metadata_Lakehouse` tables must be current
- Play 3 has been run — `h1_ultrastore` Delta tables must be current
- Fabric admin has enabled **"Service principals can use Fabric APIs"** tenant setting
- Notebook managed identity has permission to create items in the workspace

---

## Setup

### 1. Enable the Fabric API Tenant Setting

In Fabric Admin Portal → Tenant Settings → Developer settings → **Service principals can use Fabric APIs** → Enable.

This is a one-time setup per tenant. Without it, all deploy calls will return 403.

### 2. Attach a Lakehouse

Attach any lakehouse as default — Play 4 needs it to run Spark SQL against `Metadata_Lakehouse`. The default lakehouse itself doesn't matter; the queries use fully qualified names.

### 3. Fill in Cell 1

Only two values need to be set:

```python
DATA_LAKEHOUSE_NAME = "h1_ultrastore"       # display name of your data lakehouse
METADATA_LAKEHOUSE  = "Metadata_Lakehouse"  # display name of your metadata lakehouse
```

Everything else — workspace ID, lakehouse GUIDs, DirectLake connection URL — is resolved automatically from the Fabric API at runtime.

### 4. Run all cells

---

## Output

One semantic model per Tableau datasource, deployed to the Fabric workspace:

```
Fabric Workspace
├── Superstore Datasource          ← semantic model
├── Finance Datasource             ← semantic model
├── Sales Datasource               ← semantic model
└── ...
```

Each model structure:
```
{Datasource Name}
├── Orders          ← DirectLake → superstore_datasource_orders
├── People          ← DirectLake → superstore_datasource_people
├── Returns         ← DirectLake → superstore_datasource_returns
├── _Measures       ← DAX stubs for calculated fields
└── relationships   ← auto-mapped many-to-one joins (relationships.tmdl)
```

---

## What's Generated vs What's Not

| Generated automatically | Left for the SE / customer |
|------------------------|---------------------------|
| All tables from upstream sources | DAX measure translations |
| All columns with correct data types | Relationships with no Tableau-exposed join key |
| `summarizeBy` from Tableau field roles | Row-level security |
| Relationships from Tableau's hidden join keys (many-to-one) | Report-level formatting |
| Calculated field stubs with original formula | Hierarchies |
| Hidden flag removed (all fields visible) | |

**Relationships are auto-mapped where Tableau exposes a join key.** Play 4 infers cross-table relationships from Tableau's hidden disambiguated join keys and sets the many-to-one direction from the landed Delta cardinality, emitting them as `relationships.tmdl`. Relationships it can't infer — no exposed key, or an ambiguous match — are left for review; the tables and join key columns are all present, so wiring the rest takes minutes.

**DAX stubs** — calculated fields are stubbed as `= 0` with the original Tableau formula preserved in an annotation. Find them in `_Measures`, translate to DAX, done.

---

## Overwrite Behavior

`OVERWRITE = True` (default) — rerunning updates existing models in place. Use this to pick up schema changes after rerunning Play 2 and Play 3.

`OVERWRITE = False` — skips models that already exist. Use this when adding new datasources without touching existing models.

---

## Data Types

Tableau → TMDL mapping:

| Tableau | TMDL |
|---------|------|
| STRING | string |
| INTEGER | int64 |
| REAL | double |
| BOOLEAN | boolean |
| DATE | dateTime |
| DATETIME | dateTime |

---

## DirectLake and Capacity

Generated models use **DirectLake** mode — data is read directly from OneLake Delta tables without import or DirectQuery overhead. This requires an F-SKU Fabric capacity.

On trial capacity, you may see: *"DAX queries may fall back to DirectQuery"* — this is normal and expected on small capacities. On a real F-SKU this warning goes away.

For customers who want to reconnect tables to their original source systems (SQL Server, Snowflake, etc.) rather than keeping data in the Lakehouse, that's a connection string change per table — not a rebuild.

---

## Pipeline Order

```
Play 2 → Play 3 → Play 4 (this notebook)
```

Rerun Play 4 after any Play 2 or Play 3 update to keep semantic models in sync with the Tableau environment.
