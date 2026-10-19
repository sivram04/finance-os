-- Sales efficiency by month on a trailing-quarter basis (the board convention):
--   magic number = (revenue in the last 3 months - revenue in the 3 months before) x 4 / S&M spend in the 3 months before
-- Above 0.75 is efficient; below 0.5 means each S&M dollar buys little new revenue.
with m as (
    select month,
           sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
           sum(case when account_type = 'opex' and department_id = 'SAL' then natural_amount else 0 end) as sm
    from {{ ref('fct_gl_monthly') }} where month <= {{ closed_through() }} group by 1
),

w as (
    select month,
           sum(revenue) over (order by month rows between 2 preceding and current row) as rev_q,
           sum(revenue) over (order by month rows between 5 preceding and 3 preceding) as rev_prev_q,
           sum(sm) over (order by month rows between 5 preceding and 3 preceding) as sm_prev_q,
           count(*) over (order by month rows between 5 preceding and current row) as n
    from m
)

select month,
       {{ dec("rev_q", 18, 2) }} as revenue_quarter,
       {{ dec("rev_prev_q", 18, 2) }} as revenue_prior_quarter,
       {{ dec("sm_prev_q", 18, 2) }} as sm_prior_quarter,
       case when n = 6 then {{ dec("round(" ~ fdiv("(rev_q - rev_prev_q) * 4", "nullif(sm_prev_q, 0)") ~ ", 2)", 9, 2) }} end as magic_number
from w
