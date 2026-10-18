-- How good were past forecasts? Each base-scenario version against the actuals that have since closed.
-- error = forecast − actual; error_pct relative to actual. Used to tune drivers (bias = average error).
with pairs as (
    select
        f.as_of_month,
        f.month,
        f.months_ahead,
        v.line,
        case v.line when 'revenue' then f.revenue when 'cogs' then f.cogs when 'opex' then f.opex else f.ebitda end as forecast,
        case v.line when 'revenue' then a.revenue when 'cogs' then a.cogs when 'opex' then a.opex
                    else a.revenue - a.cogs - a.opex end as actual
    from {{ ref('fct_forecast_monthly') }} f
    join {{ ref('int_pnl_monthly') }} a using (month)
    cross join (select 'revenue' as line union all select 'cogs' union all select 'opex' union all select 'ebitda') v
    where f.scenario = 'base'
)

select
    as_of_month,
    month,
    months_ahead,
    line,
    {{ dec("forecast", 18, 2) }} as forecast,
    {{ dec("actual", 18, 2) }} as actual,
    {{ dec("forecast - actual", 18, 2) }} as error,
    {{ dec("round((forecast - actual) / nullif(abs(actual), 0), 4)", 9, 4) }} as error_pct
from pairs
