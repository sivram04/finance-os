-- FR-6.8: funding status per contract × CLIN × month, plus a 'TOTAL' row per contract.
-- Used = billed to date + unbilled (earned not yet billed). Alerts at 75% (Limitation of Funds notice)
-- and 90% of funded. Non-federal contracts have one TOTAL row with funded = contract value.
with months as (
    select distinct month from {{ ref('fct_project_financials') }}
),

clins as (
    select contract_id, clin_id, ceiling, funded from {{ ref('stg_projects__clins') }}
    union all
    select contract_id, 'TOTAL', ceiling, funded_amount from {{ ref('stg_projects__contracts') }}
),

earned_by_clin as (
    -- federal: labor earns to CLIN 0001, ODC to CLIN 0002
    select p.contract_id, '0001' as clin_id, l.work_month as month, sum(l.billable_value) as amount
    from {{ ref('int_project_labor') }} l
    join {{ ref('stg_projects__projects') }} p using (project_id)
    where p.project_type = 'federal_tm'
    group by all
    union all
    select p.contract_id, '0002', o.expense_month, sum(o.amount)
    from {{ ref('stg_projects__odc_expenses') }} o
    join {{ ref('stg_projects__projects') }} p using (project_id)
    where p.project_type = 'federal_tm'
    group by all
),

billed_by_clin as (
    select i.contract_id, l.clin_id, i.invoice_date, l.amount
    from {{ ref('stg_projects__project_invoice_lines') }} l
    join {{ ref('stg_projects__project_invoices') }} i using (invoice_id)
    where l.clin_id is not null
),

clin_month as (
    select
        c.contract_id, c.clin_id, m.month, c.ceiling, c.funded,
        coalesce((select sum(b.amount) from billed_by_clin b
                  where b.contract_id = c.contract_id and b.clin_id = c.clin_id
                    and b.invoice_date <= last_day(m.month)), 0) as billed_to_date,
        coalesce((select sum(e.amount) from earned_by_clin e
                  where e.contract_id = c.contract_id and e.clin_id = c.clin_id and e.month <= m.month), 0) as earned_to_date
    from clins c
    cross join months m
    where c.clin_id <> 'TOTAL'
),

contract_month as (
    -- contract totals from the project view (covers every contract type)
    select f.contract_id, 'TOTAL' as clin_id, f.month, k.ceiling, k.funded_amount as funded,
           sum(f.billed_to_date) as billed_to_date, sum(f.earned_to_date) as earned_to_date
    from {{ ref('fct_project_financials') }} f
    join {{ ref('stg_projects__contracts') }} k using (contract_id)
    group by all
),

unioned as (
    select * from clin_month
    union all
    select * from contract_month
),

rules as (
    select
        max(threshold_pct) filter (where rule_id = 'FUND-75') as t75,
        max(threshold_pct) filter (where rule_id = 'FUND-90') as t90
    from {{ ref('project_alert_rules') }}
)

select
    u.contract_id,
    u.clin_id,
    u.month,
    cast(u.ceiling as decimal(18, 2)) as ceiling,
    cast(u.funded as decimal(18, 2)) as funded,
    cast(u.billed_to_date as decimal(18, 2)) as billed_to_date,
    cast(greatest(u.earned_to_date - u.billed_to_date, 0) as decimal(18, 2)) as unbilled,
    cast(u.funded - u.billed_to_date - greatest(u.earned_to_date - u.billed_to_date, 0) as decimal(18, 2)) as funding_remaining,
    cast(round((u.billed_to_date + greatest(u.earned_to_date - u.billed_to_date, 0)) / nullif(u.funded, 0), 4) as decimal(9, 4)) as funding_used_pct,
    coalesce((u.billed_to_date + greatest(u.earned_to_date - u.billed_to_date, 0)) / nullif(u.funded, 0) >= r.t75, false) as is_funding_alert_75,
    coalesce((u.billed_to_date + greatest(u.earned_to_date - u.billed_to_date, 0)) / nullif(u.funded, 0) >= r.t90, false) as is_funding_alert_90
from unioned u
cross join rules r
