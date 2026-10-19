-- Savings won by procurement, by month: negotiated rate reductions on GPU hours actually used (against the vendor
-- previous rate for that GPU type) and early-payment discounts captured on vendor payments.
with rates as (
    select gpu_type, vendor_id, effective_from, rate_per_gpu_hour,
           lag(rate_per_gpu_hour) over (partition by gpu_type, vendor_id order by effective_from) as prior_rate
    from {{ ref('gpu_rates') }}
),

used as (
    select job_month as month, gpu_type, vendor_id, {{ fdiv("sum(gpu_seconds)", 3600) }} as hours
    from {{ ref('int_gpu_cost_jobs') }} group by 1, 2, 3
),

rate_savings as (
    select u.month, sum(u.hours * (r.prior_rate - r.rate_per_gpu_hour)) as savings
    from used u join rates r on r.gpu_type = u.gpu_type and r.vendor_id = u.vendor_id
        and u.month >= r.effective_from and r.prior_rate is not null
    group by 1
),

discounts as (
    select e.entry_month as month, sum(l.credit) as savings
    from {{ ref('stg_erp__journal_lines') }} l join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where e.entry_type = 'vendor_payment' and l.account_id = '5000' and l.credit > 0 group by 1
),

months as (select distinct month from used where month <= {{ closed_through() }})

select m.month,
       {{ dec("round(coalesce(r.savings, 0), 2)", 18, 2) }} as rate_savings,
       {{ dec("round(coalesce(d.savings, 0), 2)", 18, 2) }} as early_pay_discounts,
       {{ dec("round(coalesce(r.savings, 0) + coalesce(d.savings, 0), 2)", 18, 2) }} as total_savings
from months m
left join rate_savings r using (month)
left join discounts d using (month)
