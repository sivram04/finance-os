select
    bill_id,
    project_id,
    vendor_id,
    po_id,
    bill_date,
    {{ month_start("bill_date") }} as bill_month,
    amount,
    description,
    vendor_invoice_number
from {{ source('projects', 'subcontractor_bills') }}
