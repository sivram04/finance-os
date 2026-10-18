select
    invoice_id,
    project_id,
    contract_id,
    customer_id,
    invoice_date,
    {{ month_start("invoice_date") }} as invoice_month,
    service_month,
    amount
from {{ source('projects', 'project_invoices') }}
