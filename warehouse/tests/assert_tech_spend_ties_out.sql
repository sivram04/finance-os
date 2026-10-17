-- FR-3.1: attribution must not lose or invent spend. Per month, the daily fact equals
-- GPU job cost plus cloud line cost.
with fact as (
    select spend_month as month, sum(cost) as cost
    from {{ ref('fct_tech_spend_daily') }}
    group by 1
),

sources as (
    select month, sum(cost) as cost from (
        select job_month as month, gpu_cost as cost from {{ ref('int_gpu_cost_jobs') }}
        union all
        select usage_month, cost from {{ ref('stg_infra__cloud_costs_daily') }}
    ) group by 1
)

select f.month, f.cost as fact_cost, s.cost as source_cost
from fact f
full outer join sources s using (month)
where f.cost is distinct from s.cost
