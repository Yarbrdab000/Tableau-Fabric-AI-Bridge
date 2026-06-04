# Tableau → Fabric Migration Assessment — Dashboard Template

A deployable Power BI dashboard for the **Tableau Migration Assessment** semantic model
that Play 5 generates. It turns the estate KPIs (datasource counts, connection diversity,
flat-file/one-off risk, reuse, calculated-field complexity, certification coverage, and
stale content) into a board people can publish and slice.

The model already contains every measure — so building the report is just dropping
measures onto visuals. There are two ways to deploy.

---

## Option A — One-click in Fabric (fastest, zero files)

1. In your Fabric workspace, open the **Tableau Migration Assessment** semantic model
   (deployed by `Play5_Migration_Assessment.ipynb`).
2. Click **Auto-create report** (or **New report**).
3. Fabric generates a live report from the `_Metrics` measures. Save it.
4. Optional: rearrange to match the page layout in [`kpi_catalog.json`](./kpi_catalog.json).

This is the recommended path — it always produces a valid, live-connected report.

---

## Option B — Build it in Power BI Desktop (full control)

1. **Get data → Power BI semantic models → Tableau Migration Assessment** (live
   connection — no import, no refresh to manage).
2. Build the four pages below. Every card is a **Card** visual bound to a measure from
   the **`_Metrics`** table; every slicer/axis uses the shared dimensions.
3. Add two **Slicers** to each page: `Project[project_name]` and `Owner[owner_name]`.
   These are shared dimensions, so they cross-filter **both** datasource and workbook
   KPIs at once.
4. Publish back to the workspace.

`kpi_catalog.json` is the machine-readable source of truth for this layout — measure
names, exact DAX, format strings, and which page/visual each belongs on. It is generated
from the deployed model, so it never drifts.

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
Charts: *Stale Workbooks by Project* (column), *Stale Extract Datasources* (table)

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

## Note on a pre-built `.pbip`/`.pbix`

A live-connection report file must embed your workspace's model database GUID, which only
exists **after** the model is deployed — so a portable pre-bound file can't be shipped
generically. Option A (Auto-create) produces that bound file in one click, and Option B
takes ~5 minutes with the layout above. `kpi_catalog.json` makes either path mechanical.
