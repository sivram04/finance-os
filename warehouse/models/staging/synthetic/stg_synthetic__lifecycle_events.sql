select
    event_id,
    customer_id,
    event_date,
    event_type,
    cast(multiplier as decimal(9, 4)) as multiplier,
    reason,
    source
from {{ source('synthetic', 'lifecycle_events') }}
