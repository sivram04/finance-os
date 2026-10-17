-- FR-3.1: GPU and cloud spend by day, attributed to vendor, team, env, model and customer from labels.
-- Untagged spend keeps team = 'untagged' and is never dropped. Stands in for the design's fct_cloud_cost_daily
-- and adds GPU vendor spend; the real GCP export joins here on the cloud target.
-- Commit shortfall is monthly and lives in fct_gpu_capacity_monthly, not here.
select
    job_date as spend_date,
    job_month as spend_month,
    vendor_id,
    'gpu' as category,
    'GPU compute' as service,
    gpu_type as sku,
    gpu_type,
    model,
    product_id,
    customer_id,
    coalesce(label_team, 'untagged') as team,
    coalesce(label_env, 'untagged') as env,
    label_team is not null and label_env is not null as is_tagged,
    sum(gpu_seconds) as gpu_seconds,
    cast(sum(gpu_cost) as decimal(18, 6)) as cost
from {{ ref('int_gpu_cost_jobs') }}
group by all

union all

select
    usage_date,
    usage_month,
    'gcp',
    'cloud',
    service,
    sku,
    null,
    null,
    null,
    null,
    coalesce(label_team, 'untagged'),
    coalesce(label_env, 'untagged'),
    is_tagged,
    0,
    cost
from {{ ref('stg_infra__cloud_costs_daily') }}
