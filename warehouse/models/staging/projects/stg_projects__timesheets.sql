select
    timesheet_id,
    employee_id,
    project_id,
    week_ending,
    {{ month_start("week_ending") }} as work_month,
    labor_category,
    hours,
    approved
from {{ source('projects', 'timesheets') }}
