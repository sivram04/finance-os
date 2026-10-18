-- FR-6.2–6.4: project × cost type × month. Budget, actual in the month and to date, open commitments.
-- Actuals: labor = timesheet hours × loaded rate; subcontractor = vendor bills; odc = direct expenses.
-- Open commitments (subcontractor only) = PO amount − invoiced against the PO, never below zero.
with months as (
    select distinct entry_month as month from {{ ref('stg_erp__journal_entries') }}
),

grid as (
    select p.project_id, b.cost_type, m.month, b.budget_amount
    from {{ ref('stg_projects__projects') }} p
    join months m on m.month >= {{ month_start("p.start_date") }}
    join (
        select project_id, cost_type, budget_amount from {{ ref('stg_projects__project_budgets') }}
        union all
        -- cost types with spend but no budget line still appear, with zero budget
        select distinct project_id, 'subcontractor', 0 from {{ ref('stg_projects__subcontractor_bills') }}
        where project_id not in (select project_id from {{ ref('stg_projects__project_budgets') }} where cost_type = 'subcontractor')
    ) b on b.project_id = p.project_id
),

actuals as (
    select project_id, 'labor' as cost_type, work_month as month, sum(labor_cost) as amount
    from {{ ref('int_project_labor') }} group by all
    union all
    select project_id, 'subcontractor', bill_month, sum(amount)
    from {{ ref('stg_projects__subcontractor_bills') }} group by all
    union all
    select project_id, 'odc', expense_month, sum(amount)
    from {{ ref('stg_projects__odc_expenses') }} group by all
),

po_commitments as (
    -- open PO balance at each month end, per project
    select
        g.project_id,
        g.month,
        sum(greatest(po.amount - coalesce((
            select sum(b.amount) from {{ ref('stg_projects__subcontractor_bills') }} b
            where b.po_id = po.po_id and b.bill_date <= last_day(g.month)
        ), 0), 0)) as open_commitments
    from (select distinct project_id, month from grid) g
    join {{ ref('stg_projects__purchase_orders') }} po
        on po.project_id = g.project_id and po.po_date <= last_day(g.month)
    group by all
),

joined as (
    select
        g.project_id,
        g.cost_type,
        g.month,
        g.budget_amount as budget,
        coalesce(a.amount, 0) as actual_month,
        sum(coalesce(a.amount, 0)) over (partition by g.project_id, g.cost_type order by g.month) as actual_to_date,
        case when g.cost_type = 'subcontractor' then coalesce(c.open_commitments, 0) else 0 end as open_commitments
    from grid g
    left join actuals a using (project_id, cost_type, month)
    left join po_commitments c using (project_id, month)
)

select
    project_id,
    cost_type,
    month,
    {{ dec("budget", 18, 2) }} as budget,
    {{ dec("actual_month", 18, 2) }} as actual_month,
    {{ dec("actual_to_date", 18, 2) }} as actual_to_date,
    {{ dec("open_commitments", 18, 2) }} as open_commitments
from joined
