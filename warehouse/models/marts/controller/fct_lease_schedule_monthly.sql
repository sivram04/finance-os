-- ASC 842 operating leases (seeds/leases.csv; lease terms are simulated). For each lease and month: the payment
-- (escalating each lease year), the lease liability (present value of the remaining payments at the incremental
-- borrowing rate, payments in arrears), interest accretion, the single straight-line lease cost, the right-of-use
-- asset (initial liability less cumulative amortization, where amortization = straight-line cost - interest), and
-- the difference between straight-line cost and cash paid: the accrual a controller books when the GL carries cash
-- rent. Balances are closed form, so every month stands alone.
with months as (
    select l.*, h.n as month_no, {{ add_months("l.commencement_month", "h.n") }} as month,
           {{ dec("round(l.monthly_payment * power(1 + l.annual_escalation, floor(h.n / 12)), 2)", 18, 2) }} as payment,
           {{ fdiv("l.incremental_borrowing_rate", 12) }} as r
    from {{ ref('leases') }} l
    cross join {{ int_series('h', 0, 120) }}
    where h.n < l.term_months
),

pv as (  -- liability at the start of each month: remaining payments discounted to that point
    select a.lease_id, a.month_no,
           -- exact decimals (a discount factor fixed at 10 places) so DuckDB and BigQuery agree to the cent
           round(sum(b.payment * {{ dec("power(cast(1 + a.r as " ~ t_float() ~ "), -(b.month_no - a.month_no + 1))", 24, 10) }}), 2) as opening_liability  -- one rounding, to cents
    from months a
    join months b on b.lease_id = a.lease_id and b.month_no >= a.month_no
    group by 1, 2
),

totals as (
    select lease_id, {{ fdiv("sum(payment)", "max(term_months)") }} as straight_line_cost from months group by 1
),

sched as (
    select m.*, p.opening_liability, t.straight_line_cost,
           p.opening_liability * m.r as interest,
           first_value(p.opening_liability) over (partition by m.lease_id order by m.month_no) as initial_liability
    from months m
    join pv p using (lease_id, month_no)
    join totals t using (lease_id)
)

select
    lease_id, description, entity_id, department_id, lease_type, month, month_no + 1 as lease_month,
    month > {{ closed_through() }} as is_future,
    {{ dec("payment", 18, 2) }} as cash_payment,
    {{ dec("opening_liability", 18, 2) }} as opening_liability,
    {{ dec("interest", 18, 2) }} as interest,
    {{ dec("opening_liability + interest - payment", 18, 2) }} as closing_liability,
    {{ dec("straight_line_cost", 18, 2) }} as straight_line_cost,
    {{ dec("straight_line_cost - interest", 18, 2) }} as rou_amortization,
    {{ dec("initial_liability - sum(straight_line_cost - interest) over (partition by lease_id order by month_no)", 18, 2) }} as closing_rou_asset,
    {{ dec("straight_line_cost - payment", 18, 2) }} as cost_minus_cash
from sched
