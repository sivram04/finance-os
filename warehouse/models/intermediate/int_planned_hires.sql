-- Open and approved roles per scenario, with fully loaded monthly cost (salary + employer tax + benefits,
-- per seeds/labor_cost_policy.csv). The downside scenario hires only the earliest share of roles
-- (hiring_plan_pct), i.e. a freeze on the later ones.
with roles as (
    select
        h.*,
        date_trunc('month', cast(h.planned_start as date))::date as start_month,
        row_number() over (order by h.planned_start, h.role_id) as start_rank,
        count(*) over () as n_roles
    from {{ ref('hiring_plan') }} h
    where h.status in ('open', 'approved')
),

pct as (
    select scenario, value as hiring_pct
    from {{ ref('planning_scenarios') }}
    where driver = 'hiring_plan_pct'
)

select
    p.scenario,
    r.role_id,
    r.department_id,
    r.title,
    r.status,
    r.start_month,
    cast(r.annual_salary as decimal(18, 2)) as annual_salary,
    cast(r.annual_salary / 12.0 * (1 + l.employer_tax_pct) + l.benefits_per_month as decimal(18, 2)) as monthly_loaded_cost
from roles r
cross join pct p
cross join {{ ref('labor_cost_policy') }} l
where r.start_rank <= round(r.n_roles * p.hiring_pct)
