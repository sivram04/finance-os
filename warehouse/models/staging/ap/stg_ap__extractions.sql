-- Only the run selected by var('ap_backend') (text = rules, openai = OpenAI model).
select
    doc_file,
    backend,
    model,
    extracted_at,
    trim(vendor_name) as vendor_name,
    trim(vendor_invoice_number) as vendor_invoice_number,
    {{ try_cast_date('invoice_date') }} as invoice_date,
    nullif(trim(po_number), '') as po_number,
    currency,
    {{ dec("total", 18, 2) }} as total,
    prompt_tokens,
    completion_tokens
from {{ source('ap', 'extractions') }}
where backend = '{{ var("ap_backend") }}'
