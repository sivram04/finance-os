-- One row per API request: duplicate deliveries removed (first ingested wins), the two logging formats merged
-- into duration_ms. Failed requests are kept and flagged; only status 200 is billable.
select
    request_id,
    received_at,
    ingested_at,
    cast(received_at as date) as usage_date,
    account_id as customer_id,
    api_key_id,
    endpoint,
    model,
    region,
    status_code,
    status_code = 200 as is_billable,
    schema_version,
    coalesce(audio_duration_ms, cast(round(audio_seconds * 1000) as bigint)) as duration_ms,
    latency_ms
from {{ source('usage', 'api_requests') }}
qualify row_number() over (partition by request_id order by ingested_at) = 1
