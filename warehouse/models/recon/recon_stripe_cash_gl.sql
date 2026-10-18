-- FR-12.2: Stripe balance (charges net of fees, refunds) ↔ GL cash booked for usage billing, by month.
-- GL side: cash lines of collection, payment_fee and refund entries. Payouts move money from the Stripe
-- balance to the bank and are excluded on both sides (the GL books cash at the charge, as Stripe's balance does).
with stripe as (
    select cast({{ dbt.date_trunc('month', 'created_at') }} as date) as month, sum(net) as amount
    from {{ ref('stg_stripe__balance_transactions') }}
    where type in ('charge', 'refund')
    group by 1
),

gl as (
    select e.entry_month as month, sum(l.amount) as amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '1000' and e.entry_type in ('collection', 'payment_fee', 'refund')
    group by 1
)

select
    'stripe_balance_vs_gl_cash' as check_name,
    coalesce(s.month, g.month) as period,
    'all' as entity_id,
    s.amount as expected,
    g.amount as actual,
    coalesce(g.amount, 0) - coalesce(s.amount, 0) as variance,
    cast(null as decimal(9, 4)) as variance_pct,
    cast(0 as decimal(9, 4)) as tolerance_pct,
    case when g.amount is not distinct from s.amount then 'pass' else 'fail' end as status,
    case when g.amount is not distinct from s.amount then 'Exact match (charges net of fees, and refunds)'
         else 'GL cash differs from the Stripe balance: investigate' end as explanation
from stripe s
full outer join gl g using (month)
