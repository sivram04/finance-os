-- FR-4.5 in the other direction: every catalogued metric appears in fct_kpi_monthly for the latest month.
select c.metric_name
from {{ ref('metric_catalog') }} c
left join {{ ref('fct_kpi_monthly') }} k
    on k.metric_name = c.metric_name
    and k.month = (select max(month) from {{ ref('fct_kpi_monthly') }})
where k.metric_name is null
