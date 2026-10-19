-- Segment P&L by closed month, cut two ways (region and channel): revenue, cost of revenue (GPU, shared GPU, unused
-- commit, cloud, allocated by usage), gross margin, cost to serve (payment fees, support, success), contribution margin,
-- then the remaining operating expenses allocated to customers by OPERATIONAL DRIVERS, and segment operating income.
-- Allocation drivers (the allocation_basis column says which applied):
--   Engineering and Infrastructure opex  customer share of audio hours (usage drives platform work)
--   Sales opex                            sales-led customers, equal shares (self-serve is not sold to)
--   Professional Services opex            customer share of project services revenue
--   G&A opex                              customer share of revenue (no operational driver exists: last resort)
-- An 'Unallocated' line carries what the ledger recognized but no customer carries (timing, refunds), so each cut
-- adds up to the income statement.
with ue as (
    select month, customer_id, sum(revenue) as revenue, sum(cogs) as cogs, sum(audio_hours) as hours,
           sum(payment_fees + support_cost + success_cost) as cost_to_serve
    from {{ ref('fct_unit_economics_monthly') }}
    where month <= {{ closed_through() }}
    group by 1, 2
),

services as (
    select {{ month_start("invoice_date") }} as month, customer_id, sum(amount) as revenue
    from {{ ref('int_ar_invoices') }} where invoice_type = 'project' group by 1, 2
),

cust as (
    select coalesce(u.month, s.month) as month, coalesce(u.customer_id, s.customer_id) as customer_id,
           coalesce(u.revenue, 0) + coalesce(s.revenue, 0) as revenue, coalesce(s.revenue, 0) as services_revenue,
           coalesce(u.cogs, 0) as cogs, coalesce(u.hours, 0) as hours, coalesce(u.cost_to_serve, 0) as cost_to_serve
    from ue u full join services s on s.month = u.month and s.customer_id = u.customer_id
    where coalesce(u.month, s.month) <= {{ closed_through() }}
),

dept_opex as (  -- operating expenses not already in cost to serve, excluding depreciation, by department pool
    select month,
           sum(case when department_id in ('ENG', 'INF') then natural_amount else 0 end) as platform_opex,
           sum(case when department_id = 'SAL' then natural_amount else 0 end) as sales_opex,
           sum(case when department_id = 'PS' then natural_amount else 0 end) as services_opex,
           sum(case when department_id not in ('ENG', 'INF', 'SAL', 'PS') then natural_amount else 0 end) as ga_opex
    from {{ ref('fct_gl_monthly') }}
    where account_type = 'opex' and account_id <> '6600' and month <= {{ closed_through() }}
    group by 1
),

cost_to_serve_total as (select month, sum(cost_to_serve) as v from cust group by 1),

keyed as (
    select c.*, g.channel, g.region,
           {{ fdiv("c.hours", "nullif(sum(c.hours) over (partition by c.month), 0)") }} as hours_share,
           {{ fdiv("case when g.channel <> 'Self-serve (product-led)' and c.revenue > 0 then 1 else 0 end",
                   "nullif(sum(case when g.channel <> 'Self-serve (product-led)' and c.revenue > 0 then 1 else 0 end) over (partition by c.month), 0)") }} as sales_share,
           {{ fdiv("c.services_revenue", "nullif(sum(c.services_revenue) over (partition by c.month), 0)") }} as services_share,
           {{ fdiv("c.revenue", "nullif(sum(c.revenue) over (partition by c.month), 0)") }} as revenue_share
    from cust c join {{ ref('dim_customer_geo') }} g using (customer_id)
),

alloc as (
    -- support and success are already in cost to serve, so they come out of the Sales and Services pools first
    select k.*,
           coalesce(k.hours_share, 0) * o.platform_opex
           + coalesce(k.sales_share, 0) * o.sales_opex
           + coalesce(k.services_share, 0) * o.services_opex
           + coalesce(k.revenue_share, 0) * (o.ga_opex - t.v) as allocated_opex
    from keyed k join dept_opex o using (month) join cost_to_serve_total t using (month)
),

cuts as (
    select month, 'region' as dimension, region as segment, revenue, cogs, cost_to_serve, allocated_opex from alloc
    union all
    select month, 'channel', channel, revenue, cogs, cost_to_serve, allocated_opex from alloc
),

by_segment as (
    select month, dimension, segment, sum(revenue) as revenue, sum(cogs) as cogs, sum(cost_to_serve) as cost_to_serve,
           sum(allocated_opex) as allocated_opex
    from cuts group by 1, 2, 3
),

gl as (
    select month, sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
           sum(case when account_type = 'cogs' then natural_amount else 0 end) as cogs
    from {{ ref('fct_gl_monthly') }} where month <= {{ closed_through() }} group by 1
),

agg as (
    select * from by_segment
    union all
    select b.month, b.dimension, 'Unallocated (timing, refunds)', g.revenue - sum(b.revenue), g.cogs - sum(b.cogs), 0, 0
    from by_segment b join gl g using (month)
    group by b.month, b.dimension, g.revenue, g.cogs
)

select
    month,
    dimension,
    segment,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("cogs", 18, 2) }} as cogs,
    {{ dec("revenue - cogs", 18, 2) }} as gross_margin,
    {{ dec("round(" ~ fdiv("revenue - cogs", "nullif(revenue, 0)") ~ ", 4)", 9, 4) }} as gross_margin_pct,
    {{ dec("cost_to_serve", 18, 2) }} as cost_to_serve,
    {{ dec("revenue - cogs - cost_to_serve", 18, 2) }} as contribution_margin,
    {{ dec("round(" ~ fdiv("revenue", "nullif(sum(revenue) over (partition by month, dimension), 0)") ~ ", 4)", 9, 4) }} as revenue_share,
    {{ dec("round(allocated_opex, 2)", 18, 2) }} as allocated_opex,
    {{ dec("round(revenue - cogs - cost_to_serve - allocated_opex, 2)", 18, 2) }} as operating_income,
    'platform: audio hours; sales: sales-led customers; services: project revenue; G&A: revenue' as allocation_basis
from agg
