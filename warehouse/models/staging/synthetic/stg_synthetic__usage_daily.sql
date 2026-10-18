select
    {{ dbt.concat([dbt.cast('usage_date', api.Column.translate_type('string')), "'|'", 'customer_id', "'|'", 'product_id']) }} as usage_id,
    usage_date,
    cast({{ dbt.date_trunc('month', 'usage_date') }} as date) as usage_month,
    customer_id,
    product_id,
    cast(audio_hours as decimal(18, 4)) as audio_hours,
    requests
from {{ source('synthetic', 'usage_daily') }}
