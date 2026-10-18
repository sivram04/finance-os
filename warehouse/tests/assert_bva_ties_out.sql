-- BvA must not lose or invent amounts: per month, actual = GL income-statement total and
-- budget = original budget total.
with bva as (
    select month, sum(actual) as actual, sum(budget) as budget
    from {{ ref('fct_bva_monthly') }}
    group by month
),

gl as (
    select month, sum(natural_amount) as actual
    from {{ ref('fct_gl_monthly') }}
    where account_type in ('revenue', 'cogs', 'opex')
    group by month
),

budget as (
    select month, sum(amount) as budget
    from {{ ref('stg_erp__budgets') }}
    where version = 'original' and month <= (select max(month) from {{ ref('fct_bva_monthly') }})
    group by month
)

select b.month, b.actual, g.actual as gl_actual, b.budget, bu.budget as source_budget
from bva b
full outer join gl g using (month)
full outer join budget bu using (month)
where b.actual is distinct from g.actual
   or b.budget is distinct from bu.budget
