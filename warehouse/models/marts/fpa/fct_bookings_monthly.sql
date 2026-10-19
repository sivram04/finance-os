-- Sales-led bookings per month and segment: what closed, at what win rate and cycle, from the CRM.
--   bookings ARR       ARR of deals won in the month
--   win rate           won / (won + lost) by count, trailing 6 months (monthly counts are too small to read)
--   avg cycle days     created → won, for deals won in the month
with o as (
    select
        {{ month_start("close_date") }} as month,
        segment,
        count(case when is_won then 1 end) as won_deals,
        count(case when stage = 'closed_lost' then 1 end) as lost_deals,
        sum(case when is_won then amount_arr else 0 end) as bookings_arr,
        sum(case when stage = 'closed_lost' then amount_arr else 0 end) as lost_arr,
        avg(case when is_won then {{ days_between("created_date", "close_date") }} end) as avg_cycle_days
    from {{ ref('stg_crm__opportunities') }}
    where is_closed and close_date <= (select max(entry_date) from {{ ref('stg_erp__journal_entries') }})
    group by 1, 2
),

w as (
    select
        *,
        sum(won_deals) over (partition by segment order by month rows between 5 preceding and current row) as won_t6m,
        sum(won_deals + lost_deals) over (partition by segment order by month rows between 5 preceding and current row) as closed_t6m
    from o
)

select
    month,
    segment,
    cast(won_deals as bigint) as won_deals,
    cast(lost_deals as bigint) as lost_deals,
    {{ dec("bookings_arr", 18, 2) }} as bookings_arr,
    {{ dec("lost_arr", 18, 2) }} as lost_arr,
    {{ dec("round(avg_cycle_days, 1)", 9, 1) }} as avg_cycle_days,
    {{ dec("round(" ~ fdiv("won_t6m", "nullif(closed_t6m, 0)") ~ ", 4)", 9, 4) }} as win_rate_t6m
from w
