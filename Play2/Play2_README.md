# Play 2 — Tableau Metadata Bridge

> Part of the [Tableau + Microsoft Fabric AI Bridge](../../README.md) project.

## What This Does

Pulls governance metadata from the Tableau Metadata API (GraphQL) and lands it in a Fabric Lakehouse as four Delta tables. These tables are the control plane for the entire pipeline — Play 3 and Play 4 both read from them.

| Table | Contents |
|-------|----------|
| `tableau_datasources` | One row per published datasource — name, owner, project, certification, connection type, field count |
| `tableau_fields` | One row per field per datasource — name, type, role, data type, formula, hidden flag, source table |
| `tableau_lineage` | One row per relationship — upstream database tables and downstream workbooks |
| `tableau_workbooks` | One row per workbook — name, owner, sheets, published datasource connections |

**Run Play 2 first.** Everything else depends on it.

---

## Prerequisites

- Tableau Cloud or Tableau Server 2024.2+ (Metadata API required)
- Creator license on the Tableau site
- PAT stored in Azure Key Vault
- Fabric workspace managed identity has **Key Vault Secrets User** role on the Key Vault
- `Metadata_Lakehouse` attached to this notebook as default lakehouse

---

## Setup

### 1. Create the Metadata Lakehouse

In your Fabric workspace, create a new Lakehouse named `Metadata_Lakehouse` (or whatever you set `DS_TABLE` etc. to in Cell 1).

### 2. Store your Tableau PAT in Key Vault

```
Key Vault secret name: <your-secret-name>
Secret value:          <your Tableau PAT secret>
```

If you don't have a PAT yet: Tableau Cloud → your avatar → Account Settings → Personal Access Tokens → Add.

### 3. Attach the Lakehouse

Open the notebook in Fabric → left rail → Lakehouses → attach `Metadata_Lakehouse` as default.

### 4. Fill in Cell 1

```python
PAT_NAME        = "your-pat-name"
POD             = "10ay.online.tableau.com"   # your Tableau Cloud pod
SITE            = "your-site-slug"            # blank for Tableau Server default site
KV_URL          = "https://your-kv.vault.azure.net/"
KV_SECRET_NAME  = "your-secret-name"
```

### 5. Run all cells

---

## Output

Four Delta tables in `Metadata_Lakehouse`:

```
Metadata_Lakehouse
└── Tables
    ├── tableau_datasources   (1 row per published datasource)
    ├── tableau_fields        (1 row per field — includes source_table for Play 4)
    ├── tableau_lineage       (upstream tables + downstream workbooks)
    └── tableau_workbooks     (workbook inventory)
```

---

## Key Fields to Know

**`tableau_fields.source_table`** — which upstream database table each field comes from. This is what Play 3 uses to query VDS per-table without triggering cross-table inner joins, and what Play 4 uses to assign columns to the right table in the semantic model.

**`tableau_fields.field_type`** — `ColumnField` = physical column, `CalculatedField` = formula (Play 4 stubs these as DAX measures), everything else (HierarchyField, SetField, BinField, GroupField) is skipped by Play 3 and Play 4.

**`tableau_lineage.relationship_type`** — `upstream_table` = source database tables, `downstream_workbook` = workbooks consuming this datasource.

---

## Known Limitations

**`certification_status` / `certified_by`** — these fields are null when no datasources have been certified. The schema is there; the data populates once someone goes through the Tableau certification workflow.

**`workbook_owner` / `workbook_project` in lineage** — null for system-provisioned workbooks (e.g. Tableau sample content). Populated for user-created workbooks.

**Hidden field name mismatches** — the Tableau Metadata API returns Tableau display names for fields. VDS (Play 3) uses underlying column names for some hidden fields. The `source_table` mapping is still correct; Play 3 handles the name reconciliation via its retry logic.

**Data Management add-on** — `certificationStatus` and `certifiedBy` require the Tableau Data Management add-on. `isCertified` (boolean) is always available without it.

---

## Pipeline Order

```
Play 2 (this notebook) → Play 3 → Play 4
```

Play 2 is the manifest. Run it whenever the Tableau environment changes — new datasources, new fields, schema changes. Play 3 and Play 4 will pick up the changes on their next run.

---

## Rerunning

All tables use `overwrite` mode — each run produces a fresh snapshot of the current Tableau metadata state. Safe to rerun at any time.
