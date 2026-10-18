select
    payment_id,
    customer_id,
    received_date,
    cast(amount as decimal(18, 2)) as amount,
    remittance_ref,
    applied_ref
from {{ source('erp', 'customer_payments') }}
