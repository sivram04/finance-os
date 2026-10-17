select
    bill_id,
    line_type,
    gpu_type,
    cast(quantity_hours as decimal(18, 4)) as quantity_hours,
    cast(amount as decimal(18, 2)) as amount
from {{ source('erp', 'vendor_bill_lines') }}
