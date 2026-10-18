select
    doc_file,
    line_no,
    description,
    cast(quantity as decimal(18, 4)) as quantity,
    cast(amount as decimal(18, 2)) as amount
from {{ source('ap', 'extraction_lines') }}
where backend = '{{ var("ap_backend") }}'
