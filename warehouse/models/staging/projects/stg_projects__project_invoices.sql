select
    invoice_id,
    project_id,
    contract_id,
    customer_id,
    invoice_date,
    date_trunc('month', invoice_date)::date as invoice_month,
    service_month,
    amount
from {{ source('projects', 'project_invoices') }}
