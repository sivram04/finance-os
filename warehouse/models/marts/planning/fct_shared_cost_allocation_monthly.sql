-- Shared overhead (software, facilities, professional fees; seeds/shared_cost_allocation.csv) re-allocated
-- from where it was booked to every department by month-end headcount share. Totals are preserved: each
-- account's allocated amounts sum to what the GL booked (tested).
with pool as (
    select g.month, g.account_id, s.pool, sum(g.natural_amount) as amount
    from {{ ref('fct_gl_monthly') }} g
    join {{ ref('shared_cost_allocation') }} s on cast(s.account_id as varchar) = g.account_id
    group by all
),

heads as (
    select month, department_id, headcount,
           headcount / sum(headcount) over (partition by month) as share
    from {{ ref('fct_headcount_monthly') }}
    where headcount > 0
)

select
    p.month,
    p.account_id,
    p.pool,
    h.department_id,
    h.headcount,
    cast(round(h.share, 6) as decimal(9, 6)) as headcount_share,
    cast(p.amount as decimal(18, 2)) as pool_amount,
    cast(p.amount * h.share as decimal(18, 6)) as allocated_amount
from pool p
join heads h using (month)
