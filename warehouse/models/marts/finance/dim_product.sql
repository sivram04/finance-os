select
    p.product_id,
    p.model,
    p.workload,
    p.list_price_per_hour,
    f.gross_margin_floor_pct
from {{ ref('stg_synthetic__products') }} p
left join {{ ref('margin_floors') }} f using (product_id)
