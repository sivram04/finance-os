select
    doc_file,
    line_no,
    description,
    quantity,
    amount
from {{ source('synthetic', 'ap_document_truth_lines') }}
