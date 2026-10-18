-- FR-5.3: one overspend (or revenue shortfall) alert per department × account × month over threshold,
-- routed to the department owner. FR-5.4: commentary columns are empty here; the finance agent (M11)
-- drafts from fct_bva_drivers and a human approves. M13 delivers alerts to Telegram.
select
    'BVA-' || strftime(b.month, '%Y%m') || '-' || b.department_id || '-' || b.account_id as alert_id,
    b.month,
    b.department_id,
    d.department_name,
    d.owner_title as route_to,
    b.account_id,
    b.account_name,
    b.account_type,
    b.actual,
    b.budget,
    b.variance,
    b.variance_pct,
    b.fy_forecast_variance,
    case when b.account_type = 'revenue'
         then b.account_name || ' is $' || format('{:,.0f}', abs(b.variance)) || ' below budget'
         else d.department_name || ' ' || b.account_name || ' is $' || format('{:,.0f}', b.variance) || ' over budget'
    end
      || case when b.variance_pct is not null
              then ' (' || format('{:+.1f}', b.variance_pct * 100) || '%)' else '' end as message,
    cast(null as varchar) as commentary_draft,
    'pending' as commentary_status,
    cast(null as varchar) as approved_by
from {{ ref('fct_bva_monthly') }} b
join {{ ref('dim_department') }} d using (department_id)
where b.is_alert
