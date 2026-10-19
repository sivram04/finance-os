-- Employee-level workforce forecast for the 18 months after the last payroll month: every current employee and every
-- open or approved role, with expected (probability-weighted) monthly cost.
--   current employee   stays with probability (1 - attrition / 12)^n (attrition from fct_workforce_plan_monthly's policy:
--                      measured or benchmark, whichever is higher); salary rises at each April review by merit plus
--                      the expected promotion uplift (promotion rate x promotion raise); loaded = salary / 12 x (1 +
--                      employer tax) + benefits
--   equity             employer payroll tax on vesting equity: annual grant (share of salary) vests over four years, taxed
--                      at the employer rate as it vests
--   open role          filled with the req status's probability from its expected (slipped) start month
-- Policy in seeds/workforce_policy.csv and seeds/hire_probability.csv. Backfills for leavers are in the department plan.
with last_month as (
    select max(pay_month) as m from {{ ref('stg_payroll__pay_lines') }}
),

horizon as (
    select h.n, {{ add_months("l.m", "h.n") }} as month
    from last_month l cross join {{ int_series('h', 1, 18) }}
),

attrition as (
    select distinct department_id, attrition_rate from {{ ref('fct_workforce_plan_monthly') }}
),

people as (
    select e.employee_id, e.employee_name, e.department_id, e.title, 'current' as kind, e.annual_salary,
           cast(1 as {{ 'numeric' if target.type == 'bigquery' else 'decimal(9,4)' }}) as fill_probability, cast(null as date) as expected_start
    from {{ ref('stg_payroll__employees') }} e cross join last_month l
    where e.hire_date <= last_day(l.m) and (e.termination_date is null or e.termination_date > last_day(l.m))
    union all
    select r.role_id, r.title || ' (open role)', r.department_id, r.title, 'open_role', r.annual_salary, p.probability,
           {{ add_months("r.start_month", "cast(round(p.slip_months) as int)") }}
    from {{ ref('int_planned_hires') }} r
    join {{ ref('hire_probability') }} p using (status)
    where r.scenario = 'base'
),

grid as (
    select p.*, h.n, h.month, a.attrition_rate, w.merit_pct, w.promotion_rate, w.promotion_uplift_pct, w.equity_grant_pct,
           w.equity_employer_tax_pct, c.employer_tax_pct, c.benefits_per_month,
           cast(floor((h.n - 1 + 12 - ((w.comp_review_month - extract(month from l.m) - 1 + 12) - 12 * floor((w.comp_review_month - extract(month from l.m) - 1 + 12) / 12))) / 12) as bigint) as reviews
    from people p
    cross join horizon h
    cross join last_month l
    cross join {{ ref('labor_cost_policy') }} c
    join {{ ref('workforce_policy') }} w using (department_id)
    join attrition a using (department_id)
),

calc as (
    select g.*,
           case when g.kind = 'current' then power(1 - {{ fdiv("g.attrition_rate", 12) }}, g.n)
                when g.expected_start <= g.month then g.fill_probability else 0 end as probability,
           g.annual_salary * power(1 + g.merit_pct, case when g.kind = 'current' then g.reviews else 0 end) as salary_merit,
           g.annual_salary * power((1 + g.merit_pct) * (1 + g.promotion_rate * g.promotion_uplift_pct), case when g.kind = 'current' then g.reviews else 0 end) as salary
    from grid g
)

select
    month,
    employee_id,
    employee_name,
    department_id,
    title,
    kind,
    {{ dec("round(" ~ dec("probability", 28, 9) ~ ", 4)", 9, 4) }} as probability,
    {{ dec("round(" ~ dec("salary", 28, 9) ~ ", 2)", 18, 2) }} as annual_salary,
    {{ dec("round(" ~ dec("probability * (" ~ fdiv("salary", 12) ~ " * (1 + employer_tax_pct) + benefits_per_month)", 28, 9) ~ ", 2)", 18, 2) }} as expected_loaded_cost,
    {{ dec("round(" ~ dec("probability * " ~ fdiv("salary - salary_merit", 12) ~ " * (1 + employer_tax_pct)", 28, 9) ~ ", 2)", 18, 2) }} as promotion_cost,
    {{ dec("round(" ~ dec("probability * " ~ fdiv("annual_salary * equity_grant_pct * equity_employer_tax_pct", 48) , 28, 9) ~ ", 2)", 18, 2) }} as equity_employer_cost
from calc
