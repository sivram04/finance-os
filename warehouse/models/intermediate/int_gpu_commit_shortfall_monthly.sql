-- Reserved GPU hours paid for but not used: max(0, committed − used) × rate, per contract month.
with months as (
    select distinct job_month as month from {{ ref('int_gpu_cost_jobs') }}
),

used as (
    select vendor_id, job_month as month, gpu_type, sum(gpu_seconds) / 3600.0 as used_hours
    from {{ ref('int_gpu_cost_jobs') }}
    group by all
),

contract_months as (
    select c.vendor_id, c.contract_id, m.month, c.committed_gpu_type as gpu_type, c.committed_gpu_hours_month as committed_hours
    from {{ ref('vendor_contracts') }} c
    join months m
        on m.month >= c.start_date
        and m.month <= coalesce(c.end_date, date '9999-12-31')
    where c.committed_gpu_hours_month is not null
)

select
    cm.vendor_id,
    cm.contract_id,
    cm.month,
    cm.gpu_type,
    cm.committed_hours,
    {{ dec("coalesce(u.used_hours, 0)", 18, 4) }} as used_hours,
    {{ dec("greatest(cm.committed_hours - coalesce(u.used_hours, 0), 0)", 18, 4) }} as shortfall_hours,
    r.rate_per_gpu_hour,
    {{ dec("round(greatest(cm.committed_hours - coalesce(u.used_hours, 0), 0) * r.rate_per_gpu_hour, 2)", 18, 2) }} as shortfall_cost
from contract_months cm
left join used u using (vendor_id, month, gpu_type)
join {{ ref('gpu_rates') }} r
    on r.gpu_type = cm.gpu_type
    and cm.month >= r.effective_from
    and cm.month <= coalesce(r.effective_to, date '9999-12-31')
