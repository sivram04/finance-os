-- One row per scenario from the latest forecast: next-12-month P&L, ending cash, runway and the month cash
-- would run out (null if it never does within the horizon).
with f as (
    select * from {{ ref('fct_forecast_monthly') }} where is_latest
),

burn as (
    select scenario, avg(-ebitda) filter (where months_ahead <= 3) as avg_burn_next_3m
    from f group by scenario
)

select
    f.scenario,
    min(f.as_of_month) as as_of_month,
    cast(sum(f.revenue) filter (where f.months_ahead <= 12) as decimal(18, 2)) as revenue_next_12m,
    cast(round(sum(f.gross_margin) filter (where f.months_ahead <= 12)
               / nullif(sum(f.revenue) filter (where f.months_ahead <= 12), 0), 4) as decimal(9, 4)) as gross_margin_pct_next_12m,
    cast(sum(f.opex) filter (where f.months_ahead <= 12) as decimal(18, 2)) as opex_next_12m,
    cast(sum(f.ebitda) filter (where f.months_ahead <= 12) as decimal(18, 2)) as ebitda_next_12m,
    cast(max(f.closing_cash) filter (where f.months_ahead = 12) as decimal(18, 2)) as cash_in_12m,
    min(f.month) filter (where f.closing_cash < 0) as cash_out_month,
    cast(round(min(f.closing_cash) filter (where f.months_ahead = 1) / nullif(max(b.avg_burn_next_3m), 0), 1) as decimal(9, 1)) as runway_months
from f
join burn b using (scenario)
group by f.scenario
