-- Headcount bridge by department for each closed month and year to date: opening + hires - leavers = closing.
-- (Payroll against budget is in fct_bva_monthly; forward headcount by scenario in fct_headcount_plan_monthly.)
with hc as (
    select month, department_id, headcount, hires, leavers,
           lag(headcount) over (partition by department_id order by month) as opening
    from {{ ref('fct_headcount_monthly') }}
    where month <= {{ closed_through() }}
)

select
    h.month,
    h.department_id,
    cast(coalesce(h.opening, h.headcount - h.hires + h.leavers) as bigint) as opening,
    cast(h.hires as bigint) as hires,
    cast(h.leavers as bigint) as leavers,
    cast(h.headcount as bigint) as closing,
    cast(sum(h.hires) over (partition by h.department_id, extract(year from h.month) order by h.month) as bigint) as hires_ytd,
    cast(sum(h.leavers) over (partition by h.department_id, extract(year from h.month) order by h.month) as bigint) as leavers_ytd
from hc h
