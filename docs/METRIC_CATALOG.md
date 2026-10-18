# Metric catalog

Generated from `warehouse/metrics/kpis.yml` by `finance_os.reports.build_metric_catalog`. Do not edit by hand.

## Revenue (`revenue`)

- **Decision it supports:** Top-line growth tracking and the base for every margin.
- **Formula:** Sum of GL revenue recognized in the month (usage 4000 + project services 4100).
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Usage must equal rated usage (recon_gl_revenue); services must equal project invoices (recon_project_billing_gl).

## Cost of revenue (`cogs`)

- **Decision it supports:** Gross margin and cost-to-serve trend.
- **Formula:** Sum of GL COGS accounts (5000 GPU, 5010 cloud hosting, 5100 payment processing, 5200/5210 project subcontractors and direct costs).
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Vendor invoices reconcile to modeled cost within 1% (recon_vendor_invoices).

## Operating expenses (`opex`)

- **Decision it supports:** Spending pace by department; input to BvA (M5).
- **Formula:** Sum of GL operating expense accounts (6000–6500).
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Payroll accounts equal the payroll register exactly (recon_payroll_gl).

## Gross margin % (`gross_margin_pct`)

- **Decision it supports:** Pricing and product mix decisions.
- **Formula:** (Revenue − COGS) ÷ Revenue, from the GL.
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** GL-based; differs from fct_unit_economics_monthly, which allocates modeled cost and excludes payment fees.

## Gross burn (`gross_burn`)

- **Decision it supports:** Spending pace in cash terms.
- **Formula:** Operating cash out (GL cash account 1000, excluding financing).
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Closing cash must never be negative.

## Net burn (`net_burn`)

- **Decision it supports:** How fast the company consumes cash; drives runway.
- **Formula:** Operating cash out − operating cash in. Positive = burning.
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None beyond GL balance.

## Cash balance (`closing_cash`)

- **Decision it supports:** Liquidity and fundraising timing.
- **Formula:** Cumulative net change in GL cash (account 1000) to month end.
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Will reconcile to Stripe payouts and bank statements in M12.

## Runway (`runway_months`)

- **Decision it supports:** Fundraising timing.
- **Formula:** Closing cash ÷ average net burn over the trailing 3 months. Blank when not burning or under 3 months of history.
- **Unit / grain:** months / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Assumes the trailing burn rate continues; not a forecast.

## ARR (`arr`)

- **Decision it supports:** Growth tracking on an annualized basis.
- **Formula:** Usage run-rate (trailing-3-month usage revenue, account 4000, × 4) + committed annualized (none yet). Project services are excluded.
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Usage-based ARR moves with seasonality; read with NRR.

## Headcount (`headcount`)

- **Decision it supports:** Hiring plan tracking and per-employee ratios.
- **Formula:** Employees hired on or before month end and not yet terminated.
- **Unit / grain:** count / month
- **Source model:** `fct_headcount_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Employees with pay in the month must reconcile to headcount ± hires and leavers.

## ARR per employee (`arr_per_employee`)

- **Decision it supports:** Efficiency benchmark (FR-4.3 revenue per employee, on an annualized basis).
- **Formula:** ARR ÷ month-end headcount.
- **Unit / grain:** usd / month
- **Source model:** `fct_kpi_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None.

## Net revenue retention (`nrr`)

- **Decision it supports:** Expansion health of the existing customer base.
- **Formula:** Trailing-3-month revenue now from customers who had revenue in the same window 12 months earlier ÷ their revenue then.
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Starts once 12 months plus a 3-month window of history exist.

## Gross revenue retention (`grr`)

- **Decision it supports:** Churn and contraction, with expansion removed.
- **Formula:** Same cohort as NRR, but each customer's current revenue is capped at its prior revenue.
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Always ≤ NRR and ≤ 1.

## Active customers (`active_customers`)

- **Decision it supports:** Size of the paying base; denominator for churn.
- **Formula:** Customers with usage revenue in the month.
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Equals opening + new + reactivated − churned (assert_mrr_bridge_balances).

## New customers (`new_customers`)

- **Decision it supports:** Acquisition pace.
- **Formula:** Customers with revenue this month and none in any earlier month.
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None.

## Churned customers (`churned_customers`)

- **Decision it supports:** Retention problems by count; read with the churn reasons.
- **Formula:** Customers with revenue last month and none this month. Mid-month churn shows the month after.
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Measured from revenue; a customer that pauses for a month counts as churned, then reactivated.

## Logo churn rate (`logo_churn_rate`)

- **Decision it supports:** Share of paying customers lost each month; drives retention priorities.
- **Formula:** Churned customers ÷ customers with revenue last month.
- **Unit / grain:** ratio / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Dominated by self-serve; read alongside gross MRR churn.

## Gross MRR churn rate (`gross_mrr_churn_rate`)

- **Decision it supports:** Revenue lost from existing customers each month, before expansion.
- **Formula:** −(contraction MRR + churned MRR) ÷ opening MRR.
- **Unit / grain:** ratio / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Usage noise makes every month show some contraction; trend matters more than level.

## DSO (`dso_days`)

- **Decision it supports:** How fast customers pay; cash planning and collections staffing.
- **Formula:** Ending AR ÷ invoiced sales in the month × days in the month.
- **Unit / grain:** days / month
- **Source model:** `fct_ar_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** AR subledger must equal the GL control account (assert_ar_ties_to_gl). Month-end billing makes it swing.

## Collection effectiveness index (`cei`)

- **Decision it supports:** Collections team performance, independent of sales volume.
- **Formula:** (Beginning AR + sales − ending AR) ÷ (beginning AR + sales − ending current AR).
- **Unit / grain:** ratio / month
- **Source model:** `fct_ar_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** 1.0 means everything collectible was collected.

## AR over 60 days (`ar_over_60`)

- **Decision it supports:** Bad-debt risk and write-off candidates.
- **Formula:** Open invoice balances more than 60 days past due at month end.
- **Unit / grain:** usd / month
- **Source model:** `fct_ar_aging_snapshot`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Includes failed-payment self-serve balances that should be reviewed for write-off.
