-- Prepaid expense amortization (seeds/prepaid_contracts.csv): straight-line over the service period, with
-- opening and closing prepaid balance per month and the journal entry to post (Dr expense, Cr prepaid).
-- The last month takes the rounding remainder so each contract amortizes to exactly its amount.
with schedule as (
    select p.*, {{ add_months("p.start_month", "h.n") }} as month, h.n as month_no
    from {{ ref('prepaid_contracts') }} p
    cross join {{ int_series('h', 0, 36 - 1) }}
    where h.n < p.months
),

amort as (
    select
        *,
        case when month_no = months - 1
             then amount - round(amount / months, 2) * (months - 1)
             else round(amount / months, 2) end as expense
    from schedule
)

select
    prepaid_id,
    vendor,
    account_id,
    department_id,
    month,
    {{ dec("amount - coalesce(sum(expense) over (partition by prepaid_id order by month
                                              rows between unbounded preceding and 1 preceding), 0)", 18, 2) }} as opening_balance,
    {{ dec("expense", 18, 2) }} as amortization,
    {{ dec("amount - sum(expense) over (partition by prepaid_id order by month)", 18, 2) }} as closing_balance
from amort
