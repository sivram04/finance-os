-- Bank statement <-> GL cash, by entity and month end (fct_bank_reconciliation). Passes when the adjusted bank and
-- adjusted book balances agree to the cent: every difference is a known reconciling item. Book-side items (fees,
-- interest, keying errors) are counted in the explanation because they still need a journal entry.
select
    'bank_statement_vs_gl_cash' as check_name,
    month as period,
    entity_id,
    adjusted_bank_balance as expected,
    adjusted_book_balance as actual,
    adjusted_book_balance - adjusted_bank_balance as variance,
    {{ dec("null", 9, 4) }} as variance_pct,
    {{ dec("0", 9, 4) }} as tolerance_pct,
    case when unexplained_difference = 0 then 'pass' else 'fail' end as status,
    case when unexplained_difference <> 0 then 'Unexplained difference between bank and ledger: investigate'
         else concat('Reconciled: ', cast(deposits_in_transit_count as {{ t_string() }}), ' deposit(s) in transit, ',
                     cast(outstanding_payments_count as {{ t_string() }}), ' outstanding payment(s); ',
                     cast(items_to_book as {{ t_string() }}), ' bank item(s) to book') end as explanation
from {{ ref('fct_bank_reconciliation') }}
