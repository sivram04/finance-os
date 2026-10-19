-- Every alert condition that is true right now (design §11), one row per rule × entity × period, with its
-- severity, recipients and the workspace page it links to (seeds/alert_rules.csv). alert_key de-duplicates
-- delivery: the dispatcher (finance_os.alerts) sends a key once and marks it resolved when it drops out.
-- Monthly rules look at the last closed month.
with closed as (
    select {{ closed_through() }} as m
),

raw_alerts as (
    select 'OVERSPEND' as rule_id, b.department_id || '/' || b.account_id as entity_id, b.month as period, b.message
    from {{ ref('fct_bva_alerts') }} b cross join closed c
    where b.month = c.m

    union all
    select 'MARGIN-FLOOR', m.customer_id, m.month,
           m.customer_id || ' gross margin ' || cast(round(m.gross_margin_pct * 100, 1) as {{ t_string() }}) || '% vs floor '
           || cast(round(m.gross_margin_floor_pct * 100, 1) as {{ t_string() }}) || '%, two months running'
    from {{ ref('fct_customer_margin_monthly') }} m
    join {{ ref('fct_customer_margin_monthly') }} prev
        on prev.customer_id = m.customer_id and prev.month = {{ add_months("m.month", -1) }}
    cross join closed c
    where m.month = c.m and m.is_below_floor and prev.is_below_floor

    union all
    select 'UNTAGGED', 'cloud', t.month,
           'Untagged cloud spend ' || cast(round((1 - t.tagging_coverage_pct) * 100, 1) as {{ t_string() }}) || '% of the month ($'
           || cast(round(t.untagged_cost, 0) as {{ t_string() }}) || ')'
    from {{ ref('fct_tagging_coverage_monthly') }} t cross join closed c
    where t.month = c.m and 1 - t.tagging_coverage_pct > 0.05

    union all
    select case when f.is_funding_alert_90 then 'FUNDING-90' else 'FUNDING-75' end, f.contract_id, f.month,
           f.contract_id || ' funding ' || cast(round(f.funding_used_pct * 100, 1) as {{ t_string() }}) || '% used'
    from {{ ref('fct_contract_funding') }} f cross join closed c
    where f.month = c.m and f.clin_id = 'TOTAL' and f.is_funding_alert_75

    union all
    select 'TM-CAP-85', p.project_id, p.month,
           p.project_id || ' at ' || cast(round(p.cap_used_pct * 100, 1) as {{ t_string() }}) || '% of its T&M cap'
    from {{ ref('fct_project_financials') }} p cross join closed c
    where p.month = c.m and p.is_cap_alert

    union all
    select 'UNBILLED', r.project_id || '/' || r.reference, cast(null as date),
           r.project_id || ' ' || r.item_type || ' ' || r.reference || ' unbilled ' || cast(r.days_unbilled as {{ t_string() }}) || ' days'
    from {{ ref('fct_billing_run') }} r
    where r.is_unbilled_alert

    union all
    select 'AR-60', i.invoice_ref, cast(null as date),
           i.customer_id || ' invoice ' || i.invoice_ref || ' is ' || cast(i.days_past_due as {{ t_string() }}) || ' days past due ($'
           || cast(round(i.balance, 0) as {{ t_string() }}) || ')'
    from {{ ref('fct_ar_invoices') }} i
    where i.status = 'open' and i.days_past_due > 60

    union all
    select 'RECON-FAIL', r.check_name || '/' || r.entity_id, r.period, r.check_name || ': ' || r.explanation
    from {{ ref('recon_status') }} r
    where r.status <> 'pass'

    union all
    select 'SOURCE-STALE', s.source, cast(null as date),
           s.source || ' last loaded ' || cast(s.hours_since_load as {{ t_string() }}) || ' hours ago'
    from {{ ref('fct_source_freshness') }} s
    where s.hours_since_load > 26

    union all
    select 'COVENANT', t.rule_id, min(t.month),
           min(t.description) || case when {{ bool_or("not t.is_forecast") }} then ' (breached now)' else ' (forecast breach)' end
    from {{ ref('fct_treasury_covenants') }} t cross join closed c
    where t.status = 'breach' and t.month >= c.m
    group by t.rule_id

    union all
    select 'MIN-CASH-13W', 'cash', min(w.week_start), 'Cash falls below the $3M minimum in week ' || cast(min(w.week) as {{ t_string() }})
    from {{ ref('fct_cash_forecast_13w') }} w
    where w.is_below_min_cash
    having count(*) > 0

    union all
    select 'FUNDRAISE-LATE', f.scenario, f.close_month,
           'Cash runs out before the ' || f.scenario || ' ' || f.round_name || ' closes'
    from {{ ref('fct_fundraise_scenarios') }} f
    where f.runs_out_before_close

    union all
    select 'AP-REVIEW', q.doc_file || '/' || q.reason, cast(null as date), 'Vendor bill ' || coalesce(q.vendor_invoice_number, q.doc_file) || ': ' || q.detail
    from {{ ref('fct_ap_review_queue') }} q
)

select
    a.rule_id || '|' || a.entity_id || '|' || coalesce(cast(a.period as {{ t_string() }}), '-') as alert_key,
    a.rule_id,
    r.severity,
    a.entity_id,
    a.period,
    a.message,
    r.recipients,
    r.page
from raw_alerts a
join {{ ref('alert_rules') }} r using (rule_id)
