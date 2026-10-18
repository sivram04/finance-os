select
    employee_id,
    employee_name,
    department_id,
    function,
    title,
    hire_date,
    termination_date,
    {{ dec("annual_salary", 18, 2) }} as annual_salary
from {{ source('payroll', 'employees') }}
