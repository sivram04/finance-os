-- FR-1.4: an unbudgeted_expense anomaly (entity '<dept>-<account>') must raise a BvA alert in every month
-- that the generator posted a one-off expense to that department and account.
with a as (
    select anomaly_id,
           split_part(entity_id, '-', 1) as department_id,
           split_part(entity_id, '-', 2) as account_id
    from {{ ref('stg_synthetic__anomaly_manifest') }}
    where kind = 'unbudgeted_expense'
),

expected_months as (
    select distinct a.anomaly_id, a.department_id, a.account_id, e.entry_month as month
    from a
    join {{ ref('stg_erp__journal_lines') }} l
        on l.department_id = a.department_id and l.account_id = a.account_id
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where e.entry_type = 'one_off'
)

select x.*
from expected_months x
left join {{ ref('fct_bva_alerts') }} al using (month, department_id, account_id)
where al.alert_id is null
