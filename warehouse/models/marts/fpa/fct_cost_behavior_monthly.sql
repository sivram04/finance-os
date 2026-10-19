-- Fixed vs variable costs, contribution margin, breakeven and operating leverage per closed month.
-- Each cost account is classified in seeds/cost_behavior.csv (variable_share: the part that moves with volume).
--   contribution margin   revenue − variable costs;  CM ratio = CM / revenue
--   breakeven revenue     fixed costs / CM ratio (the monthly revenue at which operating income is 0)
--   margin of safety      1 − fixed costs / CM  (negative: revenue is below breakeven)
--   operating leverage    CM / operating income: % change in operating income per 1% change in revenue
with gl as (
    select g.month, g.account_type, g.account_id, sum(g.natural_amount) as amount
    from {{ ref('fct_gl_monthly') }} g
    where g.account_type in ('revenue', 'cogs', 'opex') and g.month <= {{ closed_through() }}
    group by 1, 2, 3
),

m as (
    select
        gl.month,
        sum(case when gl.account_type = 'revenue' then gl.amount else 0 end) as revenue,
        sum(case when gl.account_type <> 'revenue' then gl.amount * coalesce(b.variable_share, 0) else 0 end) as variable_costs,
        sum(case when gl.account_type <> 'revenue' then gl.amount * (1 - coalesce(b.variable_share, 0)) else 0 end) as fixed_costs
    from gl
    left join {{ ref('cost_behavior') }} b on b.account_id = gl.account_id
    group by 1
)

select
    month,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("variable_costs", 18, 2) }} as variable_costs,
    {{ dec("fixed_costs", 18, 2) }} as fixed_costs,
    {{ dec("revenue - variable_costs", 18, 2) }} as contribution_margin,
    {{ dec("round(" ~ fdiv("revenue - variable_costs", "nullif(revenue, 0)") ~ ", 4)", 9, 4) }} as cm_ratio,
    {{ dec("revenue - variable_costs - fixed_costs", 18, 2) }} as operating_income,
    {{ dec("round(" ~ fdiv("fixed_costs * revenue", "nullif(revenue - variable_costs, 0)") ~ ", 2)", 18, 2) }} as breakeven_revenue,
    {{ dec("round(1 - " ~ fdiv("fixed_costs", "nullif(revenue - variable_costs, 0)") ~ ", 4)", 9, 4) }} as margin_of_safety,
    -- only meaningful above breakeven: with an operating loss the ratio is negative and says nothing useful
    case when revenue - variable_costs - fixed_costs > 0 then
        {{ dec("round(" ~ fdiv("revenue - variable_costs", "revenue - variable_costs - fixed_costs") ~ ", 2)", 9, 2) }} end as operating_leverage
from m
