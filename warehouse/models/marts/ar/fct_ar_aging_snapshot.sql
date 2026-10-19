-- FR-8.1: AR aging at each month end, and as of today for the month in progress (never a future date).
-- One row per customer × open invoice × snapshot date. Balance at the snapshot = amount − cash applied on or
-- before it. Buckets on days past due.
with snapshots as (
    select distinct least(last_day(entry_month), (select max(entry_date) from {{ ref('stg_erp__journal_entries') }})) as snapshot_date
    from {{ ref('stg_erp__journal_entries') }}
),

applied as (
    select s.snapshot_date, a.invoice_ref, sum(a.amount) as applied_amount
    from snapshots s
    join {{ ref('int_ar_applications') }} a on a.applied_date <= s.snapshot_date
    group by all
),

balances as (
    select
        s.snapshot_date,
        i.invoice_ref,
        i.customer_id,
        i.segment,
        i.invoice_type,
        i.due_date,
        i.amount - coalesce(a.applied_amount, 0) as balance
    from snapshots s
    join {{ ref('int_ar_invoices') }} i on i.invoice_date <= s.snapshot_date
    left join applied a on a.snapshot_date = s.snapshot_date and a.invoice_ref = i.invoice_ref
)

select
    snapshot_date,
    customer_id,
    invoice_ref,
    segment,
    invoice_type,
    {{ dec("balance", 18, 2) }} as balance,
    greatest({{ days_between("due_date", "snapshot_date") }}, 0) as days_past_due,
    case
        when snapshot_date <= due_date then 'current'
        when {{ days_between("due_date", "snapshot_date") }} <= 30 then '1-30'
        when {{ days_between("due_date", "snapshot_date") }} <= 60 then '31-60'
        when {{ days_between("due_date", "snapshot_date") }} <= 90 then '61-90'
        else '90+'
    end as aging_bucket
from balances
where balance > 0
