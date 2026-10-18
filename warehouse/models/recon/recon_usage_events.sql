-- Request-level events ↔ daily usage drivers, per month: billable audio rolled up from deduplicated events must
-- equal the drivers to the millisecond. Catches lost, duplicated or double-counted events.
with events as (
    select {{ dbt.date_trunc('month', 'usage_date') }} as month, sum(audio_ms) as ms
    from {{ ref('int_usage_daily_from_events') }}
    group by 1
),

drivers as (
    select {{ dbt.date_trunc('month', 'u.usage_date') }} as month, sum(cast(round(u.audio_hours * 3600000) as bigint)) as ms
    from {{ ref('stg_synthetic__usage_daily') }} u
    group by 1
)

select
    'usage_events_vs_drivers' as check_name,
    coalesce(d.month, e.month) as period,
    'all' as entity_id,
    d.ms / 3600000.0 as expected,
    e.ms / 3600000.0 as actual,
    (coalesce(e.ms, 0) - coalesce(d.ms, 0)) / 3600000.0 as variance,
    cast(null as decimal(9, 4)) as variance_pct,
    cast(0 as decimal(9, 4)) as tolerance_pct,
    case when e.ms is not distinct from d.ms then 'pass' else 'fail' end as status,
    case when e.ms is not distinct from d.ms then 'Exact match (audio hours, to the millisecond)'
         else 'Events and drivers differ: lost, duplicated or double-counted requests' end as explanation
from drivers d
full outer join events e using (month)
