# Tableau + Microsoft Fabric AI Bridge

> **"You don't have to migrate your data to modernize it."**

This repository contains a collection of plays that bridge existing Tableau investments
with the Microsoft AI and Fabric ecosystem. The philosophy across all plays is the same:
meet customers where their data already lives, add AI on top, and let the ceiling sell
the modernization.

These are **"AI on top of legacy" plays — not migration plays.**

---

## Repository Structure

```
Tableau-Fabric-AI-Bridge/
├── README.md
├── Play1/
│   ├── Tableau_VDS_Bridge.ipynb    # Fabric notebook — the implementation
│   └── Play1_Runbook.docx          # Full technical runbook
└── Play2/
    ├── Play2_README.md.md          # Full setup guide
    ├── template.json               # ARM template — deploy the Logic App to Azure
    ├── main.bicep                  # Bicep equivalent of the ARM template
    ├── openapi_spec.json           # OpenAPI spec — paste into Foundry as the tool definition
    └── agent_instructions.md      # Foundry agent instructions
```

---

## Plays

| Play | What it does | Status |
|------|-------------|--------|
| **Play 1** | Pull governed Tableau data sources into Fabric Lakehouse via VDS API | ✅ Complete |
| **Play 2** | Connect an Azure AI Foundry agent to Tableau via Logic App + VDS API | ✅ Complete |
| **Play 3** | Surface Tableau metadata and lineage inside OneLake Catalog | 📋 Planned |

---

## Play 1 — Tableau VDS → Fabric Lakehouse

Tableau's VizQL Data Service (VDS) is a REST API that lets you query published Tableau
data sources programmatically — returning JSON data without needing to render a
visualization. This play uses VDS to pull governed Tableau data into a Microsoft Fabric
Lakehouse as a Delta table.

The key architectural insight: **Tableau has likely become a de facto semantic layer in
your customer's environment.** Teams have spent years curating data sources, defining
metrics, certifying dashboards, and establishing governance. This play treats those
Tableau data sources as a governed system of record and extends their reach into Fabric —
without touching or replacing them.

**Architecture:**
```
Tableau Published Data Source
        ↓  VizQL Data Service REST API
Microsoft Fabric Notebook (PySpark)
        ↓  Delta write
Fabric Lakehouse
        ↓
SQL Analytics Endpoint / Power BI / Fabric Data Agent
```

See the `Play1/` folder for the notebook and full runbook.

---

## Play 2 — Foundry Agent → Tableau VDS via Logic App

This play connects an Azure AI Foundry agent (GPT-4o) to a published Tableau data
source via the VizQL Data Service API. Business users ask questions in plain English.
The agent constructs a structured VDS query, retrieves live aggregated Tableau data,
and returns a natural language answer.

**This is not a data pipeline.** No data is copied, ingested, or replicated. The agent
talks directly to Tableau at query time.

**Architecture:**
```
User (natural language question)
        ↓
Azure AI Foundry Agent (GPT-4o)
        ↓  OpenAPI tool call
Azure Logic App (Consumption)
        ↓  GET secret
Azure Key Vault
        ↓  POST /auth/signin
Tableau REST API
        ↓  POST /vizql-data-service/query-datasource
Tableau VizQL Data Service
        ↓  aggregated JSON results
Azure AI Foundry Agent
        ↓
User (natural language answer)
```

See the `Play2/` folder for the ARM template, OpenAPI spec, agent instructions, and
full setup guide.

---

## Play 3 — Tableau Metadata → OneLake Catalog (Planned)

Surface Tableau field-level lineage and governance metadata inside Microsoft OneLake
Catalog. The goal is for the Fabric data catalog to reflect what already exists in
Tableau — certified data sources, field descriptions, ownership, and lineage — without
requiring a migration.

*Coming soon.*

---

## Philosophy

All three plays follow the same pattern:

1. **Meet customers where their data already lives** — don't fight the migration battle
2. **Add AI and Fabric capabilities on top** — extend value without disruption
3. **Let the ceiling sell the modernization** — once customers see what's possible, the
   conversation about long-term platform strategy opens naturally

These plays are designed for Microsoft SEs working with customers who have significant
existing Tableau investments. The goal is not to replace Tableau — it's to make Tableau
data accessible to the Microsoft AI and Fabric ecosystem.

---

## Prerequisites (All Plays)

- Tableau Cloud or Tableau Server 2025.1+
- Creator license on the Tableau site
- A published data source in Tableau
- Azure subscription

Each play folder contains its own detailed setup guide with environment-specific
configuration instructions.

---

*Built by Reynolds Yarbrough, Microsoft Data Platform Solutions Engineer.*
