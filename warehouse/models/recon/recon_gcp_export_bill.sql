-- Google's billing export ↔ Google's invoice, per invoice month: the export's net cost (cost + credits) must
-- equal the GCP bill posted in the ERP, to the cent. A gap means a missing export day, a credit not on the
-- invoice, or a bill keyed wrong.
with export as (
    select invoice_month as month, sum(net_cost) as net_cost
    from {{ ref('stg_gcp__billing_export') }}
    group by 1
),

bills as (
    select service_month as month, sum(total_amount) as billed
    from {{ ref('stg_erp__vendor_bills') }}
    where vendor_id = 'gcp'
    group by 1
)

select
    'gcp_export_vs_bill' as check_name,
    coalesce(b.month, e.month) as period,
    'gcp' as entity_id,
    {{ dec("b.billed", 18, 2) }} as expected,
    {{ dec("e.net_cost", 18, 2) }} as actual,
    {{ dec("coalesce(e.net_cost, 0) - coalesce(b.billed, 0)", 18, 2) }} as variance,
    cast(null as {{ t_float() }}) as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when round(coalesce(e.net_cost, 0), 2) = coalesce(b.billed, 0) then 'pass' else 'fail' end as status,
    case when e.month is null then 'Bill posted but no billing export for the month'
         when b.month is null then 'Billing export for a month with no GCP bill posted'
         when round(e.net_cost, 2) = b.billed then 'Export net cost equals the invoice'
         else 'Export and invoice differ: missing export rows, an unbilled credit, or a mis-keyed bill' end as explanation
from bills b
full outer join export e using (month)
