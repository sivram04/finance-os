-- Customer cohorts by first revenue month: how many are still paying and how much they pay, N months later.
--   logo retention     active customers / cohort size (a customer is active in a month with revenue > 0)
--   revenue retention  cohort revenue / cohort revenue in month 1 (the first full month: month 0 is partial,
--                      customers sign up mid-month). Above 100% = the cohort expanded more than it churned.
-- Closed months only. Blended churn hides a weak recent cohort behind strong old ones; this view doesn't.
with r as (
    select customer_id, month, revenue
    from {{ ref('fct_customer_revenue_monthly') }}
    where month <= {{ closed_through() }}
),

first_month as (
    select customer_id, min(month) as cohort_month from r where revenue > 0 group by 1
),

grid as (
    select
        f.cohort_month,
        (extract(year from r.month) - extract(year from f.cohort_month)) * 12
            + extract(month from r.month) - extract(month from f.cohort_month) as months_since,
        count(distinct case when r.revenue > 0 then r.customer_id end) as active_customers,
        sum(r.revenue) as revenue
    from first_month f
    join r on r.customer_id = f.customer_id and r.month >= f.cohort_month
    group by 1, 2
),

base as (
    select
        cohort_month,
        max(case when months_since = 0 then active_customers end) as cohort_size,
        max(case when months_since = 1 then revenue end) as base_revenue
    from grid group by 1
)

select
    g.cohort_month,
    cast(g.months_since as bigint) as months_since,
    cast(b.cohort_size as bigint) as cohort_size,
    cast(g.active_customers as bigint) as active_customers,
    {{ dec("g.revenue", 18, 2) }} as revenue,
    {{ dec("round(" ~ fdiv("g.active_customers", "nullif(b.cohort_size, 0)") ~ ", 4)", 9, 4) }} as logo_retention,
    case when g.months_since >= 1 then
        {{ dec("round(" ~ fdiv("g.revenue", "nullif(b.base_revenue, 0)") ~ ", 4)", 9, 4) }} end as revenue_retention
from grid g
join base b on b.cohort_month = g.cohort_month
