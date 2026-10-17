-- FR-2.1–2.3: revenue, cost to serve, gross and contribution margin per customer × product × month.
-- COGS = direct GPU + allocated shared GPU + allocated prod cloud overhead.
-- Contribution = gross margin − payment fees − allocated support − allocated success.
with direct_gpu as (
    select job_month as month, customer_id, product_id, sum(gpu_seconds) as gpu_seconds, sum(gpu_cost) as direct_gpu_cost
    from {{ ref('int_gpu_cost_jobs') }}
    where not is_shared
    group by all
),

alloc as (
    select
        month,
        customer_id,
        product_id,
        sum(case when pool = 'shared_gpu' then allocated_amount else 0 end) as shared_gpu_cost,
        sum(case when pool = 'cloud_overhead' then allocated_amount else 0 end) as cloud_overhead_cost,
        sum(case when pool = 'support' then allocated_amount else 0 end) as support_cost,
        sum(case when pool = 'success' then allocated_amount else 0 end) as success_cost
    from {{ ref('int_cost_allocations_monthly') }}
    group by all
),

joined as (
    select
        r.month,
        r.customer_id,
        r.product_id,
        p.model,
        p.workload,
        r.audio_hours,
        r.requests,
        coalesce(g.gpu_seconds, 0) as gpu_seconds,
        r.tier,
        r.list_revenue,
        r.revenue,
        coalesce(g.direct_gpu_cost, 0) as direct_gpu_cost,
        coalesce(a.shared_gpu_cost, 0) as shared_gpu_cost,
        coalesce(a.cloud_overhead_cost, 0) as cloud_overhead_cost,
        coalesce(f.payment_fees, 0) as payment_fees,
        coalesce(a.support_cost, 0) as support_cost,
        coalesce(a.success_cost, 0) as success_cost,
        mf.gross_margin_floor_pct
    from {{ ref('int_usage_rated_monthly') }} r
    join {{ ref('stg_synthetic__products') }} p using (product_id)
    left join direct_gpu g using (month, customer_id, product_id)
    left join alloc a using (month, customer_id, product_id)
    left join {{ ref('int_payment_fees_monthly') }} f using (month, customer_id, product_id)
    left join {{ ref('margin_floors') }} mf using (product_id)
),

calc as (
    select
        *,
        direct_gpu_cost + shared_gpu_cost + cloud_overhead_cost as cogs
    from joined
)

select
    month,
    customer_id,
    product_id,
    model,
    workload,
    audio_hours,
    requests,
    gpu_seconds,
    tier,
    list_revenue,
    revenue,
    cast(round(direct_gpu_cost, 2) as decimal(18, 2)) as direct_gpu_cost,
    cast(round(shared_gpu_cost, 2) as decimal(18, 2)) as shared_gpu_cost,
    cast(round(cloud_overhead_cost, 2) as decimal(18, 2)) as cloud_overhead_cost,
    cast(round(cogs, 2) as decimal(18, 2)) as cogs,
    cast(round(revenue - cogs, 2) as decimal(18, 2)) as gross_margin,
    cast(round((revenue - cogs) / nullif(revenue, 0), 4) as decimal(9, 4)) as gross_margin_pct,
    cast(round(payment_fees, 2) as decimal(18, 2)) as payment_fees,
    cast(round(support_cost, 2) as decimal(18, 2)) as support_cost,
    cast(round(success_cost, 2) as decimal(18, 2)) as success_cost,
    cast(round(revenue - cogs - payment_fees - support_cost - success_cost, 2) as decimal(18, 2)) as contribution_margin,
    cast(round((revenue - cogs - payment_fees - support_cost - success_cost) / nullif(revenue, 0), 4) as decimal(9, 4)) as contribution_margin_pct,
    cast(round(cogs / nullif(audio_hours, 0), 6) as decimal(18, 6)) as cost_to_serve_per_hour,
    gross_margin_floor_pct,
    (revenue - cogs) / nullif(revenue, 0) < gross_margin_floor_pct as is_below_floor
from calc
