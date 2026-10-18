-- Grain: department × month. Headcount at month end, with hires and leavers in the month.
with months as (
    select distinct pay_month as month, last_day(pay_month) as month_end
    from {{ ref('stg_payroll__pay_lines') }}
)

select
    m.month,
    e.department_id,
    count(case when e.hire_date <= m.month_end
                       and (e.termination_date is null or e.termination_date > m.month_end) then 1 end) as headcount,
    count(case when {{ month_start("e.hire_date") }} = m.month then 1 end) as hires,
    count(case when {{ month_start("e.termination_date") }} = m.month then 1 end) as leavers
from months m
cross join {{ ref('stg_payroll__employees') }} e
group by all
