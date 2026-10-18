-- One row per scenario from the latest forecast: next-12-month P&L, ending cash, runway and the month cash
-- would run out (null if it never does within the horizon).
with f as (
    select * from {{ ref('fct_forecast_monthly') }} where is_latest
),

burn as (
    select scenario, avg(case when months_ahead <= 3 then -ebitda end) as avg_burn_next_3m
    from f group by scenario
)

select
    f.scenario,
    min(f.as_of_month) as as_of_month,
    {{ dec("sum(case when f.months_ahead <= 12 then f.revenue end)", 18, 2) }} as revenue_next_12m,
    {{ dec("round(sum(case when f.months_ahead <= 12 then f.gross_margin end)
               / nullif(sum(case when f.months_ahead <= 12 then f.revenue end), 0), 4)", 9, 4) }} as gross_margin_pct_next_12m,
    {{ dec("sum(case when f.months_ahead <= 12 then f.opex end)", 18, 2) }} as opex_next_12m,
    {{ dec("sum(case when f.months_ahead <= 12 then f.ebitda end)", 18, 2) }} as ebitda_next_12m,
    {{ dec("max(case when f.months_ahead = 12 then f.closing_cash end)", 18, 2) }} as cash_in_12m,
    min(case when f.closing_cash < 0 then f.month end) as cash_out_month,
    {{ dec("round(min(case when f.months_ahead = 1 then f.closing_cash end) / nullif(max(b.avg_burn_next_3m), 0), 1)", 9, 1) }} as runway_months
from f
join burn b using (scenario)
group by f.scenario
