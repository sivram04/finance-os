-- Open sales pipeline today, one row per open opportunity, with what a pipeline review asks of each deal.
--   weighted ARR     amount × stage probability
--   close quarter    the quarter it is expected to close in (e.g. 2026-Q4)
--   slipped          expected close date already passed and still open (stale: inflates coverage)
--   age days         days since created, against the segment's median won sales cycle
with as_of as (
    select max(entry_date) as d from {{ ref('stg_erp__journal_entries') }}
),

won_cycle as (
    select distinct segment, {{ median_over(days_between("created_date", "close_date"), "segment") }} as median_cycle_days
    from {{ ref('stg_crm__opportunities') }} where is_won
)

select
    o.opportunity_id,
    o.account_name,
    o.segment,
    o.rep_id,
    o.stage,
    o.probability,
    o.amount_arr,
    {{ dec("o.amount_arr * o.probability", 18, 2) }} as weighted_arr,
    o.created_date,
    o.close_date,
    cast(extract(year from o.close_date) as {{ dbt.type_string() }}) || '-Q'
        || cast(cast(floor((extract(month from o.close_date) - 1) / 3) + 1 as int) as {{ dbt.type_string() }}) as close_quarter,
    o.close_date < a.d as is_slipped,
    {{ days_between("o.created_date", "a.d") }} as age_days,
    cast(floor(w.median_cycle_days) as bigint) as median_won_cycle_days
from {{ ref('stg_crm__opportunities') }} o
cross join as_of a
left join won_cycle w on w.segment = o.segment
where not o.is_closed
