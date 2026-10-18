-- 13-week cash forecast: opening cash (GL), inflows and outflows by category per week, closing cash, and
-- whether the week breaches the minimum-cash policy (seeds/treasury_policy.csv MIN-CASH).
with as_of as (
    select max(entry_date) as d from {{ ref('stg_erp__journal_entries') }}
),

weeks as (
    select cast(h.n as integer) as week, a.d + cast(1 + 7 * (h.n - 1) as integer) as week_start, a.d + cast(7 * h.n as integer) as week_end
    from as_of a cross join range(1, 14) h(n)
),

opening as (
    select sum(l.amount) as cash from {{ ref('stg_erp__journal_lines') }} l where l.account_id = '1000'
),

flows as (
    select w.week, f.category, sum(f.amount) as amount
    from weeks w
    join {{ ref('int_cash_flows_forecast') }} f on f.flow_date between w.week_start and w.week_end
    group by all
),

weekly as (
    select
        w.week, w.week_start, w.week_end,
        coalesce(sum(f.amount) filter (where f.category in ('ar_collections', 'new_billings', 'services')), 0) as inflows,
        coalesce(sum(f.amount) filter (where f.category = 'payroll'), 0) as payroll,
        coalesce(sum(f.amount) filter (where f.category in ('vendor_bills', 'future_vendor')), 0) as vendors,
        coalesce(sum(f.amount) filter (where f.category = 'other_opex'), 0) as other_opex,
        coalesce(sum(f.amount), 0) as net_flow
    from weeks w
    left join flows f using (week)
    group by all
)

select
    w.week,
    cast(w.week_start as date) as week_start,
    cast(w.week_end as date) as week_end,
    cast(o.cash + coalesce(sum(w.net_flow) over (order by w.week rows between unbounded preceding and 1 preceding), 0) as decimal(18, 2)) as opening_cash,
    cast(w.inflows as decimal(18, 2)) as inflows,
    cast(w.payroll as decimal(18, 2)) as payroll,
    cast(w.vendors as decimal(18, 2)) as vendors,
    cast(w.other_opex as decimal(18, 2)) as other_opex,
    cast(w.net_flow as decimal(18, 2)) as net_flow,
    cast(o.cash + sum(w.net_flow) over (order by w.week) as decimal(18, 2)) as closing_cash,
    o.cash + sum(w.net_flow) over (order by w.week) < p.threshold as is_below_min_cash
from weekly w
cross join opening o
cross join (select threshold from {{ ref('treasury_policy') }} where rule_id = 'MIN-CASH') p
