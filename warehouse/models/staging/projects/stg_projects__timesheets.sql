select
    timesheet_id,
    employee_id,
    project_id,
    week_ending,
    date_trunc('month', week_ending)::date as work_month,
    labor_category,
    hours,
    approved
from {{ source('projects', 'timesheets') }}
