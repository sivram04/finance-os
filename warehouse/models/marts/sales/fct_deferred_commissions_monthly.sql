-- Deferred commissions (ASC 340-40) per rep x month. Commissions are an incremental cost of obtaining a contract, so
-- they are capitalized when earned and amortized straight-line from the next month over the expected benefit period
-- (seeds/commission_accounting.csv: new logos and SPIFFs 48 months, expansions 36). Clawbacks reverse capitalized
-- cost on the new-logo schedule. The proposed month-end entry: Dr deferred commissions (asset) / Cr commissions
-- payable for the capitalized amount, and Dr commission expense / Cr deferred commissions for the amortization.
with earned as (
    select rep_id, month,
           (commission_base + commission_accelerator) * coalesce(new_share, 0) as cap_new,
           (commission_base + commission_accelerator) * (1 - coalesce(new_share, 0)) as cap_expansion,
           commission_clawback as cap_clawback,
           spiff as cap_spiff
    from {{ ref('fct_commission_statement_monthly') }}
),

layers as (
    select rep_id, month, 'new' as credit_type, cap_new + cap_clawback as amount from earned
    union all select rep_id, month, 'expansion', cap_expansion from earned
    union all select rep_id, month, 'spiff', cap_spiff from earned
),

amort as (
    select g.rep_id, g.month, sum({{ fdiv("l.amount", "a.amortization_months") }}) as amortization
    from earned g
    join layers l on l.rep_id = g.rep_id and l.month < g.month
    join {{ ref('commission_accounting') }} a on a.credit_type = l.credit_type
    where g.month <= {{ add_months("l.month", "a.amortization_months") }}
    group by 1, 2
),

current_portion as (  -- amortization due in the next 12 months on what is capitalized so far
    select g.rep_id, g.month,
           sum({{ fdiv("l.amount", "a.amortization_months") }} * greatest(0, least(12,
               a.amortization_months - ((extract(year from g.month) - extract(year from l.month)) * 12
                                        + extract(month from g.month) - extract(month from l.month))))) as current_portion
    from earned g
    join layers l on l.rep_id = g.rep_id and l.month <= g.month
    join {{ ref('commission_accounting') }} a on a.credit_type = l.credit_type
    group by 1, 2
),

monthly as (
    select e.rep_id, e.month, e.cap_new + e.cap_clawback + e.cap_expansion + e.cap_spiff as capitalized,
           coalesce(a.amortization, 0) as amortization, coalesce(c.current_portion, 0) as current_portion
    from earned e left join amort a using (rep_id, month) left join current_portion c using (rep_id, month)
)

select
    rep_id,
    month,
    {{ dec("round(capitalized, 2)", 18, 2) }} as capitalized,
    {{ dec("round(amortization, 2)", 18, 2) }} as amortization,
    {{ dec("round(sum(capitalized - amortization) over (partition by rep_id order by month), 2)", 18, 2) }} as deferred_commission_balance,
    {{ dec("round(least(current_portion, sum(capitalized - amortization) over (partition by rep_id order by month)), 2)", 18, 2) }} as current_portion,
    {{ dec("round(capitalized - amortization, 2)", 18, 2) }} as net_deferral
from monthly
