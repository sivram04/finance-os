-- FR-1.4: every streaming_shift anomaly in the manifest must be caught.
-- Fails if the customer is not below floor from the anomaly's start month, or was already below floor
-- in the 3 months just before it (then the shift is not what caused it). Earlier months can be below
-- floor for other reasons (e.g. unused GPU commit in 2025) and are left to warn_unexpected_below_floor.
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
        (m.month >= {{ month_start("a.start_date") }} and not m.is_below_floor)
     or (m.month >= {{ add_months(month_start("a.start_date"), -3) }}
         and m.month < {{ month_start("a.start_date") }}
         and m.is_below_floor)
  )
