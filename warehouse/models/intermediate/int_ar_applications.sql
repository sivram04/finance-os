-- Cash applied to invoices: GL credits to AR (1200). source_ref is the invoice the cash was applied to.
select
    e.source_ref as invoice_ref,
    l.customer_id,
    e.entry_date as applied_date,
    l.credit as amount
from {{ ref('stg_erp__journal_lines') }} l
join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
where l.account_id = '1200' and l.credit > 0
