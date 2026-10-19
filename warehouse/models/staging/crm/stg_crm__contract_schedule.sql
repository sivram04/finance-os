select
    contract_id,
    contract_year,
    period_start,
    period_end,
    {{ dec("committed_amount", 18, 2) }} as committed_amount
from {{ source('crm', 'contract_schedule') }}
