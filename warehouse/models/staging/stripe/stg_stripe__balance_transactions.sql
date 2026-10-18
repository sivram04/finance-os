-- Every movement of the Stripe balance: charges (gross, fee, net), refunds, payouts.
select
    id as balance_transaction_id,
    {{ json_str('data', 'type') }} as type,
    {{ json_str('data', 'reporting_category') }} as reporting_category,
    {{ json_str('data', 'source') }} as source_id,
    {{ json_str('data', 'status') }} as status,
    {{ unix_ts(json_int('data', 'created')) }} as created_at,
    cast({{ unix_ts(json_int('data', 'available_on')) }} as date) as available_on,
    {{ cents_to_usd(json_int('data', 'amount')) }} as amount,
    {{ cents_to_usd(json_int('data', 'fee')) }} as fee,
    {{ cents_to_usd(json_int('data', 'net')) }} as net
from {{ source('stripe', 'balance_transactions') }}
