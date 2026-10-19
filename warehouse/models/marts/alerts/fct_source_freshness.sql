-- When each source system last loaded (max _loaded_at of its raw tables), and how many hours ago (design §11
-- "source stale": alert past 26 hours, i.e. a missed morning run).
{% set sources = [('erp', 'netsuite', 'transaction'), ('stripe', 'stripe', 'invoices'), ('infra', 'infra', 'gpu_jobs'),
                  ('payroll', 'payroll', 'pay_lines'), ('usage', 'synthetic', 'usage_daily'), ('gcp', 'gcp', 'gcp_billing_export_v1')] %}
{% for name, src, table in sources %}
select '{{ name }}' as source,
       max(_loaded_at) as last_loaded_at,
       cast({{ hours_since("max(_loaded_at)") }} as integer) as hours_since_load
from {{ source(src, table) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
