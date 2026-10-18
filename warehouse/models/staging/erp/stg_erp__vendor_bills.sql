select
    bill_id,
    vendor_id,
    service_month,
    bill_date,
    cast(total_amount as decimal(18, 2)) as total_amount,
    vendor_invoice_number
from {{ source('erp', 'vendor_bills') }}
