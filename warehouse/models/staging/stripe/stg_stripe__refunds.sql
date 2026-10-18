select
    id as refund_id,
    {{ json_str('data', 'charge') }} as charge_id,
    {{ json_str('data', 'reason') }} as reason,
    {{ json_str('data', 'status') }} as status,
    {{ unix_ts(json_int('data', 'created')) }} as created_at,
    {{ cents_to_usd(json_int('data', 'amount')) }} as amount
from {{ source('stripe', 'refunds') }}
