-- FR-4.1–4.3, 4.5: one row per metric × month. Every metric_name must exist in the metric catalog
-- (seeds/metric_catalog.csv, built from warehouse/metrics/kpis.yml); a relationships test enforces it.
-- Ratios are computed in floating point and stored rounded to 4 dp.
with pnl as (
    select
        month,
        sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
        sum(case when account_type = 'cogs' then natural_amount else 0 end) as cogs,
        sum(case when account_type = 'opex' then natural_amount else 0 end) as opex
    from {{ ref('fct_gl_monthly') }}
    group by month
),

cash as (
    select
        *,
        avg(net_burn) over (order by month rows between 2 preceding and current row) as net_burn_t3m,
        count(*) over (order by month rows between 2 preceding and current row) as months_in_window
    from {{ ref('fct_cash_monthly') }}
),

headcount as (
    select month, sum(headcount) as headcount
    from {{ ref('fct_headcount_monthly') }}
    group by month
),

customer_rev as (
    select e.entry_month as month, l.customer_id, -sum(l.amount) as revenue
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '4000'
    group by all
),

customer_rev_t3m as (
    -- trailing-3-month revenue per customer, on a complete customer × month grid
    select
        m.month,
        c.customer_id,
        sum(r.revenue) as rev_t3m
    from (select distinct month from customer_rev) m
    cross join (select distinct customer_id from customer_rev) c
    left join customer_rev r
        on r.customer_id = c.customer_id
        and r.month > m.month - interval 3 month
        and r.month <= m.month
    group by all
),

retention as (
    -- cohort = customers with revenue in the T3M window ending 12 months earlier
    select
        now_.month,
        sum(now_.rev_t3m) filter (where prior.rev_t3m > 0) as cohort_rev_now,
        sum(least(coalesce(now_.rev_t3m, 0), prior.rev_t3m)) filter (where prior.rev_t3m > 0) as cohort_rev_retained,
        sum(prior.rev_t3m) filter (where prior.rev_t3m > 0) as cohort_rev_prior
    from customer_rev_t3m now_
    join customer_rev_t3m prior
        on prior.customer_id = now_.customer_id
        and prior.month = now_.month - interval 12 month
    group by now_.month
),

arr as (
    select month, sum(revenue) over (order by month rows between 2 preceding and current row) * 4 as arr,
           count(*) over (order by month rows between 2 preceding and current row) as months_in_window
    from pnl
),

base as (
    select
        p.month,
        p.revenue,
        p.cogs,
        p.opex,
        (p.revenue - p.cogs) / nullif(p.revenue, 0) as gross_margin_pct,
        c.gross_burn,
        c.net_burn,
        c.closing_cash,
        case when c.months_in_window = 3 and c.net_burn_t3m > 0 then c.closing_cash / c.net_burn_t3m end as runway_months,
        case when a.months_in_window = 3 then a.arr end as arr,
        h.headcount,
        case when a.months_in_window = 3 then a.arr / nullif(h.headcount, 0) end as arr_per_employee,
        r.cohort_rev_now / nullif(r.cohort_rev_prior, 0) as nrr,
        r.cohort_rev_retained / nullif(r.cohort_rev_prior, 0) as grr
    from pnl p
    join cash c using (month)
    left join headcount h using (month)
    left join arr a using (month)
    left join retention r using (month)
),

metrics as (
    select
        month,
        {%- for m in ['revenue', 'cogs', 'opex', 'gross_margin_pct', 'gross_burn', 'net_burn', 'closing_cash',
                      'runway_months', 'arr', 'headcount', 'arr_per_employee', 'nrr', 'grr'] %}
        cast(round({{ m }}, 4) as decimal(18, 4)) as {{ m }}{{ "," if not loop.last }}
        {%- endfor %}
    from base
)

select month, metric_name, value
from metrics
unpivot (value for metric_name in (
    revenue, cogs, opex, gross_margin_pct, gross_burn, net_burn, closing_cash,
    runway_months, arr, headcount, arr_per_employee, nrr, grr
))
