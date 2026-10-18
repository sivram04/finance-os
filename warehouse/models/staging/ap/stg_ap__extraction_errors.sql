select doc_file, backend, extracted_at, error
from {{ source('ap', 'extraction_errors') }}
where backend = '{{ var("ap_backend") }}'
