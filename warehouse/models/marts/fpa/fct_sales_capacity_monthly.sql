-- Ramp-adjusted sales capacity by month, from the first month of the books to 12 months ahead: what the account executives on payroll (and the
-- planned AE hires, base scenario) can close, against what was booked (new logos) and credited to sales (new + expansion). seeds/sales_capacity_policy.csv:
--   capacity = quota per ramped AE / 12 × ramp × expected attainment; ramp = months since start / ramp months, max 1
-- A hire contributes from the month after they start (month 1 at 1/ramp_months).
with policy as (
    select
        max(case when parameter = 'quota_per_ramped_ae_arr' then {{ dec("value", 18, 2) }} end) as quota,
        max(case when parameter = 'ramp_months' then cast(value as {{ dbt.type_int() }}) end) as ramp_months,
        max(case when parameter = 'expected_attainment' then {{ dec("value", 9, 4) }} end) as attainment
    from {{ ref('sales_capacity_policy') }}
),

aes as (
    select employee_id as ae_id, {{ month_start("hire_date") }} as start_month, {{ month_start("termination_date") }} as end_month, 'on payroll' as source
    from {{ ref('stg_payroll__employees') }} where title = 'Account Executive'
    union all
    select role_id, {{ month_start("start_month") }}, cast(null as date), 'planned hire'
    from {{ ref('int_planned_hires') }} where scenario = 'base' and title = 'Account Executive'
),

months as (  -- from the first month of the books to 12 months past the last close
    select {{ add_months("f.first_month", "n") }} as month
    from {{ int_series('s', 0, 60) }}
    cross join (select min(entry_month) as first_month from {{ ref('stg_erp__journal_entries') }}) f
    where {{ add_months("f.first_month", "n") }} <= {{ add_months(closed_through(), 12) }}
),

ae_month as (
    select
        m.month, a.ae_id, a.source,
        (extract(year from m.month) - extract(year from a.start_month)) * 12 + extract(month from m.month) - extract(month from a.start_month) as tenure
    from months m
    join aes a on a.start_month < m.month and (a.end_month is null or m.month < a.end_month)
),

cap as (
    select
        am.month,
        count(*) as aes,
        sum(case when am.tenure >= p.ramp_months then 1 else 0 end) as ramped_aes,
        sum(case when am.source = 'planned hire' then 1 else 0 end) as planned_aes,
        -- exact decimals, one rounded division per AE-month, so DuckDB and BigQuery agree to the cent
        sum(round({{ fdiv("p.quota * p.attainment * least(am.tenure, p.ramp_months)", "12 * p.ramp_months") }}, 2)) as capacity_arr
    from ae_month am cross join policy p
    group by 1
),

booked as (
    select month, sum(bookings_arr) as bookings_arr from {{ ref('fct_bookings_monthly') }} group by 1
),

credited as (  -- what sales is paid on: new logos and expansion (fct_commission_statement_monthly)
    select month, sum(new_arr + expansion_arr) as credited_arr from {{ ref('fct_commission_statement_monthly') }} group by 1
)

select
    m.month,
    m.month > {{ closed_through() }} as is_forecast,
    cast(coalesce(c.aes, 0) as bigint) as account_executives,
    cast(coalesce(c.ramped_aes, 0) as bigint) as ramped_aes,
    cast(coalesce(c.planned_aes, 0) as bigint) as planned_aes,
    {{ dec("round(coalesce(c.capacity_arr, 0), 2)", 18, 2) }} as capacity_arr,
    case when m.month <= {{ closed_through() }} then {{ dec("coalesce(b.bookings_arr, 0)", 18, 2) }} end as bookings_arr,
    case when m.month <= {{ closed_through() }} then {{ dec("coalesce(cr.credited_arr, 0)", 18, 2) }} end as credited_arr
from months m
left join cap c using (month)
left join booked b using (month)
left join credited cr using (month)
