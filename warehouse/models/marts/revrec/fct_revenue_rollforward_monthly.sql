-- Deferred revenue and contract asset roll-forward by month (the schedule auditors ask for):
-- opening + billings − recognized = closing, and ASC 606 revenue vs what the GL booked.
with m as (
    select
        month,
        sum(billed) as billings,
        sum(asc606_revenue) as asc606_revenue,
        sum(gl_revenue) as gl_revenue,
        sum(contract_asset) as contract_asset,
        sum(contract_liability) as contract_liability
    from {{ ref('fct_revenue_schedule_monthly') }}
    group by month
)

select
    month,
    cast(coalesce(lag(contract_liability - contract_asset) over (order by month), 0) as decimal(18, 2)) as opening_net_deferred,
    cast(billings as decimal(18, 2)) as billings,
    cast(asc606_revenue as decimal(18, 2)) as asc606_revenue,
    cast(contract_liability - contract_asset as decimal(18, 2)) as closing_net_deferred,
    cast(contract_asset as decimal(18, 2)) as contract_asset,
    cast(contract_liability as decimal(18, 2)) as contract_liability,
    cast(gl_revenue as decimal(18, 2)) as gl_revenue,
    cast(asc606_revenue - gl_revenue as decimal(18, 2)) as revenue_adjustment
from m
