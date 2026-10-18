-- Stripe balance integrity: what was paid out equals the balance that became available, apart from what is still
-- pending at the end of the data (not yet available) and a negative balance carried forward.
with available as (
    select sum(net) as amount from {{ ref('stg_stripe__balance_transactions') }}
    where type in ('charge', 'refund') and available_on <= (select max(cast(created_at as date)) from {{ ref('stg_stripe__balance_transactions') }})
),
paid_out as (
    select -sum(net) as amount from {{ ref('stg_stripe__balance_transactions') }} where type = 'payout'
),
payouts as (
    select sum(amount) as amount from {{ ref('stg_stripe__payouts') }}
)

select a.amount as available, p.amount as payout_txns, po.amount as payouts
from available a
cross join paid_out p
cross join payouts po
cross join (select coalesce(-sum(net), 0) as amount from {{ ref('stg_stripe__balance_transactions') }} where type = 'refund') r
where p.amount <> po.amount              -- payout objects and their balance transactions agree
   or a.amount - p.amount > 0            -- available money is always paid out (daily automatic payouts)
   or a.amount - p.amount < -r.amount    -- the only shortfall allowed is a negative day carried by refunds
