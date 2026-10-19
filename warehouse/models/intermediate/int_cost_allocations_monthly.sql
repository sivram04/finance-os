-- Allocate each pool to customer × product by the driver chosen in seeds/allocation_rules.csv
-- for var('allocation_scenario'). Pools with driver 'none' (untagged cloud) are left unallocated.
-- Shares are rounded to 6 dp with largest-remainder; assert_allocations_complete checks the totals.
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
),

rounded as (
    select
        *,
        {{ dec("round(pool_amount * " ~ fdiv("driver_value", "nullif(driver_total, 0)") ~ ", 6)", 18, 6) }} as share,
        row_number() over (partition by month, pool, pool_product_id order by driver_value desc, customer_id, product_id) as rank_in_pool
    from matched
)

-- Largest remainder: shares are rounded to 6 places, and the rounding residue goes to the row with the biggest
-- driver, so every pool allocates exactly (thousands of customers would otherwise drift by cents).
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
    share + case when rank_in_pool = 1
                 then {{ dec("pool_amount", 18, 6) }} - sum(share) over (partition by month, pool, pool_product_id)
                 else 0 end as allocated_amount
from rounded
