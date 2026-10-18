-- Every expected cash movement after the last day of actuals, dated (the input to the 13-week forecast).
--   ar_collections   open invoices: due date + the customer's average days late
--   new_billings     usage the base forecast bills next (month end), collected on segment terms + lateness
--   services         project billing at the forecast run rate, collected on 30-day terms
--   payroll          base forecast payroll, paid on the last day of each month
--   vendor_bills     unpaid vendor and subcontractor bills on their terms (seeds/vendor_payment_terms.csv)
--   future_vendor    forecast COGS, billed ~5 days after month end and paid on 30-day terms
--   other_opex       forecast non-payroll opex, paid mid-month
with as_of as (
    select max(entry_date) as d from {{ ref('stg_erp__journal_entries') }}
),

late as (
    select customer_id, invoice_type, avg_days_late from {{ ref('fct_customer_payment_behavior') }}
),

segment_late as (
    select segment, avg(avg_days_late) as avg_days_late from {{ ref('fct_customer_payment_behavior') }}
    where invoice_type = 'usage' group by segment
),

forecast as (
    select * from {{ ref('fct_forecast_monthly') }} where is_latest and scenario = 'base' and months_ahead <= 4
),

segment_mix as (
    -- share of last month's usage revenue by segment, to split forecast billings by payment terms
    select c.segment, sum(r.revenue) / sum(sum(r.revenue)) over () as share
    from {{ ref('fct_customer_revenue_monthly') }} r
    join {{ ref('stg_synthetic__customers') }} c using (customer_id)
    where r.month = (select max(month) from {{ ref('fct_customer_revenue_monthly') }})
    group by c.segment
),

open_ap as (
    select e.source_ref as bill_ref, e.entry_type, l.vendor_id, e.entry_date as booked_date, sum(l.credit) as amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '2000' and l.credit > 0
      and e.entry_type in ('vendor_bill', 'subcontractor_bill')
      and e.source_ref not in (
          select source_ref from {{ ref('stg_erp__journal_entries') }}
          where entry_type in ('vendor_payment', 'subcontractor_payment') and source_ref is not null)
    group by all
),

flows as (
    select greatest(i.due_date + cast(round(coalesce(l.avg_days_late, 0)) as integer), a.d + 1) as flow_date,
           'ar_collections' as category, i.invoice_ref as reference, i.balance as amount
    from {{ ref('fct_ar_invoices') }} i
    cross join as_of a
    left join late l using (customer_id, invoice_type)
    where i.status = 'open'

    union all
    select last_day(f.month) + p.payment_terms_days + cast(round(coalesce(sl.avg_days_late, 0)) as integer),
           'new_billings', 'usage ' || strftime(f.month, '%Y-%m') || ' ' || m.segment, f.revenue_usage * m.share
    from forecast f
    cross join segment_mix m
    join {{ ref('ar_policy') }} p on p.segment = m.segment
    left join segment_late sl on sl.segment = m.segment

    union all
    select last_day(f.month) + 30, 'services', 'services ' || strftime(f.month, '%Y-%m'), f.revenue_services
    from forecast f

    union all
    select last_day(f.month), 'payroll', 'payroll ' || strftime(f.month, '%Y-%m'), -f.payroll
    from forecast f

    union all
    select greatest(coalesce(b.bill_date, o.booked_date + 5) + coalesce(t.payment_terms_days, d.payment_terms_days), a.d + 1),
           'vendor_bills', o.bill_ref, -o.amount
    from open_ap o
    cross join as_of a
    left join {{ ref('stg_erp__vendor_bills') }} b on b.bill_id = o.bill_ref
    left join {{ ref('vendor_payment_terms') }} t on t.vendor_id = o.vendor_id
    cross join (select payment_terms_days from {{ ref('vendor_payment_terms') }} where vendor_id = 'default') d

    union all
    select last_day(f.month) + 35, 'future_vendor', 'cogs ' || strftime(f.month, '%Y-%m'), -f.cogs
    from forecast f

    union all
    select f.month + 14, 'other_opex', 'opex ' || strftime(f.month, '%Y-%m'), -f.other_opex
    from forecast f
)

select cast(flow_date as date) as flow_date, category, reference, cast(amount as decimal(18, 2)) as amount
from flows
where flow_date > (select d from as_of)
