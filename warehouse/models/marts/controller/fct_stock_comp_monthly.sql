-- Stock-based compensation (ASC 718), grant by grant and month.
-- Every employee receives a new-hire option grant on the hire date (seeds/equity_award_policy.csv), struck at the
-- 409A fair market value then in effect, and valued at grant with Black-Scholes (seeds/stock_option_valuations.csv).
-- Vesting: four years, one-year cliff, monthly after. Expense: straight line over the 48-month service period from
-- the grant month. Forfeitures are recognised as they occur: on termination, expense on unvested options is reversed,
-- so cumulative expense falls to the vested portion (to zero before the cliff). The ledger has no stock comp yet:
-- each month's expense is an entry to book (debit stock-based compensation, credit additional paid-in capital).
with valuations as (
    select effective_date, fmv_per_share, fair_value_per_option
    from {{ ref('stock_option_valuations') }}
),

grants as (
    select
        e.employee_id, e.department_id, e.function, e.hire_date as grant_date,
        {{ month_start("e.hire_date") }} as grant_month,
        -- a termination dated before the hire belongs to an earlier stint (a rehire): it does not touch this grant
        case when e.termination_date >= e.hire_date then {{ month_start("e.termination_date") }} end as termination_month,
        p.shares,
        v.fmv_per_share as strike_price,
        v.fair_value_per_option,
        row_number() over (partition by e.employee_id order by v.effective_date desc) as rn
    from {{ ref('stg_payroll__employees') }} e
    join {{ ref('equity_award_policy') }} p on p.function = e.function
    join valuations v on v.effective_date <= e.hire_date
),

months as (
    select {{ add_months("s.first_month", "h.n") }} as month
    from (select min(grant_month) as first_month from grants where rn = 1) s
    cross join {{ int_series('h', 0, 120) }}
),

grant_months as (
    select
        g.*,
        m.month,
        (extract(year from m.month) - extract(year from g.grant_month)) * 12
            + extract(month from m.month) - extract(month from g.grant_month) as months_after_grant,
        case when g.termination_month is not null then
            (extract(year from g.termination_month) - extract(year from g.grant_month)) * 12
                + extract(month from g.termination_month) - extract(month from g.grant_month) end as months_at_termination
    from grants g
    join months m on m.month >= g.grant_month and m.month <= {{ closed_through() }}
    where g.rn = 1
),

fractions as (
    select
        *,
        g.termination_month is not null and g.month >= g.termination_month as is_terminated,
        -- vested share of the grant: nothing until the 12-month cliff, then monthly to 48
        case when least(months_after_grant, coalesce(months_at_termination, months_after_grant)) >= 12
             then least(least(months_after_grant, coalesce(months_at_termination, months_after_grant)), 48) / 48.0
             else 0 end as vested_fraction,
        -- recognised share: straight line while employed; frozen at the vested share once terminated
        case when g.termination_month is not null and g.month >= g.termination_month
             then case when months_at_termination >= 12 then least(months_at_termination, 48) / 48.0 else 0 end
             else least(months_after_grant + 1, 48) / 48.0 end as recognised_fraction
    from grant_months g
),

cumulative as (
    select
        *,
        {{ dec("shares * fair_value_per_option * recognised_fraction", 18, 2) }} as cumulative_expense
    from fractions
)

select
    month,
    employee_id,
    department_id,
    function,
    'US01' as entity_id,
    grant_date,
    shares,
    {{ dec("strike_price", 18, 4) }} as strike_price,
    {{ dec("fair_value_per_option", 18, 4) }} as fair_value_per_option,
    {{ dec("shares * fair_value_per_option", 18, 2) }} as grant_fair_value,
    cast(round(shares * vested_fraction) as {{ dbt.type_int() }}) as vested_shares,
    case when is_terminated then 0 else cast(shares - round(shares * vested_fraction) as {{ dbt.type_int() }}) end as unvested_shares,
    case when is_terminated then cast(shares - round(shares * vested_fraction) as {{ dbt.type_int() }}) else 0 end as forfeited_shares,
    case when is_terminated then 'forfeited unvested'
         when vested_fraction >= 1 then 'fully vested'
         when vested_fraction > 0 then 'vesting'
         else 'before cliff' end as status,
    cumulative_expense,
    {{ dec("cumulative_expense - coalesce(lag(cumulative_expense) over (partition by employee_id order by month), 0)", 18, 2) }} as expense,
    termination_month is not null and month = termination_month as is_forfeiture_month
from cumulative
