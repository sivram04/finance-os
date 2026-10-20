-- Exceptions queue for project accounting (procure-to-pay and billing discipline).
--   bill_without_po        subcontractor bill with no purchase order
--   po_overbilled          invoiced against a PO more than the PO amount (FR-6.9-style control)
--   unbilled_milestone     milestone accepted more than 30 days ago and not fully invoiced (feeds M7 FR-7.6)
--   timesheet_without_rate T&M hours in a labor category with no contract bill rate
with last_day_of_data as (
    select max(entry_date) as as_of from {{ ref('stg_erp__journal_entries') }}
)

select 'bill_without_po' as exception_type, b.project_id, b.bill_id as reference_id, b.bill_date as exception_date,
       b.amount, 'Bill from ' || b.vendor_id || ' has no purchase order: ' || b.description as detail
from {{ ref('stg_projects__subcontractor_bills') }} b
where b.po_id is null

union all

select 'po_overbilled', po.project_id, po.po_id, max(b.bill_date), sum(b.amount) - po.amount,
       'Invoiced ' || sum(b.amount) || ' against PO amount ' || po.amount
from {{ ref('stg_projects__purchase_orders') }} po
join {{ ref('stg_projects__subcontractor_bills') }} b using (po_id)
group by po.project_id, po.po_id, po.amount
having sum(b.amount) > po.amount

union all

select 'unbilled_milestone', m.project_id, m.milestone_id, m.accepted_date, m.amount - coalesce(b.billed, 0),
       'Milestone "' || m.milestone_name || '" accepted ' || m.accepted_date
           || case when coalesce(b.billed, 0) > 0 then ' and only partly invoiced (' || cast(b.billed as {{ dbt.type_string() }}) || ' of ' || cast(m.amount as {{ dbt.type_string() }}) || ')'
                   else ' and not invoiced' end
from {{ ref('stg_projects__milestones') }} m
cross join last_day_of_data d
left join (select milestone_id, sum(amount) as billed from {{ ref('stg_projects__project_invoice_lines') }}
           where milestone_id is not null group by 1) b using (milestone_id)
where m.accepted_date is not null
  and m.accepted_date <= {{ add_days("d.as_of", -30) }}
  and m.amount - coalesce(b.billed, 0) > 0.005

union all

select 'timesheet_without_rate', l.project_id, l.timesheet_id, l.week_ending, l.hours,
       l.labor_category || ' has no bill rate on contract ' || l.contract_id
from {{ ref('int_project_labor') }} l
join {{ ref('stg_projects__projects') }} p using (project_id)
where p.project_type <> 'fixed_fee' and l.bill_rate is null
