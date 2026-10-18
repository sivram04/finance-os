-- FR-7.4: billing status per project, as of the last day of data.
--   ready      billable work waiting in the next billing run
--   sent       invoices out and not yet paid
--   paid       every invoice collected and nothing waiting
--   not_ready  nothing billed and nothing billable yet
-- ('drafted' is reserved for when the billing app records a draft awaiting approval.)
with invoices as (
    select
        i.project_id,
        i.invoice_id,
        i.invoice_date,
        i.amount,
        exists (
            select 1 from {{ ref('stg_erp__journal_entries') }} e
            where e.entry_type = 'project_collection' and e.source_ref = i.invoice_id
        ) as is_paid
    from {{ ref('stg_projects__project_invoices') }} i
),

inv as (
    select
        project_id,
        count(*) as invoices,
        max(invoice_date) as last_invoice_date,
        sum(amount) as billed_total,
        sum(amount) filter (where not is_paid) as open_ar
    from invoices
    group by project_id
),

drafts as (
    select project_id, sum(amount) as ready_to_bill, max(days_unbilled) as oldest_unbilled_days,
           bool_or(is_unbilled_alert) as has_unbilled_alert
    from {{ ref('fct_billing_run') }}
    group by project_id
)

select
    p.project_id,
    p.project_name,
    p.project_type,
    coalesce(i.invoices, 0) as invoices,
    i.last_invoice_date,
    cast(coalesce(i.billed_total, 0) as decimal(18, 2)) as billed_total,
    cast(coalesce(i.open_ar, 0) as decimal(18, 2)) as open_ar,
    cast(coalesce(d.ready_to_bill, 0) as decimal(18, 2)) as ready_to_bill,
    d.oldest_unbilled_days,
    coalesce(d.has_unbilled_alert, false) as has_unbilled_alert,
    case
        when coalesce(d.ready_to_bill, 0) > 0 then 'ready'
        when coalesce(i.open_ar, 0) > 0 then 'sent'
        when coalesce(i.invoices, 0) > 0 then 'paid'
        else 'not_ready'
    end as billing_status
from {{ ref('stg_projects__projects') }} p
left join inv i using (project_id)
left join drafts d using (project_id)
