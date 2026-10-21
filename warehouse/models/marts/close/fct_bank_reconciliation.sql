-- Bank reconciliation by entity and month end: statement balance and ledger cash balance, each adjusted by its
-- reconciling items (fct_bank_reconciling_items). Reconciled when the two adjusted balances agree to the cent;
-- book-side items still need a journal entry even then.
with months as (
    select distinct month, last_day(month) as month_end from {{ ref('fct_bank_reconciling_items') }}
),

accounts as (
    select bank_account_id, entity_id, bank_name from {{ ref('stg_bank__accounts') }}
),

bank as (
    select m.month, b.entity_id, sum(b.amount) as bank_balance
    from months m join {{ ref('stg_bank__statement_lines') }} b on b.posted_date <= m.month_end
    group by m.month, b.entity_id
),

ledger as (
    select m.month, x.entity_id, sum(x.amount) as gl_balance
    from months m join {{ ref('int_bank_cash_matches') }} x on x.entry_date <= m.month_end
    group by m.month, x.entity_id
),

items as (
    select
        month, entity_id,
        sum(case when item_type = 'deposit_in_transit' then amount else 0 end) as deposits_in_transit,
        sum(case when item_type = 'outstanding_payment' then -amount else 0 end) as outstanding_payments,
        sum(case when item_type in ('bank_fee', 'interest', 'unrecorded_bank_item') then amount else 0 end) as unrecorded_bank_items,
        sum(case when item_type = 'ledger_error' then amount else 0 end) as ledger_errors,
        sum(case when side = 'bank' then amount else 0 end) as bank_adjustments,
        sum(case when side = 'book' then amount else 0 end) as book_adjustments,
        count(case when item_type = 'deposit_in_transit' then 1 end) as deposits_in_transit_count,
        count(case when item_type = 'outstanding_payment' then 1 end) as outstanding_payments_count,
        count(case when needs_journal_entry then 1 end) as items_to_book
    from {{ ref('fct_bank_reconciling_items') }}
    group by month, entity_id
),

joined as (
    select
        m.month, a.entity_id, a.bank_account_id, a.bank_name,
        coalesce(b.bank_balance, 0) as bank_balance,
        coalesce(l.gl_balance, 0) as gl_balance,
        coalesce(i.deposits_in_transit, 0) as deposits_in_transit,
        coalesce(i.outstanding_payments, 0) as outstanding_payments,
        coalesce(i.unrecorded_bank_items, 0) as unrecorded_bank_items,
        coalesce(i.ledger_errors, 0) as ledger_errors,
        coalesce(b.bank_balance, 0) + coalesce(i.bank_adjustments, 0) as adjusted_bank_balance,
        coalesce(l.gl_balance, 0) + coalesce(i.book_adjustments, 0) as adjusted_book_balance,
        coalesce(i.deposits_in_transit_count, 0) as deposits_in_transit_count,
        coalesce(i.outstanding_payments_count, 0) as outstanding_payments_count,
        coalesce(i.items_to_book, 0) as items_to_book
    from months m
    cross join accounts a
    left join bank b on b.month = m.month and b.entity_id = a.entity_id
    left join ledger l on l.month = m.month and l.entity_id = a.entity_id
    left join items i on i.month = m.month and i.entity_id = a.entity_id
)

select
    month, entity_id, bank_account_id, bank_name,
    {{ dec("bank_balance", 18, 2) }} as bank_balance,
    {{ dec("deposits_in_transit", 18, 2) }} as deposits_in_transit,
    {{ dec("outstanding_payments", 18, 2) }} as outstanding_payments,
    {{ dec("adjusted_bank_balance", 18, 2) }} as adjusted_bank_balance,
    {{ dec("gl_balance", 18, 2) }} as gl_balance,
    {{ dec("unrecorded_bank_items", 18, 2) }} as unrecorded_bank_items,
    {{ dec("ledger_errors", 18, 2) }} as ledger_errors,
    {{ dec("adjusted_book_balance", 18, 2) }} as adjusted_book_balance,
    {{ dec("adjusted_bank_balance - adjusted_book_balance", 18, 2) }} as unexplained_difference,
    deposits_in_transit_count,
    outstanding_payments_count,
    items_to_book,
    case when adjusted_bank_balance <> adjusted_book_balance then 'difference'
         when items_to_book > 0 then 'reconciled, entries to book'
         else 'reconciled' end as status
from joined
