-- Two management bridges per closed month, month over month, in one long table (bridge, step_order, step, amount):
-- Gross margin ($):  prior gross margin → volume (audio hours x prior margin per hour) → price (revenue per hour change
--                    x hours) → cost to serve (cost per hour change x hours, sign flipped) → services and other COGS →
--                    current gross margin.
-- Net burn:          prior net burn → revenue → cost of revenue → payroll → other opex → capex → working capital and
--                    timing (collections vs revenue, payments vs costs) → current net burn. Positive steps add burn.
-- Each bridge's steps add up exactly to the change.
with usage as (
    select month, sum(audio_hours) as hours, sum(revenue) as revenue, sum(cogs) as cogs
    from {{ ref('fct_unit_economics_monthly') }} group by 1
),

gl as (
    select month,
           sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
           sum(case when account_type = 'cogs' then natural_amount else 0 end) as cogs,
           sum(case when account_id in ('6000', '6010', '6020') then natural_amount else 0 end) as payroll,
           sum(case when account_type = 'opex' and account_id not in ('6000', '6010', '6020', '6600') then natural_amount else 0 end) as other_opex
    from {{ ref('fct_gl_monthly') }} group by 1
),

capex as (
    select e.entry_month as month, sum(l.debit) as capex
    from {{ ref('stg_erp__journal_lines') }} l join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where e.entry_type = 'capex' and l.account_id = '1500' group by 1
),

j as (
    select g.month, g.revenue, g.cogs, g.payroll, g.other_opex, coalesce(cx.capex, 0) as capex, c.net_burn,
           u.hours, u.revenue as u_rev, u.cogs as u_cogs,
           lag(g.revenue) over (order by g.month) as p_revenue, lag(g.cogs) over (order by g.month) as p_cogs,
           lag(g.payroll) over (order by g.month) as p_payroll, lag(g.other_opex) over (order by g.month) as p_other_opex,
           lag(coalesce(cx.capex, 0)) over (order by g.month) as p_capex, lag(c.net_burn) over (order by g.month) as p_net_burn,
           lag(u.hours) over (order by g.month) as p_hours, lag(u.revenue) over (order by g.month) as p_u_rev,
           lag(u.cogs) over (order by g.month) as p_u_cogs
    from gl g
    join {{ ref('fct_cash_monthly') }} c on c.month = g.month
    left join usage u on u.month = g.month
    left join capex cx on cx.month = g.month
    where g.month <= {{ closed_through() }}
),

steps as (
    select month, 'gross_margin' as bridge, 0 as step_order, 'Prior month' as step, p_revenue - p_cogs as amount from j
    union all select month, 'gross_margin', 1, 'Volume (audio hours)', (hours - p_hours) * {{ fdiv("p_u_rev - p_u_cogs", "nullif(p_hours, 0)") }} from j
    union all select month, 'gross_margin', 2, 'Price (revenue per hour)', hours * ({{ fdiv("u_rev", "nullif(hours, 0)") }} - {{ fdiv("p_u_rev", "nullif(p_hours, 0)") }}) from j
    union all select month, 'gross_margin', 3, 'Cost to serve (cost per hour)', -hours * ({{ fdiv("u_cogs", "nullif(hours, 0)") }} - {{ fdiv("p_u_cogs", "nullif(p_hours, 0)") }}) from j
    union all select month, 'gross_margin', 4, 'Services and other COGS',
        ((revenue - cogs) - (p_revenue - p_cogs))
        - ((hours - p_hours) * {{ fdiv("p_u_rev - p_u_cogs", "nullif(p_hours, 0)") }}
           + hours * ({{ fdiv("u_rev", "nullif(hours, 0)") }} - {{ fdiv("p_u_rev", "nullif(p_hours, 0)") }})
           - hours * ({{ fdiv("u_cogs", "nullif(hours, 0)") }} - {{ fdiv("p_u_cogs", "nullif(p_hours, 0)") }})) from j
    union all select month, 'gross_margin', 9, 'This month', revenue - cogs from j

    union all select month, 'net_burn', 0, 'Prior month', p_net_burn from j
    union all select month, 'net_burn', 1, 'Revenue', -(revenue - p_revenue) from j
    union all select month, 'net_burn', 2, 'Cost of revenue', cogs - p_cogs from j
    union all select month, 'net_burn', 3, 'Payroll', payroll - p_payroll from j
    union all select month, 'net_burn', 4, 'Other opex', other_opex - p_other_opex from j
    union all select month, 'net_burn', 5, 'Capex', capex - p_capex from j
    union all select month, 'net_burn', 6, 'Working capital and timing',
        (net_burn - p_net_burn) - (-(revenue - p_revenue) + (cogs - p_cogs) + (payroll - p_payroll) + (other_opex - p_other_opex) + (capex - p_capex)) from j
    union all select month, 'net_burn', 9, 'This month', net_burn from j
)

select month, bridge, step_order, step, {{ dec("round(amount, 2)", 18, 2) }} as amount
from steps
where month > (select min(month) from j)
