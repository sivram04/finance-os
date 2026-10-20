-- FX exposure from running the UK and India subsidiaries: their monthly costs (COGS + opex in the GL, booked in
-- USD) restated in local currency at that month's rate, the next three months' expected spend in local currency
-- (trailing three-month average x 3), the forward contracts maturing in those three months (seeds/fx_hedges.csv,
-- simulated trades) and the hedge ratio. Treasury policy aims for 50-80% of the next quarter hedged.
with costs as (
    select l.entity_id, e.entry_month as month, sum(l.debit - l.credit) as cost_usd
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    join {{ ref('gl_accounts') }} a using (account_id)
    where a.account_type in ('cogs', 'opex') and l.entity_id <> 'US01' and e.entry_month <= {{ closed_through() }}
    group by 1, 2
),

local as (
    select c.*, n.currency, r.usd_per_unit,
           {{ fdiv("c.cost_usd", "r.usd_per_unit") }} as cost_local
    from costs c
    join {{ ref('entities') }} n using (entity_id)
    join {{ ref('fx_rates') }} r on r.month = c.month and r.currency = n.currency
),

expo as (
    select *, 3 * avg(cost_local) over (partition by entity_id order by month rows between 2 preceding and current row) as next_quarter_local
    from local
),

hedged as (
    select x.entity_id, x.month, coalesce(sum(h.notional_fc), 0) as hedged_local
    from expo x
    left join {{ ref('fx_hedges') }} h
      on h.entity_id = x.entity_id and h.trade_month <= x.month
     and h.maturity_month > x.month and h.maturity_month <= {{ add_months("x.month", 3) }}
    group by 1, 2
)

select
    x.entity_id, x.currency, x.month,
    {{ dec("x.usd_per_unit", 18, 6) }} as usd_per_unit,
    {{ dec("x.cost_usd", 18, 2) }} as cost_usd,
    {{ dec("x.cost_local", 18, 2) }} as cost_local,
    {{ dec("x.next_quarter_local", 18, 2) }} as next_quarter_exposure_local,
    {{ dec("x.next_quarter_local * x.usd_per_unit", 18, 2) }} as next_quarter_exposure_usd,
    {{ dec("h.hedged_local", 18, 2) }} as hedged_local,
    {{ dec("round(" ~ fdiv("h.hedged_local", "nullif(x.next_quarter_local, 0)") ~ ", 4)", 9, 4) }} as hedge_ratio
from expo x
join hedged h using (entity_id, month)
