-- Working capital by month: AR and AP balances from the GL, DSO, DPO and the cash conversion cycle.
-- DSO = AR ÷ trailing-3-month revenue × 91 days; DPO = AP ÷ trailing-3-month purchases on credit × 91.
-- No inventory (a software company), so DIO = 0 and CCC = DSO − DPO. AP includes costs accrued at month end.
with balances as (
    select
        month,
        sum(case when account_id = '1200' then amount else 0 end) as ar_change,
        sum(case when account_id = '2000' then -amount else 0 end) as ap_change,
        sum(case when account_id = '2000' then credit else 0 end) as purchases
    from {{ ref('fct_gl_monthly') }}
    group by month
),

joined as (
    select
        b.month,
        p.revenue,
        b.purchases,
        sum(b.ar_change) over (order by b.month) as ar_balance,
        sum(b.ap_change) over (order by b.month) as ap_balance,
        sum(p.revenue) over (order by b.month rows between 2 preceding and current row) as revenue_t3m,
        sum(b.purchases) over (order by b.month rows between 2 preceding and current row) as purchases_t3m
    from balances b
    join {{ ref('int_pnl_monthly') }} p using (month)
)

select
    month,
    cast(ar_balance as decimal(18, 2)) as ar_balance,
    cast(ap_balance as decimal(18, 2)) as ap_balance,
    cast(ar_balance - ap_balance as decimal(18, 2)) as net_working_capital,
    cast(revenue as decimal(18, 2)) as revenue,
    cast(purchases as decimal(18, 2)) as purchases_on_credit,
    cast(round(ar_balance / nullif(revenue_t3m, 0) * 91, 1) as decimal(9, 1)) as dso_days,
    cast(round(ap_balance / nullif(purchases_t3m, 0) * 91, 1) as decimal(9, 1)) as dpo_days,
    cast(0 as decimal(9, 1)) as dio_days,
    cast(round(ar_balance / nullif(revenue_t3m, 0) * 91 - ap_balance / nullif(purchases_t3m, 0) * 91, 1) as decimal(9, 1)) as cash_conversion_cycle_days
from joined
