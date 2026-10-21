-- Operating bank accounts: one per legal entity.
select
    bank_account_id,
    entity_id,
    bank_name,
    currency,
    {{ dec("monthly_fee", 18, 2) }} as monthly_fee
from {{ source('bank', 'accounts') }}
