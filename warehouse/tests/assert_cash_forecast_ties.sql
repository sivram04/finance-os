-- 13-week forecast: each week's closing cash = opening + net flow, and weeks chain together.
select * from (
    select *, lag(closing_cash) over (order by week) as prior_close from {{ ref('fct_cash_forecast_13w') }}
)
where abs(opening_cash + net_flow - closing_cash) > 0.01
   or (prior_close is not null and prior_close <> opening_cash)
