select
    tier,
    min_hours_month,
    lead(min_hours_month) over (order by min_hours_month) as max_hours_month_exclusive,
    {{ dec("discount_pct", 5, 4) }} as discount_pct
from {{ source('synthetic', 'volume_tiers') }}
