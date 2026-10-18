select
    contract_id,
    labor_category,
    bill_rate
from {{ source('projects', 'contract_rates') }}
