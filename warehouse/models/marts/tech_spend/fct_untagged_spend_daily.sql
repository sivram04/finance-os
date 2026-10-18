-- Daily untagged spend vs. its trailing 28-day median. A spike is > 3× the median and > $100 above it.
with daily as (
    select spend_date, sum(case when is_tagged then 0 else cost end) as untagged_cost
    from {{ ref('fct_tech_spend_daily') }}
    group by spend_date
),

numbered as (
    select spend_date, untagged_cost, row_number() over (order by spend_date) as rn from daily
),

with_baseline as (
    -- exact median of the 28 preceding days (BigQuery has no median over a sliding window, so: self-join)
    select distinct d.spend_date, d.untagged_cost,
           {{ median_over("p.untagged_cost", "d.spend_date") }} as trailing_median_28d
    from numbered d
    left join numbered p on p.rn between d.rn - 28 and d.rn - 1
)

select
    spend_date,
    {{ dec("untagged_cost", 18, 2) }} as untagged_cost,
    {{ dec("trailing_median_28d", 18, 2) }} as trailing_median_28d,
    coalesce(untagged_cost > 3 * trailing_median_28d and untagged_cost - trailing_median_28d > 100, false) as is_spike
from with_baseline
