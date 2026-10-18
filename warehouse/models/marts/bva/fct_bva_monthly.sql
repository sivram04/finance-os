-- FR-5.1, FR-5.2: budget vs. actuals by department × GL account × month, through the last month of actuals.
-- Amounts are in natural sign (revenue and costs both positive). Unfavorable = revenue below budget or
-- cost above budget. Full-year forecast as of each month = YTD actual + budget for the rest of the year.
-- A line alerts when it is unfavorable by more than the seed thresholds (both % and $).
with actual as (
    select month, department_id, account_id, sum(natural_amount) as actual
    from {{ ref('fct_gl_monthly') }}
    where account_type in ('revenue', 'cogs', 'opex')
    group by all
),

budget as (
    select month, department_id, account_id, sum(amount) as budget
    from {{ ref('stg_erp__budgets') }}
    where version = 'original'
    group by all
),

last_actual as (
    select max(month) as last_month from actual
),

all_months as (
    -- every key × month in a budgeted year, so the full-year forecast can add remaining budget
    select coalesce(a.month, b.month) as month,
           coalesce(a.department_id, b.department_id) as department_id,
           coalesce(a.account_id, b.account_id) as account_id,
           coalesce(a.actual, 0) as actual,
           coalesce(b.budget, 0) as budget
    from actual a
    full outer join budget b using (month, department_id, account_id)
),

running as (
    select
        m.*,
        extract(year from m.month) as fiscal_year,
        m.month <= l.last_month as is_actual_month,
        sum(case when m.month <= l.last_month then m.actual else 0 end)
            over (partition by extract(year from m.month), m.department_id, m.account_id order by m.month) as ytd_actual,
        sum(m.budget)
            over (partition by extract(year from m.month), m.department_id, m.account_id order by m.month) as ytd_budget,
        sum(m.budget)
            over (partition by extract(year from m.month), m.department_id, m.account_id) as fy_budget,
        sum(m.budget)
            over (partition by extract(year from m.month), m.department_id, m.account_id order by m.month
                  rows between 1 following and unbounded following) as remaining_budget
    from all_months m
    cross join last_actual l
),

scored as (
    select
        r.*,
        a.account_name,
        a.account_type,
        case when a.account_type = 'revenue' then r.budget - r.actual else r.actual - r.budget end as unfavorable_amount
    from running r
    join {{ ref('gl_accounts') }} a using (account_id)
)

select
    s.month,
    s.fiscal_year,
    s.department_id,
    s.account_id,
    s.account_name,
    s.account_type,
    {{ dec("s.actual", 18, 2) }} as actual,
    {{ dec("s.budget", 18, 2) }} as budget,
    {{ dec("s.actual - s.budget", 18, 2) }} as variance,
    {{ dec("round((s.actual - s.budget) / nullif(abs(s.budget), 0), 4)", 9, 4) }} as variance_pct,
    s.unfavorable_amount > 0 as is_unfavorable,
    {{ dec("s.ytd_actual", 18, 2) }} as ytd_actual,
    {{ dec("s.ytd_budget", 18, 2) }} as ytd_budget,
    {{ dec("s.fy_budget", 18, 2) }} as fy_budget,
    {{ dec("s.ytd_actual + coalesce(s.remaining_budget, 0)", 18, 2) }} as fy_forecast,
    {{ dec("s.ytd_actual + coalesce(s.remaining_budget, 0) - s.fy_budget", 18, 2) }} as fy_forecast_variance,
    s.unfavorable_amount > t.min_variance_abs
        and (s.budget = 0 or s.unfavorable_amount / abs(s.budget) > t.min_variance_pct) as is_alert
from scored s
cross join (select * from {{ ref('variance_thresholds') }} where rule_id = 'BVA-1') t
where s.is_actual_month
