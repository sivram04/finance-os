select
    project_id,
    cost_type,
    budget_amount
from {{ source('projects', 'project_budgets') }}
