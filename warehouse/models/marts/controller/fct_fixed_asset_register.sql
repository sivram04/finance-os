-- Fixed-asset register built from the ledger: every capex entry on account 1500 is an asset, classed by its memo
-- (seeds/asset_classes.csv: useful life and method). Depreciation starts the month after purchase, straight line,
-- as booked. Balances are as of the last closed month; fct_depreciation_reconciliation ties it to the GL.
with capex as (
    select l.entry_id as asset_id, e.memo as description, e.entry_date as acquired_date, l.entity_id, l.department_id,
           l.debit as cost
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '1500' and l.debit > 0 and e.entry_type = 'capex'
),

classed as (
    select c.*, a.class_id, a.asset_class, a.useful_life_months, a.method,
           {{ add_months(month_start("c.acquired_date"), 1) }} as in_service_month,
           row_number() over (partition by c.asset_id order by a.class_id) as rn
    from capex c
    join {{ ref('asset_classes') }} a on lower(c.description) like concat('%', a.match_keyword, '%')
),

aged as (
    select c.*,
           round({{ fdiv("c.cost", "c.useful_life_months") }}, 2) as monthly,
           greatest(0, least(c.useful_life_months,
               (extract(year from t.month) * 12 + extract(month from t.month))
               - (extract(year from c.in_service_month) * 12 + extract(month from c.in_service_month)) + 1)) as months_depreciated,
           t.month as as_of_month
    from classed c
    cross join (select {{ closed_through() }} as month) t
    where c.rn = 1
)

select
    asset_id, description, asset_class, entity_id, department_id, acquired_date, in_service_month,
    useful_life_months, method,
    {{ dec("cost", 18, 2) }} as cost,
    {{ dec("monthly", 18, 2) }} as monthly_depreciation,
    cast(months_depreciated as integer) as months_depreciated,
    {{ dec("least(cost, monthly * months_depreciated)", 18, 2) }} as accumulated_depreciation,
    {{ dec("cost - least(cost, monthly * months_depreciated)", 18, 2) }} as net_book_value,
    {{ add_months("in_service_month", "useful_life_months") }} as fully_depreciated_month,
    as_of_month
from aged
