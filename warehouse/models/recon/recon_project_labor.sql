-- FR-12.5 / design §8 M6 check: timesheet cost of hours ↔ payroll cost, per employee × month.
-- An employee can't charge projects more loaded cost than payroll paid them that month (hours are capped by
-- their pay). Fails when project labor cost exceeds payroll total cost by more than $1.
with project_labor as (
    select employee_id, work_month as month, sum(labor_cost) as amount
    from {{ ref('int_project_labor') }}
    group by all
),

payroll as (
    select employee_id, pay_month as month, sum(total_cost) as amount
    from {{ ref('stg_payroll__pay_lines') }}
    group by all
)

select
    'project_labor_within_payroll' as check_name,
    l.month as period,
    l.employee_id as entity_id,
    p.amount as expected,
    l.amount as actual,
    l.amount - coalesce(p.amount, 0) as variance,
    {{ dec("round(l.amount / nullif(p.amount, 0), 4)", 9, 4) }} as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when p.amount is not null and l.amount <= p.amount + 1 then 'pass' else 'fail' end as status,
    case when p.amount is null then 'Project hours for an employee with no pay that month'
         when l.amount <= p.amount + 1 then 'Within payroll cost (' || round(100 * l.amount / p.amount) || '% charged to projects)'
         else 'Project labor exceeds payroll cost: check rates or hours' end as explanation
from project_labor l
left join payroll p using (employee_id, month)
