select
    month,
    pool,
    cast(amount as decimal(18, 2)) as amount
from {{ source('erp', 'opex_pools_monthly') }}
