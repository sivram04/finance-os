-- Covenant and policy tests by month, actuals then the base forecast (seeds/treasury_policy.csv):
--   MIN-CASH   cash ≥ threshold
--   RUNWAY-12  cash ÷ trailing-3-month net burn ≥ threshold months
--   LIQ-1      (cash + AR) ÷ (3 × trailing-3-month opex) ≥ threshold
with actual as (
    select c.month, false as is_forecast, c.closing_cash as cash, c.net_burn,
           w.ar_balance, p.opex
    from {{ ref('fct_cash_monthly') }} c
    join {{ ref('fct_working_capital_monthly') }} w using (month)
    join {{ ref('int_pnl_monthly') }} p using (month)
),

forecast as (
    select f.month, true, f.closing_cash, -f.ebitda, w.ar_balance * (f.revenue / nullif(l.revenue, 0)), f.opex
    from {{ ref('fct_forecast_monthly') }} f
    cross join (select ar_balance from {{ ref('fct_working_capital_monthly') }} order by month desc limit 1) w
    cross join (select revenue from {{ ref('int_pnl_monthly') }} order by month desc limit 1) l
    where f.is_latest and f.scenario = 'base'
),

series as (
    select *,
           avg(net_burn) over (order by month rows between 2 preceding and current row) as burn_t3m,
           avg(opex) over (order by month rows between 2 preceding and current row) as opex_t3m
    from (select * from actual union all select * from forecast)
),

metrics as (
    select month, is_forecast, 'MIN-CASH' as rule_id, cash as value from series
    union all
    select month, is_forecast, 'RUNWAY-12', case when burn_t3m > 0 then cash / burn_t3m end from series
    union all
    select month, is_forecast, 'LIQ-1', (cash + ar_balance) / nullif(3 * opex_t3m, 0) from series
)

select
    m.month,
    m.is_forecast,
    m.rule_id,
    p.description,
    cast(round(m.value, 2) as decimal(18, 2)) as value,
    cast(p.threshold as decimal(18, 2)) as threshold,
    case when m.value is null then 'not_burning'
         when m.value >= p.threshold then 'pass'
         else 'breach' end as status
from metrics m
join {{ ref('treasury_policy') }} p using (rule_id)
