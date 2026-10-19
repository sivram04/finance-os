-- Commission statement per rep x month (M10): credited ARR (new, expansion, clawback, after credit splits), the comp
-- credit the plan pays on (expansion at the plan's multiplier), fiscal-year-to-date quota attainment, commission at
-- the base rate up to quota and the accelerator above it, clawbacks at the base rate, and SPIFFs. Rates, quota and
-- multipliers come from the comp plan version in effect for the month (seeds/comp_plans.csv). Every credit traces to
-- billed revenue (int_sales_credits).
with months as (
    select distinct month from {{ ref('fct_customer_revenue_monthly') }} where month <= {{ closed_through() }}
),

grid as (
    select r.rep_id, r.rep_name, r.segment_focus, p.plan_id, p.annual_quota_arr, p.base_rate, p.accelerator_rate, m.month
    from {{ ref('sales_reps') }} r
    cross join months m
    join {{ ref('comp_plans') }} p on p.rep_id = r.rep_id and m.month between p.effective_from and p.effective_to
),

spiff as (
    select c.rep_id, c.month, sum(s.amount_per_credit * c.split_pct) as spiff_amount, count(*) as spiff_credits
    from {{ ref('int_sales_credits') }} c
    join {{ ref('spiffs') }} s on s.segment = c.segment and s.credit_type = c.credit_type
        and c.month between s.start_month and s.end_month
    where not c.is_clawback
    group by 1, 2
),

monthly as (
    select
        g.*,
        coalesce(sum(case when c.credit_type = 'new' then c.credited_arr end), 0) as new_arr,
        coalesce(sum(case when c.credit_type = 'expansion' then c.credited_arr end), 0) as expansion_arr,
        coalesce(sum(case when c.is_clawback then c.credited_arr end), 0) as clawback_arr,
        coalesce(sum(case when c.is_clawback then c.comp_credit end), 0) as clawback_credit,
        coalesce(sum(case when not c.is_clawback then c.comp_credit end), 0) as credit,
        coalesce(sum(case when c.credit_type = 'new' then c.comp_credit end), 0) as new_credit
    from grid g
    left join {{ ref('int_sales_credits') }} c on c.rep_id = g.rep_id and c.month = g.month
    group by g.rep_id, g.rep_name, g.segment_focus, g.plan_id, g.annual_quota_arr, g.base_rate, g.accelerator_rate, g.month
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
    s.rep_id,
    s.rep_name,
    s.segment_focus,
    s.plan_id,
    s.month,
    {{ dec("s.new_arr", 18, 2) }} as new_arr,
    {{ dec("s.expansion_arr", 18, 2) }} as expansion_arr,
    {{ dec("s.clawback_arr", 18, 2) }} as clawback_arr,
    {{ dec("s.credit", 18, 2) }} as comp_credit,
    {{ dec("s.ytd_after", 18, 2) }} as ytd_credited_arr,
    {{ dec("s.annual_quota_arr", 18, 2) }} as annual_quota_arr,
    {{ dec("round(" ~ fdiv("s.ytd_after", "s.annual_quota_arr") ~ ", 4)", 9, 4) }} as quota_attainment_pct,
    {{ dec("round(s.credit_in_quota * s.base_rate, 2)", 18, 2) }} as commission_base,
    {{ dec("round(s.credit_above_quota * s.accelerator_rate, 2)", 18, 2) }} as commission_accelerator,
    {{ dec("round(s.clawback_credit * s.base_rate, 2)", 18, 2) }} as commission_clawback,
    {{ dec("coalesce(x.spiff_amount, 0)", 18, 2) }} as spiff,
    {{ dec("round(" ~ fdiv("s.new_credit", "nullif(s.credit, 0)") ~ ", 4)", 9, 4) }} as new_share,
    {{ dec("round(s.credit_in_quota * s.base_rate + s.credit_above_quota * s.accelerator_rate + s.clawback_credit * s.base_rate, 2) + coalesce(x.spiff_amount, 0)", 18, 2) }} as commission_total
from split s
left join spiff x using (rep_id, month)
