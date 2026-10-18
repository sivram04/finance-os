select
    bill_id,
    vendor_id,
    service_month,
    bill_date,
    {{ dec("total_amount", 18, 2) }} as total_amount,
    vendor_invoice_number
from {{ source('erp', 'vendor_bills') }}
