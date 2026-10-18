-- Grain: customer × month, from the customer's first revenue month to the last month of data.
-- Revenue is GL usage revenue (account 4000). Movements are measured from revenue alone:
--   new          revenue now, none last month, never before
--   reactivation revenue now, none last month, some earlier
--   churn        none now, revenue last month
--   expansion / contraction / flat   revenue both months, up / down / equal
--   inactive     none either month
-- is_usage_spike: revenue > 3× the trailing-3-month average (3 full prior months) and next month falls
-- back below 1.5× that average — a one-off that inflates run-rate metrics like ARR.
with customer_rev as (
    select e.entry_month as month, l.customer_id, -sum(l.amount) as revenue
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '4000'
    group by all
),

months as (
    select distinct entry_month as month from {{ ref('stg_erp__journal_entries') }}
),

first_month as (
    select customer_id, min(month) as first_month from customer_rev group by customer_id
),

grid as (
    select f.customer_id, m.month
    from first_month f
    join months m on m.month >= f.first_month
),

filled as (
    select g.customer_id, g.month, coalesce(r.revenue, 0) as revenue
    from grid g
    left join customer_rev r using (customer_id, month)
),

windowed as (
    select
        *,
        coalesce(lag(revenue) over w, 0) as prior_revenue,
        lead(revenue) over w as next_revenue,
        coalesce(sum(revenue) over (partition by customer_id order by month rows between unbounded preceding and 1 preceding), 0) as revenue_before,
        avg(revenue) over (partition by customer_id order by month rows between 3 preceding and 1 preceding) as avg_prior_3m,
        min(revenue) over (partition by customer_id order by month rows between 3 preceding and 1 preceding) as min_prior_3m,
        count(*) over (partition by customer_id order by month rows between 3 preceding and 1 preceding) as n_prior
    from filled
    window w as (partition by customer_id order by month)
)

select
    month,
    customer_id,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("prior_revenue", 18, 2) }} as prior_revenue,
    {{ dec("revenue - prior_revenue", 18, 2) }} as revenue_change,
    case
        when revenue > 0 and prior_revenue = 0 and revenue_before = 0 then 'new'
        when revenue > 0 and prior_revenue = 0 then 'reactivation'
        when revenue = 0 and prior_revenue > 0 then 'churn'
        when revenue > prior_revenue and prior_revenue > 0 then 'expansion'
        when revenue < prior_revenue and revenue > 0 then 'contraction'
        when revenue > 0 then 'flat'
        else 'inactive'
    end as movement,
    coalesce(
        n_prior = 3 and min_prior_3m > 0
        and revenue > 3 * avg_prior_3m
        and next_revenue < 1.5 * avg_prior_3m,
        false
    ) as is_usage_spike
from windowed
