-- Committed-use contracts by contract x closed month: what the customer owes us under contract and how fast it is
-- being consumed. Measured at each month end (me).
--   current_commitment   this contract year's committed amount (ramps step up each year)
--   consumed_ytd         usage revenue billed in this contract year so far (billing months from the year's first month)
--   remaining_current    commitment not yet consumed this year (owed: billed as usage or trued up at year end)
--   future_commitment    later contract years not started yet
--   rpo                  remaining performance obligation = remaining_current + future_commitment
--   crpo                 the part of RPO expected in the next 12 months (future years prorated by days)
--   contracted_arr       current-year commitment, annualized (contract years are 12 months)
--   burn_pace            consumed / (commitment x elapsed share of the year): 1.0 = on pace, below = shortfall risk
--   projected_shortfall  commitment minus usage at the year-to-date run rate, if positive (true-up or credits lost)
--   projected_overage    usage at the run rate above the commitment, if positive (billed as overage)
--   days_to_renewal      days from month end to the contract end (renewal base when the contract is in its last 180 days)
with months as (
    select distinct month from {{ ref('fct_customer_revenue_monthly') }} where month <= {{ closed_through() }}
),

c as (
    select c.*, m.month, {{ add_months("m.month", 1) }} as next_month
    from {{ ref('stg_crm__contracts') }} c
    cross join months m
    where c.start_date < {{ add_months("m.month", 1) }}
      and c.end_date >= {{ add_months("m.month", 1) }}
      and (c.terminated_date is null or c.terminated_date >= {{ add_months("m.month", 1) }})
),

years as (
    select c.contract_id, c.month, s.contract_year, s.period_start, s.period_end, s.committed_amount
    from c join {{ ref('stg_crm__contract_schedule') }} s using (contract_id)
),

cur as (
    select * from years where period_start < {{ add_months("month", 1) }} and period_end >= {{ add_months("month", 1) }}
),

consumed as (
    select y.contract_id, y.month, sum(r.revenue) as consumed
    from cur y
    join {{ ref('stg_crm__contracts') }} k using (contract_id)
    join {{ ref('fct_customer_revenue_monthly') }} r
      on r.customer_id = k.customer_id and r.month between {{ month_start("y.period_start") }} and y.month
    group by 1, 2
),

future as (
    select contract_id, month, sum(committed_amount) as future_commitment,
           sum(committed_amount * least(greatest({{ days_between(add_months("month", 1), "least(period_end, " ~ add_months(add_months("month", 1), 12) ~ ")") }} - {{ days_between(add_months("month", 1), "period_start") }}, 0), 365) / 365.0) as future_within_12m
    from years where period_start >= {{ add_months("month", 1) }}
    group by 1, 2
),

pos as (
    select c.month, c.contract_id, c.customer_id, c.segment, c.billing_model, c.start_date, c.end_date, c.status,
           cur.contract_year, cur.committed_amount as current_commitment,
           coalesce(x.consumed, 0) as consumed_ytd,
           {{ days_between("c.next_month", "c.end_date") }} + 1 as days_to_renewal,
           least((extract(year from c.month) - extract(year from {{ month_start("cur.period_start") }})) * 12
                 + extract(month from c.month) - extract(month from {{ month_start("cur.period_start") }}) + 1, 12) as elapsed_months,
           coalesce(f.future_commitment, 0) as future_commitment,
           coalesce(f.future_within_12m, 0) as future_within_12m
    from c
    join cur using (contract_id, month)
    left join consumed x using (contract_id, month)
    left join future f using (contract_id, month)
)

select
    month, contract_id, customer_id, segment, billing_model, start_date, end_date, contract_year,
    cast(elapsed_months as bigint) as elapsed_months,
    {{ dec("current_commitment", 18, 2) }} as current_commitment,
    {{ dec("round(consumed_ytd, 2)", 18, 2) }} as consumed_ytd,
    {{ dec("round(greatest(current_commitment - consumed_ytd, 0), 2)", 18, 2) }} as remaining_current,
    {{ dec("future_commitment", 18, 2) }} as future_commitment,
    {{ dec("round(greatest(current_commitment - consumed_ytd, 0) + future_commitment, 2)", 18, 2) }} as rpo,
    {{ dec("round(greatest(current_commitment - consumed_ytd, 0) + future_within_12m, 2)", 18, 2) }} as crpo,
    {{ dec("current_commitment", 18, 2) }} as contracted_arr,
    {{ dec("round(" ~ fdiv("consumed_ytd * 12", "current_commitment * elapsed_months") ~ ", 4)", 9, 4) }} as burn_pace,
    {{ dec("round(greatest(current_commitment - " ~ fdiv("consumed_ytd * 12", "elapsed_months") ~ ", 0), 2)", 18, 2) }} as projected_shortfall,
    {{ dec("round(greatest(" ~ fdiv("consumed_ytd * 12", "elapsed_months") ~ " - current_commitment, 0), 2)", 18, 2) }} as projected_overage,
    cast(days_to_renewal as bigint) as days_to_renewal,
    days_to_renewal <= 180 as in_renewal_window
from pos
