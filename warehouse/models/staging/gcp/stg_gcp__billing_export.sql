-- Google's billing export, one row per project × service × SKU × hour, flattened: labels to columns, credits
-- summed, invoice month as a date. cost is Google's gross cost; net_cost = cost + credits (credits are negative)
-- is what the invoice charges. Floats from the export become exact decimals at 6 places, as Google bills them.
select
    usage_start_time,
    cast(usage_start_time as date) as usage_date,
    {{ yyyymm_to_date("invoice.month") }} as invoice_month,
    service.description as service,
    sku.description as sku,
    project.id as project_id,
    {{ kv_value("labels", "team") }} as label_team,
    {{ kv_value("labels", "env") }} as label_env,
    {{ kv_value("labels", "team") }} is not null as is_tagged,
    {{ dec("cost", 18, 6) }} as cost,
    {{ dec(sum_credits("credits"), 18, 6) }} as credits,
    {{ dec("cost", 18, 6) }} + {{ dec(sum_credits("credits"), 18, 6) }} as net_cost,
    usage.amount_in_pricing_units as usage_in_pricing_units,
    usage.pricing_unit as pricing_unit
from {{ source('gcp', 'gcp_billing_export_v1') }}
