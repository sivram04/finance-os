-- Debt facilities (seeds/debt_facilities.csv; lender terms are illustrative). The books carry no debt: both
-- facilities are undrawn, so for each one this shows (a) the actual position (drawn balance and the commitment fee
-- on the undrawn amount) and (b) a pro-forma schedule if the full commitment were drawn the month after the last
-- close: interest-only months, then straight-line amortization, with interest on the opening balance.
-- fct_treasury_covenants tests the covenants these facilities carry.
with draw as (select {{ add_months(closed_through(), 1) }} as draw_month),

months as (
    select f.*, h.n as month_no, {{ add_months("a.draw_month", "h.n") }} as month,
           case when f.facility_type = 'term_loan' then f.commitment else 0 end as pro_forma_draw
    from {{ ref('debt_facilities') }} f
    cross join draw a
    cross join {{ int_series('h', 0, 47) }}
    where h.n < greatest(f.interest_only_months + f.amortization_months, 12)
),

sched as (
    select *,
           case when month_no < interest_only_months or amortization_months = 0 then pro_forma_draw
                else pro_forma_draw * (1 - (month_no - interest_only_months) * 1.0 / amortization_months) end as opening_balance,
           case when month_no >= interest_only_months and amortization_months > 0
                then pro_forma_draw * 1.0 / amortization_months else 0 end as principal
    from months
)

select
    facility_id, lender, facility_type, month, month_no + 1 as schedule_month,
    {{ dec("commitment", 18, 2) }} as commitment,
    {{ dec("drawn", 18, 2) }} as actual_drawn,
    {{ dec("(commitment - drawn) * undrawn_fee / 12", 18, 2) }} as actual_commitment_fee,
    {{ dec("opening_balance", 18, 2) }} as pro_forma_opening_balance,
    {{ dec("opening_balance * annual_rate / 12", 18, 2) }} as pro_forma_interest,
    {{ dec("principal", 18, 2) }} as pro_forma_principal,
    {{ dec("opening_balance - principal", 18, 2) }} as pro_forma_closing_balance,
    {{ dec("opening_balance * annual_rate / 12 + principal", 18, 2) }} as pro_forma_debt_service,
    annual_rate
from sched
