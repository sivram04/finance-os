select
    usage_date || '|' || customer_id || '|' || product_id as usage_id,
    usage_date,
    date_trunc('month', usage_date)::date as usage_month,
    customer_id,
    product_id,
    cast(audio_hours as decimal(18, 4)) as audio_hours
from {{ source('synthetic', 'usage_daily') }}
