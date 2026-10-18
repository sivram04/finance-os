-- Company P&L lines by month from the GL, in natural sign: the actuals every plan and forecast compares to.
select
    month,
    cast(sum(case when account_id in ('4000', '4010') then natural_amount else 0 end) as decimal(18, 2)) as revenue_usage,
    cast(sum(case when account_id = '4100' then natural_amount else 0 end) as decimal(18, 2)) as revenue_services,
    cast(sum(case when account_type = 'revenue' then natural_amount else 0 end) as decimal(18, 2)) as revenue,
    cast(sum(case when account_type = 'cogs' then natural_amount else 0 end) as decimal(18, 2)) as cogs,
    cast(sum(case when account_type = 'opex' and rollup = 'Payroll' then natural_amount else 0 end) as decimal(18, 2)) as payroll,
    cast(sum(case when account_type = 'opex' and rollup <> 'Payroll' then natural_amount else 0 end) as decimal(18, 2)) as other_opex,
    cast(sum(case when account_type = 'opex' then natural_amount else 0 end) as decimal(18, 2)) as opex
from {{ ref('fct_gl_monthly') }}
where month <= {{ closed_through() }}
group by month
