-- Vendor invoices ↔ AP postings in the GL, by vendor and service month. Exact match expected.
with bills as (
    select vendor_id, service_month as month, bill_id, total_amount as amount
    from {{ ref('stg_erp__vendor_bills') }}
),

gl as (
    select e.source_ref as bill_id, -sum(l.amount) as amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where e.entry_type = 'vendor_bill' and l.account_id = '2000'
    group by e.source_ref
)

select
    'vendor_bill_vs_gl_ap' as check_name,
    b.month as period,
    b.vendor_id as entity_id,
    b.amount as expected,
    g.amount as actual,
    g.amount - b.amount as variance,
    {{ dec("round((g.amount - b.amount) / nullif(b.amount, 0), 4)", 9, 4) }} as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when g.amount is not distinct from b.amount then 'pass' else 'fail' end as status,
    case when g.amount is null then 'Invoice not posted to the GL'
         when g.amount = b.amount then 'Exact match'
         else 'AP posting differs from invoice: investigate' end as explanation
from bills b
left join gl g using (bill_id)
