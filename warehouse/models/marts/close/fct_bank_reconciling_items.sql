-- Bank reconciliation, item by item, at each month end since the bank feed started (closed months only).
-- Bank side (adjusts the statement balance to what the ledger should show):
--   deposit_in_transit     booked in the ledger, not yet on the statement
--   outstanding_payment    cheque or payment booked, not yet cleared
-- Book side (adjusts the ledger to what the bank shows; these need a journal entry):
--   bank_fee / interest    on the statement only, not recorded in the ledger
--   unrecorded_bank_item   any other statement line with no ledger entry
--   ledger_error           cleared at a different amount than the ledger recorded (amount = bank - ledger)
-- Adjusted bank balance = statement + bank-side items; adjusted book balance = ledger + book-side items.
with months as (
    select distinct posted_month as month, last_day(posted_month) as month_end
    from {{ ref('stg_bank__statement_lines') }}
    where is_bank_only and posted_month <= {{ closed_through() }}
),

matches as (
    select * from {{ ref('int_bank_cash_matches') }}
),

matched_lines as (
    select distinct statement_line_id from matches where statement_line_id is not null
),

timing as (
    select
        m.month, x.entity_id,
        case when x.amount > 0 then 'deposit_in_transit' else 'outstanding_payment' end as item_type,
        'bank' as side,
        x.entry_date as item_date,
        x.reference, x.entry_id, cast(null as {{ t_string() }}) as statement_line_id,
        x.memo as description,
        x.amount,
        {{ days_between("x.entry_date", "m.month_end") }} as days_outstanding
    from months m
    join matches x on x.entry_date <= m.month_end and (x.cleared_date is null or x.cleared_date > m.month_end)
),

bank_only as (
    select
        m.month, b.entity_id,
        case when b.transaction_code in ('bank_fee', 'interest') then b.transaction_code else 'unrecorded_bank_item' end as item_type,
        'book' as side,
        b.posted_date as item_date,
        b.bank_reference as reference, cast(null as {{ t_string() }}) as entry_id, b.statement_line_id,
        b.description,
        b.amount,
        {{ days_between("b.posted_date", "m.month_end") }} as days_outstanding
    from months m
    join {{ ref('stg_bank__statement_lines') }} b on b.posted_date <= m.month_end
    left join matched_lines ml on ml.statement_line_id = b.statement_line_id
    where ml.statement_line_id is null
),

errors as (
    select
        m.month, x.entity_id,
        'ledger_error' as item_type,
        'book' as side,
        x.cleared_date as item_date,
        x.reference, x.entry_id, x.statement_line_id,
        x.memo as description,
        x.amount_difference as amount,
        {{ days_between("x.cleared_date", "m.month_end") }} as days_outstanding
    from months m
    join matches x on x.cleared_date <= m.month_end and x.amount_difference <> 0
),

items as (
    select * from timing
    union all select * from bank_only
    union all select * from errors
)

select
    month,
    entity_id,
    item_type,
    side,
    item_date,
    reference,
    entry_id,
    statement_line_id,
    description,
    {{ dec("amount", 18, 2) }} as amount,
    days_outstanding,
    case
        when item_type = 'deposit_in_transit' then 'Clears on its own; follow up if still open after 5 days'
        when item_type = 'outstanding_payment' and days_outstanding > 30 then 'Stale: contact the payee or void and reissue'
        when item_type = 'outstanding_payment' then 'Clears when the payee deposits it'
        when item_type = 'bank_fee' then 'Book it: debit bank charges, credit cash'
        when item_type = 'interest' then 'Book it: debit cash, credit interest income'
        when item_type = 'ledger_error' then 'Correct the ledger entry to the cleared amount'
        else 'Investigate: on the statement with no ledger entry'
    end as action,
    side = 'book' as needs_journal_entry
from items
