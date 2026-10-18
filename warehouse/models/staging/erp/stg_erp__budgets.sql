select
    fiscal_year,
    month,
    department_id,
    cast(account_id as varchar) as account_id,
    version,
    cast(amount as decimal(18, 2)) as amount
from {{ source('erp', 'budgets') }}
