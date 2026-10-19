-- Price / volume / mix bridge of usage revenue, month over month, by product.
--   price   (this month's price per hour − last month's) × this month's hours       (discount tiers, list price)
--   volume  (total hours now − total before) × the product's prior share × prior average price   (more usage)
--   mix     what is left: the shift between products at last month's prices        (stream vs batch)
-- price + volume + mix = revenue change, exactly, for every product and month.
with p as (
    select month, product_id, sum(audio_hours) as hours, sum(revenue) as revenue
    from {{ ref('int_usage_rated_monthly') }}
    where month <= {{ closed_through() }}
    group by 1, 2
),

t as (
    select month, sum(hours) as total_hours, sum(revenue) as total_revenue from p group by 1
),

j as (
    select
        p.month,
        p.product_id,
        p.hours,
        p.revenue,
        coalesce(prev.hours, 0) as hours_prev,
        coalesce(prev.revenue, 0) as revenue_prev,
        t.total_hours,
        tp.total_hours as total_hours_prev,
        {{ fdiv("tp.total_revenue", "nullif(tp.total_hours, 0)") }} as avg_price_prev,
        {{ fdiv("prev.revenue", "nullif(prev.hours, 0)") }} as price_prev,
        {{ fdiv("p.revenue", "nullif(p.hours, 0)") }} as price_now
    from p
    join t on t.month = p.month
    join t tp on tp.month = {{ add_months("p.month", -1) }}
    left join p prev on prev.product_id = p.product_id and prev.month = tp.month
),

e as (
    select
        *,
        coalesce(price_now - price_prev, 0) * hours as price_effect,
        (total_hours - total_hours_prev) * coalesce({{ fdiv("hours_prev", "nullif(total_hours_prev, 0)") }}, 0) * avg_price_prev as volume_effect
    from j
)

select
    month,
    product_id,
    {{ dec("hours", 18, 2) }} as audio_hours,
    {{ dec("hours_prev", 18, 2) }} as audio_hours_prev,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("revenue_prev", 18, 2) }} as revenue_prev,
    {{ dec("revenue - revenue_prev", 18, 2) }} as revenue_change,
    {{ dec("round(price_effect, 2)", 18, 2) }} as price_effect,
    {{ dec("round(volume_effect, 2)", 18, 2) }} as volume_effect,
    {{ dec("revenue - revenue_prev - round(price_effect, 2) - round(volume_effect, 2)", 18, 2) }} as mix_effect
from e
