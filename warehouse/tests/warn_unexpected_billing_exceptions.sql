{{ config(severity='warn') }}
-- Billing exceptions that no injected anomaly explains.
select e.*
from {{ ref('fct_billing_exceptions') }} e
where not exists (
    select 1 from {{ ref('stg_synthetic__anomaly_manifest') }} a
    where a.kind = 'wrong_bill_rate' and a.entity_id = e.project_id
      and e.exception_type = 'rate_mismatch' and e.service_month = {{ month_start("a.start_date") }}
)
