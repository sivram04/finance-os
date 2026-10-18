# Finance OS

Finance and project-accounting platform for the fictional company Echo Labs. Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md).

## Run locally (DuckDB)

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"          # installs the finance_os package from src/
.venv/Scripts/python -m finance_os.generator                 # CSVs → data/synthetic/
.venv/Scripts/python -m finance_os.ingestion.synthetic_loader  # → data/finance_os.duckdb, raw_* schemas
.venv/Scripts/python -m finance_os.ingestion.ap_intake         # reads vendor bill PDFs in data/inbox/ap → raw_ap
cd warehouse && ../.venv/Scripts/dbt build --profiles-dir .
.venv/Scripts/python -m pytest tests
```

## Status
- Step 1: generator (customers, products, price list, daily usage), DuckDB loader, dbt staging + tests.
- Step 2 (M2 unit economics): GPU job logs, cloud overhead, support/success pools, anomaly manifest;
  seed-driven cost allocation; `fct_unit_economics_monthly`, `fct_customer_margin_monthly`.
  Switch allocation drivers with `dbt build --vars '{allocation_scenario: hours}'`.
  Revenue is rated usage and payment fees are modeled until Stripe is connected.
- Step 3 (M3 tech spend): GPU vendor contract with reserved H100 hours, monthly vendor invoices,
  `fct_tech_spend_daily` (label attribution), tagging coverage, untagged-spike detection, GPU capacity vs. commit,
  vendor renewal flags, 3-month spend forecast, and `recon.recon_vendor_invoices` (invoice vs. modeled, 1%).
  Uses synthetic cloud lines; the real GCP billing export joins on the BigQuery target.
- Step 4 (M4 burn, runway, KPIs): employees and payroll, a double-entry GL (revenue, collections, fees,
  vendor bills and payments, payroll, opex, funding), `fct_gl_monthly`, `fct_cash_monthly`, `fct_headcount_monthly`,
  `fct_kpi_monthly`; recon checks GL ↔ rated revenue, payroll ↔ GL, vendor bills ↔ AP, all in `recon.recon_status`.
  Unit economics now include unused reserved GPU hours, and support/success cost comes from payroll.
- Customer lifecycle: self-serve and mid-market churn (voluntary and failed-payment, with win-backs),
  expansion and contraction, a competitor price cut hitting mid-market, an enterprise account lost to a
  competitor (A-M4-01) and a one-off backfill spike that inflates ARR (A-M4-02). Measured from revenue in
  `fct_customer_revenue_monthly` and `fct_mrr_bridge_monthly`; churn KPIs added to the catalog.
- Step 5 (M5 budget vs. actuals): original budgets for FY2025 (from plan) and FY2026 (from the Oct 2025
  run-rate, optimistic), `fct_bva_monthly` (variance, YTD, full-year forecast), `fct_bva_alerts` routed to the
  department owner (threshold in `seeds/variance_thresholds.csv`), and `fct_bva_drivers` (top journal lines behind
  each alert, for the variance explainer). Anomaly A-M5-01: unbudgeted legal fees in G&A, Mar–May 2026.
- Step 6 (M6 project accounting): six implementation projects (fixed fee, T&M, T&M with cap, federal T&M with
  CLINs) with contracts, budgets by cost type, POs, weekly timesheets, subcontractor bills, ODCs, milestones,
  project invoices and PM estimates; services revenue and project costs in the GL. Marts: `fct_project_costs_monthly`,
  `fct_project_financials` (EAC, % complete, earned, unbilled, deferred, cap usage), `fct_contract_funding`
  (75%/90% funding alerts), `fct_project_exceptions`. Recon: project invoices ↔ GL, project labor ≤ payroll.
  ARR now counts usage revenue only. Anomalies A-M6-01..04 and A-M6-05 (unbilled milestone, for M7).
- Step 7 (M7 billing operations): pre-bill validation on every invoice line (`fct_billing_exceptions`: rate,
  hours, duplicates, milestone acceptance, cap, funding), the next billing run with unbilled-days alerts
  (`fct_billing_run`), billing status per project (`fct_project_billing_status`), and invoice PDFs with backup
  hours (`finance_os.reports.invoice_pdf`). Anomaly A-M7-01: a P-102 line billed at the wrong labor-category rate.
- Step 8 (M8 AR and collections): customer payments recorded with remittance vs. applied invoice, and a dispute
  log. Marts: `fct_ar_invoices`, `fct_ar_aging_snapshot` (month-end buckets), `fct_ar_monthly` (DSO, CEI),
  `fct_customer_payment_behavior` (per customer and invoice type), `fct_collections_queue` (ranked; disputes and
  cash-application problems held), `fct_cash_application_exceptions`, `fct_disputes`. AR subledger ties to GL 1200.
  Reminder drafts: `python -m finance_os.collections.draft_reminders` (template or `--backend openai`; drafts only,
  checked to quote the exact invoice and amount, never sent). Anomalies A-M8-01 (slow payer), A-M8-02 (misapplied payment).
- AP document intake (M16): the generator writes 82 vendor bill PDFs in four vendor layouts to `data/inbox/ap`.
  `ingestion/ap_intake` reads them (rules backend offline; OpenAI backend with `OPENAI_API_KEY`), and the warehouse
  checks each one (`fct_ap_documents`): known vendor, total = lines, duplicate, PO exists and matches the vendor,
  matches the posted bill. Failures go to `fct_ap_review_queue`; `fct_ap_extraction_accuracy` scores the extractor.
  Anomalies A-AP-01..03 (arithmetic error, duplicate submission, wrong PO).

## The live company (runs every morning)
After the synthetic history ends (30 Sep 2026), Echo Labs keeps operating on real dates. Each morning
`python -m finance_os.daily` simulates every day since the last run, through today:
- **AI decides what happens** (Claude Code headless on your Claude plan; it may only search the company's memory),
  code validates every event and computes every amount: signups, churn, expansions, late payers, card failures,
  refunds, project milestones, vendor price increases, duplicate bills, one-off bills from new vendors.
- **Revenue side:** usage, GPU job logs and cloud costs daily; usage invoices on the 1st (also in the Stripe
  sandbox), card charges and declines, collections on terms.
- **AP side:** cloud/GPU costs accrued at month end; bills arrive on the 5th as PDFs in `data/inbox/ap` (read by
  M16 intake) with any true-up; recurring opex on the 15th; Thursday payment runs with early-pay discounts;
  payroll at month end; planned hires start on their dates.
- Everything posts balanced journal entries, is appended to the warehouse after the history, and dbt rebuilds.
  KPIs, forecasts and reconciliations use closed months (a month closes when it is billed on the 1st).

Scheduled with Windows Task Scheduler at 7:00 (runs when the laptop is back if it was off):
```bash
powershell -ExecutionPolicy Bypass -File scripts/schedule_daily.ps1
```
Logs: `data/live/logs/<date>.log`. Settings in `.env`: `SIM_PROVIDERS=claude_code` (default; add `,api` for an API fallback);
`SIM_API_KEY` / `SIM_BASE_URL` / `SIM_MODEL` for an OpenAI-compatible fallback (e.g. Groq's free tier), else
OpenAI as the API provider; `STRIPE_SECRET_KEY` (sandbox) to mirror billing in Stripe.

## Scale and BigQuery
The generator has three company sizes: `--scale S` (default: 105 customers, ~32M API requests; local DuckDB,
tests), `M` (400 customers) and `L` (2,000 customers, ~590M API requests, ~70 GB; BigQuery). Request-level usage
events are generated inside the warehouse by SQL from the daily drivers, with duplicates, late arrivals, failed
requests and a mid-2026 logging change; dbt dedupes and rolls them up, and `recon_usage_events` proves they add back
to the drivers to the millisecond.
```bash
.venv/Scripts/python -m finance_os.generator.high_volume --engine duckdb
```
BigQuery (project `finance-os-sivaram`, your gcloud login, no key files):
```bash
.venv/Scripts/python -m finance_os.generator --scale L --out data/synthetic_L --inbox data/inbox_L/ap
```
```bash
.venv/Scripts/python -m finance_os.ingestion.bigquery_loader --src data/synthetic_L
```
```bash
.venv/Scripts/python -m finance_os.generator.high_volume --engine bigquery
```
Generation runs month by month (on-demand BigQuery caps CPU per byte scanned). dbt target `cloud` is configured;
porting every model to run on it is in progress (usage-event models run on both today).

## Web app
Assistant panel (agentic, shows every tool step, approval cards) next to a card-based workspace: Home (KPIs, periods,
position chart, Needs you, approvals, modules) and pages for Revenue, Tech spend, Budget, Projects, Billing,
Receivables, AP inbox and Trust. Pages read the same tools as the assistant, so both show the same numbers.
Chats are kept (History menu; the last chat reopens after a reload). Drop a vendor bill into the assistant (PDF,
scanned PDF or photo): it is read (PDF text, or OpenAI vision OCR for scans and images), checked against vendors,
POs and the ledger (duplicate, arithmetic, PO owner and open balance), and the assistant prepares an approve or
reject card. Sample scans: `python -m finance_os.generator.documents.sample_scans` → `data/samples/`.
On phones the app shows one panel at a time with a Workspace / Assistant switch.

Run the API and the web dev server, then open http://localhost:5173:
```bash
.venv/Scripts/python -m finance_os.app
```
```bash
npm --prefix web install && npm --prefix web run dev
```

## Assistant backend (stage 1 of the web app)
Agentic assistant over the warehouse: OpenAI with tool calling, 18 read-only tools, 3 proposal-only actions,
a code validator for numbers and grounding, and an approve / reject / undo audit trail in `data/app.duckdb`.
```bash
.venv/Scripts/python -m finance_os.app
```
API at http://127.0.0.1:8000 (interactive docs at `/docs`). Eval (31 questions, real API, costs cents per question):
```bash
.venv/Scripts/python -m finance_os.app.eval --runs 3
```
Model: `OPENAI_ASSISTANT_MODEL` in `.env` (default `gpt-4.1`). Latest result: 93/93 over 3 runs (`evals/assistant/results/`).

## Using OpenAI for extraction
Put the key in `.env` (git-ignored), then extract and score:
```bash
.venv/Scripts/python -m finance_os.ingestion.ap_intake --backend openai
```
```bash
cd warehouse && ../.venv/Scripts/dbt build --profiles-dir . --vars "{ap_backend: openai}"
```
`.env` holds `OPENAI_API_KEY=...` and optionally `OPENAI_MODEL=...` (default `gpt-4.1-mini`).

## Metrics and board pack
KPIs are defined in `warehouse/metrics/kpis.yml`. After editing it:
```bash
.venv/Scripts/python -m finance_os.reports.build_metric_catalog
```
That writes `warehouse/seeds/metric_catalog.csv` and [docs/METRIC_CATALOG.md](docs/METRIC_CATALOG.md); dbt fails any KPI not in the catalog.

One-page board summary for the latest month (written to `reports/`):
```bash
.venv/Scripts/python -m finance_os.reports.board_pack
```

Invoice PDF with backup detail (written to `reports/invoices/`):
```bash
.venv/Scripts/python -m finance_os.reports.invoice_pdf --invoice PINV00014
```

After changing a seed's columns, run `dbt seed --full-refresh` once.
