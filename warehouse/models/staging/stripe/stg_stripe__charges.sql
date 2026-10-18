select
    id as charge_id,
    {{ json_str('data', 'invoice') }} as invoice_id,
    {{ json_str('data', 'status') }} as status,
    {{ json_str('data', 'failure_code') }} as failure_code,
    {{ json_str('data', 'payment_method_details.type') }} as payment_method_type,
    {{ json_str('data', 'balance_transaction') }} as balance_transaction_id,
    {{ unix_ts(json_int('data', 'created')) }} as created_at,
    {{ cents_to_usd(json_int('data', 'amount')) }} as amount,
    {{ cents_to_usd(json_int('data', 'amount_refunded')) }} as amount_refunded
from {{ source('stripe', 'charges') }}
