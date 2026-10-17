-- Driver values per customer × product × month, long format: one row per driver.
with direct_gpu as (
    select job_month as month, customer_id, product_id, sum(gpu_seconds) as gpu_seconds
    from {{ ref('int_gpu_cost_jobs') }}
    where not is_shared
    group by all
)

select month, customer_id, product_id, 'gpu_seconds' as driver, cast(gpu_seconds as decimal(38, 6)) as driver_value
from direct_gpu
union all
select month, customer_id, product_id, 'requests', cast(requests as decimal(38, 6))
from {{ ref('int_usage_rated_monthly') }}
union all
select month, customer_id, product_id, 'audio_hours', cast(audio_hours as decimal(38, 6))
from {{ ref('int_usage_rated_monthly') }}
union all
select month, customer_id, product_id, 'revenue', cast(revenue as decimal(38, 6))
from {{ ref('int_usage_rated_monthly') }}
