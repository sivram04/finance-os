-- Grain: month. MRR bridge: opening + new + expansion + contraction + churn + reactivation = closing.
-- MRR here is the month's recognized usage revenue (usage business, no subscriptions yet).
-- Contraction and churn are negative. Customer counts follow the same movements.
select
    month,
    {{ dec("sum(prior_revenue)", 18, 2) }} as opening_mrr,
    {{ dec("sum(case when movement = 'new' then revenue_change else 0 end)", 18, 2) }} as new_mrr,
    {{ dec("sum(case when movement = 'expansion' then revenue_change else 0 end)", 18, 2) }} as expansion_mrr,
    {{ dec("sum(case when movement = 'contraction' then revenue_change else 0 end)", 18, 2) }} as contraction_mrr,
    {{ dec("sum(case when movement = 'churn' then revenue_change else 0 end)", 18, 2) }} as churned_mrr,
    {{ dec("sum(case when movement = 'reactivation' then revenue_change else 0 end)", 18, 2) }} as reactivation_mrr,
    {{ dec("sum(revenue)", 18, 2) }} as closing_mrr,
    count(case when prior_revenue > 0 then 1 end) as opening_customers,
    count(case when movement = 'new' then 1 end) as new_customers,
    count(case when movement = 'churn' then 1 end) as churned_customers,
    count(case when movement = 'reactivation' then 1 end) as reactivated_customers,
    count(case when revenue > 0 then 1 end) as closing_customers
from {{ ref('fct_customer_revenue_monthly') }}
group by month
