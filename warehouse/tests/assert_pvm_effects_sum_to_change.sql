-- Price + volume + mix must equal the revenue change for every product and month (to the cent), and a product
-- appears once per month.
select month, product_id, count(*) as n,
       sum(revenue_change) - sum(price_effect + volume_effect + mix_effect) as gap
from {{ ref('fct_revenue_pvm_monthly') }}
group by 1, 2
having count(*) > 1 or abs(sum(revenue_change) - sum(price_effect + volume_effect + mix_effect)) > 0.01
