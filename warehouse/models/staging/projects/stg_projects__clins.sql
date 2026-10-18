select
    contract_id,
    clin_id,
    description,
    ceiling,
    funded
from {{ source('projects', 'clins') }}
