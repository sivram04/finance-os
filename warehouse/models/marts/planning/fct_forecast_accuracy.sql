-- How good were past forecasts? Each base-scenario version against the actuals that have since closed.
-- error = forecast − actual; error_pct relative to actual. Used to tune drivers (bias = average error).
select
    f.as_of_month,
    f.month,
    f.months_ahead,
    line,
    cast(forecast as decimal(18, 2)) as forecast,
    cast(actual as decimal(18, 2)) as actual,
    cast(forecast - actual as decimal(18, 2)) as error,
    cast(round((forecast - actual) / nullif(abs(actual), 0), 4) as decimal(9, 4)) as error_pct
from {{ ref('fct_forecast_monthly') }} f
join {{ ref('int_pnl_monthly') }} a using (month)
cross join lateral (
    values ('revenue', f.revenue, a.revenue),
           ('cogs', f.cogs, a.cogs),
           ('opex', f.opex, a.opex),
           ('ebitda', f.ebitda, a.revenue - a.cogs - a.opex)
) v(line, forecast, actual)
where f.scenario = 'base'
