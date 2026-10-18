-- FR-4.1: monthly cash view from GL cash lines (account 1000).
-- Operating = everything except financing (funding). Gross burn = operating cash out.
-- Net burn = operating cash out − operating cash in (positive means the company is burning cash).
with cash as (
    select
        e.entry_month as month,
        e.entry_type = 'funding' as is_financing,
        l.amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '1000'
),

months as (
    select distinct entry_month as month from {{ ref('stg_erp__journal_entries') }}
),

monthly as (
    select
        m.month,
        coalesce(sum(case when not c.is_financing and c.amount > 0 then c.amount end), 0) as operating_cash_in,
        coalesce(sum(case when not c.is_financing and c.amount < 0 then -c.amount end), 0) as operating_cash_out,
        coalesce(sum(case when c.is_financing then c.amount end), 0) as financing_cash_in,
        coalesce(sum(c.amount), 0) as net_change
    from months m
    left join cash c using (month)
    group by m.month
)

select
    month,
    {{ dec("coalesce(sum(net_change) over (order by month rows between unbounded preceding and 1 preceding), 0)", 18, 2) }} as opening_cash,
    {{ dec("operating_cash_in", 18, 2) }} as operating_cash_in,
    {{ dec("operating_cash_out", 18, 2) }} as operating_cash_out,
    {{ dec("financing_cash_in", 18, 2) }} as financing_cash_in,
    {{ dec("sum(net_change) over (order by month rows between unbounded preceding and current row)", 18, 2) }} as closing_cash,
    {{ dec("operating_cash_out", 18, 2) }} as gross_burn,
    {{ dec("operating_cash_out - operating_cash_in", 18, 2) }} as net_burn
from monthly
