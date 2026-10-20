-- Depreciation per the fixed-asset register vs depreciation booked in the GL (account 6600), by month and
-- department, for closed months. A difference means an asset was missed, double-booked or given the wrong life.
with schedule as (
    select r.department_id, {{ add_months("r.in_service_month", "h.n") }} as month, r.monthly_depreciation as amount
    from {{ ref('fct_fixed_asset_register') }} r
    cross join {{ int_series('h', 0, 120) }}
    where h.n < r.useful_life_months
),

per_register as (
    select department_id, month, sum(amount) as register_depreciation
    from schedule
    where month <= {{ closed_through() }}
    group by 1, 2
),

per_gl as (
    select l.department_id, e.entry_month as month, sum(l.debit - l.credit) as gl_depreciation
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '6600' and e.entry_month <= {{ closed_through() }}
    group by 1, 2
)

select
    coalesce(r.department_id, g.department_id) as department_id,
    coalesce(r.month, g.month) as month,
    {{ dec("coalesce(r.register_depreciation, 0)", 18, 2) }} as register_depreciation,
    {{ dec("coalesce(g.gl_depreciation, 0)", 18, 2) }} as gl_depreciation,
    {{ dec("coalesce(g.gl_depreciation, 0) - coalesce(r.register_depreciation, 0)", 18, 2) }} as difference,
    case when abs(coalesce(g.gl_depreciation, 0) - coalesce(r.register_depreciation, 0)) < 1 then 'ties' else 'difference' end as status
from per_register r
full outer join per_gl g on g.department_id = r.department_id and g.month = r.month
