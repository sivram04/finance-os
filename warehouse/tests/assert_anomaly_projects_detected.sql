-- FR-1.4 for the M6 anomalies, checked at the last month of data.
with a as (
    select anomaly_id, kind, entity_id from {{ ref('stg_synthetic__anomaly_manifest') }} where module in ('M6', 'M7')
),

last_month as (
    select max(month) as month from {{ ref('fct_project_financials') }}
),

checks as (
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_project_financials') }} f, last_month l
        where f.project_id = a.entity_id and f.month = l.month and f.eac_pct_of_budget >= 1.15) as ok
    from a where kind = 'project_over_budget'
    union all
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_project_financials') }} f, last_month l
        where f.project_id = a.entity_id and f.month = l.month and f.is_cap_alert)
    from a where kind = 'tm_cap_threshold'
    union all
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_contract_funding') }} f, last_month l
        where f.contract_id = a.entity_id and f.clin_id = 'TOTAL' and f.month = l.month and f.is_funding_alert_75)
    from a where kind = 'funding_threshold'
    union all
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_project_exceptions') }} e
        where e.project_id = a.entity_id and e.exception_type = 'bill_without_po')
    from a where kind = 'bill_without_po'
    union all
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_project_financials') }} f, last_month l
        where f.project_id = a.entity_id and f.month = l.month and f.unbilled > 0)
        and exists (
        select 1 from {{ ref('fct_project_exceptions') }} e
        where e.project_id = a.entity_id and e.exception_type = 'unbilled_milestone')
    from a where kind = 'unbilled_milestone'
)

select * from checks where not ok
