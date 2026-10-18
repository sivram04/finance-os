-- Re-allocated shared costs add back to what the GL booked (to the cent) for every pool and month.
select month, account_id, max(pool_amount) as pool, sum(allocated_amount) as allocated
from {{ ref('fct_shared_cost_allocation_monthly') }}
group by month, account_id
having abs(max(pool_amount) - sum(allocated_amount)) > 0.01
