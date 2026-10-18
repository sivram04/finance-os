# Finance OS

Finance and project-accounting platform for the fictional company Echo Labs. Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md).

## Run locally (DuckDB)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m generator                 # CSVs → data/synthetic/
.venv/Scripts/python -m ingestion.synthetic_loader  # → data/finance_os.duckdb, raw_* schemas
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

## Metrics and board pack
KPIs are defined in `warehouse/metrics/kpis.yml`. After editing it:
```bash
.venv/Scripts/python scripts/build_metric_catalog.py
```
That writes `warehouse/seeds/metric_catalog.csv` and [docs/METRIC_CATALOG.md](docs/METRIC_CATALOG.md); dbt fails any KPI not in the catalog.

One-page board summary for the latest month (written to `reports/`):
```bash
.venv/Scripts/python scripts/board_pack.py
```

After changing a seed's columns, run `dbt seed --full-refresh` once.
