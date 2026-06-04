# Play 3 — VizQL Data Service Bridge

> Part of the [Tableau + Microsoft Fabric AI Bridge](../README.md) project.

## What This Does

Reads the datasource and field inventory from Play 2's metadata tables, then uses Tableau's VizQL Data Service (VDS) REST API to pull each upstream table from each published datasource into the Fabric Lakehouse as individual Delta tables.

**Key design decision:** VDS is queried once per upstream table, using only that table's fields. This prevents cross-table inner joins that would silently reduce row counts. Each Delta table contains clean, complete row-level data.

---

## Prerequisites

- Play 2 has been run — `Metadata_Lakehouse` tables must be current
- Tableau Cloud or Tableau Server 2025.1+ (VDS API required)
- Creator license on the Tableau site (VDS rate limit is capacity-based: 100 calls/hour per Creator license)
- PAT stored in Azure Key Vault (same PAT as Play 2)
- `h1_ultrastore` attached as **default** lakehouse
- `Metadata_Lakehouse` attached as **secondary** lakehouse

---

## Setup

### 1. Attach Both Lakehouses

In the notebook left rail:
- `h1_ultrastore` → set as **default** (Play 3 writes Delta tables here)
- `Metadata_Lakehouse` → attach as secondary (Play 3 reads metadata from here)

### 2. Fill in Cell 1

```python
PAT_NAME          = "your-pat-name"
POD               = "10ay.online.tableau.com"
SITE              = "your-site-slug"
KV_URL            = "https://your-kv.vault.azure.net/"
KV_SECRET_NAME    = "your-secret-name"
METADATA_LAKEHOUSE = "Metadata_Lakehouse"
VDS_RATE_LIMIT    = 100   # × number of Creator licenses on your site
```

### 3. Configure Batch Controls (optional)

For large deployments, use the filter and batch controls to process in chunks:

```python
DATASOURCE_FILTER = ["Finance Datasource", "Sales Datasource"]  # empty = all
PROJECT_FILTER    = ["Finance"]                                  # empty = all
BATCH_SIZE        = 10    # datasources per run, 0 = no limit
BATCH_OFFSET      = 0     # increment by BATCH_SIZE for next chunk
```

### 4. Run all cells

---

## Output

One Delta table per upstream source table, per datasource:

```
h1_ultrastore
└── Tables
    ├── superstore_datasource_orders
    ├── superstore_datasource_people
    ├── superstore_datasource_returns
    ├── finance_datasource_transactions
    └── ...
```

**Naming convention:** `{datasource_name}_{upstream_table}` — slugified (lowercase, spaces/special chars → underscores).

> **This lakehouse is accelerator-or-final.** For smaller estates it can simply *be* the
> destination. For larger ones it's a bootstrap: because Play 3 lands **one Delta table per
> upstream physical table** and Play 4's models bind by table *name + schema*, you can later
> rebind any table to its real native source (OneLake Shortcut / Mirroring / pipeline / ETL)
> without touching the semantic model — as long as the table keeps the same name and column/type
> contract. Performing that native cutover is a separate, source-specific step; this toolkit gets
> you running first.

---

## Rate Limiting

VDS has a capacity-based rate limit of **100 calls/hour per Creator license** on the site. The notebook enforces this automatically via `VDS_RATE_LIMIT`:

```
VDS calls required = number of datasources × average upstream tables per datasource
Estimated runtime  = (VDS calls × 3600 / VDS_RATE_LIMIT) seconds
```

Cell 3 prints the estimated call count and runtime before starting. For large deployments, use `BATCH_SIZE` and `BATCH_OFFSET` to chunk runs overnight.

---

## How VDS Field Resolution Works

Play 3 uses a hybrid approach to determine what to query:

1. **Table discovery** — calls VDS `read-metadata` to get logical table names via `logicalTableId`
2. **Field captions** — reads from Play 2 `tableau_fields` (not VDS metadata), which includes hidden join key fields that VDS `read-metadata` doesn't surface
3. **Retry logic** — if a batch query fails (field name mismatch between Metadata API and VDS), retries field-by-field, drops unrecognized fields, and logs them

Dropped fields are logged in the verification output. In practice this only affects hidden fields where Tableau's display name differs from the underlying column name (e.g. `Person` → `Regional Manager`).

---

## Column Typing (dates land as dates, not text)

VDS `query-datasource` (OBJECTS format) returns **DATE, DATETIME, and BOOLEAN values as strings**. If those columns are written to Delta as-is, Spark infers them as `string`, and Play 4 — which maps the *physical* Delta type — would surface, say, `order_date` as a text field (breaking date hierarchies, time intelligence, and DirectLake date binding).

Play 3 fixes this at the source: before writing each table it casts every landed column to its Tableau `dataType`, taken from VDS `read-metadata` for payload fields and from the Metadata API (`tableau_fields.data_type`) for hidden keys.

| Tableau `dataType` | Cast | Lands in Delta as | Play 4 emits |
| --- | --- | --- | --- |
| `DATE` / `DATETIME` | `to_datetime` | `timestamp` | `dateTime` |
| `INTEGER` | numeric | `bigint` (or `double` if nulls) | `int64` |
| `REAL` | numeric | `double` | `double` |
| `BOOLEAN` | true/false map | `boolean` | `boolean` |
| `STRING` / other | unchanged | `string` | `string` |

Unparseable values become null (`NaT`/`NaN`) rather than failing the whole table. Re-run Play 3 then Play 4 to retype any tables that were landed before this fix (`overwriteSchema` re-lands them).

---

## Known Limitations

**Hidden join key fields** — some hidden fields that VDS `read-metadata` doesn't advertise are still queryable via VDS when passed directly. Play 3 handles this via the retry logic. Fields that genuinely can't be queried are dropped and logged.

**Single-field secondary tables** — tables where VDS can only expose one field (e.g. a Returns table where the join key is not queryable) will return reduced row counts. This is a VDS limitation, not a bug. The data is documented in the verification output.

**Extracts** — for datasources using Tableau extracts, data reflects the last extract refresh time, not the live source. Check `extract_last_refresh` in `tableau_datasources` to understand data freshness.

**VDS requires Tableau 2025.1+** — VDS is not available on older Tableau Server versions.

---

## Pipeline Order

```
Play 2 → Play 3 (this notebook) → Play 4
```

Rerun Play 3 (this notebook) whenever you want to refresh the data in the Lakehouse. Always run Play 2 first if the Tableau environment has changed (new datasources, schema changes).
