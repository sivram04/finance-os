select
    customer_id,
    product_id,
    cast(share as decimal(5, 4)) as share
from {{ source('synthetic', 'customer_product_mix') }}
