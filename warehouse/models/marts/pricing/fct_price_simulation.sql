-- Price-change simulation per scenario (seeds/price_scenarios.csv) on the last 3 months, annualized:
-- new hours = hours × (1 + elasticity × price change); revenue moves with price and volume; COGS moves with
-- volume at today's cost per hour. Positive delta_gross_margin means the change pays for itself.
with base as (
    select product_id,
           sum(audio_hours) / 3 * 12 as hours,
           sum(revenue) / 3 * 12 as revenue,
           sum(cogs) / 3 * 12 as cogs
    from {{ ref('fct_unit_economics_monthly') }}
    where month > (select max(month) from {{ ref('fct_unit_economics_monthly') }}) - interval 3 month
    group by product_id
)

select
    s.scenario,
    s.product_id,
    s.note,
    s.price_change_pct,
    s.volume_elasticity,
    cast(b.hours as decimal(18, 2)) as annual_hours,
    cast(b.hours * (1 + s.volume_elasticity * s.price_change_pct) as decimal(18, 2)) as new_annual_hours,
    cast(b.revenue as decimal(18, 2)) as annual_revenue,
    cast(b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct) as decimal(18, 2)) as new_annual_revenue,
    cast(b.revenue - b.cogs as decimal(18, 2)) as annual_gross_margin,
    cast(b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct)
         - b.cogs * (1 + s.volume_elasticity * s.price_change_pct) as decimal(18, 2)) as new_annual_gross_margin,
    cast(b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct) - b.revenue as decimal(18, 2)) as delta_revenue,
    cast((b.revenue * (1 + s.price_change_pct) - b.cogs) * (1 + s.volume_elasticity * s.price_change_pct)
         - (b.revenue - b.cogs) as decimal(18, 2)) as delta_gross_margin
from {{ ref('price_scenarios') }} s
join base b using (product_id)
