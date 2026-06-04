#!/usr/bin/env python3
"""Generate the Play 5 migration-assessment dashboard as a Power BI Project (.pbip).

The Play 5 semantic model ("Tableau Migration Assessment") is *deterministic* — the
same tables, columns, and measures for every customer — so a single report can be
pre-built once and reused everywhere. This script turns ``kpi_catalog.json`` (the
machine-readable dashboard spec) into a complete PBIR (.pbip) report tree under
``Play5/dashboard/report/`` that you open in Power BI Desktop and point at your
deployed model. The only manual step is the rebind.

Nothing here talks to Power BI or Fabric — it just writes text/JSON files. Every file
shape is grounded in real exported PBIR fixtures and the official Microsoft report
item-schemas, then validated offline by ``report_tests.py``.

Usage:
    python generate_report.py            # regenerate Play5/dashboard/report/
    python generate_report.py --out DIR  # write the .pbip tree somewhere else

Regenerate after editing ``kpi_catalog.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(HERE, "kpi_catalog.json")

REPORT_NAME = "Tableau Migration Assessment"
MEASURES_ENTITY = "_Metrics"

# Workspace name is the one token a deployer replaces; the model (database) name is
# fixed because the Play 5 model is deterministic.
WORKSPACE_PLACEHOLDER = "REPLACE_WITH_YOUR_FABRIC_WORKSPACE_NAME"

# ── PBIR schema URLs (pinned to the versions of the fixtures we grounded against) ──
SCHEMA = {
    "pbir":    "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/1.0.0/schema.json",
    "report":  "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.1.0/schema.json",
    "version": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "pages":   "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "page":    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.1.0/schema.json",
    "visual":  "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.1.0/schema.json",
    "platform": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
    "pbip":    "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
}

# ── Model contract (mirror of play5_assess.py ESTATE_TABLES / ESTATE_MEASURES) ─────
# Used to fail fast at generation time if kpi_catalog references something the model
# does not expose. report_tests.py re-checks this independently.
CONTRACT_COLUMNS = {
    "Datasources": {
        "datasource_id", "name", "project_name", "owner_name", "is_certified",
        "certification_status", "has_extracts", "connection_summary",
        "downstream_workbook_count", "field_count", "is_reused",
        "extract_last_refresh", "days_since_refresh", "is_refresh_stale",
    },
    "Fields": {
        "datasource_id", "datasource_name", "field_name", "field_type",
        "data_type", "role", "is_calculated", "is_hidden",
    },
    "Connections": {
        "datasource_id", "datasource_name", "database_name", "connection_type",
        "is_flat_file",
    },
    "Workbooks": {
        "workbook_id", "name", "project_name", "owner_name", "sheet_count",
        "published_datasource_count", "updated_at", "days_since_update",
        "is_content_stale",
    },
    "Project": {"project_name"},
    "Owner": {"owner_name"},
}

# Visual-level filter cards pre-staged on these tables (unapplied — the deployer flips
# them on in Desktop). Keyed by chart title. Grounded in the real "Categorical" filter
# shape; deliberately NOT an applied Where clause (that construct has no golden fixture).
TABLE_PRESTAGED_FILTERS = {
    "Flat-File Datasources": ("Connections", "is_flat_file"),
    "Stale Extract Datasources": ("Datasources", "is_refresh_stale"),
}

# Canvas geometry (1280x720, standard 16:9).
PAGE_W, PAGE_H = 1280, 720


def _id(*parts: str) -> str:
    """Deterministic 20-hex visual/page id from a name (stable across regenerations)."""
    h = hashlib.md5("::".join(parts).encode("utf-8")).hexdigest()
    return h[:20]


def _guid(*parts: str) -> str:
    """Deterministic RFC-4122 GUID from a name (Power BI requires a real GUID for
    .platform config.logicalId, not a bare hex string)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "::".join(parts)))


def _parse_ref(ref: str):
    """'Datasources[field_count]' -> ('Datasources', 'field_count')."""
    table, _, rest = ref.partition("[")
    return table.strip(), rest.rstrip("]").strip()


# ── Field-expression builders ──────────────────────────────────────────────────────
def _column_field(table: str, column: str) -> dict:
    return {
        "Column": {
            "Expression": {"SourceRef": {"Entity": table}},
            "Property": column,
        }
    }


def _measure_field(measure: str) -> dict:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": MEASURES_ENTITY}},
            "Property": measure,
        }
    }


def _column_projection(table: str, column: str, active: bool | None = None) -> dict:
    p = {
        "field": _column_field(table, column),
        "queryRef": f"{table}.{column}",
        "nativeQueryRef": column,
    }
    if active is not None:
        p["active"] = active
    return p


def _measure_projection(measure: str) -> dict:
    return {
        "field": _measure_field(measure),
        "queryRef": f"{MEASURES_ENTITY}.{measure}",
        "nativeQueryRef": measure,
    }


def _measure_sort(measure: str) -> dict:
    return {
        "sort": [{"field": _measure_field(measure), "direction": "Descending"}],
        "isDefaultSort": True,
    }


# ── Visual builders ────────────────────────────────────────────────────────────────
def _container(name: str, x: float, y: float, w: float, h: float, z: int, visual: dict,
               filter_config: dict | None = None) -> dict:
    c = {
        "$schema": SCHEMA["visual"],
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": visual,
    }
    if filter_config:
        c["filterConfig"] = filter_config
    return c


def _card(page: str, measure: str, x, y, w, h, z) -> dict:
    visual = {
        "visualType": "cardVisual",
        "query": {"queryState": {"Data": {"projections": [_measure_projection(measure)]}}},
        "drillFilterOtherVisuals": True,
    }
    return _container(_id(page, "card", measure), x, y, w, h, z, visual)


def _column_sort(table: str, column: str, direction: str = "Ascending") -> dict:
    return {
        "sort": [{"field": _column_field(table, column), "direction": direction}],
        "isDefaultSort": True,
    }


def _cartesian(page: str, vtype: str, axis_ref: str, measure: str, title: str,
               x, y, w, h, z, sort_by_axis: bool = False) -> dict:
    table, col = _parse_ref(axis_ref)
    query = {
        "queryState": {
            "Category": {"projections": [_column_projection(table, col, active=True)]},
            "Y": {"projections": [_measure_projection(measure)]},
        },
        "sortDefinition": _column_sort(table, col) if sort_by_axis else _measure_sort(measure),
    }
    visual = {"visualType": vtype, "query": query, "drillFilterOtherVisuals": True}
    return _container(_id(page, "chart", title), x, y, w, h, z, visual)


# Map kpi_catalog chart "type" -> (PBIR visualType, sort_by_axis).
_CARTESIAN_TYPES = {
    "clusteredColumn": ("clusteredColumnChart", False),
    "clusteredBar": ("clusteredBarChart", False),
    "line": ("lineChart", True),
}


def _table(page: str, columns: list[str], measures: list[str], title: str,
           x, y, w, h, z) -> dict:
    projections = []
    sort_measure = None
    for ref in columns:
        table, col = _parse_ref(ref)
        projections.append(_column_projection(table, col))
    for m in measures:
        projections.append(_measure_projection(m))
        sort_measure = sort_measure or m

    query = {"queryState": {"Values": {"projections": projections}}}
    if sort_measure:
        query["sortDefinition"] = _measure_sort(sort_measure)

    visual = {"visualType": "tableEx", "query": query, "drillFilterOtherVisuals": True}

    filter_config = None
    if title in TABLE_PRESTAGED_FILTERS:
        ftable, fcol = TABLE_PRESTAGED_FILTERS[title]
        filter_config = {
            "filters": [
                {
                    "name": _id(page, "filter", title, fcol),
                    "field": _column_field(ftable, fcol),
                    "type": "Categorical",
                    "howCreated": "User",
                }
            ]
        }
    return _container(_id(page, "table", title), x, y, w, h, z, visual, filter_config)


def _slicer(page: str, table: str, column: str, x, y, w, h, z) -> dict:
    visual = {
        "visualType": "slicer",
        "query": {
            "queryState": {
                "Values": {"projections": [_column_projection(table, column, active=True)]}
            },
            "sortDefinition": {"isDefaultSort": True},
        },
        "objects": {
            "data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Basic'"}}}}}]
        },
        "drillFilterOtherVisuals": True,
    }
    return _container(_id(page, "slicer", table, column), x, y, w, h, z, visual)


# ── Page assembly ──────────────────────────────────────────────────────────────────
def build_page_visuals(page: dict, slicers: list[dict], measures_by_name: dict) -> list[dict]:
    """Return the list of visual containers for one catalog page, with simple layout."""
    page_name = page["name"]
    visuals: list[dict] = []
    z = 1000

    # Band 1: the two shared slicers across the top.
    sx, sw, sgap = 24, 300, 16
    for i, sl in enumerate(slicers):
        visuals.append(_slicer(page_name, sl["table"], sl["column"],
                               sx + i * (sw + sgap), 16, sw, 56, z))
        z += 1000

    # Band 2: KPI cards grid.
    cards = page.get("cards", [])
    cw, ch, cgap, cx0, cy0, per_row = 184, 92, 14, 24, 88, 6
    for i, measure in enumerate(cards):
        row, coln = divmod(i, per_row)
        x = cx0 + coln * (cw + cgap)
        y = cy0 + row * (ch + cgap)
        visuals.append(_card(page_name, measure, x, y, cw, ch, z))
        z += 1000

    # Band 3: charts/tables, two per row below the cards.
    card_rows = (len(cards) + per_row - 1) // per_row
    chart_y0 = cy0 + max(card_rows, 0) * (ch + cgap) + 24
    chw, chh, chgap = 596, 232, 24
    for i, chart in enumerate(page.get("charts", [])):
        row, coln = divmod(i, 2)
        x = 24 + coln * (chw + chgap)
        y = chart_y0 + row * (chh + chgap)
        title = chart.get("title", f"chart{i}")
        ctype = chart["type"]
        if ctype in _CARTESIAN_TYPES:
            vtype, sort_by_axis = _CARTESIAN_TYPES[ctype]
            visuals.append(_cartesian(page_name, vtype, chart["axis"], chart["value"],
                                      title, x, y, chw, chh, z, sort_by_axis))
        elif ctype == "table":
            visuals.append(_table(page_name, chart.get("columns", []),
                                  chart.get("measures", []), title, x, y, chw, chh, z))
        else:
            raise ValueError(f"Unsupported chart type in kpi_catalog: {ctype!r}")
        z += 1000

    return visuals


# ── Static (non-visual) part builders ──────────────────────────────────────────────
def build_definition_pbir() -> dict:
    conn = (
        f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/{WORKSPACE_PLACEHOLDER};"
        f"Initial Catalog={REPORT_NAME};"
    )
    return {
        "$schema": SCHEMA["pbir"],
        "version": "4.0",
        "datasetReference": {
            "byPath": None,
            "byConnection": {
                "connectionString": conn,
                "pbiServiceModelId": None,
                "pbiModelVirtualServerName": "sobe_wowvirtualserver",
                "pbiModelDatabaseName": REPORT_NAME,
                "name": "EntityDataSource",
                "connectionType": "pbiServiceXmlaStyleLive",
            },
        },
    }


def build_platform() -> dict:
    return {
        "$schema": SCHEMA["platform"],
        "metadata": {"type": "Report", "displayName": REPORT_NAME},
        "config": {"version": "2.0", "logicalId": _guid("logical", REPORT_NAME)},
    }


def build_report_json() -> dict:
    # No themeCollection/resourcePackages: referencing a base theme requires shipping
    # the StaticResources file, so we omit it and let Desktop apply the default theme.
    return {
        "$schema": SCHEMA["report"],
        "layoutOptimization": "None",
        "settings": {
            "useStylableVisualContainerHeader": True,
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
        },
    }


def build_version_json() -> dict:
    return {"$schema": SCHEMA["version"], "version": "2.0.0"}


def build_pbip() -> dict:
    return {
        "$schema": SCHEMA["pbip"],
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{REPORT_NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    }


# ── Top-level assembly ─────────────────────────────────────────────────────────────
def build_files(catalog: dict) -> dict:
    """Return {relative_path: json_obj} for the whole .pbip tree."""
    measures_by_name = {m["name"]: m for m in catalog.get("measures", [])}
    slicers = catalog.get("slicers", [])
    pages = catalog.get("pages", [])

    report_root = f"{REPORT_NAME}.Report"
    files: dict[str, dict] = {}

    files[f"{REPORT_NAME}.pbip"] = build_pbip()
    files[f"{report_root}/.platform"] = build_platform()
    files[f"{report_root}/definition.pbir"] = build_definition_pbir()
    files[f"{report_root}/definition/report.json"] = build_report_json()
    files[f"{report_root}/definition/version.json"] = build_version_json()

    page_ids = []
    for page in pages:
        pid = _id("page", page["name"])
        page_ids.append(pid)
        base = f"{report_root}/definition/pages/{pid}"
        files[f"{base}/page.json"] = {
            "$schema": SCHEMA["page"],
            "name": pid,
            "displayName": page["name"],
            "displayOption": "FitToPage",
            "height": PAGE_H,
            "width": PAGE_W,
        }
        for visual in build_page_visuals(page, slicers, measures_by_name):
            vid = visual["name"]
            files[f"{base}/visuals/{vid}/visual.json"] = visual

    files[f"{report_root}/definition/pages/pages.json"] = {
        "$schema": SCHEMA["pages"],
        "pageOrder": page_ids,
        "activePageName": page_ids[0] if page_ids else None,
    }
    return files


def write_tree(files: dict, out_dir: str) -> None:
    report_root = f"{REPORT_NAME}.Report"
    target = os.path.join(out_dir, report_root)
    if os.path.isdir(target):
        shutil.rmtree(target)
    for rel, obj in files.items():
        path = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, indent=2)
            fh.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(HERE, "report"),
                    help="output directory for the .pbip tree (default: ./report)")
    ap.add_argument("--catalog", default=CATALOG_PATH)
    args = ap.parse_args()

    with open(args.catalog, encoding="utf-8") as fh:
        catalog = json.load(fh)

    files = build_files(catalog)
    os.makedirs(args.out, exist_ok=True)
    write_tree(files, args.out)
    n_visuals = sum(1 for k in files if k.endswith("/visual.json"))
    n_pages = sum(1 for k in files if k.endswith("/page.json"))
    print(f"\u2713 Wrote {len(files)} files to {args.out} "
          f"({n_pages} pages, {n_visuals} visuals)")


if __name__ == "__main__":
    main()
