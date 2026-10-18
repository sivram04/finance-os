-- FR-8.5: dispute log with age and the balance held up.
with as_of as (
    select max(entry_date) as as_of_date from {{ ref('stg_erp__journal_entries') }}
)

select
    d.dispute_id,
    d.customer_id,
    d.invoice_ref,
    d.project_id,
    d.opened_date,
    d.status,
    d.root_cause,
    d.note,
    d.amount as disputed_amount,
    i.balance as invoice_balance,
    date_diff('day', d.opened_date, coalesce(d.resolved_date, o.as_of_date)) as days_open
from {{ ref('stg_erp__disputes') }} d
cross join as_of o
left join {{ ref('fct_ar_invoices') }} i using (invoice_ref)
