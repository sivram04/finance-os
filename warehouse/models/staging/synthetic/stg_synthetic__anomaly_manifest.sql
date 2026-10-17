select
    anomaly_id,
    module,
    kind,
    entity_id,
    start_date,
    description,
    expected_detection
from {{ source('synthetic', 'anomaly_manifest') }}
