select
    employee_id,
    employee_name,
    department_id,
    function,
    title,
    hire_date,
    termination_date,
    cast(annual_salary as decimal(18, 2)) as annual_salary
from {{ source('payroll', 'employees') }}
