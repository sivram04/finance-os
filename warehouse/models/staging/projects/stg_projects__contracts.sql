select
    contract_id,
    customer_id,
    contract_type,
    start_date,
    end_date,
    contract_value,
    ceiling,
    funded_amount,
    payment_terms_days,
    is_federal
from {{ source('projects', 'contracts') }}
