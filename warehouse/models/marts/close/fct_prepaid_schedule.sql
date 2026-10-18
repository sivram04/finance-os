-- Prepaid expense amortization (seeds/prepaid_contracts.csv): straight-line over the service period, with
-- opening and closing prepaid balance per month and the journal entry to post (Dr expense, Cr prepaid).
-- The last month takes the rounding remainder so each contract amortizes to exactly its amount.
with months as (
    select p.*, cast(p.start_month + to_months(cast(h.n as integer)) as date) as month, h.n as month_no
    from {{ ref('prepaid_contracts') }} p
    cross join range(0, 36) h(n)
    where h.n < p.months
),

amort as (
    select
        *,
        case when month_no = months - 1
             then amount - round(amount / months, 2) * (months - 1)
             else round(amount / months, 2) end as expense
    from months
)

select
    prepaid_id,
    vendor,
    account_id,
    department_id,
    month,
    cast(amount - coalesce(sum(expense) over (partition by prepaid_id order by month
                                              rows between unbounded preceding and 1 preceding), 0) as decimal(18, 2)) as opening_balance,
    cast(expense as decimal(18, 2)) as amortization,
    cast(amount - sum(expense) over (partition by prepaid_id order by month) as decimal(18, 2)) as closing_balance
from amort
