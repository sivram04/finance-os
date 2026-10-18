-- Grain: month. MRR bridge: opening + new + expansion + contraction + churn + reactivation = closing.
-- MRR here is the month's recognized usage revenue (usage business, no subscriptions yet).
-- Contraction and churn are negative. Customer counts follow the same movements.
select
    month,
    cast(sum(prior_revenue) as decimal(18, 2)) as opening_mrr,
    cast(sum(case when movement = 'new' then revenue_change else 0 end) as decimal(18, 2)) as new_mrr,
    cast(sum(case when movement = 'expansion' then revenue_change else 0 end) as decimal(18, 2)) as expansion_mrr,
    cast(sum(case when movement = 'contraction' then revenue_change else 0 end) as decimal(18, 2)) as contraction_mrr,
    cast(sum(case when movement = 'churn' then revenue_change else 0 end) as decimal(18, 2)) as churned_mrr,
    cast(sum(case when movement = 'reactivation' then revenue_change else 0 end) as decimal(18, 2)) as reactivation_mrr,
    cast(sum(revenue) as decimal(18, 2)) as closing_mrr,
    count(*) filter (where prior_revenue > 0) as opening_customers,
    count(*) filter (where movement = 'new') as new_customers,
    count(*) filter (where movement = 'churn') as churned_customers,
    count(*) filter (where movement = 'reactivation') as reactivated_customers,
    count(*) filter (where revenue > 0) as closing_customers
from {{ ref('fct_customer_revenue_monthly') }}
group by month
