-- Modeled payment fees (ASSUMED): one invoice per customer per month, fee from the segment's schedule,
-- split to products by revenue share. Replaced by Stripe balance-transaction fees when Stripe lands.
with customer_month as (
    select r.month, r.customer_id, c.segment, sum(r.revenue) as customer_revenue
    from {{ ref('int_usage_rated_monthly') }} r
    join {{ ref('stg_synthetic__customers') }} c using (customer_id)
    group by all
),

fees as (
    select
        cm.month,
        cm.customer_id,
        cm.customer_revenue,
        case when cm.customer_revenue = 0 then 0
             else least(cm.customer_revenue * f.fee_pct + f.fee_fixed, coalesce(f.fee_cap, 999999999))
        end as customer_fee
    from customer_month cm
    join {{ ref('payment_fee_schedule') }} f using (segment)
)

select
    r.month,
    r.customer_id,
    r.product_id,
    {{ dec("round(coalesce(f.customer_fee * (r.revenue / nullif(f.customer_revenue, 0)), 0), 6)", 18, 6) }} as payment_fees
from {{ ref('int_usage_rated_monthly') }} r
join fees f using (month, customer_id)
