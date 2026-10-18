-- Billable audio per customer × model × day, rolled up from request-level events.
-- Incremental: a run re-reads only the last few days of events (3-day lookback for late deliveries) and merges
-- them; on BigQuery the table is partitioned by day and the date filter is a literal, so the scan is pruned to
-- those days' partitions instead of the whole events table. Same dedupe as stg_usage__api_requests: the first
-- delivery of each request wins, then only status 200 is billable.
{{ config(
    materialized='incremental',
    unique_key=['usage_date', 'customer_id', 'model'],
    incremental_strategy=('merge' if target.type == 'bigquery' else 'delete+insert'),
    partition_by=({'field': 'usage_date', 'data_type': 'date', 'granularity': 'day'} if target.type == 'bigquery' else none),
    cluster_by=(['customer_id'] if target.type == 'bigquery' else none)
) }}

{% set since = none %}
{% if is_incremental() and execute %}
    {% set last = run_query("select max(usage_date) from " ~ this).columns[0].values()[0] %}
    {% if last %}{% set since = last | string %}{% endif %}
{% endif %}

with events as (
    select
        request_id,
        cast(received_at as date) as usage_date,
        account_id as customer_id,
        model,
        status_code,
        coalesce(audio_duration_ms, cast(round(audio_seconds * 1000) as bigint)) as duration_ms
    from {{ source('usage', 'api_requests') }}
    where true
    {% if since %}
      and received_at >= cast({{ add_days("date '" ~ since[:10] ~ "'", -3) }} as timestamp)
    {% endif %}
    qualify row_number() over (partition by request_id order by ingested_at) = 1
)

select
    usage_date,
    customer_id,
    model,
    count(*) as billable_requests,
    sum(duration_ms) as audio_ms,
    {{ dec("sum(duration_ms)", 18, 4) }} / 3600000 as audio_hours
from events
where status_code = 200
group by 1, 2, 3
