select
    project_id,
    contract_id,
    customer_id,
    project_name,
    project_type,
    start_date,
    planned_end_date
from {{ source('projects', 'projects') }}
