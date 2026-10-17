-- FR-1.4: each day of an untagged_gpu_cluster anomaly must be flagged as an untagged spike.
-- Day count comes from the manifest start date and the number of days the anomaly lines exist.
with anomaly_days as (
    select a.anomaly_id, c.usage_date
    from {{ ref('stg_synthetic__anomaly_manifest') }} a
    join {{ ref('stg_infra__cloud_costs_daily') }} c
        on c.usage_date >= a.start_date
        and not c.is_tagged
        and c.sku like '%GPU%'
    where a.kind = 'untagged_gpu_cluster'
)

select d.anomaly_id, d.usage_date, u.untagged_cost, u.trailing_median_28d, u.is_spike
from anomaly_days d
join {{ ref('fct_untagged_spend_daily') }} u on u.spend_date = d.usage_date
where not u.is_spike
