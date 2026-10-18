-- Every churn event in the generator (ground truth) must show up as measured churn: the customer has a
-- 'churn' movement in the churn month or the month after (mid-month churn still bills a partial month),
-- and no revenue afterwards unless a reactivation event follows. A customer won back within about a month
-- never has a zero-revenue month, so those are not expected to show as measured churn.
with churns as (
    select e.customer_id, e.event_date,
           exists (select 1 from {{ ref('stg_synthetic__lifecycle_events') }} r
                   where r.customer_id = e.customer_id and r.event_type = 'reactivation'
                     and r.event_date > e.event_date) as reactivated,
           -- won back before the month after churn ended: no full month without revenue, so nothing to detect
           exists (select 1 from {{ ref('stg_synthetic__lifecycle_events') }} r
                   where r.customer_id = e.customer_id and r.event_type = 'reactivation'
                     and r.event_date > e.event_date
                     and r.event_date < {{ add_months(month_start("e.event_date"), 2) }}) as quick_win_back
    from {{ ref('stg_synthetic__lifecycle_events') }} e
    where e.event_type = 'churn'
      and e.event_date < (select max(month) from {{ ref('fct_customer_revenue_monthly') }})
),

measured as (
    select c.customer_id, c.event_date, c.reactivated, c.quick_win_back,
           min(case when m.movement = 'churn' and m.month >= {{ month_start("c.event_date") }} then m.month end) as churn_month
    from churns c
    join {{ ref('fct_customer_revenue_monthly') }} m using (customer_id)
    group by all
)

select *
from measured
where not quick_win_back
  and (churn_month is null
   or churn_month > {{ add_months(month_start("event_date"), 1) }})
