-- Customer health today, from leading indicators (usage moves before revenue does), for every customer with
-- revenue in the last closed month or usage in the last 90 days.
--   usage trend      daily audio hours, last 30 days vs the 60 days before them
--   at_risk          usage down 40%+, or no usage for 14+ days, or an open dispute
--   watch            usage down 20-40%, or invoices 30+ days past due, or gross margin below its floor
-- Also each customer's share of revenue (concentration). Reasons say why, in words.
with as_of as (
    select max(usage_date) as d from {{ ref('stg_synthetic__usage_daily') }}
),

usage as (
    select
        u.customer_id,
        sum(case when u.usage_date > {{ add_days("a.d", -30) }} then u.audio_hours else 0 end) / 30.0 as hours_per_day_30d,
        sum(case when u.usage_date <= {{ add_days("a.d", -30) }} and u.usage_date > {{ add_days("a.d", -90) }}
                 then u.audio_hours else 0 end) / 60.0 as hours_per_day_prior_60d,
        max(case when u.audio_hours > 0 then u.usage_date end) as last_usage_date,
        max(a.d) as as_of_date
    from {{ ref('stg_synthetic__usage_daily') }} u
    cross join as_of a
    where u.usage_date > {{ add_days("a.d", -90) }}
    group by 1
),

rev as (
    select customer_id, revenue
    from {{ ref('fct_customer_revenue_monthly') }}
    where month = {{ closed_through() }}
),

overdue as (
    select customer_id, sum(balance) as overdue_balance, max(days_past_due) as max_days_past_due
    from {{ ref('fct_ar_aging_snapshot') }}
    where snapshot_date = (select max(snapshot_date) from {{ ref('fct_ar_aging_snapshot') }}) and days_past_due > 0
    group by 1
),

disputes as (
    select customer_id, sum(disputed_amount) as disputed_amount
    from {{ ref('fct_disputes') }} where status = 'open' group by 1
),

margin as (
    select customer_id, {{ bool_or("is_below_floor") }} as below_floor
    from {{ ref('fct_customer_margin_monthly') }} where month = {{ closed_through() }} group by 1
),

j as (
    select
        c.customer_id,
        c.segment,
        coalesce(r.revenue, 0) as mrr,
        coalesce(u.hours_per_day_30d, 0) as hours_per_day_30d,
        coalesce(u.hours_per_day_prior_60d, 0) as hours_per_day_prior_60d,
        u.last_usage_date,
        {{ days_between("u.last_usage_date", "u.as_of_date") }} as days_since_usage,
        coalesce(o.overdue_balance, 0) as overdue_balance,
        coalesce(o.max_days_past_due, 0) as max_days_past_due,
        coalesce(d.disputed_amount, 0) as disputed_amount,
        coalesce(m.below_floor, false) as below_floor
    from {{ ref('dim_customer') }} c
    left join usage u on u.customer_id = c.customer_id
    left join rev r on r.customer_id = c.customer_id
    left join overdue o on o.customer_id = c.customer_id
    left join disputes d on d.customer_id = c.customer_id
    left join margin m on m.customer_id = c.customer_id
    where coalesce(r.revenue, 0) > 0 or coalesce(u.hours_per_day_30d, 0) + coalesce(u.hours_per_day_prior_60d, 0) > 0
),

t as (
    select
        *,
        case when hours_per_day_prior_60d > 0 then hours_per_day_30d / hours_per_day_prior_60d - 1 end as usage_trend,
        mrr / nullif(sum(mrr) over (), 0) as revenue_share,
        row_number() over (order by mrr desc, customer_id) as revenue_rank
    from j
)

select
    customer_id,
    segment,
    {{ dec("mrr", 18, 2) }} as mrr,
    {{ dec("mrr * 12", 18, 2) }} as arr,
    {{ dec("round(revenue_share, 4)", 9, 4) }} as revenue_share,
    cast(revenue_rank as bigint) as revenue_rank,
    {{ dec("round(hours_per_day_30d, 2)", 18, 2) }} as hours_per_day_30d,
    {{ dec("round(hours_per_day_prior_60d, 2)", 18, 2) }} as hours_per_day_prior_60d,
    {{ dec("round(usage_trend, 4)", 9, 4) }} as usage_trend,
    last_usage_date,
    days_since_usage,
    {{ dec("overdue_balance", 18, 2) }} as overdue_balance,
    max_days_past_due,
    {{ dec("disputed_amount", 18, 2) }} as disputed_amount,
    below_floor,
    case
        when usage_trend <= -0.40 or coalesce(days_since_usage, 999) >= 14 or disputed_amount > 0 then 'at_risk'
        when usage_trend <= -0.20 or max_days_past_due >= 30 or below_floor then 'watch'
        else 'healthy'
    end as health,
    trim(
        case when usage_trend <= -0.20 then 'usage down ' || cast(cast(round(-usage_trend * 100) as int) as {{ dbt.type_string() }}) || '%; ' else '' end
        || case when coalesce(days_since_usage, 999) >= 14 then 'no usage for 14+ days; ' else '' end
        || case when disputed_amount > 0 then 'open dispute; ' else '' end
        || case when max_days_past_due >= 30 then 'invoices ' || cast(max_days_past_due as {{ dbt.type_string() }}) || ' days late; ' else '' end
        || case when below_floor then 'margin below floor; ' else '' end
    ) as reasons
from t
