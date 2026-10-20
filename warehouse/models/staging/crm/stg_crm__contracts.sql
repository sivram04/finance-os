select
    contract_id,
    customer_id,
    segment,
    start_date,
    end_date,
    term_months,
    billing_model,
    {{ dec("total_commitment", 18, 2) }} as total_commitment,
    renewal_of,
    status,
    terminated_date
from {{ source('crm', 'customer_contracts') }}
