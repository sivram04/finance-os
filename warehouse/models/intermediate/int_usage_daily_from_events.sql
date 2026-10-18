-- Billable audio per customer × model × day, rolled up from request-level events.
select
    usage_date,
    customer_id,
    model,
    count(*) as billable_requests,
    sum(duration_ms) as audio_ms,
    cast(sum(duration_ms) as decimal(18, 4)) / 3600000 as audio_hours
from {{ ref('stg_usage__api_requests') }}
where is_billable
group by 1, 2, 3
