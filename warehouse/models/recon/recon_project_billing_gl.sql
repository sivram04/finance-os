-- Project invoices ↔ GL services revenue (account 4100), by month. Exact match expected.
with billing as (
    select invoice_month as month, sum(amount) as amount
    from {{ ref('stg_projects__project_invoices') }}
    group by 1
),

gl as (
    select month, sum(natural_amount) as amount
    from {{ ref('fct_gl_monthly') }}
    where account_id = '4100'
    group by month
)

select
    'project_billing_vs_gl' as check_name,
    coalesce(b.month, g.month) as period,
    'all' as entity_id,
    b.amount as expected,
    g.amount as actual,
    g.amount - b.amount as variance,
    {{ dec("round((g.amount - b.amount) / nullif(b.amount, 0), 4)", 9, 4) }} as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when g.amount is not distinct from b.amount then 'pass' else 'fail' end as status,
    case when g.amount is not distinct from b.amount then 'Exact match'
         else 'Services revenue in the GL differs from project invoices: investigate' end as explanation
from billing b
full outer join gl g using (month)
