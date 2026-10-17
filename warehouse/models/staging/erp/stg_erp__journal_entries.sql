select
    entry_id,
    entry_date,
    date_trunc('month', entry_date)::date as entry_month,
    entry_type,
    memo,
    source_ref
from {{ source('erp', 'journal_entries') }}
