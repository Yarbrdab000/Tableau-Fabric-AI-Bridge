# Play 5 — Migration Assessment

> Part of the [Tableau + Microsoft Fabric AI Bridge](../../README.md) project.

## What This Does

Reads the Tableau metadata that Play 2 landed and builds a single **estate
migration-assessment** semantic model in Fabric — plus a deployable Power BI dashboard
template — that answers the questions you actually need before a Tableau → Fabric
migration: how big is the estate, what is it connected to, what is reused, what is
complex, and what is stale.

It is **independent of Play 3 / Play 4** — it only needs the Play 2 metadata tables.

The notebook:
- Derives tidy, analysis-ready `mig_*` Delta tables from the raw Play 2 metadata, with
  the migration flags computed up front (`is_reused`, `is_refresh_stale`,
  `is_content_stale`, `is_flat_file`, `is_calculated`, …)
- Builds connection facts at the **real connection-instance grain** from the lineage
  table (distinct upstream databases/files), with a fallback to the datasource's
  connector-type set when table-level lineage is absent
- Adds shared **Project** and **Owner** dimensions so one slicer cross-filters both
  datasource and workbook KPIs
- Deploys one DirectLake semantic model with a `_Metrics` table of 18 migration-KPI DAX
  measures, via the Fabric REST API
- Asserts the written Delta schema against the model's type contract **before** deploy,
  so a silent type drift can't break DirectLake binding

**This is the "should we migrate, and what will it cost?" lens.** Point it at a
customer's Tableau estate (via Play 2) and the dashboard gives migration scope on day
one — before anyone commits to moving anything.

---

## Prerequisites

- **Play 2 has been run** — `Metadata_Lakehouse` must contain `tableau_datasources`,
  `tableau_fields`, `tableau_lineage`, and `tableau_workbooks`
- Fabric admin has enabled **"Service principals can use Fabric APIs"** tenant setting
- Notebook managed identity has permission to create items in the workspace

---

## Setup

### 1. Enable the Fabric API Tenant Setting

Fabric Admin Portal → Tenant Settings → Developer settings → **Service principals can use
Fabric APIs** → Enable. One-time per tenant; without it, deploy calls return 403.

### 2. Attach the Metadata Lakehouse

Attach **`Metadata_Lakehouse`** (the Play 2 output) as the notebook's default lakehouse.
The derived `mig_*` tables are written here and the semantic model binds to this lakehouse
via DirectLake.

### 3. Fill in the Config Cell

| Variable | Default | Notes |
|----------|---------|-------|
| `METADATA_LAKEHOUSE` | `Metadata_Lakehouse` | Play 2 output lakehouse display name |
| `MODEL_DISPLAY_NAME` | `Tableau Migration Assessment` | Deployed model name |
| `STALE_DAYS` | `90` | Extract/workbook staleness threshold |
| `FLAT_FILE_TYPES` | (tunable set) | Tableau `connectionType`s treated as flat-file/one-off |
| `OVERWRITE` | `True` | Update the model if it already exists |

### 4. Run All

Read → derive → write `mig_*` Delta tables → assert schema → generate TMDL → deploy →
refresh → verify.

---

## Output

A semantic model named **`Tableau Migration Assessment`** containing:

- **Datasources / Fields / Connections / Workbooks** — DirectLake tables over the derived
  `mig_*` tables
- **Project / Owner** — shared dimensions (single slicer cross-filters datasources +
  workbooks)
- **Real date fields** — `Datasources[extract_last_refresh]` and `Workbooks[updated_at]`
  land as true `dateTime` columns (not text), so the report can use date-range slicers and
  time hierarchies alongside the pre-computed `days_since_*` signals
- **`_Metrics`** — the migration-KPI measures:

| KPI | Meaning |
|-----|---------|
| Data Sources / Workbooks / Fields | Estate size |
| Calculated Fields / Calc Field Density | DAX-translation effort (see Play 4) |
| Unique Connections | Distinct upstream DB/file instances (true footprint) |
| Unique Connection Types | Distinct connector types |
| Flat-File Sources / Flat-File One-Off Sources | Re-platform / throwaway candidates |
| Reused Data Sources | Datasources feeding >1 workbook (highest impact) |
| Certified Data Sources / Certification Rate | Governance maturity |
| Extract-Based Sources / Stale Extracts / Avg Extract Age | Refresh hygiene |
| Stale Workbooks | Content to retire vs migrate |
| Hidden Fields / Avg Fields per Source | Model-size signals |

The full catalog (names, DAX, format strings, descriptions) is in
[`dashboard/kpi_catalog.json`](./dashboard/kpi_catalog.json).

---

## Dashboard

[`dashboard/`](./dashboard/) ships the deployable template — a four-page layout
(Overview · Connections · Complexity · Governance) plus the machine-readable KPI catalog.
Deploy it in one click via Fabric **Auto-create report**, or build it in Power BI Desktop
in ~5 minutes against the live model. See [`dashboard/README.md`](./dashboard/README.md).

---

## Design notes

- **Why derived `mig_*` tables instead of modelling the raw Play 2 tables directly?**
  Migration flags (staleness, reuse, flat-file, calculated) are computed once in Python
  where the logic is testable, keeping the KPI DAX simple and unambiguous and avoiding
  delimited-string parsing in DAX.
- **Connections from lineage, not the joined `connection_types` string.** This gives a
  true *Unique Connections* (distinct database/file instances) alongside *Unique
  Connection Types*, which the raw comma-joined set can't express.
- **Refresh staleness vs content staleness are distinct.** Live (non-extract)
  datasources have no refresh signal, so `is_refresh_stale` applies only to extracts;
  workbook staleness (`is_content_stale`) is driven by last-update date.
- **Schema contract assertion.** The notebook fails fast if any derived Delta column
  doesn't land as the expected physical type — the same class of DirectLake binding bug
  Play 4 hardened against.
- **Pretuned column types (incl. dates).** Because this model's schema is fixed and
  authored by hand (`ESTATE_TABLES`), every column's `dataType` is declared, not inferred.
  Date columns (`extract_last_refresh`, `updated_at`) are written as Spark `TimestampType`
  and emitted as TMDL `dateTime` (Short Date) — so unlike a dynamic model they can never
  land as text. (Play 4, which mirrors the *physical* Delta schema, gets the same
  correctness from the Play 3 column-typing fix.)

---

## Pipeline position

```
Play 2 (metadata) ──► Play 5 (assessment model + dashboard)
                  └──► Play 3 ──► Play 4 (data + per-datasource models)
```

Play 5 runs straight off Play 2 and does not depend on Play 3/4.
