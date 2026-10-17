-- FR-3.2: share of spend carrying team and env labels.
select
    spend_month as month,
    cast(sum(cost) as decimal(18, 2)) as total_cost,
    cast(sum(case when is_tagged then cost else 0 end) as decimal(18, 2)) as tagged_cost,
    cast(sum(case when is_tagged then 0 else cost end) as decimal(18, 2)) as untagged_cost,
    cast(round(sum(case when is_tagged then cost else 0 end) / sum(cost), 4) as decimal(9, 4)) as tagging_coverage_pct
from {{ ref('fct_tech_spend_daily') }}
group by spend_month
