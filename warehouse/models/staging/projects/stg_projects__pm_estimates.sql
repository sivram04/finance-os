select
    project_id,
    as_of_month,
    etc_amount
from {{ source('projects', 'pm_estimates') }}
