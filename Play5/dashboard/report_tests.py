#!/usr/bin/env python3
"""Offline validation for the generated Play 5 dashboard .pbip.

No Power BI / Fabric needed. These assertions can't prove a visual *renders* (only
Desktop/Fabric can), but they catch the structural and semantic mistakes that make a
PBIR import fail or a visual bind to nothing: malformed parts, dangling table/column/
measure references, uncovered KPIs, broken page/visual wiring, and a stale committed
tree. Charts/tables/slicers are the parts most likely to still need a tweak on first
open in Desktop — that's expected and documented in README.md.

Run:  python report_tests.py
"""
from __future__ import annotations

import json
import os

import generate_report as G

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(HERE, "report")

_checks = 0
_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    global _checks
    _checks += 1
    if not cond:
        _fails.append(msg)


def load_catalog() -> dict:
    with open(G.CATALOG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ── reference extraction ───────────────────────────────────────────────────────────
def iter_field_refs(obj):
    """Yield ('column', table, prop) / ('measure', entity, prop) from any field expr."""
    if isinstance(obj, dict):
        if "Column" in obj and isinstance(obj["Column"], dict):
            c = obj["Column"]
            ent = c.get("Expression", {}).get("SourceRef", {}).get("Entity")
            yield ("column", ent, c.get("Property"))
        if "Measure" in obj and isinstance(obj["Measure"], dict):
            m = obj["Measure"]
            ent = m.get("Expression", {}).get("SourceRef", {}).get("Entity")
            yield ("measure", ent, m.get("Property"))
        for v in obj.values():
            yield from iter_field_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_field_refs(v)


def measures_used(visual: dict) -> set[str]:
    return {p for k, e, p in iter_field_refs(visual) if k == "measure"}


# ── tests ──────────────────────────────────────────────────────────────────────────
def main() -> int:
    catalog = load_catalog()
    files = G.build_files(catalog)

    catalog_measures = {m["name"] for m in catalog.get("measures", [])}
    report_root = f"{G.REPORT_NAME}.Report"

    # 1. Every emitted object is JSON-serialisable and round-trips.
    for path, obj in files.items():
        try:
            json.loads(json.dumps(obj))
            check(True, "")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{path}: not JSON-serialisable: {exc}")

    # 2. Required top-level parts exist.
    for required in (
        f"{G.REPORT_NAME}.pbip",
        f"{report_root}/.platform",
        f"{report_root}/definition.pbir",
        f"{report_root}/definition/report.json",
        f"{report_root}/definition/version.json",
        f"{report_root}/definition/pages/pages.json",
    ):
        check(required in files, f"missing required part: {required}")

    # 3. .platform declares a Report.
    plat = files[f"{report_root}/.platform"]
    check(plat["metadata"]["type"] == "Report", ".platform type must be 'Report'")
    check(plat["metadata"]["displayName"] == G.REPORT_NAME, ".platform displayName wrong")

    # 4. Binding: byConnection to the deterministic model, with a replaceable workspace.
    pbir = files[f"{report_root}/definition.pbir"]
    bc = pbir.get("datasetReference", {}).get("byConnection")
    check(bc is not None, "definition.pbir missing byConnection")
    check(pbir["datasetReference"].get("byPath") is None, "byPath must be null for live connect")
    check(bc.get("pbiModelDatabaseName") == G.REPORT_NAME, "binding model name must match REPORT_NAME")
    check(bc.get("connectionType") == "pbiServiceXmlaStyleLive", "wrong connectionType")
    cs = bc.get("connectionString") or ""
    check(G.WORKSPACE_PLACEHOLDER in cs, "connectionString must contain the workspace placeholder")
    check(f"Initial Catalog={G.REPORT_NAME}" in cs, "connectionString must target the model")

    # 4b. Every part carries the $schema Power BI Desktop now requires, and the
    #     .pbip property file matches Desktop's required pattern exactly. (A wrong
    #     or missing $schema makes Desktop refuse to open the project.)
    import re as _re
    pbip_pattern = _re.compile(
        r"^https://developer\.microsoft\.com/json-schemas/fabric/pbip/"
        r"pbipProperties/1\.[0-9]+\.[0-9]+/schema\.json$"
    )
    pbip_obj = files[f"{G.REPORT_NAME}.pbip"]
    check(
        bool(pbip_pattern.match(pbip_obj.get("$schema", ""))),
        f".pbip $schema must match Desktop's pattern, got {pbip_obj.get('$schema')!r}",
    )
    expected_schema = {
        f"{report_root}/.platform": G.SCHEMA["platform"],
        f"{report_root}/definition.pbir": G.SCHEMA["pbir"],
        f"{report_root}/definition/report.json": G.SCHEMA["report"],
        f"{report_root}/definition/version.json": G.SCHEMA["version"],
        f"{report_root}/definition/pages/pages.json": G.SCHEMA["pages"],
    }
    for path, want in expected_schema.items():
        check(files[path].get("$schema") == want, f"{path}: wrong/missing $schema")
    for path, obj in files.items():
        if path.endswith("/page.json"):
            check(obj.get("$schema") == G.SCHEMA["page"], f"{path}: wrong page $schema")
        elif path.endswith("/visual.json"):
            check(obj.get("$schema") == G.SCHEMA["visual"], f"{path}: wrong visual $schema")
    # Every PBIR part must declare a $schema (Desktop validates all of them).
    for path, obj in files.items():
        if path.endswith(".json") or path.endswith(".pbir") or path.endswith(".platform") or path.endswith(".pbip"):
            check("$schema" in obj, f"{path}: missing $schema")

    # 5. pages.json wiring matches the page folders on disk-in-memory.
    page_files = [p for p in files if p.endswith("/page.json")]
    page_ids_on_tree = {p.split("/")[3] for p in page_files}
    pages_meta = files[f"{report_root}/definition/pages/pages.json"]
    check(set(pages_meta["pageOrder"]) == page_ids_on_tree, "pageOrder != page folders")
    check(pages_meta["activePageName"] in page_ids_on_tree, "activePageName not a real page")
    check(len(page_files) == len(catalog.get("pages", [])), "page count != catalog pages")

    # 6. Per-page + per-visual structural integrity.
    allowed_visuals = {"cardVisual", "clusteredColumnChart", "clusteredBarChart",
                       "lineChart", "tableEx", "slicer"}
    seen_visual_names: set[str] = set()
    for page in catalog.get("pages", []):
        pid = G._id("page", page["name"])
        pj = files.get(f"{report_root}/definition/pages/{pid}/page.json")
        check(pj is not None, f"missing page.json for {page['name']}")
        if pj:
            check(pj["name"] == pid, f"page.json name mismatch for {page['name']}")
            check(pj.get("displayName") == page["name"], f"page displayName wrong for {page['name']}")

        page_visuals = [v for p, v in files.items()
                        if p.startswith(f"{report_root}/definition/pages/{pid}/visuals/")]
        for v in page_visuals:
            name = v.get("name")
            check(bool(name), "visual missing name")
            check(name not in seen_visual_names, f"duplicate visual id {name}")
            seen_visual_names.add(name)
            pos = v.get("position", {})
            check(all(k in pos for k in ("x", "y", "z", "width", "height")),
                  f"visual {name} missing position fields")
            vis = v.get("visual", {})
            check(vis.get("visualType") in allowed_visuals,
                  f"visual {name} has unexpected type {vis.get('visualType')}")
            check("queryState" in vis.get("query", {}), f"visual {name} missing queryState")

        # Slicers: both shared slicers present on every page.
        page_slicer_fields = set()
        for v in page_visuals:
            if v["visual"].get("visualType") == "slicer":
                for k, ent, prop in iter_field_refs(v["visual"]):
                    if k == "column":
                        page_slicer_fields.add((ent, prop))
        for sl in catalog.get("slicers", []):
            check((sl["table"], sl["column"]) in page_slicer_fields,
                  f"slicer {sl['table']}[{sl['column']}] missing on page {page['name']}")

        # Cards: every catalog card measure present as a card on this page.
        page_card_measures = set()
        for v in page_visuals:
            if v["visual"].get("visualType") == "cardVisual":
                page_card_measures |= measures_used(v["visual"])
        for card in page.get("cards", []):
            check(card in page_card_measures,
                  f"card '{card}' missing on page {page['name']}")

    # 7. Reference integrity: every column/measure reference resolves to the model contract.
    all_visuals = [v for p, v in files.items() if p.endswith("/visual.json")]
    for v in all_visuals:
        for kind, entity, prop in iter_field_refs(v):
            if kind == "column":
                cols = G.CONTRACT_COLUMNS.get(entity)
                check(cols is not None, f"unknown table entity {entity} in {v['name']}")
                if cols is not None:
                    check(prop in cols, f"unknown column {entity}[{prop}] in {v['name']}")
            else:  # measure
                check(entity == G.MEASURES_ENTITY,
                      f"measure {prop} bound to {entity}, expected {G.MEASURES_ENTITY}")
                check(prop in catalog_measures, f"unknown measure '{prop}' in {v['name']}")

    # 8. Coverage: every catalog measure is surfaced by at least one visual.
    used = set()
    for v in all_visuals:
        used |= measures_used(v["visual"])
    for m in catalog_measures:
        check(m in used, f"measure '{m}' not surfaced by any visual")

    # 9. Prestaged filters on the flat-file / stale tables.
    for title, (ftable, fcol) in G.TABLE_PRESTAGED_FILTERS.items():
        match = [v for v in all_visuals
                 if v["visual"].get("visualType") == "tableEx"
                 and any(k == "column" and e == ftable and p == fcol
                         for k, e, p in iter_field_refs(v.get("filterConfig", {})))]
        check(bool(match), f"table '{title}' missing prestaged filter {ftable}[{fcol}]")

    # 10. The committed on-disk tree is up to date (no drift vs the generator).
    if os.path.isdir(REPORT_DIR):
        for rel, obj in files.items():
            disk = os.path.join(REPORT_DIR, *rel.split("/"))
            if not os.path.isfile(disk):
                check(False, f"committed tree missing {rel} (run generate_report.py)")
                continue
            with open(disk, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            check(on_disk == obj, f"committed {rel} is stale (run generate_report.py)")
        disk_files = {
            os.path.relpath(os.path.join(dp, fn), REPORT_DIR).replace(os.sep, "/")
            for dp, _, fns in os.walk(REPORT_DIR) for fn in fns
        }
        for extra in disk_files - set(files):
            check(False, f"committed tree has stray file {extra} (run generate_report.py)")
    else:
        check(False, "report/ not generated yet (run generate_report.py)")

    # ── report ──
    passed = _checks - len(_fails)
    if _fails:
        print(f"\u2717 {len(_fails)} FAILED / {_checks} checks")
        for f in _fails[:50]:
            print(f"   - {f}")
        return 1
    print(f"\u2713 {passed}/{_checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
