-- FR-8.6: cash application exceptions.
--   remittance_mismatch  the customer's remittance names one invoice, AR applied the cash to another
--   overapplied          an invoice has more cash applied than it was billed
--   unmatched_payment    a payment applied to an invoice reference that doesn't exist
select 'remittance_mismatch' as exception_type, p.customer_id, p.payment_id as reference_id, p.received_date as exception_date,
       p.amount, 'Remittance says ' || p.remittance_ref || '; applied to ' || p.applied_ref as detail
from {{ ref('stg_erp__customer_payments') }} p
where p.remittance_ref <> p.applied_ref

union all

select 'overapplied', customer_id, invoice_ref, invoice_date, -balance,
       'Applied ' || applied_amount || ' to an invoice of ' || amount
from {{ ref('fct_ar_invoices') }}
where status = 'overapplied'

union all

select 'unmatched_payment', p.customer_id, p.payment_id, p.received_date, p.amount,
       'Applied to unknown invoice ' || p.applied_ref
from {{ ref('stg_erp__customer_payments') }} p
left join {{ ref('int_ar_invoices') }} i on i.invoice_ref = p.applied_ref
where i.invoice_ref is null
