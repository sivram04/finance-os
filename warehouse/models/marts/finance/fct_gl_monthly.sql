-- Grain: account × department × month, CONSOLIDATED: every entity, with intercompany accounts (1300, 2300, 4900,
-- 6900) eliminated, so the group's numbers are what customers, vendors and employees did (see fct_consolidation_monthly
-- for the entity-by-entity view). amount = debit − credit; natural_amount flips the sign for credit-normal accounts
-- (revenue, liability, equity) so revenue and payables read as positive.
select
    e.entry_month as month,
    l.account_id,
    a.account_name,
    a.account_type,
    a.{{ adapter.quote('rollup') }},
    coalesce(l.department_id, 'NONE') as department_id,
    sum(l.debit) as debit,
    sum(l.credit) as credit,
    sum(l.amount) as amount,
    case when a.account_type in ('revenue', 'liability', 'equity') then -sum(l.amount) else sum(l.amount) end as natural_amount
from {{ ref('stg_erp__journal_lines') }} l
join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
join {{ ref('gl_accounts') }} a using (account_id)
where a.{{ adapter.quote('rollup') }} <> 'Intercompany'
group by 1, 2, 3, 4, 5, 6
