-- Every bridge must add up: opening + steps = closing (cloud cost by product and total; margin and burn bridges).
select 'cloud' as bridge, month, product_id as k
from {{ ref('fct_cloud_cost_bridge_monthly') }}
where abs(opening + demand + efficiency + rate + shared + commitment + other_cloud - closing) > 0.05
union all
select bridge, month, 'all'
from {{ ref('fct_margin_burn_bridge_monthly') }}
group by bridge, month
having abs(sum(case when step_order between 0 and 8 then amount else 0 end) - sum(case when step_order = 9 then amount else 0 end)) > 0.05
