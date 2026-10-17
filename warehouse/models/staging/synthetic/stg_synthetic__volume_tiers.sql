select
    tier,
    min_hours_month,
    lead(min_hours_month) over (order by min_hours_month) as max_hours_month_exclusive,
    cast(discount_pct as decimal(5, 4)) as discount_pct
from {{ source('synthetic', 'volume_tiers') }}
