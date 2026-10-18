-- Cash position across accounts today: GL cash split by the treasury policy's target mix
-- (seeds/treasury_accounts.csv), monthly interest at each account's yield, and how many weeks of
-- forecast outflows the operating account covers (policy MIN-OPERATING).
with cash as (
    select sum(amount) as total from {{ ref('stg_erp__journal_lines') }} where account_id = '1000'
),

weekly_out as (
    select -avg(payroll + vendors + other_opex) as avg_weekly_outflow from {{ ref('fct_cash_forecast_13w') }}
)

select
    a.account_id,
    a.bank,
    a.account_type,
    cast(a.target_share as decimal(9, 4)) as target_share,
    cast(c.total * a.target_share as decimal(18, 2)) as balance,
    cast(a.annual_yield as decimal(9, 4)) as annual_yield,
    cast(c.total * a.target_share * a.annual_yield / 12 as decimal(18, 2)) as monthly_interest,
    case when a.account_type = 'operating'
         then cast(round(c.total * a.target_share / nullif(w.avg_weekly_outflow, 0), 1) as decimal(9, 1)) end as weeks_of_outflows,
    case when a.account_type = 'operating'
         then c.total * a.target_share / nullif(w.avg_weekly_outflow, 0) < p.threshold end as is_below_policy
from {{ ref('treasury_accounts') }} a
cross join cash c
cross join weekly_out w
cross join (select threshold from {{ ref('treasury_policy') }} where rule_id = 'MIN-OPERATING') p
