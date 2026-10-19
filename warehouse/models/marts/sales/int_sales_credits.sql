-- Commission credits per customer × month, from billed usage revenue (M10, FR-10.2: reconciled to billed revenue).
-- Owner: mid-market and enterprise accounts are assigned round-robin (by customer id) to the reps who cover the
-- segment (seeds/sales_reps.csv); self-serve is house business (no commission).
-- Credit (high-water mark, so usage noise is never paid twice): the first billed month is new ARR (revenue × 12);
-- after that, only revenue above the customer's previous peak month counts, as expansion ARR.
-- Clawback: a customer who churns within the rep's clawback window (days from signup) takes back everything credited.
{{ config(materialized='table') }}
with reps as (
    select r.*, row_number() over (partition by segment_focus order by rep_id) - 1 as slot,
           count(*) over (partition by segment_focus) as reps_in_segment
    from {{ ref('sales_reps') }} r
),

accounts as (
    select c.customer_id, c.segment, c.signup_date,
           row_number() over (partition by c.segment order by c.customer_id) - 1 as seq
    from {{ ref('stg_synthetic__customers') }} c
    where c.segment in (select segment_focus from {{ ref('sales_reps') }})
),

owners as (
    select a.customer_id, a.segment, a.signup_date, r.rep_id
    from accounts a
    join reps r on r.segment_focus = a.segment and r.slot = mod(a.seq, r.reps_in_segment)
),

revenue as (
    select o.rep_id, o.customer_id, o.signup_date, m.month, m.revenue, m.movement,
           max(m.revenue) over (partition by m.customer_id order by m.month
                                rows between unbounded preceding and 1 preceding) as prior_peak
    from {{ ref('fct_customer_revenue_monthly') }} m
    join owners o using (customer_id)
    where m.month <= {{ closed_through() }}
),

credits as (
    select
        rep_id, customer_id, signup_date, month, revenue, movement,
        case when coalesce(prior_peak, 0) = 0 and revenue > 0 then 'new'
             when revenue > prior_peak then 'expansion' end as credit_type,
        case when coalesce(prior_peak, 0) = 0 and revenue > 0 then revenue * 12
             when revenue > prior_peak then (revenue - prior_peak) * 12
             else 0 end as credited_arr
    from revenue
),

churned_early as (
    select c.customer_id, min(c.month) as churn_month
    from credits c
    join {{ ref('sales_reps') }} r on r.rep_id = c.rep_id
    where c.movement = 'churn' and {{ days_between("c.signup_date", "c.month") }} <= r.clawback_days + 31
    group by c.customer_id
)

select
    c.rep_id,
    c.customer_id,
    c.month,
    c.credit_type,
    {{ dec("c.revenue", 18, 2) }} as billed_revenue,
    {{ dec("c.credited_arr", 18, 2) }} as credited_arr,
    false as is_clawback
from credits c
where c.credited_arr > 0

union all

-- the clawback lands in the churn month, for everything credited on that customer before it
select c.rep_id, c.customer_id, e.churn_month, 'clawback', {{ dec("0", 18, 2) }},
       {{ dec("-sum(c.credited_arr)", 18, 2) }}, true
from credits c
join churned_early e using (customer_id)
where c.credited_arr > 0 and c.month < e.churn_month
group by c.rep_id, c.customer_id, e.churn_month
