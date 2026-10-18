-- FR-8.2: AR health by month.
-- DSO = ending AR ÷ invoiced sales in the month × days in the month.
-- CEI = (beginning AR + sales − ending AR) ÷ (beginning AR + sales − ending current AR), i.e. what was
-- collected over what was collectible (ending current AR is not yet due, so not collectible).
with months as (
    select distinct entry_month as month, last_day(entry_month) as month_end
    from {{ ref('stg_erp__journal_entries') }}
),

ending as (
    select snapshot_date as month_end,
           sum(balance) as ending_ar,
           sum(case when aging_bucket = 'current' then balance end) as ending_current_ar,
           sum(case when aging_bucket in ('61-90', '90+') then balance end) as ar_over_60
    from {{ ref('fct_ar_aging_snapshot') }}
    group by snapshot_date
),

sales as (
    select {{ month_start("invoice_date") }} as month, sum(amount) as sales
    from {{ ref('int_ar_invoices') }}
    group by 1
),

joined as (
    select
        m.month,
        coalesce(lag(e.ending_ar) over (order by m.month), 0) as beginning_ar,
        coalesce(s.sales, 0) as sales,
        coalesce(e.ending_ar, 0) as ending_ar,
        coalesce(e.ending_current_ar, 0) as ending_current_ar,
        coalesce(e.ar_over_60, 0) as ar_over_60,
        extract(day from m.month_end) as days_in_month
    from months m
    left join ending e using (month_end)
    left join sales s using (month)
)

select
    month,
    {{ dec("beginning_ar", 18, 2) }} as beginning_ar,
    {{ dec("sales", 18, 2) }} as sales,
    {{ dec("ending_ar", 18, 2) }} as ending_ar,
    {{ dec("ending_current_ar", 18, 2) }} as ending_current_ar,
    {{ dec("ar_over_60", 18, 2) }} as ar_over_60,
    {{ dec("round(ending_ar / nullif(sales, 0) * days_in_month, 1)", 9, 1) }} as dso_days,
    {{ dec("round((beginning_ar + sales - ending_ar) / nullif(beginning_ar + sales - ending_current_ar, 0), 4)", 9, 4) }} as cei
from joined
