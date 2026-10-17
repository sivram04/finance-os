-- Double entry: every journal entry's debits equal its credits.
select entry_id, sum(debit) as debits, sum(credit) as credits
from {{ ref('stg_erp__journal_lines') }}
group by entry_id
having sum(debit) <> sum(credit)
