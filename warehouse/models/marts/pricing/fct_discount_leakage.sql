-- Discount leakage by customer × month: list price vs billed, against the segment's discount policy
-- (seeds/discount_policy.csv). Also flags customers sitting just over a volume-tier threshold (within 5%):
-- a small usage dip would end the discount, and a small push got it — the classic tier-cliff leakage.
with rated as (
    select r.month, r.customer_id, c.segment,
           sum(r.audio_hours) as hours, sum(r.list_revenue) as list_revenue, sum(r.revenue) as revenue,
           max(r.discount_pct) as discount_pct
    from {{ ref('int_usage_rated_monthly') }} r
    join {{ ref('stg_synthetic__customers') }} c using (customer_id)
    group by all
),

thresholds as (
    select min_hours_month from {{ ref('stg_synthetic__volume_tiers') }} where min_hours_month > 0
)

select
    r.month,
    r.customer_id,
    r.segment,
    {{ dec("r.hours", 18, 2) }} as audio_hours,
    {{ dec("r.list_revenue", 18, 2) }} as list_revenue,
    {{ dec("r.revenue", 18, 2) }} as billed_revenue,
    {{ dec("r.list_revenue - r.revenue", 18, 2) }} as discount_amount,
    {{ dec("r.discount_pct", 9, 4) }} as discount_pct,
    p.max_discount_pct,
    r.discount_pct > p.max_discount_pct as is_over_policy,
    exists (select 1 from thresholds t where r.hours >= t.min_hours_month and r.hours < t.min_hours_month * 1.05) as is_near_tier_cliff
from rated r
join {{ ref('discount_policy') }} p using (segment)
