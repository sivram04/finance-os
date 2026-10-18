select
    entry_id,
    entry_date,
    {{ month_start("entry_date") }} as entry_month,
    entry_type,
    memo,
    source_ref
from {{ source('erp', 'journal_entries') }}
