-- Usage rated at list price with the customer's monthly volume tier.
-- Tier is chosen on the customer's total hours across products and applied to all units (all-units tiering).
-- Stand-in for billed revenue until Stripe invoices land (FR-7.5 reconciles the two).
with usage as (
    select
        usage_month as month,
        customer_id,
        product_id,
        sum(audio_hours) as audio_hours,
        sum(requests) as requests
    from {{ ref('stg_synthetic__usage_daily') }}
    group by all
),

customer_month as (
    select month, customer_id, sum(audio_hours) as customer_hours
    from usage
    group by all
),

tiered as (
    select cm.month, cm.customer_id, cm.customer_hours, t.tier, t.discount_pct
    from customer_month cm
    join {{ ref('stg_synthetic__volume_tiers') }} t
        on cm.customer_hours >= t.min_hours_month
        and (t.max_hours_month_exclusive is null or cm.customer_hours < t.max_hours_month_exclusive)
)

select
    u.month,
    u.customer_id,
    u.product_id,
    u.audio_hours,
    u.requests,
    p.list_price_per_hour,
    t.tier,
    t.discount_pct,
    cast(round(u.audio_hours * p.list_price_per_hour, 2) as decimal(18, 2)) as list_revenue,
    cast(round(u.audio_hours * p.list_price_per_hour * (1 - t.discount_pct), 2) as decimal(18, 2)) as revenue
from usage u
join {{ ref('stg_synthetic__products') }} p using (product_id)
join tiered t using (month, customer_id)
