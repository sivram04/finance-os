-- Five-year long-range plan (seeds/lrp_assumptions.csv) from the trailing twelve closed months.
-- Revenue compounds at each year's growth; costs follow the year's gross margin and opex ratios; cash starts
-- at the last closed month, adds the base-case raise (seeds/fundraise_scenarios.csv) in its year, and moves by
-- free cash flow (EBITDA − capex; working capital timing is left to the 18-month forecast).
with ttm as (
    select sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue
    from {{ ref('fct_gl_monthly') }}
    where month > {{ add_months(closed_through(), -12) }} and month <= {{ closed_through() }}
),

start_cash as (
    select closing_cash from {{ ref('fct_cash_monthly') }} where month = {{ closed_through() }}
),

a as (
    select
        l.*,
        exp(sum(ln(1 + cast(l.revenue_growth as {{ 'float64' if target.type == 'bigquery' else 'double' }}))) over (order by l.year)) as growth_index
    from {{ ref('lrp_assumptions') }} l
),

pl as (
    select
        a.year,
        a.note,
        a.revenue_growth,
        a.gross_margin_pct,
        t.revenue * a.growth_index as revenue,
        t.revenue * a.growth_index * a.gross_margin_pct as gross_profit,
        t.revenue * a.growth_index * a.sm_pct_revenue as sales_marketing,
        t.revenue * a.growth_index * a.rd_pct_revenue as research_development,
        t.revenue * a.growth_index * a.ga_pct_revenue as general_admin,
        t.revenue * a.growth_index * (a.gross_margin_pct - a.sm_pct_revenue - a.rd_pct_revenue - a.ga_pct_revenue) as ebitda,
        t.revenue * a.growth_index * a.capex_pct_revenue as capex,
        case when extract(year from r.close_month) = a.year then r.raise_amount else 0 end as financing
    from a
    cross join ttm t
    left join {{ ref('fundraise_scenarios') }} r on r.scenario = 'base'
)

select
    year,
    {{ dec("round(revenue, 2)", 18, 2) }} as revenue,
    {{ dec("revenue_growth", 9, 4) }} as revenue_growth,
    {{ dec("round(gross_profit, 2)", 18, 2) }} as gross_profit,
    {{ dec("gross_margin_pct", 9, 4) }} as gross_margin_pct,
    {{ dec("round(sales_marketing, 2)", 18, 2) }} as sales_marketing,
    {{ dec("round(research_development, 2)", 18, 2) }} as research_development,
    {{ dec("round(general_admin, 2)", 18, 2) }} as general_admin,
    {{ dec("round(ebitda, 2)", 18, 2) }} as ebitda,
    {{ dec("round(" ~ fdiv("ebitda", "nullif(revenue, 0)") ~ ", 4)", 9, 4) }} as ebitda_margin,
    {{ dec("round(capex, 2)", 18, 2) }} as capex,
    {{ dec("round(ebitda - capex, 2)", 18, 2) }} as free_cash_flow,
    {{ dec("financing", 18, 2) }} as financing,
    {{ dec("round((select closing_cash from start_cash) + sum(ebitda - capex + financing) over (order by year), 2)", 18, 2) }} as closing_cash,
    {{ dec("round(revenue_growth + " ~ fdiv("ebitda", "nullif(revenue, 0)") ~ ", 4)", 9, 4) }} as rule_of_40,
    note
from pl
