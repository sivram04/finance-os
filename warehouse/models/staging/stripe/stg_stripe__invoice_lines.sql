-- One row per invoice line (Stripe nests them under lines.data).
select
    i.id as invoice_id,
    {{ json_str('line', 'id') }} as line_id,
    {{ json_str('line', 'metadata.product_id') }} as product_id,
    {{ dec(json_str('line', 'metadata.audio_hours'), 18, 4) }} as audio_hours,
    {{ cents_to_usd(json_int('line', 'amount')) }} as amount
from {{ source('stripe', 'invoices') }} i
{{ json_unnest('i.data', 'lines.data', 'line') }}
