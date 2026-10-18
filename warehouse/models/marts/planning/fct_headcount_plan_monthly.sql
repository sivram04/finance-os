-- Headcount plan by scenario × department × month for the 18 months after the last payroll month:
-- current employees (still employed at the last month end) plus planned hires from their start month,
-- with fully loaded payroll cost.
with last_month as (
    select max(pay_month) as m from {{ ref('stg_payroll__pay_lines') }}
),

horizon as (
    select cast(l.m + to_months(cast(h.n as integer)) as date) as month
    from last_month l
    cross join range(1, 19) h(n)
),

current_staff as (
    select e.department_id, count(*) as heads,
           sum(e.annual_salary / 12.0 * (1 + p.employer_tax_pct) + p.benefits_per_month) as monthly_cost
    from {{ ref('stg_payroll__employees') }} e
    cross join last_month l
    cross join {{ ref('labor_cost_policy') }} p
    where e.hire_date <= last_day(l.m) and (e.termination_date is null or e.termination_date > last_day(l.m))
    group by e.department_id
),

scenarios as (
    select distinct scenario from {{ ref('planning_scenarios') }}
),

grid as (
    select s.scenario, h.month, c.department_id, c.heads, c.monthly_cost
    from scenarios s cross join horizon h cross join current_staff c
),

hires as (
    select g.scenario, g.month, g.department_id,
           count(r.role_id) as new_heads,
           count(r.role_id) filter (where r.start_month = g.month) as hires_in_month,
           coalesce(sum(r.monthly_loaded_cost), 0) as new_cost
    from grid g
    left join {{ ref('int_planned_hires') }} r
        on r.scenario = g.scenario and r.department_id = g.department_id and r.start_month <= g.month
    group by all
)

select
    g.scenario,
    g.month,
    g.department_id,
    g.heads as current_headcount,
    h.new_heads as planned_hires_to_date,
    h.hires_in_month,
    g.heads + h.new_heads as headcount,
    cast(g.monthly_cost as decimal(18, 2)) as current_payroll_cost,
    cast(h.new_cost as decimal(18, 2)) as new_hire_payroll_cost,
    cast(g.monthly_cost + h.new_cost as decimal(18, 2)) as payroll_cost
from grid g
join hires h using (scenario, month, department_id)
