-- The line-item payroll register ties out per employee and run: net pay = gross − employee taxes − employee
-- deductions, and the pay_lines summary equals the register (gross, employer taxes, employer benefits).
with reg as (
    select pay_run_id, employee_id,
           sum(case when line_type = 'earning' then amount else 0 end) as gross,
           sum(case when line_type = 'employee_tax' then amount else 0 end) as ee_tax,
           sum(case when line_type = 'employee_deduction' then amount else 0 end) as ee_ded,
           sum(case when line_type = 'employer_tax' then amount else 0 end) as er_tax,
           sum(case when line_type = 'employer_benefit' then amount else 0 end) as er_ben,
           sum(case when line_type = 'net_pay' then amount else 0 end) as net
    from {{ source('payroll', 'pay_register_lines') }}
    group by 1, 2
)

select r.*, p.gross_pay, p.employer_tax, p.benefits
from reg r
left join {{ source('payroll', 'pay_lines') }} p using (pay_run_id, employee_id)
where r.net <> r.gross - r.ee_tax - r.ee_ded
   or p.gross_pay is distinct from r.gross
   or p.employer_tax is distinct from r.er_tax
   or p.benefits is distinct from r.er_ben
