-- Commission statement per rep × month (M10): credited ARR (new, expansion, clawback), fiscal-year-to-date quota
-- attainment, and commission at the base rate up to quota and the accelerator rate above it. Clawbacks reverse at
-- the base rate. Every credit traces to billed revenue (int_sales_credits).
with months as (
    select distinct month from {{ ref('fct_customer_revenue_monthly') }} where month <= {{ closed_through() }}
),

grid as (
    select r.rep_id, r.rep_name, r.segment_focus, r.annual_quota_arr, r.base_rate, r.accelerator_rate, m.month
    from {{ ref('sales_reps') }} r cross join months m
),

monthly as (
    select
        g.*,
        coalesce(sum(case when c.credit_type = 'new' then c.credited_arr end), 0) as new_arr,
        coalesce(sum(case when c.credit_type = 'expansion' then c.credited_arr end), 0) as expansion_arr,
        coalesce(sum(case when c.is_clawback then c.credited_arr end), 0) as clawback_arr,
        coalesce(sum(case when not c.is_clawback then c.credited_arr end), 0) as credit
    from grid g
    left join {{ ref('int_sales_credits') }} c on c.rep_id = g.rep_id and c.month = g.month
    group by g.rep_id, g.rep_name, g.segment_focus, g.annual_quota_arr, g.base_rate, g.accelerator_rate, g.month
),

ytd as (
    select
        *,
        sum(credit) over (partition by rep_id, extract(year from month) order by month) as ytd_after,
        sum(credit) over (partition by rep_id, extract(year from month) order by month) - credit as ytd_before
    from monthly
),

split as (
    select
        *,
        greatest(least(ytd_after, annual_quota_arr) - least(ytd_before, annual_quota_arr), 0) as credit_in_quota,
        greatest(ytd_after - greatest(ytd_before, annual_quota_arr), 0) as credit_above_quota
    from ytd
)

select
    rep_id,
    rep_name,
    segment_focus,
    month,
    {{ dec("new_arr", 18, 2) }} as new_arr,
    {{ dec("expansion_arr", 18, 2) }} as expansion_arr,
    {{ dec("clawback_arr", 18, 2) }} as clawback_arr,
    {{ dec("ytd_after", 18, 2) }} as ytd_credited_arr,
    {{ dec("annual_quota_arr", 18, 2) }} as annual_quota_arr,
    {{ dec("round(" ~ fdiv("ytd_after", "annual_quota_arr") ~ ", 4)", 9, 4) }} as quota_attainment_pct,
    {{ dec("credit_in_quota * base_rate", 18, 2) }} as commission_base,
    {{ dec("credit_above_quota * accelerator_rate", 18, 2) }} as commission_accelerator,
    {{ dec("clawback_arr * base_rate", 18, 2) }} as commission_clawback,
    {{ dec("credit_in_quota * base_rate + credit_above_quota * accelerator_rate + clawback_arr * base_rate", 18, 2) }} as commission_total
from split
