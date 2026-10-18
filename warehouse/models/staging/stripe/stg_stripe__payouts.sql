select
    id as payout_id,
    {{ json_str('data', 'status') }} as status,
    {{ unix_ts(json_int('data', 'created')) }} as created_at,
    cast({{ unix_ts(json_int('data', 'arrival_date')) }} as date) as arrival_date,
    {{ cents_to_usd(json_int('data', 'amount')) }} as amount
from {{ source('stripe', 'payouts') }}
