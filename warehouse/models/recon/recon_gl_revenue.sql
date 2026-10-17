-- GL usage revenue (account 4000) ↔ usage rated from metered hours, by month. Exact match expected.
-- Becomes Stripe ↔ GL (FR-12.1) once Stripe invoices replace rated usage.
with gl as (
    select month, sum(natural_amount) as amount
    from {{ ref('fct_gl_monthly') }}
    where account_id = '4000'
    group by month
),

rated as (
    select month, sum(revenue) as amount
    from {{ ref('int_usage_rated_monthly') }}
    group by month
)

select
    'gl_revenue_vs_rated_usage' as check_name,
    coalesce(r.month, g.month) as period,
    'all' as entity_id,
    r.amount as expected,
    g.amount as actual,
    g.amount - r.amount as variance,
    cast(round((g.amount - r.amount) / nullif(r.amount, 0), 4) as decimal(9, 4)) as variance_pct,
    cast(0 as decimal(9, 4)) as tolerance_pct,
    case when g.amount is not distinct from r.amount then 'pass' else 'fail' end as status,
    case when g.amount is not distinct from r.amount then 'Exact match'
         else 'GL revenue differs from rated usage: investigate' end as explanation
from rated r
full outer join gl g using (month)
