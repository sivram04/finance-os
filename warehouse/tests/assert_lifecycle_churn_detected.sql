-- Every churn event in the generator (ground truth) must show up as measured churn: the customer has a
-- 'churn' movement in the churn month or the month after (mid-month churn still bills a partial month),
-- and no revenue afterwards unless a reactivation event follows.
with churns as (
    select e.customer_id, e.event_date,
           exists (select 1 from {{ ref('stg_synthetic__lifecycle_events') }} r
                   where r.customer_id = e.customer_id and r.event_type = 'reactivation'
                     and r.event_date > e.event_date) as reactivated
    from {{ ref('stg_synthetic__lifecycle_events') }} e
    where e.event_type = 'churn'
      and e.event_date < (select max(month) from {{ ref('fct_customer_revenue_monthly') }})
),

measured as (
    select c.customer_id, c.event_date, c.reactivated,
           min(m.month) filter (where m.movement = 'churn' and m.month >= date_trunc('month', c.event_date)) as churn_month
    from churns c
    join {{ ref('fct_customer_revenue_monthly') }} m using (customer_id)
    group by all
)

select *
from measured
where churn_month is null
   or churn_month > date_trunc('month', event_date) + interval 1 month
