-- Month-end close checklist (seeds/close_tasks.csv) with each task's status driven by evidence in the data:
--   recon checks       complete when every recon_status row for the period passes, else exceptions
--   prepaids           complete when the amortization schedule covers the month
--   bva                review: the number of open BvA alerts the FP&A owner must explain
--   signoff            ready only when every other task is complete
-- Due date = the task's workday after month end (Mon–Fri).
with months as (
    select distinct cast(period as date) as month from {{ ref('recon_status') }}
),

recon as (
    select cast(period as date) as month, check_name,
           count(case when status <> 'pass' then 1 end) as exceptions, count(*) as checks
    from {{ ref('recon_status') }}
    group by all
),

bva as (
    select month, count(case when is_alert then 1 end) as alerts from {{ ref('fct_bva_monthly') }} group by month
),

prepaid as (
    select distinct month from {{ ref('fct_prepaid_schedule') }}
),

tasks as (
    select
        m.month,
        t.task_id,
        t.workday,
        t.owner,
        t.task,
        t.evidence,
        case
            when t.evidence = 'signoff' then null
            when t.evidence = 'bva' then case when coalesce(b.alerts, 0) = 0 then 'complete' else 'review' end
            when t.evidence = 'prepaids' then case when p.month is not null then 'complete' else 'not_applicable' end
            when t.evidence = 'bank_statement_vs_gl_cash' and r.checks is null then 'not_applicable'  -- before the bank feed
            when r.checks is null then 'no_data'
            when r.exceptions = 0 then 'complete'
            else 'exceptions'
        end as status,
        case when t.evidence = 'bva' then b.alerts else r.exceptions end as open_items
    from months m
    cross join {{ ref('close_tasks') }} t
    left join recon r on r.month = m.month and r.check_name = t.evidence
    left join bva b on b.month = m.month
    left join prepaid p on p.month = m.month
),

workdays as (
    -- the n-th weekday after month end
    select month, row_number() over (partition by month order by d) as workday, d as due_date
    from (
        select m.month, {{ add_days("last_day(m.month)", "g.n") }} as d
        from months m
        cross join {{ int_series('g', 1, 14) }}
    ) days_after
    where {{ day_of_week("d") }} between 1 and 5
)

select
    t.month,
    t.task_id,
    t.workday,
    w.due_date,
    t.owner,
    t.task,
    t.evidence,
    coalesce(t.status,
             case when count(case when t.status not in ('complete', 'not_applicable') and t.evidence <> 'signoff' then 1 end)
                       over (partition by t.month) = 0 then 'ready' else 'blocked' end) as status,
    t.open_items
from tasks t
join workdays w on w.month = t.month and w.workday = t.workday
