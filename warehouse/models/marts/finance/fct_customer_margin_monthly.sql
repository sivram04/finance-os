-- FR-2.6: customer margin ranking. The customer's floor is the revenue-weighted floor of its product mix,
-- so a customer is flagged when its blended gross margin is below what its mix should earn.
with by_customer as (
    select
        month,
        customer_id,
        sum(audio_hours) as audio_hours,
        sum(revenue) as revenue,
        sum(cogs) as cogs,
        sum(gross_margin) as gross_margin,
        sum(contribution_margin) as contribution_margin,
        sum(revenue * gross_margin_floor_pct) / nullif(sum(revenue), 0) as floor_pct
    from {{ ref('fct_unit_economics_monthly') }}
    group by all
)

select
    b.month,
    b.customer_id,
    c.segment,
    b.audio_hours,
    b.revenue,
    b.cogs,
    b.gross_margin,
    cast(round(b.gross_margin / nullif(b.revenue, 0), 4) as decimal(9, 4)) as gross_margin_pct,
    b.contribution_margin,
    cast(round(b.contribution_margin / nullif(b.revenue, 0), 4) as decimal(9, 4)) as contribution_margin_pct,
    cast(round(b.floor_pct, 4) as decimal(9, 4)) as gross_margin_floor_pct,
    coalesce(b.gross_margin / nullif(b.revenue, 0) < b.floor_pct, false) as is_below_floor,
    rank() over (partition by b.month order by b.gross_margin / nullif(b.revenue, 0) asc nulls last) as margin_rank_asc
from by_customer b
join {{ ref('stg_synthetic__customers') }} c using (customer_id)
