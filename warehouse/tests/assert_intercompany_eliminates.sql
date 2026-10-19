-- Intercompany must net to zero across the group every month: what subsidiaries charge (4900) equals what the parent
-- expenses (6900), and receivables (1300) equal payables (2300). Otherwise consolidation would leave a residue.
select month,
       sum(case when account_id = '4900' then -amount_usd else 0 end) as ic_revenue,
       sum(case when account_id = '6900' then amount_usd else 0 end) as ic_expense,
       sum(case when account_id in ('1300', '2300') then amount_usd else 0 end) as ic_balance_net
from {{ ref('fct_gl_entity_monthly') }}
group by month
having abs(sum(case when account_id = '4900' then -amount_usd else 0 end) - sum(case when account_id = '6900' then amount_usd else 0 end)) > 0.01
    or abs(sum(case when account_id in ('1300', '2300') then amount_usd else 0 end)) > 0.01
