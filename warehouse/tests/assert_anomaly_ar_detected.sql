-- FR-1.4 for M8: the slow payer is flagged, and the misapplied payment shows as both a remittance
-- mismatch and an overapplied invoice.
with a as (
    select anomaly_id, kind, entity_id from {{ ref('stg_synthetic__anomaly_manifest') }} where module = 'M8'
),

checks as (
    select a.anomaly_id, exists (
        select 1 from {{ ref('fct_customer_payment_behavior') }} b
        where b.customer_id = a.entity_id and b.is_chronic_late) as ok
    from a where kind = 'slow_payer'
    union all
    select a.anomaly_id,
           exists (select 1 from {{ ref('fct_cash_application_exceptions') }} e
                   where e.customer_id = a.entity_id and e.exception_type = 'remittance_mismatch')
       and exists (select 1 from {{ ref('fct_cash_application_exceptions') }} e
                   where e.customer_id = a.entity_id and e.exception_type = 'overapplied')
    from a where kind = 'misapplied_payment'
)

select * from checks where not ok

union all

-- and no reminder is queued for a customer whose payment was misapplied
select a.anomaly_id, false
from a
join {{ ref('fct_collections_queue') }} q on q.customer_id = a.entity_id
where a.kind = 'misapplied_payment' and q.reminder_tone is not null
