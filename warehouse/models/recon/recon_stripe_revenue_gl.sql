-- FR-12.1: Stripe usage invoices ↔ GL usage revenue (account 4000), by service month. Exact match expected:
-- every finalized invoice (paid, open or uncollectible) is revenue in the month it bills.
with stripe as (
    select service_month as month, sum(total) as amount
    from {{ ref('stg_stripe__invoices') }}
    group by 1
),

gl as (
    select month, sum(natural_amount) as amount
    from {{ ref('fct_gl_monthly') }}
    where account_id = '4000'
    group by 1
)

select
    'stripe_invoices_vs_gl_revenue' as check_name,
    coalesce(s.month, g.month) as period,
    'all' as entity_id,
    s.amount as expected,
    g.amount as actual,
    coalesce(g.amount, 0) - coalesce(s.amount, 0) as variance,
    cast(null as decimal(9, 4)) as variance_pct,
    cast(0 as decimal(9, 4)) as tolerance_pct,
    case when g.amount is not distinct from s.amount then 'pass' else 'fail' end as status,
    case when g.amount is not distinct from s.amount then 'Exact match'
         else 'GL usage revenue differs from Stripe invoices: investigate' end as explanation
from stripe s
full outer join gl g using (month)
