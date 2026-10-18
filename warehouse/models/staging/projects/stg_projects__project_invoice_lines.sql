select
    invoice_id,
    line_no,
    line_type,
    clin_id,
    labor_category,
    milestone_id,
    hours,
    rate,
    amount
from {{ source('projects', 'project_invoice_lines') }}
