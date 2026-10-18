select
    bill_id,
    project_id,
    vendor_id,
    po_id,
    bill_date,
    date_trunc('month', bill_date)::date as bill_month,
    amount,
    description,
    vendor_invoice_number
from {{ source('projects', 'subcontractor_bills') }}
