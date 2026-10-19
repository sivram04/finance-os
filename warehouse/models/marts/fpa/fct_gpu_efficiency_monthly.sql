-- GPU efficiency by month and GPU type: how much paid GPU time served customers.
--   idle share         shared (idle / warm-pool) GPU seconds / all GPU seconds
--   commit coverage    committed hours / used hours (reserved-capacity coverage; above 100% = paying for idle commit)
--   commit utilization used / committed
with jobs as (
    select job_month as month, gpu_type, {{ fdiv("sum(gpu_seconds)", 3600) }} as gpu_hours,
           {{ fdiv("sum(case when is_shared then gpu_seconds else 0 end)", 3600) }} as idle_hours, sum(gpu_cost) as cost,
           sum(case when is_shared then gpu_cost else 0 end) as idle_cost
    from {{ ref('int_gpu_cost_jobs') }} group by 1, 2
),

c as (
    select month, gpu_type, sum(committed_hours) as committed_hours, sum(shortfall_cost) as shortfall_cost
    from {{ ref('int_gpu_commit_shortfall_monthly') }} group by 1, 2
)

select j.month, j.gpu_type,
       {{ dec("round(j.gpu_hours, 2)", 18, 2) }} as gpu_hours,
       {{ dec("round(j.idle_hours, 2)", 18, 2) }} as idle_hours,
       {{ dec("round(" ~ fdiv("j.idle_hours", "nullif(j.gpu_hours, 0)") ~ ", 4)", 9, 4) }} as idle_share,
       {{ dec("round(j.idle_cost, 2)", 18, 2) }} as idle_cost,
       {{ dec("round(coalesce(c.committed_hours, 0), 2)", 18, 2) }} as committed_hours,
       case when c.committed_hours > 0 then {{ dec("round(" ~ fdiv("c.committed_hours", "nullif(j.gpu_hours, 0)") ~ ", 4)", 9, 4) }} end as commit_coverage,
       case when c.committed_hours > 0 then {{ dec("round(" ~ fdiv("j.gpu_hours", "c.committed_hours") ~ ", 4)", 9, 4) }} end as commit_utilization,
       {{ dec("round(coalesce(c.shortfall_cost, 0), 2)", 18, 2) }} as unused_commit_cost
from jobs j
left join c using (month, gpu_type)
where j.month <= {{ closed_through() }}
