-- Price-change simulation per scenario (seeds/price_scenarios.csv) on the last 3 months, annualized:
-- new hours = hours × (1 + elasticity × price change); revenue moves with price and volume; COGS moves with
-- volume at today's cost per hour. Positive delta_gross_margin means the change pays for itself.
with base as (
    select product_id,
           sum(audio_hours) / 3 * 12 as hours,
           sum(revenue) / 3 * 12 as revenue,
           sum(cogs) / 3 * 12 as cogs
    from {{ ref('fct_unit_economics_monthly') }}
    where month > {{ add_months("(select max(month) from " ~ ref('fct_unit_economics_monthly') ~ ")", -3) }}
    group by product_id
)

select
    s.scenario,
    s.product_id,
    s.note,
    s.price_change_pct,
    s.volume_elasticity,
    {{ dec("b.hours", 18, 2) }} as annual_hours,
    {{ dec("b.hours * (1 + s.volume_elasticity * s.price_change_pct)", 18, 2) }} as new_annual_hours,
    {{ dec("b.revenue", 18, 2) }} as annual_revenue,
    {{ dec("b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct)", 18, 2) }} as new_annual_revenue,
    {{ dec("b.revenue - b.cogs", 18, 2) }} as annual_gross_margin,
    {{ dec("b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct)
         - b.cogs * (1 + s.volume_elasticity * s.price_change_pct)", 18, 2) }} as new_annual_gross_margin,
    {{ dec("b.revenue * (1 + s.price_change_pct) * (1 + s.volume_elasticity * s.price_change_pct) - b.revenue", 18, 2) }} as delta_revenue,
    {{ dec("(b.revenue * (1 + s.price_change_pct) - b.cogs) * (1 + s.volume_elasticity * s.price_change_pct)
         - (b.revenue - b.cogs)", 18, 2) }} as delta_gross_margin
from {{ ref('price_scenarios') }} s
join base b using (product_id)
