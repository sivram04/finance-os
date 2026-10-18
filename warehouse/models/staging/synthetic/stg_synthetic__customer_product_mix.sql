select
    customer_id,
    product_id,
    {{ dec("share", 5, 4) }} as share
from {{ source('synthetic', 'customer_product_mix') }}
