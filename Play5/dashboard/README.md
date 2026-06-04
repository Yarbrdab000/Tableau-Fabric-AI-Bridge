# Tableau → Fabric Migration Assessment — Dashboard Template

A deployable Power BI dashboard for the **Tableau Migration Assessment** semantic model
that Play 5 generates. It turns the estate KPIs (datasource counts, connection diversity,
flat-file/one-off risk, reuse, calculated-field complexity, certification coverage, and
stale content) into a board people can publish and slice.

The model already contains every measure, and this folder ships a **pre-built report**
(`report/` — a Power BI Project, i.e. `.pbip`) generated from `kpi_catalog.json`. You open
it, point it at your deployed model, and publish. The only manual step is the rebind.

Because the Play 5 model is **deterministic** (same tables, columns, and measure names for
every customer), one report works everywhere — only the *workspace* differs.

---

## Option A — Open the pre-built report and point it at your model (recommended)

1. Make sure `Play5_Migration_Assessment.ipynb` has deployed the **Tableau Migration
   Assessment** semantic model to your Fabric workspace.
2. Point the report at *your* workspace. Open
   [`report/Tableau Migration Assessment.Report/definition.pbir`](./report/Tableau%20Migration%20Assessment.Report/definition.pbir)
   in a text editor and replace `REPLACE_WITH_YOUR_FABRIC_WORKSPACE_NAME` in the
   `connectionString` with your workspace name (the model name is already correct).
   *(Alternatively, skip this and repoint the model from inside Desktop in step 3.)*
3. Open `report/Tableau Migration Assessment.pbip` in **Power BI Desktop**. It live-connects
   to the model — no import, no refresh to manage. If it can't resolve the connection, use
   **Home → Transform data → Data source settings** (or the model picker) to point at your
   **Tableau Migration Assessment** model.
4. **Publish** to your workspace.

The two slicers (`Project[project_name]`, `Owner[owner_name]`) are shared dimensions, so they
cross-filter **both** datasource and workbook KPIs at once.

> **Charts, tables, and slicers are best-effort.** The report is generated from JSON grounded
> in real Power BI fixtures and passes offline validation, but it is **not render-tested**.
> KPI cards are the most robust; a chart/table/slicer may occasionally need a small tweak on
> first open. See *If a visual renders blank* below.

---

## Option B — One-click Auto-create in Fabric (zero files, fallback)

1. In your Fabric workspace, open the **Tableau Migration Assessment** semantic model.
2. Click **Auto-create report** (or **New report**).
3. Fabric generates a live report from the `_Metrics` measures. Save it.
4. Optional: rearrange to match the layout in [`kpi_catalog.json`](./kpi_catalog.json).

This always produces a valid live-connected report, but with Fabric's default layout rather
than the curated four-page board.

---

## `kpi_catalog.json` — the spec that drives the report

`kpi_catalog.json` is the machine-readable source of truth — every measure name, exact DAX,
format string, and which page/visual it belongs on. **`generate_report.py` reads it and emits
the `report/` `.pbip` tree.** Edit the catalog and regenerate (see *Regenerating* below) to
change the board; the two never drift.

### Page layout

**1. Overview** — estate size + migration scope
Cards: Data Sources · Workbooks · Fields · Calculated Fields · Unique Connections ·
Reused Data Sources · Flat-File Sources · Certification Rate
Charts: *Datasources by Project* (bar), *Workbooks by Project* (column)

**2. Connections** — connectivity diversity + flat-file/one-off risk
Cards: Unique Connections · Unique Connection Types · Flat-File Sources ·
Flat-File One-Off Sources
Charts: *Connections by Type* (bar on `Connections[connection_type]`), *Flat-File
Datasources* (table)

**3. Complexity** — calculated-field + model-size effort
Cards: Calculated Fields · Calc Field Density · Avg Fields per Source · Hidden Fields
Charts: *Calculated Fields by Project* (bar), *Calc-Heavy Datasources* (table)

**4. Governance** — certification + stale content to triage
Cards: Certified Data Sources · Certification Rate · Extract-Based Sources ·
Stale Extracts · Stale Workbooks · Avg Extract Age (days)
Charts: *Stale Workbooks by Project* (column), *Stale Extract Datasources* (table),
*Workbook Update Recency* (line on `Workbooks[updated_at]`)

> **Two tables ship with a pre-staged filter card** (unapplied): *Flat-File Datasources*
> carries `Connections[is_flat_file]` and *Stale Extract Datasources* carries
> `Datasources[is_refresh_stale]`. They show all rows until you flip the filter to `True`
> in the Filters pane — a one-click way to scope each table to just the rows that matter.

---

## What each KPI means

See [`kpi_catalog.json`](./kpi_catalog.json) for the full list with descriptions and the
exact DAX. Highlights:

| KPI | Migration signal |
|-----|------------------|
| **Unique Connections** | Distinct upstream DB/file instances — true connection footprint (not just connector types). |
| **Flat-File / One-Off Sources** | Excel/CSV/Access/etc. sources — usually need re-platforming or are throwaway. |
| **Reused Data Sources** | Datasources feeding >1 workbook — prioritise these; they have the most downstream impact. |
| **Calc Field Density** | Calculated fields per datasource — proxy for DAX-translation effort (see Play 4). |
| **Stale Extracts / Stale Workbooks** | Content untouched beyond `STALE_DAYS` — candidates to retire rather than migrate. |
| **Certification Rate** | Governance maturity of the estate. |

---

## Tunables

These are set in the Play 5 notebook **before** the model is built, then baked into the
data:

- **`STALE_DAYS`** (default 90) — staleness threshold for extracts and workbooks.
- **`FLAT_FILE_TYPES`** — the Tableau `connectionType` set treated as flat-file/one-off.

Change them in the notebook and re-run to re-shape `Stale *` and `Flat-File *` KPIs.

---

## Regenerating the report

The `report/` tree is generated — don't hand-edit it. After changing `kpi_catalog.json`
(or the model contract), rebuild it:

```bash
cd Play5/dashboard
python generate_report.py      # rewrites report/
python report_tests.py         # offline validation (must print all checks passed)
```

`generate_report.py` emits a [PBIR](https://learn.microsoft.com/power-bi/developer/projects/projects-report)
`.pbip` tree whose every file shape is grounded in real exported Power BI fixtures.
`report_tests.py` validates it offline: well-formed parts, the live-connection binding,
every catalog measure surfaced by a visual, and every table/column/measure reference
resolving to the model contract — plus a check that the committed `report/` is in sync with
the generator. Offline validation can't prove a visual *renders* (only Desktop/Fabric can),
which is why charts/tables/slicers are best-effort.

## If a visual renders blank

A blank chart/table/slicer almost always means a field mapping needs a nudge — the data is
fine, the visual just isn't bound the way Desktop wants:

1. Select the visual and check the **Build visual** pane. The fields are listed by name; if
   one shows an error, remove and re-drag it from the **Data** pane (same table/column).
2. KPI **cards** are the most reliable — if a whole page looks empty, confirm the report is
   connected to the model (Option A, step 3).
3. Worst case, delete the offending visual; the rest of the board is unaffected. The exact
   measure/column it used is documented in [`kpi_catalog.json`](./kpi_catalog.json).

## Why a pre-bound `.pbix` isn't shipped

A binary `.pbix` embeds the model's database GUID, which only exists *after* the model is
deployed — so it can't be shipped generically. A **`.pbip` is text/JSON**, so the connection
lives in one editable file (`definition.pbir`) and you repoint it in seconds. That's why this
folder ships a `.pbip` rather than a `.pbix`/`.pbit`.
