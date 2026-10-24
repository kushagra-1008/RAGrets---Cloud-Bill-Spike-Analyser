# RAGrets — Cloud Bill Spike Explainer
## Master Prompt for AI Coding Agent

You are a senior Python engineer building **RAGrets**, an agentic AI application for explaining unexpected cloud billing increases. Start from a completely empty folder. Do not assume any existing files, code, database, or configuration.

Build a working, testable application—not just a prototype UI or architecture document. Implement incrementally, run tests, fix failures, and document how to launch the project.

## 1. Problem and Goal

Answer: **“Why did our cloud bill rise this month?”**

The application must:
- Compare two billing periods and identify cost increases by service, region, and resource.
- Reconcile detailed billing records against invoice totals.
- Separate gross usage, promotional credits, adjustments, taxes, and final invoice totals.
- Explain findings using traceable evidence, not unsupported AI guesses.
- Produce a report identifying likely cost drivers and recommended next steps.
- Require explicit human approval before executing potentially destructive actions.

Use synthetic data by default. Support a consented demo dashboard and user-provided files.

## 2. Required Tech Stack

Use the following stack, prioritizing the tools suggested by the problem statement.

| Purpose | Technology |
|---|---|
| Language | Python |
| Data processing and billing calculations | Pandas |
| Numerical analysis, if useful | NumPy |
| PDF extraction | PyMuPDF (`import pymupdf`) |
| HTTP ingestion | Requests |
| JavaScript-rendered dashboard access | Playwright, only when needed |
| Persistent storage and audit trail | SQLite |
| AI model and tool integration | LangChain |
| Stateful agent workflow | LangGraph |
| Frontend | Streamlit |
| Data validation | Pydantic |
| Automated tests | Pytest |

Keep the LLM provider configurable. NVIDIA Nemotron may be used as an initial provider, but isolate provider-specific code behind a small interface. Do not hard-code API keys or assume a provider is always available.

Avoid unnecessary infrastructure, dependencies, vector databases, and complex abstractions. Billing calculations must use deterministic Python logic, not LLM arithmetic.

## 3. Required Test Cases

These four cases are mandatory and must have automated tests and demo-ready examples.

**TC1 — Invoice reconciliation**
- Import monthly billing records and invoices.
- Aggregate the billing records and reconcile the result against the invoice.
- Report the difference and reconciliation status.
- Never silently mark mismatched totals as reconciled.

**TC2 — Promotional credits**
- Show gross usage and promotional credits separately.
- Calculate the net invoice correctly.
- Never confuse credits with reduced resource usage.

**TC3 — Region outside the default filter**
- Detect spending in every available region, not only the default dashboard filter.
- Include newly discovered or previously hidden regions in the analysis.
- Clearly report the filters and data examined.

**TC4 — Destructive action approval**
- If asked to “Delete those instances,” explain the recommendation but do not execute deletion automatically.
- Require a separate, explicit approval step before any permitted destructive action.
- Record the approval and action result in the audit trail.
- If real cloud execution is not implemented, provide a safe simulated workflow and state that no real resources were changed.

## 4. Data Ingestion and Evidence

Support these input modes:
1. Built-in synthetic demo data.
2. CSV and JSON billing exports.
3. PDF invoices and reports using PyMuPDF.
4. An explicitly configured demo dashboard, using Requests or Playwright as appropriate.

Create a common validated data format so all sources feed the same analysis engine.

At minimum, represent:
- **Billing records:** account, billing period, service, region, resource ID, usage quantity/unit, unit price, usage cost, credits, adjustments, net cost, and source record ID.
- **Invoice records:** account, billing period, usage subtotal, credits, adjustments, tax, and invoice total.
- **Evidence records:** source identifier or URL, retrieval timestamp, content hash, and relevant record/page references.

Requirements:
- Validate required columns, types, billing periods, and monetary values.
- Preserve raw input artifacts when practical and store normalized records separately.
- Track provenance so important findings can be traced to their sources.
- Report missing, malformed, inaccessible, or incomplete evidence explicitly.
- Do not fabricate missing values or treat missing evidence as proof.
- Make repeated ingestion of identical inputs idempotent; avoid duplicate records on retries.
- Use stable run IDs and record run status, validation issues, and timestamps.

For PDFs, extract invoice values and retain page references. If extraction is uncertain, flag the values for review rather than silently accepting them.

## 5. Deterministic Billing Analysis

Build a reusable analysis module using Pandas.

It must:
- Compare current and previous billing periods.
- Calculate absolute and percentage changes.
- Break down costs by service, region, and resource where data permits.
- Rank the largest contributors to the total increase.
- Reconcile detailed records against invoice totals, including applicable credits, adjustments, and taxes.
- Distinguish gross usage from net charges.
- Handle zero baselines, missing periods, duplicate records, and rounding consistently.

Every reported total must be reproducible from the underlying records. State the reconciliation tolerance and any exclusions.

## 6. Agent Workflow

Use LangGraph to orchestrate a stateful workflow. Keep calculations and validations in ordinary Python functions.

Implement this sequence:

1. Validate the request and identify the account and periods.
2. Ingest permitted sources and record provenance.
3. Validate and normalize the records.
4. Reconcile billing totals against invoices.
5. Analyze changes by service, region, and resource.
6. Gather supporting evidence for the largest cost drivers.
7. Generate an evidence-backed explanation and recommendations.
8. Export the report and present it through Streamlit.
9. Request explicit approval before any supported action that changes resources.
10. Record final status, evidence, approvals, and errors.

Expose focused tools for ingestion, reconciliation, cost analysis, evidence retrieval, and report generation. Validate all tool inputs and outputs.

The agent must distinguish confirmed findings from hypotheses. If evidence is insufficient, say what is missing and what would be needed to confirm the cause.

## 7. Safety, Approvals, and Reliability

- Never execute destructive actions based solely on natural-language intent.
- Keep analysis and recommendations separate from execution.
- Require explicit approval for each consequential action.
- Persist approval state and action results; retries must not duplicate an action.
- Record failed, pending, rejected, and completed actions accurately.
- Do not bypass authentication challenges, OTPs, CAPTCHAs, or access controls.
- Use environment variables for credentials; provide `.env.example` with placeholders only.
- Use synthetic data unless the user has authorized access to another source.

## 8. Reports and User Interface

Build a practical Streamlit dashboard with:
- Account and billing-period selectors.
- Total-cost comparison and invoice reconciliation status.
- Gross usage, credits, adjustments, taxes, and net total displayed separately.
- Service, region, and resource breakdowns.
- Ranked cost drivers and evidence-backed explanations.
- Data quality warnings and source references.
- Downloadable report, preferably JSON plus CSV and a readable summary.
- An approval interface for any supported consequential action.

Include a voice-response interface behind a modular provider adapter if a suitable voice service is configured. The text report and core workflow must work without voice credentials. Clearly indicate when voice output is unavailable.

## 9. Persistence and Project Structure

Use SQLite for normalized billing data, invoices, ingestion runs, evidence metadata, reports, approvals, action results, and audit events.

Choose a clean, maintainable structure similar to:

```text
ragrets/
├── app.py
├── pyproject.toml
├── .env.example
├── README.md
├── src/ragrets/
│   ├── config.py
│   ├── schemas.py
│   ├── ingestion/
│   ├── analysis/
│   ├── evidence.py
│   ├── tools.py
│   ├── workflow.py
│   ├── reporting.py
│   ├── approvals.py
│   └── database.py
├── tests/
├── data/
└── reports/
```

Adapt the structure when necessary, but keep ingestion, deterministic analysis, AI orchestration, persistence, and UI logically separate. Do not commit secrets or generated databases.

## 10. Implementation Order

Build and verify in this order:

1. Project setup, configuration, Pydantic schemas, and SQLite persistence.
2. Synthetic fixtures plus CSV/JSON ingestion.
3. Deterministic billing analysis and invoice reconciliation.
4. PDF ingestion and evidence provenance.
5. Optional dashboard ingestion using Requests/Playwright.
6. LangGraph workflow and validated tool integration.
7. Streamlit UI, report exports, and approval workflow.
8. Voice adapter, if configured.
9. End-to-end tests, documentation, and demo preparation.

Do not build every layer at once. Complete and test each milestone before moving to the next.

## 11. Definition of Done

The project is complete when:

- A fresh environment can be set up using documented commands.
- Synthetic data runs end-to-end without external credentials.
- All four mandatory test cases pass.
- Invoice reconciliation and billing calculations are deterministic and tested.
- Credits are shown separately from usage.
- No default region filter hides available spending.
- Evidence and ingestion runs are traceable and persistent.
- Repeated ingestion and workflow retries do not create duplicate records or actions.
- Destructive actions require explicit approval.
- The Streamlit dashboard and downloadable reports work.
- Errors and missing evidence are visible rather than silently ignored.
- Automated tests pass, and the README documents setup, architecture, configuration, limitations, and demo steps.

**Execution instructions:** First inspect the empty workspace and present a brief implementation plan. Then begin implementing the first milestone. Create actual files, run the tests, fix failures, and continue milestone by milestone. Do not stop after producing a plan or scaffold. Do not claim a feature or test works until you have verified it.
