-- FR-7.1, FR-7.6: the next billing run, as of the last day of data. Draft lines for everything billable and
-- not yet invoiced: approved T&M hours (at the contract rate) and ODCs for months with no invoice, and
-- accepted milestones with no invoice line. Each draft is validated against the cap and funding, and
-- flagged when it has waited longer than the UNBILLED rule.
with as_of as (
    select max(entry_date) as as_of_date from {{ ref('stg_erp__journal_entries') }}
),

invoiced_months as (
    select distinct project_id, service_month from {{ ref('stg_projects__project_invoices') }} where service_month is not null
),

tm_drafts as (
    select
        l.project_id,
        'labor' as item_type,
        l.work_month::varchar || ' ' || l.labor_category as reference,
        last_day(l.work_month) as billable_since,
        sum(l.hours) as hours,
        max(l.bill_rate) as rate,
        sum(l.hours * l.bill_rate) as amount
    from {{ ref('int_project_labor') }} l
    left join invoiced_months i on i.project_id = l.project_id and i.service_month = l.work_month
    where l.bill_rate is not null and l.approved and i.project_id is null
    group by l.project_id, l.work_month, l.labor_category
),

odc_drafts as (
    select o.project_id, 'odc', o.expense_month::varchar, last_day(o.expense_month), null, null, sum(o.amount)
    from {{ ref('stg_projects__odc_expenses') }} o
    join {{ ref('stg_projects__projects') }} p using (project_id)
    left join invoiced_months i on i.project_id = o.project_id and i.service_month = o.expense_month
    where p.project_type <> 'fixed_fee' and i.project_id is null
    group by all
),

milestone_drafts as (
    select m.project_id, 'milestone', m.milestone_id || ' ' || m.milestone_name, m.accepted_date, null, null, m.amount
    from {{ ref('stg_projects__milestones') }} m
    where m.accepted_date is not null
      and not exists (select 1 from {{ ref('stg_projects__project_invoice_lines') }} l where l.milestone_id = m.milestone_id)
),

drafts as (
    select * from tm_drafts
    union all select * from odc_drafts
    union all select * from milestone_drafts
),

headroom as (
    select f.project_id, k.ceiling - f.billed_to_date as cap_headroom, f.project_type
    from {{ ref('fct_project_financials') }} f
    join {{ ref('stg_projects__contracts') }} k using (contract_id)
    where f.month = (select max(month) from {{ ref('fct_project_financials') }})
)

select
    d.project_id,
    d.item_type,
    d.reference,
    d.billable_since,
    d.hours,
    d.rate,
    cast(d.amount as decimal(18, 2)) as amount,
    date_diff('day', d.billable_since, a.as_of_date) as days_unbilled,
    case
        when h.project_type in ('tm_cap', 'federal_tm')
             and sum(d.amount) over (partition by d.project_id) > h.cap_headroom then 'exceeds_cap_or_funding'
        else 'pass'
    end as validation_status,
    date_diff('day', d.billable_since, a.as_of_date) > r.threshold_days as is_unbilled_alert
from drafts d
cross join as_of a
cross join (select threshold_days from {{ ref('billing_rules') }} where rule_id = 'UNBILLED-30') r
left join headroom h using (project_id)
