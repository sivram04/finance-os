-- Where each customer is and how it was won: country from the billing profile (sales-led) or the Stripe customer's
-- address (self-serve); region group for segment reporting; channel from how the account is sold and served.
select
    c.customer_id,
    c.segment,
    coalesce(b.country, s.country, 'US') as country,
    case
        when coalesce(b.country, s.country, 'US') in ('US', 'CA') then 'North America'
        when coalesce(b.country, s.country, 'US') in ('GB', 'DE', 'FR', 'NL', 'IE', 'ES', 'IT', 'SE') then 'EMEA'
        else 'APAC'
    end as region,
    case
        when c.segment = 'self_serve' then 'Self-serve (product-led)'
        when c.segment = 'federal' or c.customer_id like 'FED-%' then 'Public sector'
        else 'Direct sales'
    end as channel
from {{ ref('dim_customer') }} c
left join {{ ref('customer_billing_profile') }} b on b.customer_id = c.customer_id
left join (select customer_id, max(country) as country from {{ ref('stg_stripe__customers') }} group by 1) s on s.customer_id = c.customer_id
