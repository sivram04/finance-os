-- The governed metric layer: every catalogued metric's value by month, in one place, whichever mart computes it.
-- Pages, the assistant and reports read metrics from here or from the mart named in the catalog; the catalog
-- (seeds/metric_catalog.csv) holds the contract (definition, version, owner); this table holds the numbers.
select month, metric_name, value, 'fct_kpi_monthly' as source_model from {{ ref('fct_kpi_monthly') }}
{% for col in ['net_new_arr', 'quick_ratio', 'burn_multiple'] %}
union all
select month, '{{ col }}', {{ dec(col, 18, 4) }}, 'fct_growth_efficiency_monthly' from {{ ref('fct_growth_efficiency_monthly') }} where {{ col }} is not null
{% endfor %}
{% for col in ['rule_of_40', 'cac', 'cac_burdened', 'ltv_to_cac_burdened', 'cac_payback_burdened_months'] %}
union all
select month, '{{ col }}', {{ dec(col, 18, 4) }}, 'fct_saas_metrics_monthly' from {{ ref('fct_saas_metrics_monthly') }} where {{ col }} is not null
{% endfor %}
union all
select month, 'magic_number', {{ dec("magic_number", 18, 4) }}, 'fct_efficiency_quarterly' from {{ ref('fct_efficiency_quarterly') }} where magic_number is not null
{% for col in ['contracted_arr', 'rpo', 'crpo'] %}
union all
select month, '{{ col }}', {{ dec("sum(" ~ col ~ ")", 18, 4) }}, 'fct_contract_revenue_monthly' from {{ ref('fct_contract_revenue_monthly') }} group by month
{% endfor %}
