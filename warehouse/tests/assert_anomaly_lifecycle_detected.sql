-- FR-1.4 for the M4 anomalies.
-- A-M4-01 enterprise_churn: contraction in the start month and churn in the month after the churn event.
-- A-M4-02 usage_spike: is_usage_spike in the start month.
with a as (
    select anomaly_id, kind, entity_id, date_trunc('month', start_date) as start_month
    from {{ ref('stg_synthetic__anomaly_manifest') }}
    where kind in ('enterprise_churn', 'usage_spike')
),

churn_event as (
    select customer_id, date_trunc('month', max(event_date)) as churn_month
    from {{ ref('stg_synthetic__lifecycle_events') }}
    where event_type = 'churn'
    group by customer_id
),

checks as (
    select a.anomaly_id, 'contraction at start' as expectation,
           exists (select 1 from {{ ref('fct_customer_revenue_monthly') }} m
                   where m.customer_id = a.entity_id and m.month = a.start_month and m.movement = 'contraction') as ok
    from a where a.kind = 'enterprise_churn'
    union all
    select a.anomaly_id, 'churn the month after the churn event',
           exists (select 1 from {{ ref('fct_customer_revenue_monthly') }} m
                   join churn_event c on c.customer_id = m.customer_id
                   where m.customer_id = a.entity_id and m.movement = 'churn'
                     and m.month = c.churn_month + interval 1 month)
    from a where a.kind = 'enterprise_churn'
    union all
    select a.anomaly_id, 'usage spike flagged',
           exists (select 1 from {{ ref('fct_customer_revenue_monthly') }} m
                   where m.customer_id = a.entity_id and m.month = a.start_month and m.is_usage_spike)
    from a where a.kind = 'usage_spike'
)

select * from checks where not ok
