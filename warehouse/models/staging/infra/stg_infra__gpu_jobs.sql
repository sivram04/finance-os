select
    job_id,
    job_date,
    {{ month_start("job_date") }} as job_month,
    customer_id,
    product_id,
    model,
    workload,
    gpu_type,
    gpu_seconds,
    region,
    label_team,
    label_env,
    customer_id is null as is_shared
from {{ source('infra', 'gpu_jobs') }}
