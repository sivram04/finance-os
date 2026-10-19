-- Google Cloud cost per day × service × SKU × team × environment, from Google's own billing export
-- (gross cost, credits, net). The export is what Google invoices; fct_tech_spend_daily is our own metering.
select
    usage_date,
    invoice_month,
    service,
    sku,
    project_id,
    coalesce(label_team, 'untagged') as team,
    coalesce(label_env, 'untagged') as env,
    {{ dec("sum(cost)", 18, 2) }} as gross_cost,
    {{ dec("sum(credits)", 18, 2) }} as credits,
    {{ dec("sum(net_cost)", 18, 2) }} as net_cost
from {{ ref('stg_gcp__billing_export') }}
group by 1, 2, 3, 4, 5, 6, 7
