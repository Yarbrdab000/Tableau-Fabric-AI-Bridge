---
name: tableau-datasource-profiler
description: >-
  Profile a published Tableau datasource. Returns a field-level report — data
  types, roles, hidden flags, folders, calculated-field formulas, lineage, and
  datasource-level migration signals (unsupported custom SQL, calculated-field
  count, RLS/user references). Optionally adds value-level statistics
  (cardinality, null rates, numeric ranges, date ranges) via the VizQL Data
  Service. Use this when a user wants to understand, inventory, audit, or assess
  the migration readiness of a Tableau datasource, or before landing it in
  Microsoft Fabric (Plays 2–4 of this repo). Read-only; never modifies Tableau.
---

# Tableau Datasource Profiler

Profiles a single published Tableau datasource using Tableau's REST APIs directly
(no `tableauserverclient`, so it works against **Tableau Cloud and Tableau Server**).

## When to use this skill

Use it when the user asks to:
- Inventory or document a Tableau datasource's fields, types, or calculations.
- Assess migration readiness (calculated fields needing DAX, unsupported custom SQL, RLS).
- Profile data quality (cardinality, null rates, value/date ranges) before landing data in Fabric.
- Scope a phased migration (which datasource/fields to move first).

## How it works

Two API paths:

1. **Metadata API (GraphQL)** — the default, **no VDS rate limit**. Returns per-field
   `name, role, dataType, aggregation, isHidden, folderName, description`,
   `CalculatedField.formula`, lineage (upstream tables / referenced columns), and
   datasource-level signals (`containsUnsupportedCustomSql`, `hasUserReference`, certification).
2. **VizQL Data Service (VDS)** — optional (`--with-stats`). Adds value statistics:
   approximate row count, per-field null rates, dimension cardinality (COUNTD), numeric
   MIN/MAX/AVG, and date MIN/MAX. Each aggregate function is sent as its own batched query
   (VDS forbids referencing the same field twice in one query) — roughly 7 calls plus
   chunking for very wide datasources. Fields VDS can't aggregate are handled robustly:
   bins/groups/sets are excluded up front, and any batch that 400s or returns multiple rows
   (a field acting as a GROUP BY) is split and retried so one bad field doesn't sink the rest.
   Stays under the **100 VDS calls/hour per Creator** limit, aborts up front if the estimate
   would exceed it, and degrades to the schema profile (with a note) on a 429. Requires
   Tableau 2025.1+ with VDS enabled; if unavailable the skill degrades gracefully to the
   schema profile. (Row count is approximated as the max non-null count across fields, since
   VDS has no COUNT(*); value stats also reflect only rows the PAT user can see under RLS.)

## Setup

```bash
pip install -r .github/skills/tableau-datasource-profiler/requirements.txt
```

Set credentials as environment variables (PAT must belong to a **Site Administrator** for a
complete inventory; a Creator PAT returns only what that user can see):

| Variable | Meaning |
|---|---|
| `TABLEAU_SERVER` | Base URL, e.g. `https://10ax.online.tableau.com` |
| `TABLEAU_SITE` | Site `contentUrl` (URL slug; empty string for the Default site) |
| `TABLEAU_PAT_NAME` | Personal Access Token name |
| `TABLEAU_PAT_VALUE` | Personal Access Token secret |
| `TABLEAU_REST_VERSION` | (optional) REST API version, default `3.24` |

## Usage

```bash
# Schema profile (cheap, default) as Markdown
python .github/skills/tableau-datasource-profiler/scripts/profile_datasource.py \
  --datasource-name "Superstore"

# Full profile with value stats, as JSON to a file
python .github/skills/tableau-datasource-profiler/scripts/profile_datasource.py \
  --datasource-luid abc-123-luid --with-stats --format json --out profile.json

# See exactly what requests would be sent, without calling Tableau
python .github/skills/tableau-datasource-profiler/scripts/profile_datasource.py \
  --datasource-name "Superstore" --with-stats --dry-run
```

Select the datasource with **either** `--datasource-name` (resolved to a LUID via REST) **or**
`--datasource-luid`. Other flags: `--format md|json`, `--out <path>`, `--with-stats`,
`--dry-run`, `--page-size`, `--max-fields-per-query`, `--rest-version`.

## Agent guidance

- Prefer the default schema profile first; only add `--with-stats` when the user explicitly
  wants value-level numbers, because VDS is rate-limited.
- If credentials are not set, run with `--dry-run` to show the user what would be sent, then
  ask them to provide the environment variables.
- The tool is strictly read-only and always signs out. It never writes to Tableau.
- Surface the migration signals (calculated-field count, `containsUnsupportedCustomSql`,
  `hasUserReference`) when the user's intent is migration to Fabric / Power BI.
