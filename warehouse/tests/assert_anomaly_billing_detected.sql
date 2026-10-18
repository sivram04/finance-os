-- FR-1.4 for M7: the wrong-rate line is caught by validation, and the accepted-but-unbilled milestone
-- sits in the billing run with an unbilled alert.
with a as (
    select anomaly_id, kind, entity_id, {{ month_start("start_date") }} as start_month
    from {{ ref('stg_synthetic__anomaly_manifest') }}
    where kind in ('wrong_bill_rate', 'unbilled_milestone')
),

checks as (
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_billing_exceptions') }} e
        where e.project_id = a.entity_id and e.exception_type = 'rate_mismatch' and e.service_month = a.start_month) as ok
    from a where kind = 'wrong_bill_rate'
    union all
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_billing_run') }} r
        where r.project_id = a.entity_id and r.item_type = 'milestone' and r.is_unbilled_alert)
    from a where kind = 'unbilled_milestone'
)

select * from checks where not ok
