-- Daily untagged spend vs. its trailing 28-day median. A spike is > 3× the median and > $100 above it.
with daily as (
    select spend_date, sum(case when is_tagged then 0 else cost end) as untagged_cost
    from {{ ref('fct_tech_spend_daily') }}
    group by spend_date
),

with_baseline as (
    select
        spend_date,
        untagged_cost,
        median(untagged_cost) over (order by spend_date rows between 28 preceding and 1 preceding) as trailing_median_28d
    from daily
)

select
    spend_date,
    cast(untagged_cost as decimal(18, 2)) as untagged_cost,
    cast(trailing_median_28d as decimal(18, 2)) as trailing_median_28d,
    coalesce(untagged_cost > 3 * trailing_median_28d and untagged_cost - trailing_median_28d > 100, false) as is_spike
from with_baseline
