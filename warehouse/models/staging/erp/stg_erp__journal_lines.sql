select
    entry_id,
    line_no,
    cast(account_id as varchar) as account_id,
    department_id,
    customer_id,
    vendor_id,
    cast(debit as decimal(18, 2)) as debit,
    cast(credit as decimal(18, 2)) as credit,
    cast(debit - credit as decimal(18, 2)) as amount
from {{ source('erp', 'journal_lines') }}
