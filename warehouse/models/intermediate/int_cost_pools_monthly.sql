-- Indirect cost pools to allocate (design §7.6). product_id is set when the pool is scoped to one product.
select job_month as month, 'shared_gpu' as pool, product_id, sum(gpu_cost) as amount
from {{ ref('int_gpu_cost_jobs') }}
where is_shared
group by all

union all

select usage_month, 'cloud_overhead', null, sum(cost)
from {{ ref('stg_infra__cloud_costs_daily') }}
where is_tagged and label_team = 'infra' and label_env = 'prod'
group by all

union all

select usage_month, 'untagged_cloud', null, sum(cost)
from {{ ref('stg_infra__cloud_costs_daily') }}
where not is_tagged
group by all

union all

select month, pool, null, amount
from {{ ref('stg_erp__opex_pools_monthly') }}
