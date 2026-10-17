-- FR-3.4: GPU hours used vs. committed (reserved) hours, per vendor × GPU type × month.
-- GPU types without a commit show used hours only.
with used as (
    select vendor_id, job_month as month, gpu_type,
           sum(gpu_seconds) / 3600.0 as used_hours,
           sum(gpu_cost) as usage_cost
    from {{ ref('int_gpu_cost_jobs') }}
    group by all
)

select
    u.vendor_id,
    u.month,
    u.gpu_type,
    cast(u.used_hours as decimal(18, 4)) as used_hours,
    s.committed_hours,
    cast(round(u.used_hours / nullif(s.committed_hours, 0), 4) as decimal(9, 4)) as commit_utilization_pct,
    coalesce(s.shortfall_hours, 0) as shortfall_hours,
    cast(round(u.usage_cost, 2) as decimal(18, 2)) as usage_cost,
    coalesce(s.shortfall_cost, 0) as shortfall_cost
from used u
left join {{ ref('int_gpu_commit_shortfall_monthly') }} s using (vendor_id, month, gpu_type)
