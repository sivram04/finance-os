-- Extraction quality against the generator's ground truth, per field, for the selected backend.
-- This is the eval for the AI extractor: run with --vars '{ap_backend: grok}' to score Grok.
with t as (
    select * from {{ ref('stg_synthetic__ap_document_truth') }}
),

e as (
    select * from {{ ref('stg_ap__extractions') }}
),

line_match as (
    select tl.doc_file,
           bool_and(el.amount is not distinct from tl.amount
                    and el.quantity is not distinct from tl.quantity
                    and el.description = tl.description) and count(el.line_no) = count(*) as lines_ok
    from {{ ref('stg_synthetic__ap_document_truth_lines') }} tl
    left join {{ ref('stg_ap__extraction_lines') }} el using (doc_file, line_no)
    group by tl.doc_file
),

per_doc as (
    select
        t.doc_file,
        e.doc_file is not null as extracted,
        e.vendor_name is not distinct from t.vendor_name as vendor_name_ok,
        e.vendor_invoice_number is not distinct from t.vendor_invoice_number as invoice_number_ok,
        e.invoice_date is not distinct from t.invoice_date as invoice_date_ok,
        e.po_number is not distinct from t.po_number as po_number_ok,
        e.total is not distinct from t.total as total_ok,
        coalesce(l.lines_ok, false) as lines_ok
    from t
    left join e using (doc_file)
    left join line_match l using (doc_file)
)

select
    '{{ var("ap_backend") }}' as backend,
    field,
    count(*) as documents,
    count(*) filter (where ok) as correct,
    cast(round(count(*) filter (where ok) / count(*), 4) as decimal(9, 4)) as accuracy
from per_doc
unpivot (ok for field in (extracted, vendor_name_ok, invoice_number_ok, invoice_date_ok, po_number_ok, total_ok, lines_ok))
group by field
