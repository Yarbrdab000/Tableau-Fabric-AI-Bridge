# Tableau Datasource Profiler

A read-only Copilot CLI skill that profiles a published Tableau datasource and reports its
fields, types, calculated-field formulas, lineage, and (optionally) value-level statistics.

Built directly on Tableau's REST + Metadata + VizQL Data Service APIs — **no
`tableauserverclient`**, so it works against both **Tableau Cloud** and **Tableau Server**.

See [`SKILL.md`](./SKILL.md) for full setup, usage, and agent guidance. Quick version:

```bash
pip install -r requirements.txt

export TABLEAU_SERVER="https://10ax.online.tableau.com"
export TABLEAU_SITE="your_site_content_url"
export TABLEAU_PAT_NAME="your_pat_name"
export TABLEAU_PAT_VALUE="your_pat_secret"

python scripts/profile_datasource.py --datasource-name "Superstore"            # schema only
python scripts/profile_datasource.py --datasource-name "Superstore" --with-stats # + value stats
python scripts/profile_datasource.py --datasource-name "Superstore" --dry-run   # show requests only
```

## What you get

- **Schema profile (default, no rate limit):** per-field role, data type, aggregation, hidden
  flag, folder, description, calculated-field formulas, and lineage; plus datasource-level
  migration signals (`containsUnsupportedCustomSql`, calculated-field count, `hasUserReference`).
- **Value stats (`--with-stats`, optional):** approximate row count, null rates, cardinality,
  numeric ranges, and date ranges via the VizQL Data Service — sent one aggregate function per
  query (VDS forbids repeating a field in a query) and batched to respect the 100 calls/hour
  per-Creator limit. Bin/group/set and other non-aggregatable fields are skipped robustly
  (batches that 400 or return grouped rows are split and retried), and stats degrade to
  schema-only with a note on a 429. Requires Tableau 2025.1+ with VDS enabled. Note: value
  stats reflect only rows the PAT user can see under RLS — use a Site Admin PAT for full data.

## How it fits this repo

This is the first reusable skill on top of the same APIs that power the Tableau → Fabric
bridge. Its output feeds the later motions: migration-readiness scoring, DAX translation of
harvested calculated-field formulas, phased-migration scoping, and post-migration parity tests.
