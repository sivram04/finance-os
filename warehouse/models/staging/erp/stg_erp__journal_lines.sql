select
    entry_id,
    line_no,
    cast(account_id as {{ t_string() }}) as account_id,
    department_id,
    customer_id,
    vendor_id,
    {{ dec("debit", 18, 2) }} as debit,
    {{ dec("credit", 18, 2) }} as credit,
    {{ dec("debit - credit", 18, 2) }} as amount
from {{ source('erp', 'journal_lines') }}
