-- Journal-entry testing, the way auditors sample the ledger: each entry with the red flags it raises.
--   manual       keyed by hand rather than produced by a system feed (one-off, capex, funding, opex)
--   weekend      a manual entry posted on a Saturday or Sunday
--   round        a manual entry for a large round amount (at least $10,000 and a multiple of $1,000)
--   period_end   a manual entry posted in the last two days of the month
--   outlier      any entry more than 10x the median size of entries of the same type
-- System feeds (billing, payroll, depreciation, payments) post on schedule, so timing and roundness are not flags
-- for them.
-- risk_score counts the flags; entries with two or more are the sample to review.
with entries as (
    select e.entry_id, e.entry_date, e.entry_month, e.entry_type, e.memo, e.source_ref,
           sum(l.debit) as amount, count(*) as lines
    from {{ ref('stg_erp__journal_entries') }} e
    join {{ ref('stg_erp__journal_lines') }} l using (entry_id)
    where e.entry_month <= {{ closed_through() }}
    group by 1, 2, 3, 4, 5, 6
),

scored as (
    select *,
           entry_type in ('one_off', 'capex', 'funding', 'opex') as is_manual,
           entry_type in ('one_off', 'capex', 'funding', 'opex') and {{ day_of_week("entry_date") }} in (0, 6) as is_weekend,
           entry_type in ('one_off', 'capex', 'funding', 'opex') and amount >= 10000 and amount = round(amount, -3) as is_round,
           amount > 10 * {{ median_over("amount", "entry_type") }} as is_outlier,
           entry_type in ('one_off', 'capex', 'funding', 'opex')
               and {{ days_between("entry_date", add_months("entry_month", 1)) }} <= 2 as is_period_end
    from entries
)

select
    entry_id, entry_date, entry_month, entry_type, memo, source_ref, lines,
    {{ dec("amount", 18, 2) }} as amount,
    is_weekend, is_round, is_manual, is_outlier, is_period_end,
    cast(is_weekend as integer) + cast(is_round as integer) + cast(is_manual as integer)
        + cast(is_outlier as integer) + cast(is_period_end as integer) as risk_score
from scored
