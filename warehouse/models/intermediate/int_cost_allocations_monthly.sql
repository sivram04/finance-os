-- Allocate each pool to customer × product by the driver chosen in seeds/allocation_rules.csv
-- for var('allocation_scenario'). Pools with driver 'none' (untagged cloud) are left unallocated.
-- Shares are ratios rounded to 6 dp; assert_allocations_complete checks the totals.
with rules as (
    select pool, driver, scope
    from {{ ref('allocation_rules') }}
    where scenario = '{{ var("allocation_scenario") }}'
      and driver <> 'none'
),

matched as (
    select
        p.month,
        p.pool,
        p.product_id as pool_product_id,
        p.amount as pool_amount,
        r.driver,
        d.customer_id,
        d.product_id,
        d.driver_value,
        sum(d.driver_value) over (partition by p.month, p.pool, p.product_id) as driver_total
    from {{ ref('int_cost_pools_monthly') }} p
    join rules r on r.pool = p.pool
    join {{ ref('int_allocation_drivers_monthly') }} d
        on d.driver = r.driver
        and d.month = p.month
        and (r.scope = 'all' or d.product_id = p.product_id)
)

select
    month,
    pool,
    pool_product_id,
    driver,
    customer_id,
    product_id,
    pool_amount,
    driver_value,
    driver_total,
    cast(round(pool_amount * (driver_value / nullif(driver_total, 0)), 6) as decimal(18, 6)) as allocated_amount
from matched
