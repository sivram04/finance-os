select
    usage_date,
    {{ month_start("usage_date") }} as usage_month,
    service,
    sku,
    label_team,
    label_env,
    {{ dec("cost", 18, 6) }} as cost,
    label_team is not null and label_env is not null as is_tagged
from {{ source('infra', 'cloud_costs_daily') }}
