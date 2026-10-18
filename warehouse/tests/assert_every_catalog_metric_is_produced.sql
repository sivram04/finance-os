-- FR-4.5 in the other direction: every catalogued metric is produced by the KPI pipeline (in at least one month).
-- Not necessarily in the latest month: some metrics are undefined for a while (runway while the company isn't
-- burning cash, as at scale L), and fct_kpi_monthly holds no row for an undefined value.
with produced as (
    select distinct metric_name from {{ ref('fct_kpi_monthly') }}
)

select c.metric_name
from {{ ref('metric_catalog') }} c
left join produced k on k.metric_name = c.metric_name
where k.metric_name is null
