-- Usage invoices. Amounts are cents in Stripe; here exact dollars. service_month = the billed period's month.
select
    i.id as invoice_id,
    {{ json_str('i.data', 'number') }} as invoice_number,
    {{ json_str('i.data', 'metadata.erp_invoice_ref') }} as erp_invoice_ref,
    c.customer_id,
    {{ json_str('i.data', 'status') }} as status,
    {{ json_str('i.data', 'collection_method') }} as collection_method,
    cast({{ unix_ts(json_int('i.data', 'period_start')) }} as date) as service_month,
    {{ unix_ts(json_int('i.data', 'created')) }} as created_at,
    {{ unix_ts(json_int('i.data', 'due_date')) }} as due_at,
    {{ unix_ts(json_int('i.data', 'status_transitions.paid_at')) }} as paid_at,
    {{ json_int('i.data', 'attempt_count') }} as attempt_count,
    {{ cents_to_usd(json_int('i.data', 'total')) }} as total,
    {{ cents_to_usd(json_int('i.data', 'amount_paid')) }} as amount_paid,
    {{ cents_to_usd(json_int('i.data', 'amount_remaining')) }} as amount_remaining
from {{ source('stripe', 'invoices') }} i
left join {{ ref('stg_stripe__customers') }} c on c.stripe_customer_id = {{ json_str('i.data', 'customer') }}
