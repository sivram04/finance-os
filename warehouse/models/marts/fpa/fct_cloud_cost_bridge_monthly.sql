-- Cloud and GPU cost, month over month, split by cause (so overspend has an owner):
--   demand      (audio hours now - before) x GPU hours per audio hour before x rate before     → customer growth
--   efficiency  audio hours now x (GPU hours per audio hour now - before) x rate before         → architecture / routing
--   rate        GPU hours now x (rate now - rate before)                                         → procurement / price
--   shared      change in shared GPU (idle and warm-pool) cost
--   commitment  change in unused committed capacity paid for
--   other cloud change in non-GPU cloud services (storage, network, logging, compute)
-- For each product the first three add up exactly to its direct GPU cost change; the total row adds every step.
with direct as (
    select j.job_month as month, j.product_id, sum(j.gpu_seconds) / 3600.0 as gpu_hours, sum(j.gpu_cost) as cost
    from {{ ref('int_gpu_cost_jobs') }} j where not j.is_shared group by 1, 2
),

hours as (
    select usage_month as month, product_id, sum(audio_hours) as audio_hours
    from {{ ref('stg_synthetic__usage_daily') }} group by 1, 2
),

p as (
    select d.month, d.product_id, h.audio_hours, d.gpu_hours, d.cost,
           {{ fdiv("d.gpu_hours", "nullif(h.audio_hours, 0)") }} as intensity,
           {{ fdiv("d.cost", "nullif(d.gpu_hours, 0)") }} as rate
    from direct d join hours h using (month, product_id)
),

pb as (
    select cur.month, cur.product_id, coalesce(prv.cost, 0) as opening, cur.cost as closing,
           (cur.audio_hours - coalesce(prv.audio_hours, 0)) * coalesce(prv.intensity, cur.intensity) * coalesce(prv.rate, cur.rate) as demand,
           cur.audio_hours * (cur.intensity - coalesce(prv.intensity, cur.intensity)) * coalesce(prv.rate, cur.rate) as efficiency
    from p cur
    left join p prv on prv.product_id = cur.product_id and prv.month = {{ add_months("cur.month", -1) }}
    where cur.month <= {{ closed_through() }}
),

product_rows as (
    select month, product_id, opening, demand, efficiency,
           closing - opening - demand - efficiency as rate,  -- exact remainder: GPU hours now x rate change
           cast(0 as {{ dbt.type_float() }}) as shared, cast(0 as {{ dbt.type_float() }}) as commitment,
           cast(0 as {{ dbt.type_float() }}) as other_cloud, closing
    from pb
),

shared as (
    select job_month as month, sum(gpu_cost) as v from {{ ref('int_gpu_cost_jobs') }} where is_shared group by 1
),

commit_short as (
    select month, sum(shortfall_cost) as v from {{ ref('int_gpu_commit_shortfall_monthly') }} group by 1
),

other as (
    select usage_month as month, sum(cost) as v from {{ ref('stg_infra__cloud_costs_daily') }} group by 1
),

months as (select distinct month from product_rows),

totals as (
    select
        m.month,
        'all' as product_id,
        sum(pr.opening) + coalesce(max(s0.v), 0) + coalesce(max(c0.v), 0) + coalesce(max(o0.v), 0) as opening,
        sum(pr.demand) as demand,
        sum(pr.efficiency) as efficiency,
        sum(pr.rate) as rate,
        coalesce(max(s1.v), 0) - coalesce(max(s0.v), 0) as shared,
        coalesce(max(c1.v), 0) - coalesce(max(c0.v), 0) as commitment,
        coalesce(max(o1.v), 0) - coalesce(max(o0.v), 0) as other_cloud,
        sum(pr.closing) + coalesce(max(s1.v), 0) + coalesce(max(c1.v), 0) + coalesce(max(o1.v), 0) as closing
    from months m
    join product_rows pr on pr.month = m.month
    left join shared s1 on s1.month = m.month
    left join shared s0 on s0.month = {{ add_months("m.month", -1) }}
    left join commit_short c1 on c1.month = m.month
    left join commit_short c0 on c0.month = {{ add_months("m.month", -1) }}
    left join other o1 on o1.month = m.month
    left join other o0 on o0.month = {{ add_months("m.month", -1) }}
    group by m.month
)

select month, product_id,
       {{ dec("round(opening, 2)", 18, 2) }} as opening, {{ dec("round(demand, 2)", 18, 2) }} as demand,
       {{ dec("round(efficiency, 2)", 18, 2) }} as efficiency, {{ dec("round(rate, 2)", 18, 2) }} as rate,
       {{ dec("round(shared, 2)", 18, 2) }} as shared, {{ dec("round(commitment, 2)", 18, 2) }} as commitment,
       {{ dec("round(other_cloud, 2)", 18, 2) }} as other_cloud, {{ dec("round(closing, 2)", 18, 2) }} as closing
from (select * from product_rows union all select * from totals) b
