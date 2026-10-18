-- FR-12.5: payroll register (gross + employer tax + benefits) ↔ GL payroll accounts 6000–6020, by month.
with register as (
    select pay_month as month, sum(total_cost) as amount
    from {{ ref('stg_payroll__pay_lines') }}
    group by pay_month
),

gl as (
    select month, sum(natural_amount) as amount
    from {{ ref('fct_gl_monthly') }}
    where account_id in ('6000', '6010', '6020')
    group by month
)

select
    'payroll_register_vs_gl' as check_name,
    coalesce(r.month, g.month) as period,
    'all' as entity_id,
    r.amount as expected,
    g.amount as actual,
    g.amount - r.amount as variance,
    {{ dec("round((g.amount - r.amount) / nullif(r.amount, 0), 4)", 9, 4) }} as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when g.amount is not distinct from r.amount then 'pass' else 'fail' end as status,
    case when g.amount is not distinct from r.amount then 'Exact match'
         else 'GL payroll differs from the register: investigate' end as explanation
from register r
full outer join gl g using (month)
