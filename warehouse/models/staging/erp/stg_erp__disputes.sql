select
    dispute_id,
    customer_id,
    invoice_ref,
    project_id,
    opened_date,
    {{ dec("amount", 18, 2) }} as amount,
    status,
    root_cause,
    resolved_date,
    note
from {{ source('erp', 'disputes') }}
