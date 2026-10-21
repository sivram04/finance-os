-- Every cash movement in the ledger (account 1000) matched to the bank statement line that cleared it.
-- A ledger cash item is one entity's cash for one source reference on one day (a Stripe payment and its fee
-- arrive as one net payout, so they are one item). It matches the first statement line on the same account with
-- the same reference, the same direction, cleared on or within 20 days after the booking date. Unmatched items have
-- not cleared yet; amount_difference <> 0 means the ledger and the bank disagree on a cleared item.
with gl as (
    select
        l.entity_id,
        e.entry_date,
        coalesce(e.source_ref, e.entry_id) as reference,
        min(e.entry_id) as entry_id,
        min(e.entry_type) as entry_type,
        min(e.memo) as memo,
        sum(l.amount) as amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e on e.entry_id = l.entry_id
    where l.account_id = '1000'
    group by l.entity_id, e.entry_date, coalesce(e.source_ref, e.entry_id)
    having sum(l.amount) <> 0
),

candidates as (
    select
        g.entity_id, g.entry_date, g.reference,
        b.statement_line_id, b.posted_date, b.amount as bank_amount, b.description as bank_description,
        row_number() over (partition by g.entity_id, g.entry_date, g.reference order by b.posted_date, b.statement_line_id) as rn_gl,
        row_number() over (partition by b.statement_line_id order by g.entry_date desc, g.reference) as rn_bank
    from gl g
    join {{ ref('stg_bank__statement_lines') }} b
      on b.entity_id = g.entity_id
     and b.bank_reference = g.reference
     and not b.is_bank_only
     and b.posted_date between g.entry_date and {{ add_days("g.entry_date", 20) }}
     and sign(b.amount) = sign(g.amount)
)

select
    g.entity_id,
    g.entry_date,
    g.reference,
    g.entry_id,
    g.entry_type,
    g.memo,
    g.amount,
    c.statement_line_id,
    c.posted_date as cleared_date,
    c.bank_amount,
    c.bank_description,
    {{ dec("coalesce(c.bank_amount - g.amount, 0)", 18, 2) }} as amount_difference
from gl g
left join candidates c
  on c.entity_id = g.entity_id and c.entry_date = g.entry_date and c.reference = g.reference
 and c.rn_gl = 1 and c.rn_bank = 1
