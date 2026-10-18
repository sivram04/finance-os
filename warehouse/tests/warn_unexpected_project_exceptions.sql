{{ config(severity='warn') }}
-- Project exceptions that no injected anomaly explains.
select e.*
from {{ ref('fct_project_exceptions') }} e
where not exists (
    select 1 from {{ ref('stg_synthetic__anomaly_manifest') }} a
    where a.entity_id = e.project_id
      and ((a.kind = 'bill_without_po' and e.exception_type = 'bill_without_po')
        or (a.kind = 'unbilled_milestone' and e.exception_type = 'unbilled_milestone'))
)
