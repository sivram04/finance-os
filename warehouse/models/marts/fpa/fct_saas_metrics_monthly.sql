-- SaaS unit economics per closed month (CAC on trailing 3 months to smooth lumpy spend and signups):
--   CAC              sales & marketing spend (department SAL, incl. its payroll) / new customers
--   ARPA             revenue / active customers (monthly);  LTV = ARPA × gross margin / monthly logo churn
--   CAC payback      CAC / (ARPA × gross margin), in months
--   Rule of 40       revenue growth year over year + EBITDA margin
--   Free cash flow   change in cash excluding equity raised (operations + capex)
with kpi as (
    select
        month,
        max(case when metric_name = 'revenue' then value end) as revenue,
        max(case when metric_name = 'gross_margin_pct' then value end) as gross_margin_pct,
        max(case when metric_name = 'active_customers' then value end) as active_customers,
        max(case when metric_name = 'new_customers' then value end) as new_customers,
        max(case when metric_name = 'logo_churn_rate' then value end) as logo_churn_rate,
        max(case when metric_name = 'arr' then value end) as arr
    from {{ ref('fct_kpi_monthly') }}
    group by 1
),

gl as (
    select
        month,
        sum(case when account_type = 'opex' and department_id = 'SAL' then natural_amount else 0 end) as sm_spend,
        sum(case when account_type = 'revenue' then natural_amount
                 when account_type in ('cogs', 'opex') and account_id <> '6600' then -natural_amount else 0 end) as ebitda,
        sum(case when account_id = '1000' then amount else 0 end) as cash_change,
        sum(case when account_id = '3000' then natural_amount else 0 end) as equity_raised
    from {{ ref('fct_gl_monthly') }}
    group by 1
),

j as (
    select
        k.*,
        g.sm_spend,
        g.ebitda,
        g.cash_change - g.equity_raised as free_cash_flow,
        sum(g.sm_spend) over (order by k.month rows between 2 preceding and current row) as sm_t3m,
        sum(k.new_customers) over (order by k.month rows between 2 preceding and current row) as new_t3m,
        avg(k.logo_churn_rate) over (order by k.month rows between 2 preceding and current row) as churn_t3m,
        lag(k.revenue, 12) over (order by k.month) as revenue_ly
    from kpi k
    join gl g on g.month = k.month
),

u as (
    select
        *,
        {{ fdiv("sm_t3m", "nullif(new_t3m, 0)") }} as cac,
        {{ fdiv("revenue", "nullif(active_customers, 0)") }} as arpa,
        {{ fdiv("revenue - revenue_ly", "nullif(revenue_ly, 0)") }} as growth_yoy,
        {{ fdiv("ebitda", "nullif(revenue, 0)") }} as ebitda_margin
    from j
)

select
    month,
    {{ dec("revenue", 18, 2) }} as revenue,
    {{ dec("arr", 18, 2) }} as arr,
    {{ dec("sm_spend", 18, 2) }} as sm_spend,
    cast(new_customers as bigint) as new_customers,
    {{ dec("round(cac, 2)", 18, 2) }} as cac,
    {{ dec("round(arpa, 2)", 18, 2) }} as arpa,
    {{ dec("round(churn_t3m, 4)", 9, 4) }} as monthly_logo_churn,
    {{ dec("round(" ~ fdiv("arpa * gross_margin_pct", "nullif(churn_t3m, 0)") ~ ", 2)", 18, 2) }} as ltv,
    {{ dec("round(" ~ fdiv("arpa * gross_margin_pct", "nullif(churn_t3m * cac, 0)") ~ ", 2)", 9, 2) }} as ltv_to_cac,
    {{ dec("round(" ~ fdiv("cac", "nullif(arpa * gross_margin_pct, 0)") ~ ", 1)", 9, 1) }} as cac_payback_months,
    {{ dec("round(growth_yoy, 4)", 9, 4) }} as revenue_growth_yoy,
    {{ dec("round(ebitda_margin, 4)", 9, 4) }} as ebitda_margin,
    {{ dec("round(growth_yoy + ebitda_margin, 4)", 9, 4) }} as rule_of_40,
    {{ dec("free_cash_flow", 18, 2) }} as free_cash_flow,
    {{ dec("round(" ~ fdiv("free_cash_flow", "nullif(revenue, 0)") ~ ", 4)", 9, 4) }} as fcf_margin
from u
where month <= {{ closed_through() }}
