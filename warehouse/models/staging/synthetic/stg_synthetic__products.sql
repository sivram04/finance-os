select
    product_id,
    model,
    workload,
    {{ dec("list_price_per_hour", 18, 4) }} as list_price_per_hour
from {{ source('synthetic', 'products') }}
