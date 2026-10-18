select
    expense_id,
    project_id,
    expense_date,
    date_trunc('month', expense_date)::date as expense_month,
    amount,
    description
from {{ source('projects', 'odc_expenses') }}
