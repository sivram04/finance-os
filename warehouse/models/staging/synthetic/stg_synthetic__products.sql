select
    product_id,
    model,
    workload,
    cast(list_price_per_hour as decimal(18, 4)) as list_price_per_hour
from {{ source('synthetic', 'products') }}
