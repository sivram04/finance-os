-- FR-6.5–6.7: project × month health.
-- EAC = actual to date + open commitments + PM estimate to complete. Variance at completion = budget − EAC.
-- Earned to date:
--   fixed fee   cost-to-cost: (actual ÷ EAC) × contract value  (FR-6.6; see design note on milestone policy)
--   T&M types   hours × contract bill rate + ODC at cost
-- Unbilled (WIP) = earned − billed when positive; deferred = billed − earned when positive.
-- Cap alert for T&M with cap when earned reaches the CAP-85 threshold of the cap.
with costs as (
    select project_id, month,
           sum(budget) as budget,
           sum(actual_to_date) as actual_to_date,
           sum(open_commitments) as open_commitments
    from {{ ref('fct_project_costs_monthly') }}
    group by all
),

tm_earned as (
    select project_id, month, sum(amount) over (partition by project_id order by month) as earned_to_date
    from (
        select project_id, work_month as month, sum(billable_value) as amount
        from {{ ref('int_project_labor') }} where bill_rate is not null group by all
        union all
        select o.project_id, o.expense_month, sum(o.amount)
        from {{ ref('stg_projects__odc_expenses') }} o
        join {{ ref('stg_projects__projects') }} p using (project_id)
        where p.project_type <> 'fixed_fee'
        group by all
    )
),

tm_earned_monthly as (
    select project_id, month, max(earned_to_date) as earned_to_date from tm_earned group by all
),

billed as (
    select c.project_id, c.month,
           coalesce(sum(i.amount) filter (where i.invoice_date <= last_day(c.month)), 0) as billed_to_date
    from costs c
    left join {{ ref('stg_projects__project_invoices') }} i using (project_id)
    group by all
),

base as (
    select
        c.project_id,
        c.month,
        p.project_name,
        p.project_type,
        p.customer_id,
        k.contract_id,
        k.contract_value,
        k.ceiling,
        c.budget,
        c.actual_to_date,
        c.open_commitments,
        coalesce(e.etc_amount, 0) as etc,
        c.actual_to_date + c.open_commitments + coalesce(e.etc_amount, 0) as eac,
        b.billed_to_date,
        coalesce(t.earned_to_date, 0) as tm_earned_to_date
    from costs c
    join {{ ref('stg_projects__projects') }} p using (project_id)
    join {{ ref('stg_projects__contracts') }} k using (contract_id)
    left join {{ ref('stg_projects__pm_estimates') }} e on e.project_id = c.project_id and e.as_of_month = c.month
    left join billed b using (project_id, month)
    left join (
        -- carry the last T&M earned value forward into months with no new activity
        select g.project_id, g.month, max(t.earned_to_date) as earned_to_date
        from costs g
        left join tm_earned_monthly t on t.project_id = g.project_id and t.month <= g.month
        group by all
    ) t using (project_id, month)
),

calc as (
    select
        *,
        case when project_type = 'fixed_fee' then actual_to_date / nullif(eac, 0) end as pct_complete,
        case when project_type = 'fixed_fee'
             then least(actual_to_date / nullif(eac, 0), 1) * contract_value
             else tm_earned_to_date end as earned_to_date
    from base
)

select
    c.project_id,
    c.month,
    c.project_name,
    c.project_type,
    c.customer_id,
    c.contract_id,
    c.contract_value,
    cast(c.budget as decimal(18, 2)) as budget,
    cast(c.actual_to_date as decimal(18, 2)) as actual_to_date,
    cast(c.open_commitments as decimal(18, 2)) as open_commitments,
    cast(c.etc as decimal(18, 2)) as etc,
    cast(c.eac as decimal(18, 2)) as eac,
    cast(c.budget - c.eac as decimal(18, 2)) as variance_at_completion,
    cast(round(c.eac / nullif(c.budget, 0), 4) as decimal(9, 4)) as eac_pct_of_budget,
    cast(round(c.pct_complete, 4) as decimal(9, 4)) as pct_complete,
    cast(c.earned_to_date as decimal(18, 2)) as earned_to_date,
    cast(c.billed_to_date as decimal(18, 2)) as billed_to_date,
    cast(greatest(c.earned_to_date - c.billed_to_date, 0) as decimal(18, 2)) as unbilled,
    cast(greatest(c.billed_to_date - c.earned_to_date, 0) as decimal(18, 2)) as deferred,
    case when c.project_type = 'tm_cap' then cast(round(c.earned_to_date / c.ceiling, 4) as decimal(9, 4)) end as cap_used_pct,
    coalesce(c.project_type = 'tm_cap' and c.earned_to_date / c.ceiling >= cap.threshold_pct, false) as is_cap_alert,
    coalesce(c.eac / nullif(c.budget, 0) > eac.threshold_pct, false) as is_over_budget
from calc c
cross join (select threshold_pct from {{ ref('project_alert_rules') }} where rule_id = 'CAP-85') cap
cross join (select threshold_pct from {{ ref('project_alert_rules') }} where rule_id = 'EAC-110') eac
