-- Each GPU job costed at the rate in effect on the job date.
select
    j.*,
    r.vendor_id,
    r.rate_per_gpu_hour,
    cast(j.gpu_seconds * r.rate_per_gpu_hour / 3600 as decimal(18, 6)) as gpu_cost
from {{ ref('stg_infra__gpu_jobs') }} j
join {{ ref('gpu_rates') }} r
    on r.gpu_type = j.gpu_type
    and j.job_date >= r.effective_from
    and j.job_date <= coalesce(r.effective_to, date '9999-12-31')
