-- FR-7.2: pre-bill validation rules applied to every invoice line, so errors that slipped through are visible.
--   rate_mismatch          labor line rate ≠ contract bill rate for the labor category
--   hours_mismatch         labor line hours ≠ approved timesheet hours for that project × month × category
--   duplicate_line         the same project × month × category, or the same milestone, billed more than once
--   milestone_not_accepted milestone billed before (or without) an acceptance record
--   cap_exceeded           T&M-with-cap cumulative billing above the cap
--   funding_exceeded       federal CLIN cumulative billing above the funded amount
with lines as (
    select l.*, i.project_id, i.contract_id, i.invoice_date, i.service_month, p.project_type
    from {{ ref('stg_projects__project_invoice_lines') }} l
    join {{ ref('stg_projects__project_invoices') }} i using (invoice_id)
    join {{ ref('stg_projects__projects') }} p using (project_id)
),

approved_hours as (
    select project_id, work_month as service_month, labor_category, sum(hours) as hours
    from {{ ref('stg_projects__timesheets') }}
    where approved
    group by all
),

cumulative as (
    select
        project_id, contract_id, project_type, invoice_id, invoice_date, clin_id,
        sum(amount) over (partition by project_id order by invoice_date, invoice_id
                          rows between unbounded preceding and current row) as project_billed_to_date,
        sum(amount) over (partition by contract_id, clin_id order by invoice_date, invoice_id
                          rows between unbounded preceding and current row) as clin_billed_to_date
    from lines
)

select 'rate_mismatch' as exception_type, l.project_id, l.invoice_id, l.line_no, l.service_month, l.amount,
       l.labor_category || ' billed at ' || l.rate || '/h; contract rate is ' || r.bill_rate || '/h' as detail,
       cast((l.rate - r.bill_rate) * l.hours as decimal(18, 2)) as amount_at_risk
from lines l
join {{ ref('stg_projects__contract_rates') }} r
    on r.contract_id = l.contract_id and r.labor_category = l.labor_category
where l.line_type = 'labor' and l.rate <> r.bill_rate

union all

select 'hours_mismatch', l.project_id, l.invoice_id, l.line_no, l.service_month, l.amount,
       'Billed ' || l.hours || ' h; approved timesheets show ' || coalesce(a.hours, 0) || ' h',
       cast((l.hours - coalesce(a.hours, 0)) * l.rate as decimal(18, 2))
from lines l
left join approved_hours a using (project_id, service_month, labor_category)
where l.line_type = 'labor' and l.hours is distinct from a.hours

union all

select 'duplicate_line', project_id, max(invoice_id), max(line_no), service_month, sum(amount),
       'Billed ' || count(*) || ' times: ' || coalesce(milestone_id, labor_category, line_type),
       cast(sum(amount) - max(amount) as decimal(18, 2))
from lines
group by project_id, service_month, line_type, labor_category, milestone_id, clin_id
having count(*) > 1

union all

select 'milestone_not_accepted', l.project_id, l.invoice_id, l.line_no, l.service_month, l.amount,
       'Milestone ' || l.milestone_id || ' billed ' || l.invoice_date || ' without acceptance',
       l.amount
from lines l
join {{ ref('stg_projects__milestones') }} m using (milestone_id)
where l.line_type = 'milestone' and (m.accepted_date is null or m.accepted_date > l.invoice_date)

union all

select 'cap_exceeded', c.project_id, c.invoice_id, null, null, c.project_billed_to_date,
       'Cumulative billing ' || c.project_billed_to_date || ' exceeds cap ' || k.ceiling,
       cast(c.project_billed_to_date - k.ceiling as decimal(18, 2))
from (select distinct project_id, contract_id, project_type, invoice_id, project_billed_to_date from cumulative) c
join {{ ref('stg_projects__contracts') }} k using (contract_id)
where c.project_type = 'tm_cap' and c.project_billed_to_date > k.ceiling

union all

select 'funding_exceeded', c.project_id, c.invoice_id, null, null, c.clin_billed_to_date,
       'CLIN ' || c.clin_id || ' cumulative billing ' || c.clin_billed_to_date || ' exceeds funded ' || cl.funded,
       cast(c.clin_billed_to_date - cl.funded as decimal(18, 2))
from cumulative c
join {{ ref('stg_projects__clins') }} cl using (contract_id, clin_id)
where c.clin_billed_to_date > cl.funded
