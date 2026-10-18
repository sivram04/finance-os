select
    fiscal_year,
    month,
    department_id,
    cast(account_id as {{ t_string() }}) as account_id,
    version,
    {{ dec("amount", 18, 2) }} as amount
from {{ source('erp', 'budgets') }}
