-- Entities plus eliminations must equal the consolidated ledger for every P&L account and month.
with c as (
    select month, account_id, sum(balance_usd) as v from {{ ref('fct_consolidation_monthly') }}
    where account_type in ('revenue', 'cogs', 'opex') group by 1, 2
),
g as (
    select month, account_id, sum(amount) as v from {{ ref('fct_gl_monthly') }}
    where account_type in ('revenue', 'cogs', 'opex') group by 1, 2
)
select coalesce(c.month, g.month) as month, coalesce(c.account_id, g.account_id) as account_id, c.v, g.v
from c full join g on c.month = g.month and c.account_id = g.account_id
where abs(coalesce(c.v, 0) - coalesce(g.v, 0)) > 0.01
