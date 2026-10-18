-- The bridge must close: opening + all movements = closing, and customer counts likewise.
select *
from {{ ref('fct_mrr_bridge_monthly') }}
where opening_mrr + new_mrr + expansion_mrr + contraction_mrr + churned_mrr + reactivation_mrr <> closing_mrr
   or opening_customers + new_customers + reactivated_customers - churned_customers <> closing_customers
