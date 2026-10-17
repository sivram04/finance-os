{{ config(severity='warn') }}
-- Untagged spikes that no injected anomaly explains: real findings to investigate.
with explained as (
    select c.usage_date
    from {{ ref('stg_synthetic__anomaly_manifest') }} a
    join {{ ref('stg_infra__cloud_costs_daily') }} c
        on c.usage_date >= a.start_date and not c.is_tagged and c.sku like '%GPU%'
    where a.kind = 'untagged_gpu_cluster'
)

select u.*
from {{ ref('fct_untagged_spend_daily') }} u
where u.is_spike
  and u.spend_date not in (select usage_date from explained)
