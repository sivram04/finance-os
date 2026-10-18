select
    milestone_id,
    project_id,
    milestone_name,
    amount,
    accepted_date
from {{ source('projects', 'milestones') }}
