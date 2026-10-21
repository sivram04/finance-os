-- Bank statement lines: what cleared the account, when, for how much (deposits positive, withdrawals negative).
-- transaction_code says what kind of movement it was; bank_fee and interest exist only on the bank's side.
select
    statement_line_id,
    bank_account_id,
    entity_id,
    cast(posted_date as date) as posted_date,
    {{ month_start("posted_date") }} as posted_month,
    {{ dec("amount", 18, 2) }} as amount,
    description,
    bank_reference,
    transaction_code,
    transaction_code in ('bank_fee', 'interest') as is_bank_only
from {{ source('bank', 'statement_lines') }}
