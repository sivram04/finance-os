select
    usage_date,
    date_trunc('month', usage_date)::date as usage_month,
    service,
    sku,
    label_team,
    label_env,
    cast(cost as decimal(18, 6)) as cost,
    label_team is not null and label_env is not null as is_tagged
from {{ source('infra', 'cloud_costs_daily') }}
