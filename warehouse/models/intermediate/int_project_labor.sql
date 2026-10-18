-- Timesheet hours costed at the employee's loaded hourly rate and valued at the contract bill rate.
-- Loaded rate = (salary × (1 + employer tax) + benefits × 12) ÷ standard hours (seeds/labor_cost_policy.csv).
-- bill_rate is null on fixed-fee contracts (no hourly billing).
with policy as (
    select * from {{ ref('labor_cost_policy') }} where policy_id = 'LOADED-1'
)

select
    t.timesheet_id,
    t.employee_id,
    t.project_id,
    p.contract_id,
    t.week_ending,
    t.work_month,
    t.labor_category,
    t.hours,
    t.approved,
    cast(round((e.annual_salary * (1 + pol.employer_tax_pct) + pol.benefits_per_month * 12) / pol.standard_hours_year, 2)
         as decimal(18, 2)) as cost_rate,
    cast(round(t.hours * round((e.annual_salary * (1 + pol.employer_tax_pct) + pol.benefits_per_month * 12)
                               / pol.standard_hours_year, 2), 2) as decimal(18, 2)) as labor_cost,
    r.bill_rate,
    cast(t.hours * r.bill_rate as decimal(18, 2)) as billable_value
from {{ ref('stg_projects__timesheets') }} t
join {{ ref('stg_payroll__employees') }} e using (employee_id)
join {{ ref('stg_projects__projects') }} p using (project_id)
cross join policy pol
left join {{ ref('stg_projects__contract_rates') }} r
    on r.contract_id = p.contract_id and r.labor_category = t.labor_category
