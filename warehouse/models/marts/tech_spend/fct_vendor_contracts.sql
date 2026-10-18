-- FR-3.5: vendor spend summary with contract end dates and renewal flags, as of the last day of data.
-- Flag when the contract ends within its notice period plus 30 days of lead time.
with as_of as (
    select max(spend_date) as as_of_date from {{ ref('fct_tech_spend_daily') }}
),

monthly as (
    select vendor_id, spend_month, sum(cost) as cost
    from {{ ref('fct_tech_spend_daily') }}
    group by all
),

t3m as (
    select m.vendor_id, avg(m.cost) as avg_monthly_spend_t3m
    from monthly m, as_of a
    where m.spend_month > {{ add_months(month_start("a.as_of_date"), -3) }}
    group by m.vendor_id
)

select
    c.vendor_id,
    c.vendor_name,
    c.contract_id,
    c.category,
    c.start_date,
    c.end_date,
    c.committed_gpu_type,
    c.committed_gpu_hours_month,
    c.renewal_notice_days,
    a.as_of_date,
    {{ dec("round(t.avg_monthly_spend_t3m, 2)", 18, 2) }} as avg_monthly_spend_t3m,
    {{ days_between("a.as_of_date", "c.end_date") }} as days_to_end,
    coalesce({{ days_between("a.as_of_date", "c.end_date") }} <= c.renewal_notice_days + 30, false) as is_renewal_due
from {{ ref('vendor_contracts') }} c
cross join as_of a
left join t3m t using (vendor_id)
