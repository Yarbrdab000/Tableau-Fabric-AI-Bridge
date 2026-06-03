# Play 4 — Semantic Model Generator

> Part of the [Tableau + Microsoft Fabric AI Bridge](../README.md) project.

## What This Does

Reads the datasource and field metadata from Play 2 and generates a fully structured Power BI semantic model for each Tableau datasource — deployed directly to the Fabric workspace via the Fabric REST API.

Each generated semantic model:
- Has one table per upstream source table, pointing at the Play 3 Delta tables via DirectLake
- Has all columns with correct data types and `summarizeBy` settings derived from Tableau field roles
- Has cross-table relationships auto-inferred from Tableau's hidden join keys — many-to-one direction determined from the landed Delta cardinality and emitted as `relationships.tmdl`
- Has a `_Measures` table where simple Tableau calculated fields are **translated to working DAX**, and anything more complex is left as an inert stub — with the original Tableau formula preserved as an annotation on every measure
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
├── _Measures       ← simple calcs → DAX; complex calcs → annotated stubs
└── relationships   ← auto-mapped many-to-one joins (relationships.tmdl)
```

---

## What's Generated vs What's Not

| Generated automatically | Left for the SE / customer |
|------------------------|---------------------------|
| All tables from upstream sources | DAX for complex calcs (IF/CASE/LOD/window/etc.) |
| All columns with correct data types | Relationships with no Tableau-exposed join key |
| `summarizeBy` from Tableau field roles | Row-level security |
| Relationships from Tableau's hidden join keys (many-to-one) | Report-level formatting |
| **DAX for simple aggregation calcs** (see below) | Hierarchies |
| Original Tableau formula preserved on every measure | |
| Hidden flag removed (all fields visible) | |

**Relationships are auto-mapped where Tableau exposes a join key.** Play 4 infers cross-table relationships from Tableau's hidden disambiguated join keys and sets the many-to-one direction from the landed Delta cardinality, emitting them as `relationships.tmdl`. Relationships it can't infer — no exposed key, or an ambiguous match — are left for review; the tables and join key columns are all present, so wiring the rest takes minutes.

---

## Calculated Field → DAX Translation

Play 4 ships a **deterministic** (no-LLM) translator that converts the *simple, safe* subset of Tableau calculated fields into working DAX measures. Everything else stays an inert `= 0` stub. **In all cases the original Tableau formula is preserved verbatim** as `annotation TableauFormula` on the measure — so a mistranslation can always be audited against the source and repaired by hand. Translated measures additionally carry `annotation TranslatedBy = "Play4 deterministic translator"` so you can tell the two apart.

**Translated (working DAX):**
- Aggregations over a single bare field: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNTD`, `MEDIAN`
- Arithmetic between those terms and numeric literals: `+ - * /`, parentheses, unary minus
- Example: `SUM([Profit])/SUM([Sales])` → `DIVIDE(SUM('Orders'[Profit]), SUM('Orders'[Sales]))`

**Mapping choices that preserve Tableau semantics:**
- `COUNT` → `COUNTA` (Tableau `COUNT` counts non-null of any type; DAX `COUNT` errors on text)
- `COUNTD` → `DISTINCTCOUNTNOBLANK` (plain `DISTINCTCOUNT` counts BLANK → off-by-one)
- `a / b` → `DIVIDE(a, b)` (safe divide; no divide-by-zero errors)

**Left as an annotated stub (`= 0`)** — anything outside the subset, by design: `IF`/`CASE`, LOD expressions (`{FIXED …}`), string/date/logical/window/table-calc functions, arithmetic *inside* an aggregation (`SUM([A]-[B])`), references to other calculated fields, fields that don't resolve unambiguously to a single landed column, aggregates applied to an incompatible column type, and any calc whose terms span **more than one table** (a relationship path alone doesn't guarantee DAX reproduces Tableau's filter context, so it fails safe).

The translator is verified by an offline self-test cell that runs every time the notebook executes. At the end of a run, a **translation summary** lists exactly which measures became DAX and which were stubbed (with the reason), so the calcs that still need manual attention are obvious.

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
