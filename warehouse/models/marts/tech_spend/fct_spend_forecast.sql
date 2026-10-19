-- FR-3.3: 3-month forecast of GPU and cloud spend.
-- Volume trend: compound monthly growth over the last 3 actual months, (m / m−2)^(1/2) − 1.
-- GPU cost = forecast hours × the rate effective in the forecast month; committed contracts add any shortfall.
-- Cloud cost grows at its own trend. Growth is computed in floating point; amounts are rounded to cents.
with last_month as (
    -- the last closed month: the open month is partial and would read as a fall in usage
    select {{ closed_through() }} as base_month
),

horizon as (
    select k, {{ add_months("base_month", "k") }} as forecast_month
    from last_month cross join (select n as k from {{ int_series('t', 1, 3) }})
),

gpu_hist as (
    select vendor_id, gpu_type, job_month as month, sum(gpu_seconds) / 3600.0 as hours
    from {{ ref('int_gpu_cost_jobs') }}, last_month
    where job_month > {{ add_months("base_month", -3) }}
    group by all
),

gpu_trend as (
    select
        vendor_id,
        gpu_type,
        max(case when month = (select base_month from last_month) then hours end) as base_hours,
        pow(
            max(case when month = (select base_month from last_month) then hours end)
            / nullif(max(case when month = {{ add_months("(select base_month from last_month)", -2) }} then hours end), 0),
            0.5
        ) - 1 as monthly_growth
    from gpu_hist
    group by all
),

gpu_forecast as (
    select
        h.forecast_month,
        g.vendor_id,
        g.gpu_type,
        g.monthly_growth,
        g.base_hours * pow(1 + g.monthly_growth, h.k) as hours,
        r.rate_per_gpu_hour
    from gpu_trend g
    cross join horizon h
    join {{ ref('gpu_rates') }} r
        on r.gpu_type = g.gpu_type
        and h.forecast_month >= r.effective_from
        and h.forecast_month <= coalesce(r.effective_to, date '9999-12-31')
),

shortfall as (
    select f.forecast_month, f.vendor_id, f.gpu_type, f.monthly_growth,
           greatest(c.committed_gpu_hours_month - f.hours, 0) as hours, f.rate_per_gpu_hour
    from gpu_forecast f
    join {{ ref('vendor_contracts') }} c
        on c.vendor_id = f.vendor_id
        and c.committed_gpu_type = f.gpu_type
        and f.forecast_month between c.start_date and coalesce(c.end_date, date '9999-12-31')
),

cloud_hist as (
    select usage_month as month, sum(cost) as cost
    from {{ ref('stg_infra__cloud_costs_daily') }}, last_month
    where usage_month > {{ add_months("base_month", -3) }}
    group by all
),

cloud_trend as (
    select
        max(case when month = (select base_month from last_month) then cost end) as base_cost,
        pow(
            max(case when month = (select base_month from last_month) then cost end)
            / nullif(max(case when month = {{ add_months("(select base_month from last_month)", -2) }} then cost end), 0),
            0.5
        ) - 1 as monthly_growth
    from cloud_hist
)

select forecast_month, vendor_id, 'gpu_usage' as line_type, gpu_type,
       {{ dec("round(monthly_growth, 4)", 9, 4) }} as monthly_growth,
       {{ dec("round(hours, 4)", 18, 4) }} as forecast_hours,
       {{ dec("round(hours * rate_per_gpu_hour, 2)", 18, 2) }} as forecast_amount
from gpu_forecast

union all

select forecast_month, vendor_id, 'commit_shortfall', gpu_type,
       {{ dec("round(monthly_growth, 4)", 9, 4) }},
       {{ dec("round(hours, 4)", 18, 4) }},
       {{ dec("round(hours * rate_per_gpu_hour, 2)", 18, 2) }}
from shortfall
where hours > 0

union all

select h.forecast_month, 'gcp', 'cloud_services', null,
       {{ dec("round(c.monthly_growth, 4)", 9, 4) }},
       null,
       {{ dec("round(c.base_cost * pow(1 + c.monthly_growth, h.k), 2)", 18, 2) }}
from cloud_trend c
cross join horizon h
