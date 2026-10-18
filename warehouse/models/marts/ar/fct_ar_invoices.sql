-- One row per customer invoice, as of the last day of data: applied cash, balance, payment timing, status.
--   open         balance > 0
--   paid         balance = 0
--   overapplied  more cash applied than invoiced (a cash-application error)
with as_of as (
    select max(entry_date) as as_of_date from {{ ref('stg_erp__journal_entries') }}
),

applied as (
    select invoice_ref, sum(amount) as applied_amount, max(applied_date) as last_applied_date
    from {{ ref('int_ar_applications') }}
    group by invoice_ref
)

select
    i.invoice_ref,
    i.customer_id,
    i.invoice_type,
    i.segment,
    i.project_id,
    i.invoice_date,
    i.due_date,
    i.amount,
    coalesce(a.applied_amount, 0) as applied_amount,
    cast(i.amount - coalesce(a.applied_amount, 0) as decimal(18, 2)) as balance,
    case when i.amount - coalesce(a.applied_amount, 0) <= 0 then a.last_applied_date end as paid_date,
    case when i.amount - coalesce(a.applied_amount, 0) <= 0
         then date_diff('day', i.invoice_date, a.last_applied_date) end as days_to_pay,
    case when i.amount - coalesce(a.applied_amount, 0) <= 0
         then greatest(date_diff('day', i.due_date, a.last_applied_date), 0) end as days_paid_late,
    greatest(date_diff('day', i.due_date, o.as_of_date), 0) as days_past_due,
    d.dispute_id is not null and d.status = 'open' as is_disputed,
    case
        when i.amount - coalesce(a.applied_amount, 0) < 0 then 'overapplied'
        when i.amount - coalesce(a.applied_amount, 0) = 0 then 'paid'
        else 'open'
    end as status
from {{ ref('int_ar_invoices') }} i
cross join as_of o
left join applied a using (invoice_ref)
left join {{ ref('stg_erp__disputes') }} d on d.invoice_ref = i.invoice_ref
