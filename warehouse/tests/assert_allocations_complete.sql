-- Design §8 M2 check: every allocated pool is fully allocated (sum of allocations = pool), within $0.01.
with rules as (
    select pool from {{ ref('allocation_rules') }}
    where scenario = '{{ var("allocation_scenario") }}' and driver <> 'none'
),

allocated as (
    select month, pool, pool_product_id, sum(allocated_amount) as allocated
    from {{ ref('int_cost_allocations_monthly') }}
    group by all
)

select p.month, p.pool, p.product_id, p.amount, a.allocated
from {{ ref('int_cost_pools_monthly') }} p
join rules r using (pool)
left join allocated a
    on a.month = p.month and a.pool = p.pool
    and a.pool_product_id is not distinct from p.product_id
where abs(p.amount - coalesce(a.allocated, 0)) > 0.01
