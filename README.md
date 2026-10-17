# Finance OS

Finance and project-accounting platform for the fictional company Echo Labs. Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md).

## Run locally (DuckDB)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m generator                 # CSVs → data/synthetic/
.venv/Scripts/python -m ingestion.synthetic_loader  # → data/finance_os.duckdb, schema raw_synth
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

After changing a seed's columns, run `dbt seed --full-refresh` once.
