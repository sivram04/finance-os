-- Consolidation by month and account: each entity's balance (P&L: the month's activity; balance sheet: cumulative),
-- the intercompany eliminations, and the consolidated total, which equals fct_gl_monthly to the cent.
-- Translation (ASC 830): subsidiaries keep books in GBP / INR. P&L is translated at the month's average rate (the rate
-- the books were kept at, so it equals the USD booked); the balance sheet is translated at the closing rate (the next
-- month's opening rate). The difference on net assets is the cumulative translation adjustment (CTA), shown in equity.
with e as (
    select month, entity_id, currency, account_id, account_name, account_type, {{ adapter.quote('rollup') }} as rollup_name,
           sum(amount_usd) as amount_usd, sum(amount_local) as amount_local
    from {{ ref('fct_gl_entity_monthly') }} group by 1, 2, 3, 4, 5, 6, 7
),

months as (select distinct month from e),

closing as (  -- closing rate for a month = the next month's average (the last month keeps its own)
    select r.month, r.currency,
           coalesce(lead(r.usd_per_unit) over (partition by r.currency order by r.month), r.usd_per_unit) as closing_rate
    from {{ ref('fx_rates') }} r
),

pl as (
    select month, entity_id, account_id, account_name, account_type, rollup_name, amount_usd as balance_usd
    from e where account_type in ('revenue', 'cogs', 'opex')
),

bs_cum as (  -- balance sheet: cumulative local and booked-USD balances at each month end
    select m.month, x.entity_id, x.currency, x.account_id, x.account_name, x.account_type, x.rollup_name,
           sum(x.amount_local) as balance_local, sum(x.amount_usd) as balance_usd_historical
    from months m join e x on x.month <= m.month and x.account_type in ('asset', 'liability', 'equity')
    group by 1, 2, 3, 4, 5, 6, 7
),

bs as (
    select b.month, b.entity_id, b.account_id, b.account_name, b.account_type, b.rollup_name,
           case when b.currency = 'USD' then b.balance_usd_historical
                else round(b.balance_local * c.closing_rate, 2) end as balance_usd,
           b.balance_usd_historical
    from bs_cum b left join closing c on c.month = b.month and c.currency = b.currency
),

-- CTA per subsidiary: assets and liabilities at the closing rate minus what they were booked at (equity and retained
-- earnings stay at historical rates), so the translated balance sheet balances
cta as (
    select month, entity_id, '3900' as account_id, 'Cumulative translation adjustment' as account_name, 'equity' as account_type,
           'Equity' as rollup_name, -sum(balance_usd - balance_usd_historical) as balance_usd
    from bs where account_type in ('asset', 'liability') and entity_id <> 'US01'
    group by 1, 2
),

entity_lines as (
    select month, entity_id, account_id, account_name, account_type, rollup_name, balance_usd from pl
    union all
    select month, entity_id, account_id, account_name, account_type, rollup_name, balance_usd from bs
    union all
    select * from cta
),

elim as (
    select month, 'ELIM' as entity_id, account_id, account_name, account_type, rollup_name, -sum(balance_usd) as balance_usd
    from entity_lines where rollup_name = 'Intercompany' group by 1, 2, 3, 4, 5, 6
)

select month, entity_id, account_id, account_name, account_type, rollup_name, {{ dec("balance_usd", 18, 2) }} as balance_usd
from entity_lines
union all
select month, entity_id, account_id, account_name, account_type, rollup_name, {{ dec("balance_usd", 18, 2) }} from elim
