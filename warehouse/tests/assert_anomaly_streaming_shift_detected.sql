-- FR-1.4: every streaming_shift anomaly in the manifest must be caught.
-- Fails if the customer is not below floor from the anomaly's start month,
-- or was already below floor before it (then the shift is not what caused it).
select
    a.anomaly_id,
    m.customer_id,
    m.month,
    m.gross_margin_pct,
    m.gross_margin_floor_pct,
    m.is_below_floor
from {{ ref('stg_synthetic__anomaly_manifest') }} a
join {{ ref('fct_customer_margin_monthly') }} m on m.customer_id = a.entity_id
where a.kind = 'streaming_shift'
  and (
        (m.month >= date_trunc('month', a.start_date) and not m.is_below_floor)
     or (m.month <  date_trunc('month', a.start_date) and m.is_below_floor)
  )
