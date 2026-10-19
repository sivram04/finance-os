-- Each legal entity's own ledger by month, in USD (as booked) and in its functional currency at the month's average
-- rate (seeds/fx_rates.csv is the monthly average). Intercompany accounts are kept: they are real in each entity.
with lines as (
    select e.entry_month as month, l.entity_id, l.account_id, coalesce(l.department_id, 'NONE') as department_id, l.amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
)

select
    l.month,
    l.entity_id,
    d.currency,
    l.account_id,
    a.account_name,
    a.account_type,
    a.{{ adapter.quote('rollup') }},
    l.department_id,
    {{ dec("sum(l.amount)", 18, 2) }} as amount_usd,
    {{ dec("round(" ~ fdiv("sum(l.amount)", "max(coalesce(r.usd_per_unit, 1))") ~ ", 2)", 18, 2) }} as amount_local,
    {{ dec("case when a.account_type in ('revenue', 'liability', 'equity') then -sum(l.amount) else sum(l.amount) end", 18, 2) }} as natural_amount_usd
from lines l
join {{ ref('gl_accounts') }} a using (account_id)
join {{ ref('dim_entity') }} d using (entity_id)
left join {{ ref('fx_rates') }} r on r.month = l.month and r.currency = d.currency
group by l.month, l.entity_id, d.currency, l.account_id, a.account_name, a.account_type, a.{{ adapter.quote('rollup') }}, l.department_id
