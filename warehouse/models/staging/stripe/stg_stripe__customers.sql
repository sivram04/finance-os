select
    id as stripe_customer_id,
    {{ json_str('data', 'metadata.erp_customer_id') }} as customer_id,
    {{ json_str('data', 'metadata.segment') }} as segment,
    {{ json_str('data', 'email') }} as email,
    {{ json_str('data', 'address.country') }} as country,
    {{ json_bool('data', 'delinquent') }} as is_delinquent,
    {{ unix_ts(json_int('data', 'created')) }} as created_at
from {{ source('stripe', 'customers') }}
