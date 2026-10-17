-- Indirect cost pools to allocate (design §7.6). product_id is set when the pool is scoped to one product.
-- gpu_commit_shortfall: reserved GPU hours paid for but unused. Split to the products running on that GPU type
-- by their share of its direct GPU-seconds, then allocated within each product like shared GPU.
with gpu_type_product_seconds as (
    select vendor_id, job_month as month, gpu_type, product_id, sum(gpu_seconds) as gpu_seconds
    from {{ ref('int_gpu_cost_jobs') }}
    where not is_shared
    group by all
),

gpu_type_product_share as (
    select
        vendor_id,
        month,
        gpu_type,
        product_id,
        gpu_seconds / sum(gpu_seconds) over (partition by vendor_id, month, gpu_type) as share
    from gpu_type_product_seconds
)

select job_month as month, 'shared_gpu' as pool, product_id, sum(gpu_cost) as amount
from {{ ref('int_gpu_cost_jobs') }}
where is_shared
group by all

union all

select s.month, 'gpu_commit_shortfall', p.product_id, s.shortfall_cost * p.share
from {{ ref('int_gpu_commit_shortfall_monthly') }} s
join gpu_type_product_share p using (vendor_id, month, gpu_type)
where s.shortfall_cost > 0

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

-- Support and success pools: fully loaded payroll of employees in those functions.
select p.pay_month, e.function, null, sum(p.total_cost)
from {{ ref('stg_payroll__pay_lines') }} p
join {{ ref('stg_payroll__employees') }} e using (employee_id)
where e.function in ('support', 'success')
group by all
