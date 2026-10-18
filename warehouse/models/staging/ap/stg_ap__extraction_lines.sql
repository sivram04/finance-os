select
    doc_file,
    line_no,
    description,
    {{ dec("quantity", 18, 4) }} as quantity,
    {{ dec("amount", 18, 2) }} as amount
from {{ source('ap', 'extraction_lines') }}
where backend = '{{ var("ap_backend") }}'
