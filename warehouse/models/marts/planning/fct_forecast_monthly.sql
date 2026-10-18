-- Driver-based 18-month forecast, re-run as of each of the last 6 closed months (a rolling forecast), for
-- each scenario in seeds/planning_scenarios.csv. Every version uses only data up to its as-of month:
--   usage revenue    trailing-3-month run rate × (1 + growth)^n
--   services revenue trailing-3-month run rate × scenario multiple
--   COGS             revenue × (trailing-3-month COGS % + scenario change)
--   payroll          as-of month payroll + loaded cost of planned hires starting after the as-of month
--   other opex       trailing-3-month run rate × (1 + growth)^n
--   closing cash     as-of cash + cumulative EBITDA (working-capital timing is in the 13-week cash forecast)
with pnl as (
    select * from {{ ref('int_pnl_monthly') }}
),

versions as (
    select month as as_of_month
    from pnl
    where month > {{ add_months("(select max(month) from pnl)", -6) }}
),

run_rates as (
    select
        v.as_of_month,
        avg(p.revenue_usage) as usage_rr,
        avg(p.revenue_services) as services_rr,
        sum(p.cogs) / nullif(sum(p.revenue), 0) as cogs_pct,
        avg(p.other_opex) as other_opex_rr,
        max(case when p.month = v.as_of_month then p.payroll end) as payroll_last
    from versions v
    join pnl p on p.month between {{ add_months("v.as_of_month", -2) }} and v.as_of_month
    group by v.as_of_month
),

drivers as (
    select
        scenario,
        max(case when driver = 'usage_growth_monthly' then value end) as usage_growth,
        max(case when driver = 'services_monthly' then value end) as services_mult,
        max(case when driver = 'cogs_pct_change' then value end) as cogs_change,
        max(case when driver = 'other_opex_growth_monthly' then value end) as opex_growth
    from {{ ref('planning_scenarios') }}
    group by scenario
),

grid as (
    select d.*, r.*, h.n as months_ahead,
           {{ add_months("r.as_of_month", "h.n") }} as month
    from drivers d
    cross join run_rates r
    cross join {{ int_series('h', 1, 19 - 1) }}
),

hires as (
    select g.scenario, g.as_of_month, g.month, coalesce(sum(r.monthly_loaded_cost), 0) as new_hire_cost
    from grid g
    left join {{ ref('int_planned_hires') }} r
        on r.scenario = g.scenario and r.start_month > g.as_of_month and r.start_month <= g.month
    group by all
),

lines as (
    select
        g.scenario,
        g.as_of_month,
        g.month,
        g.months_ahead,
        g.usage_rr * pow(1 + g.usage_growth, g.months_ahead) as revenue_usage,
        g.services_rr * g.services_mult as revenue_services,
        g.cogs_pct + g.cogs_change as cogs_pct,
        g.payroll_last + h.new_hire_cost as payroll,
        g.other_opex_rr * pow(1 + g.opex_growth, g.months_ahead) as other_opex
    from grid g
    join hires h using (scenario, as_of_month, month)
),

pnl_lines as (
    select
        *,
        revenue_usage + revenue_services as revenue,
        (revenue_usage + revenue_services) * cogs_pct as cogs,
        payroll + other_opex as opex
    from lines
),

with_cash as (
    select
        p.*,
        p.revenue - p.cogs - p.opex as ebitda,
        c.closing_cash + sum(p.revenue - p.cogs - p.opex) over (
            partition by p.scenario, p.as_of_month order by p.month) as closing_cash
    from pnl_lines p
    join {{ ref('fct_cash_monthly') }} c on c.month = p.as_of_month
)

select
    scenario,
    as_of_month,
    month,
    months_ahead,
    as_of_month = (select max(as_of_month) from versions) as is_latest,
    {{ dec("revenue_usage", 18, 2) }} as revenue_usage,
    {{ dec("revenue_services", 18, 2) }} as revenue_services,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("cogs", 18, 2) }} as cogs,
    {{ dec("revenue - cogs", 18, 2) }} as gross_margin,
    {{ dec("round((revenue - cogs) / nullif(revenue, 0), 4)", 9, 4) }} as gross_margin_pct,
    {{ dec("payroll", 18, 2) }} as payroll,
    {{ dec("other_opex", 18, 2) }} as other_opex,
    {{ dec("opex", 18, 2) }} as opex,
    {{ dec("ebitda", 18, 2) }} as ebitda,
    {{ dec("closing_cash", 18, 2) }} as closing_cash
from with_cash
