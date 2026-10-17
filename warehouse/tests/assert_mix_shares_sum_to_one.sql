-- Each customer's product shares must sum to exactly 1.
select customer_id, sum(share) as total_share
from {{ ref('stg_synthetic__customer_product_mix') }}
group by customer_id
having sum(share) <> 1
