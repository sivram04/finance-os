-- Next fiscal year's budget, built two ways and reconciled (FY = first full year after the last actual).
--   bottom-up  departments' plans: payroll from the headcount plan (base), other opex from each department's
--              trailing-3-month run rate × base growth; revenue and COGS from the base forecast.
--   top-down   board targets (seeds/planning_targets.csv): revenue = trailing-3-month run rate × 12 ×
--              (1 + growth target); COGS at the gross-margin target; opex ceiling = trailing-3-month opex
--              run rate × 12 × (1 + opex growth cap), spread across departments by their bottom-up ask.
-- gap = bottom-up − top-down (a positive opex gap means departments asked for more than the ceiling allows).
with fy as (
    select year(max(month)) + 1 as fiscal_year from {{ ref('int_pnl_monthly') }}
),

targets as (
    select
        max(case when target = 'revenue_growth_yoy' then value end) as growth,
        max(case when target = 'gross_margin_pct' then value end) as gm,
        max(case when target = 'opex_growth_yoy' then value end) as opex_growth
    from {{ ref('planning_targets') }} t
    join fy on t.fiscal_year = fy.fiscal_year
),

forecast as (
    select sum(revenue) as revenue, sum(cogs) as cogs
    from {{ ref('fct_forecast_monthly') }} f
    join fy on year(f.month) = fy.fiscal_year
    where f.is_latest and f.scenario = 'base'
),

run_rate as (
    select avg(revenue) * 12 as revenue_annual, avg(opex) * 12 as opex_annual
    from {{ ref('int_pnl_monthly') }}
    where month > (select max(month) from {{ ref('int_pnl_monthly') }}) - interval 3 month
),

dept_payroll as (
    select department_id, sum(payroll_cost) as amount
    from {{ ref('fct_headcount_plan_monthly') }} h
    join fy on year(h.month) = fy.fiscal_year
    where scenario = 'base'
    group by department_id
),

dept_other as (
    select g.department_id, avg_month * 12 * (1 + growth * 6) as amount   -- mid-year growth approximation
    from (
        select department_id, sum(natural_amount) / 3 as avg_month
        from {{ ref('fct_gl_monthly') }}
        where account_type = 'opex' and rollup <> 'Payroll'
          and month > (select max(month) from {{ ref('fct_gl_monthly') }}) - interval 3 month
        group by department_id
    ) g
    cross join (select value as growth from {{ ref('planning_scenarios') }}
                where scenario = 'base' and driver = 'other_opex_growth_monthly') d
),

dept as (
    select coalesce(p.department_id, o.department_id) as department_id,
           coalesce(p.amount, 0) as payroll, coalesce(o.amount, 0) as other_opex
    from dept_payroll p
    full outer join dept_other o using (department_id)
),

top as (
    select r.revenue_annual * (1 + t.growth) as revenue,
           r.revenue_annual * (1 + t.growth) * (1 - t.gm) as cogs,
           r.opex_annual * (1 + t.opex_growth) as opex_ceiling
    from run_rate r cross join targets t
),

rows_ as (
    select 'revenue' as line, null as department_id, f.revenue as bottom_up, t.revenue as top_down
    from forecast f cross join top t
    union all
    select 'cogs', null, f.cogs, t.cogs from forecast f cross join top t
    union all
    select 'opex', d.department_id, d.payroll + d.other_opex,
           t.opex_ceiling * (d.payroll + d.other_opex) / sum(d.payroll + d.other_opex) over ()
    from dept d cross join top t
)

select
    fy.fiscal_year,
    line,
    department_id,
    cast(bottom_up as decimal(18, 2)) as bottom_up,
    cast(top_down as decimal(18, 2)) as top_down,
    cast(bottom_up - top_down as decimal(18, 2)) as gap,
    cast(round((bottom_up - top_down) / nullif(top_down, 0), 4) as decimal(9, 4)) as gap_pct
from rows_
cross join fy
