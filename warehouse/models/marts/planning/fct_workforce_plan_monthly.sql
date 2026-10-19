-- Risk-adjusted workforce plan by department x month for the 18 months after the last payroll month, next to the
-- base headcount plan. The plan assumes every role starts on time and nobody leaves; this adjusts for:
--   hiring probability   approved / open roles are filled with the probability in seeds/hire_probability.csv
--   start-date slippage  expected start = planned start + the status's usual slip (rounded to months)
--   attrition            the higher of measured attrition (leavers in the last 12 months / heads) and the
--                        department benchmark (seeds/workforce_policy.csv); leavers are backfilled after a lag, so
--                        heads dip by attrition x lag and backfills keep coming at the attrition rate
--   comp reviews         merit increase on current staff from each year's review month
--   recruiting and equipment   one-off cost per hire (planned or backfill): fee % of salary and a laptop/setup kit
with last_month as (
    select max(pay_month) as m from {{ ref('stg_payroll__pay_lines') }}
),

horizon as (
    select h.n, {{ add_months("l.m", "h.n") }} as month
    from last_month l cross join {{ int_series('h', 1, 18) }}
),

staff as (
    select e.department_id, count(*) as heads, avg(e.annual_salary) as avg_salary,
           sum({{ fdiv("e.annual_salary", 12) }} * (1 + p.employer_tax_pct) + p.benefits_per_month) as monthly_cost
    from {{ ref('stg_payroll__employees') }} e
    cross join last_month l
    cross join {{ ref('labor_cost_policy') }} p
    where e.hire_date <= last_day(l.m) and (e.termination_date is null or e.termination_date > last_day(l.m))
    group by e.department_id
),

leavers as (
    select e.department_id, count(*) as leavers_12m
    from {{ ref('stg_payroll__employees') }} e cross join last_month l
    where e.termination_date > {{ add_months("l.m", -11) }} and e.termination_date <= last_day(l.m)
    group by e.department_id
),

dept as (
    select s.*, w.backfill_lag_months, w.recruiting_fee_pct, w.equipment_per_hire, w.merit_pct, w.comp_review_month,
           {{ fdiv("coalesce(x.leavers_12m, 0)", "s.heads + coalesce(x.leavers_12m, 0)") }} as measured_attrition,
           greatest({{ fdiv("coalesce(x.leavers_12m, 0)", "s.heads + coalesce(x.leavers_12m, 0)") }}, w.attrition_benchmark) as attrition
    from staff s
    join {{ ref('workforce_policy') }} w using (department_id)
    left join leavers x using (department_id)
),

grid as (
    select d.*, h.n, h.month,
           -- comp reviews passed by this month (the review month of each year after the last payroll month)
           cast(floor((h.n - 1 + 12 - ((d.comp_review_month - extract(month from l.m) - 1 + 12) - 12 * floor((d.comp_review_month - extract(month from l.m) - 1 + 12) / 12))) / 12) as bigint) as reviews
    from dept d cross join horizon h cross join last_month l
),

roles as (
    select r.department_id, r.role_id, r.annual_salary, r.monthly_loaded_cost, p.probability,
           {{ add_months("r.start_month", "cast(round(p.slip_months) as int)") }} as expected_start
    from {{ ref('int_planned_hires') }} r
    join {{ ref('hire_probability') }} p using (status)
    where r.scenario = 'base'
),

planned as (
    select g.department_id, g.month,
           coalesce(sum(case when r.expected_start <= g.month then r.probability end), 0) as expected_new_heads,
           coalesce(sum(case when r.expected_start <= g.month then r.probability * r.monthly_loaded_cost end), 0) as expected_new_cost,
           coalesce(sum(case when r.expected_start = g.month then r.probability * r.annual_salary * g.recruiting_fee_pct end), 0) as planned_recruiting,
           coalesce(sum(case when r.expected_start = g.month then r.probability * g.equipment_per_hire end), 0) as planned_equipment
    from grid g left join roles r on r.department_id = g.department_id
    group by g.department_id, g.month
),

plan as (
    select department_id, month, headcount as plan_headcount, payroll_cost as plan_payroll
    from {{ ref('fct_headcount_plan_monthly') }} where scenario = 'base'
),

calc as (
    select g.month, g.department_id, g.attrition, g.measured_attrition,
           g.heads - g.heads * {{ fdiv("g.attrition", 12) }} * least(g.n, g.backfill_lag_months) as expected_current_heads,
           g.monthly_cost * (1 - {{ fdiv("g.attrition", 12) }} * least(g.n, g.backfill_lag_months)) * power(1 + g.merit_pct, g.reviews) as current_cost,
           g.monthly_cost * (power(1 + g.merit_pct, g.reviews) - 1) as merit_uplift,
           case when g.n > g.backfill_lag_months then g.heads * {{ fdiv("g.attrition", 12) }} else 0 end as backfills,
           case when g.n > g.backfill_lag_months then g.heads * {{ fdiv("g.attrition", 12) }} * g.avg_salary * g.recruiting_fee_pct else 0 end
               + p.planned_recruiting as recruiting_cost,
           case when g.n > g.backfill_lag_months then g.heads * {{ fdiv("g.attrition", 12) }} * g.equipment_per_hire else 0 end
               + p.planned_equipment as equipment_cost,
           p.expected_new_heads, p.expected_new_cost
    from grid g join planned p using (department_id, month)
)

select
    c.month,
    c.department_id,
    {{ dec("round(" ~ dec("c.attrition", 28, 9) ~ ", 4)", 9, 4) }} as attrition_rate,
    {{ dec("round(" ~ dec("c.measured_attrition", 28, 9) ~ ", 4)", 9, 4) }} as measured_attrition,
    cast(p.plan_headcount as bigint) as plan_headcount,
    {{ dec("round(" ~ dec("c.expected_current_heads + c.expected_new_heads", 28, 9) ~ ", 1)", 9, 1) }} as expected_headcount,
    {{ dec("round(" ~ dec("c.backfills", 28, 9) ~ ", 2)", 9, 2) }} as backfill_hires,
    {{ dec("p.plan_payroll", 18, 2) }} as plan_payroll,
    {{ dec("round(" ~ dec("c.current_cost + c.expected_new_cost", 28, 9) ~ ", 2)", 18, 2) }} as expected_payroll,
    {{ dec("round(" ~ dec("c.merit_uplift", 28, 9) ~ ", 2)", 18, 2) }} as merit_uplift,
    {{ dec("round(" ~ dec("c.recruiting_cost", 28, 9) ~ ", 2)", 18, 2) }} as recruiting_cost,
    {{ dec("round(" ~ dec("c.equipment_cost", 28, 9) ~ ", 2)", 18, 2) }} as equipment_cost,
    {{ dec("round(" ~ dec("c.current_cost + c.expected_new_cost + c.recruiting_cost + c.equipment_cost", 28, 9) ~ ", 2)", 18, 2) }} as expected_people_cost,
    {{ dec("round(" ~ dec("c.current_cost + c.expected_new_cost + c.recruiting_cost + c.equipment_cost - p.plan_payroll", 28, 9) ~ ", 2)", 18, 2) }} as variance_to_plan
from calc c
join plan p using (department_id, month)
