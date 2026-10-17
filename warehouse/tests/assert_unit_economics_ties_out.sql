-- Design §8 M2 check: the mart's revenue equals rated revenue, and its GPU cost equals total job cost,
-- per month. GPU tolerance allows for rounding each mart row to cents ($0.005 per row).
with mart as (
    select month,
           sum(revenue) as revenue,
           sum(direct_gpu_cost + shared_gpu_cost) as gpu_cost,
           count(*) * 0.005 as tolerance
    from {{ ref('fct_unit_economics_monthly') }}
    group by month
),

rated as (
    select month, sum(revenue) as revenue
    from {{ ref('int_usage_rated_monthly') }}
    group by month
),

jobs as (
    select job_month as month, sum(gpu_cost) as gpu_cost
    from {{ ref('int_gpu_cost_jobs') }}
    group by job_month
)

select m.month, m.revenue, r.revenue as rated_revenue, m.gpu_cost, j.gpu_cost as job_gpu_cost
from mart m
join rated r using (month)
join jobs j using (month)
where m.revenue <> r.revenue
   or abs(m.gpu_cost - j.gpu_cost) > m.tolerance
