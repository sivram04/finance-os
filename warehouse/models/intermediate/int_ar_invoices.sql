-- Every customer invoice that hit AR (GL account 1200 debits), usage and project, with its due date.
-- Usage invoices are due per the customer's segment terms (seeds/ar_policy.csv); project invoices per the
-- contract. Customers outside the usage base (the federal agency) take the 'federal' policy.
with ar_debits as (
    select e.source_ref as invoice_ref, e.entry_type, e.entry_date as invoice_date, l.customer_id, l.debit as amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '1200' and l.debit > 0
)

select
    d.invoice_ref,
    d.customer_id,
    case when d.entry_type = 'project_invoice' then 'project' else 'usage' end as invoice_type,
    coalesce(c.segment, case when k.is_federal then 'federal' end, 'enterprise') as segment,
    i.project_id,
    d.invoice_date,
    d.invoice_date + coalesce(k.payment_terms_days, p.payment_terms_days) as due_date,
    d.amount
from ar_debits d
left join {{ ref('stg_synthetic__customers') }} c using (customer_id)
left join {{ ref('stg_projects__project_invoices') }} i on i.invoice_id = d.invoice_ref
left join {{ ref('stg_projects__contracts') }} k on k.contract_id = i.contract_id
left join {{ ref('ar_policy') }} p
    on p.segment = coalesce(c.segment, case when k.is_federal then 'federal' end, 'enterprise')
