-- Forward contracts (seeds/fx_hedges.csv, simulated trades) marked to market each month from trade to maturity:
-- buying foreign currency forward gains when the spot rate rises above the contracted forward rate.
--   mtm_usd = notional x (spot - forward); at maturity it is the realized gain or loss.
-- Months after the last close use the planning FX rates and are flagged as projected.
with months as (
    select h.*, {{ add_months("h.trade_month", "g.n") }} as month
    from {{ ref('fx_hedges') }} h
    cross join {{ int_series('g', 0, 12) }}
    where {{ add_months("h.trade_month", "g.n") }} <= h.maturity_month
)

select
    m.hedge_id, m.currency, m.entity_id, m.instrument, m.purpose, m.month, m.trade_month, m.maturity_month,
    {{ dec("m.notional_fc", 18, 2) }} as notional_fc,
    {{ dec("m.forward_rate", 18, 6) }} as forward_rate,
    {{ dec("r.usd_per_unit", 18, 6) }} as spot_rate,
    {{ dec("m.notional_fc * m.forward_rate", 18, 2) }} as notional_usd_at_forward,
    {{ dec("m.notional_fc * (r.usd_per_unit - m.forward_rate)", 18, 2) }} as mtm_usd,
    case when m.month = m.maturity_month then 'settled' else 'open' end as status,
    m.month > {{ closed_through() }} as is_projected
from months m
join {{ ref('fx_rates') }} r on r.month = m.month and r.currency = m.currency
