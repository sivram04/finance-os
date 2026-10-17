select
    l.pay_run_id,
    r.pay_date,
    date_trunc('month', r.period_start)::date as pay_month,
    l.employee_id,
    l.department_id,
    cast(l.gross_pay as decimal(18, 2)) as gross_pay,
    cast(l.employer_tax as decimal(18, 2)) as employer_tax,
    cast(l.benefits as decimal(18, 2)) as benefits,
    cast(l.gross_pay + l.employer_tax + l.benefits as decimal(18, 2)) as total_cost
from {{ source('payroll', 'pay_lines') }} l
join {{ source('payroll', 'pay_runs') }} r using (pay_run_id)
