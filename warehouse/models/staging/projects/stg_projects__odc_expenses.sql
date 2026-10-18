select
    expense_id,
    project_id,
    expense_date,
    {{ month_start("expense_date") }} as expense_month,
    amount,
    description
from {{ source('projects', 'odc_expenses') }}
