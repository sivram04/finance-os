select
    bill_id,
    line_type,
    gpu_type,
    {{ dec("quantity_hours", 18, 4) }} as quantity_hours,
    {{ dec("amount", 18, 2) }} as amount
from {{ source('erp', 'vendor_bill_lines') }}
