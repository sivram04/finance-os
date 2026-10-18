select
    event_id,
    customer_id,
    event_date,
    event_type,
    {{ dec("multiplier", 9, 4) }} as multiplier,
    reason,
    source
from {{ source('synthetic', 'lifecycle_events') }}
