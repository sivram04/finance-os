# Metric catalog

Generated from `warehouse/metrics/kpis.yml` by `finance_os.reports.build_metric_catalog`. Do not edit by hand.

## Revenue (`revenue`)

- **Decision it supports:** Top-line growth tracking and the base for every margin.
- **Formula:** Sum of GL revenue recognized in the month (usage 4000 + project services 4100).
- **Numerator / denominator:** GL revenue accounts 4000 + 4010 + 4100 / n/a
- **Includes / excludes:** Usage, refunds and credits, project services / Intercompany service revenue (4900, eliminated)
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Usage must equal rated usage (recon_gl_revenue); services must equal project invoices (recon_project_billing_gl).

## Cost of revenue (`cogs`)

- **Decision it supports:** Gross margin and cost-to-serve trend.
- **Formula:** Sum of GL COGS accounts (5000 GPU, 5010 cloud hosting, 5100 payment processing, 5200/5210 project subcontractors and direct costs).
- **Numerator / denominator:** GL COGS accounts 5000-5210 / n/a
- **Includes / excludes:** GPU, cloud hosting, payment processing, project subcontractors and direct costs / Depreciation (opex)
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Vendor invoices reconcile to modeled cost within 1% (recon_vendor_invoices).

## Operating expenses (`opex`)

- **Decision it supports:** Spending pace by department; input to BvA (M5).
- **Formula:** Sum of GL operating expense accounts (6000–6500).
- **Numerator / denominator:** GL opex accounts 6000-6600 / n/a
- **Includes / excludes:** Payroll, cloud R&D, software, rent, professional fees, marketing, depreciation / Intercompany service fees (6900, eliminated)
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Payroll accounts equal the payroll register exactly (recon_payroll_gl).

## Gross margin % (`gross_margin_pct`)

- **Decision it supports:** Pricing and product mix decisions.
- **Formula:** (Revenue − COGS) ÷ Revenue, from the GL.
- **Numerator / denominator:** revenue - cogs / revenue
- **Includes / excludes:** As revenue and cogs / Depreciation
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** GL-based; differs from fct_unit_economics_monthly, which allocates modeled cost and excludes payment fees.

## Gross burn (`gross_burn`)

- **Decision it supports:** Spending pace in cash terms.
- **Formula:** Operating cash out (GL cash account 1000, excluding financing).
- **Numerator / denominator:** Cash paid out in the month (credits to account 1000) / n/a
- **Includes / excludes:** Operating and capital payments / Intercompany settlements (net to zero across entities)
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Closing cash must never be negative.

## Net burn (`net_burn`)

- **Decision it supports:** How fast the company consumes cash; drives runway.
- **Formula:** Operating cash out − operating cash in. Positive = burning.
- **Numerator / denominator:** Cash out - cash in, excluding equity raised / n/a
- **Includes / excludes:** Operations and capex / Funding rounds
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None beyond GL balance.

## Cash balance (`closing_cash`)

- **Decision it supports:** Liquidity and fundraising timing.
- **Formula:** Cumulative net change in GL cash (account 1000) to month end.
- **Numerator / denominator:** Balance of account 1000 at month end, all entities / n/a
- **Includes / excludes:** Operating bank, money market, T-bills (one GL account) / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Will reconcile to Stripe payouts and bank statements in M12.

## Runway (`runway_months`)

- **Decision it supports:** Fundraising timing.
- **Formula:** Closing cash ÷ average net burn over the trailing 3 months. Blank when not burning or under 3 months of history.
- **Numerator / denominator:** closing_cash / average net burn, trailing 3 months
- **Includes / excludes:** As net burn / Planned raises (see the scenario engine for runway with financing)
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** months / month
- **Source model:** `fct_cash_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Assumes the trailing burn rate continues; not a forecast.

## Run-rate ARR (`arr`)

- **Decision it supports:** Growth tracking on an annualized basis.
- **Formula:** Recognized usage revenue in the month x 12. A run rate, not contracted ARR (see contracted_arr) and not GAAP revenue.
- **Numerator / denominator:** Recognized usage revenue in the month x 12 / n/a
- **Includes / excludes:** Usage revenue (4000) / Project services, refunds
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 2, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Usage-based ARR moves with seasonality; read with NRR.

## Headcount (`headcount`)

- **Decision it supports:** Hiring plan tracking and per-employee ratios.
- **Formula:** Employees hired on or before month end and not yet terminated.
- **Numerator / denominator:** Employees on payroll at month end, all entities / n/a
- **Includes / excludes:** Full-time employees / Contractors, planned hires
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** count / month
- **Source model:** `fct_headcount_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Employees with pay in the month must reconcile to headcount ± hires and leavers.

## ARR per employee (`arr_per_employee`)

- **Decision it supports:** Efficiency benchmark (FR-4.3 revenue per employee, on an annualized basis).
- **Formula:** ARR ÷ month-end headcount.
- **Numerator / denominator:** arr / headcount
- **Includes / excludes:** As arr and headcount / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_kpi_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None.

## Net revenue retention (`nrr`)

- **Decision it supports:** Expansion health of the existing customer base.
- **Formula:** Trailing-3-month revenue now from customers who had revenue in the same window 12 months earlier ÷ their revenue then.
- **Numerator / denominator:** Revenue this month from customers active 12 months ago / Their revenue 12 months ago
- **Includes / excludes:** Expansion, contraction, churn / New customers
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Starts once 12 months plus a 3-month window of history exist.

## Gross revenue retention (`grr`)

- **Decision it supports:** Churn and contraction, with expansion removed.
- **Formula:** Same cohort as NRR, but each customer's current revenue is capped at its prior revenue.
- **Numerator / denominator:** Revenue this month from customers active 12 months ago, each capped at its revenue then / Their revenue 12 months ago
- **Includes / excludes:** Contraction and churn / Expansion, new customers
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_gl_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Always ≤ NRR and ≤ 1.

## Active customers (`active_customers`)

- **Decision it supports:** Size of the paying base; denominator for churn.
- **Formula:** Customers with usage revenue in the month.
- **Numerator / denominator:** Customers with revenue in the month / n/a
- **Includes / excludes:** All segments / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Equals opening + new + reactivated − churned (assert_mrr_bridge_balances).

## New customers (`new_customers`)

- **Decision it supports:** Acquisition pace.
- **Formula:** Customers with revenue this month and none in any earlier month.
- **Numerator / denominator:** Customers whose first revenue month is this month / n/a
- **Includes / excludes:** All segments / Reactivations
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** None.

## Churned customers (`churned_customers`)

- **Decision it supports:** Retention problems by count; read with the churn reasons.
- **Formula:** Customers with revenue last month and none this month. Mid-month churn shows the month after.
- **Numerator / denominator:** Customers with revenue last month and none this month / n/a
- **Includes / excludes:** All segments / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** count / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Measured from revenue; a customer that pauses for a month counts as churned, then reactivated.

## Logo churn rate (`logo_churn_rate`)

- **Decision it supports:** Share of paying customers lost each month; drives retention priorities.
- **Formula:** Churned customers ÷ customers with revenue last month.
- **Numerator / denominator:** churned_customers / active customers last month
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Dominated by self-serve; read alongside gross MRR churn.

## Gross MRR churn rate (`gross_mrr_churn_rate`)

- **Decision it supports:** Revenue lost from existing customers each month, before expansion.
- **Formula:** −(contraction MRR + churned MRR) ÷ opening MRR.
- **Numerator / denominator:** Revenue lost from churned customers / Opening MRR
- **Includes / excludes:** As the formula / Contraction
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_mrr_bridge_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Usage noise makes every month show some contraction; trend matters more than level.

## DSO (`dso_days`)

- **Decision it supports:** How fast customers pay; cash planning and collections staffing.
- **Formula:** Ending AR ÷ invoiced sales in the month × days in the month.
- **Numerator / denominator:** Ending AR / Invoiced sales in the month x days in the month
- **Includes / excludes:** Usage and project invoices / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** days / month
- **Source model:** `fct_ar_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** AR subledger must equal the GL control account (assert_ar_ties_to_gl). Month-end billing makes it swing.

## Collection effectiveness index (`cei`)

- **Decision it supports:** Collections team performance, independent of sales volume.
- **Formula:** (Beginning AR + sales − ending AR) ÷ (beginning AR + sales − ending current AR).
- **Numerator / denominator:** Beginning AR + sales - ending AR / Beginning AR + sales - ending current AR
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_ar_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** 1.0 means everything collectible was collected.

## AR over 60 days (`ar_over_60`)

- **Decision it supports:** Bad-debt risk and write-off candidates.
- **Formula:** Open invoice balances more than 60 days past due at month end.
- **Numerator / denominator:** Open invoice balances more than 60 days past due / n/a
- **Includes / excludes:** As the formula / Disputed invoices are included and flagged
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2025-01-01. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_ar_aging_snapshot`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Includes failed-payment self-serve balances that should be reviewed for write-off.

## Net new run-rate ARR (`net_new_arr`)

- **Decision it supports:** Growth quality: where ARR came from and went.
- **Formula:** (new + expansion + reactivation + contraction + churn) MRR x 12
- **Numerator / denominator:** (new + expansion + reactivation + contraction + churn) MRR x 12 / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_growth_efficiency_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## SaaS quick ratio (`quick_ratio`)

- **Decision it supports:** Is growth efficient: ARR added per ARR lost.
- **Formula:** (new + expansion + reactivation) / |contraction + churn|, trailing 3 months
- **Numerator / denominator:** (new + expansion + reactivation) / |contraction + churn|, trailing 3 months / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_growth_efficiency_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Burn multiple (`burn_multiple`)

- **Decision it supports:** Capital efficiency: cash burned per dollar of net new ARR.
- **Formula:** net burn / net new ARR, trailing 3 months; null when net new ARR is not positive
- **Numerator / denominator:** net burn / net new ARR, trailing 3 months; null when net new ARR is not positive / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_growth_efficiency_monthly`
- **Owner:** CFO
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Rule of 40 (`rule_of_40`)

- **Decision it supports:** Balance of growth and profitability.
- **Formula:** revenue growth year on year + EBITDA margin
- **Numerator / denominator:** revenue growth year on year + EBITDA margin / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_saas_metrics_monthly`
- **Owner:** CFO
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## CAC (S&M only) (`cac`)

- **Decision it supports:** Cost to acquire a customer.
- **Formula:** Sales department opex / new customers, trailing 3 months
- **Numerator / denominator:** Sales department opex / new customers, trailing 3 months / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_saas_metrics_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## CAC (fully burdened) (`cac_burdened`)

- **Decision it supports:** Unit economics without hidden overhead.
- **Formula:** (Sales opex + Sales' headcount share of G&A) / new customers, trailing 3 months
- **Numerator / denominator:** (Sales opex + Sales' headcount share of G&A) / new customers, trailing 3 months / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_saas_metrics_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## LTV : CAC (fully burdened) (`ltv_to_cac_burdened`)

- **Decision it supports:** Is acquisition creating value.
- **Formula:** ARPA x gross margin / monthly logo churn, over burdened CAC
- **Numerator / denominator:** ARPA x gross margin / monthly logo churn, over burdened CAC / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_saas_metrics_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## CAC payback (fully burdened) (`cac_payback_burdened_months`)

- **Decision it supports:** How long to earn back acquisition cost.
- **Formula:** burdened CAC / (ARPA x gross margin)
- **Numerator / denominator:** burdened CAC / (ARPA x gross margin) / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** months / month
- **Source model:** `fct_saas_metrics_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Magic number (`magic_number`)

- **Decision it supports:** Sales efficiency: new revenue per S&M dollar.
- **Formula:** (revenue this quarter - revenue last quarter) x 4 / S&M spend last quarter
- **Numerator / denominator:** (revenue this quarter - revenue last quarter) x 4 / S&M spend last quarter / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** ratio / month
- **Source model:** `fct_efficiency_quarterly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Contracted ARR (`contracted_arr`)

- **Decision it supports:** Revenue under contract, not run rate.
- **Formula:** Annualized committed minimums of active contracts
- **Numerator / denominator:** Annualized committed minimums of active contracts / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_contract_revenue_monthly`
- **Owner:** VP Finance
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Remaining performance obligations (`rpo`)

- **Decision it supports:** Contracted revenue not yet recognized (ASC 606).
- **Formula:** Committed minimums remaining on active contracts + prepaid credits not yet used
- **Numerator / denominator:** Committed minimums remaining on active contracts + prepaid credits not yet used / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_contract_revenue_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.

## Current RPO (`crpo`)

- **Decision it supports:** What we will recognize in the next 12 months from contracts.
- **Formula:** The portion of RPO expected within 12 months
- **Numerator / denominator:** The portion of RPO expected within 12 months / see formula
- **Includes / excludes:** As the formula / None
- **Currency:** USD as booked. Foreign-currency invoices are converted at the invoice date's rate; currency moves on collection go to realized FX, not this metric.
- **Period:** Closed months only; a month closes when it is billed on the 1st of the next month. Refresh: Daily (morning run); final at month close
- **Version:** 1, effective 2026-10-19. Restatement: Closed months are not restated; corrections post in the open month and are disclosed in the board pack
- **Unit / grain:** usd / month
- **Source model:** `fct_contract_revenue_monthly`
- **Owner:** Controller
- **Status:** MEASURED
- **Tolerance / caveats:** Recomputed from governed marts; parity-tested on two engines.
