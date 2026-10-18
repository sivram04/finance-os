select
    l.pay_run_id,
    r.pay_date,
    {{ month_start("r.period_start") }} as pay_month,
    l.employee_id,
    l.department_id,
    {{ dec("l.gross_pay", 18, 2) }} as gross_pay,
    {{ dec("l.employer_tax", 18, 2) }} as employer_tax,
    {{ dec("l.benefits", 18, 2) }} as benefits,
    {{ dec("l.gross_pay + l.employer_tax + l.benefits", 18, 2) }} as total_cost
from {{ source('payroll', 'pay_lines') }} l
join {{ source('payroll', 'pay_runs') }} r using (pay_run_id)
