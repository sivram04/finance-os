{{ config(severity='warn') }}
-- Customers below their margin floor that no injected anomaly explains. A warning, not a failure:
-- these are real findings to investigate, not broken data.
select m.month, m.customer_id, m.segment, m.gross_margin_pct, m.gross_margin_floor_pct
from {{ ref('fct_customer_margin_monthly') }} m
left join {{ ref('stg_synthetic__anomaly_manifest') }} a on a.entity_id = m.customer_id
where m.is_below_floor and a.anomaly_id is null
