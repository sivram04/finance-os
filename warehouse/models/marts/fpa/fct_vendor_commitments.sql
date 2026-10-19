-- Procurement: purchase commitments still to be paid on vendor contracts.
--   remaining commitment = committed GPU hours per month x the contract rate x months left on the contract
with as_of_month as (select max(month) as m from {{ ref('fct_kpi_monthly') }}),

c as (
    select c.vendor_id, c.contract_id, c.start_date, c.end_date, c.committed_gpu_type, c.committed_gpu_hours_month,
           r.rate_per_gpu_hour, a.m as as_of
    from {{ ref('vendor_contracts') }} c
    cross join as_of_month a
    left join {{ ref('gpu_rates') }} r on r.gpu_type = c.committed_gpu_type
        and a.m between r.effective_from and coalesce(r.effective_to, date '9999-12-31')
    where c.committed_gpu_hours_month is not null
)

select vendor_id, contract_id, start_date, end_date, committed_gpu_type,
       {{ dec("committed_gpu_hours_month", 18, 2) }} as committed_hours_month,
       {{ dec("rate_per_gpu_hour", 18, 4) }} as rate,
       {{ dec("committed_gpu_hours_month * rate_per_gpu_hour", 18, 2) }} as committed_spend_month,
       cast(greatest((extract(year from end_date) - extract(year from as_of)) * 12 + extract(month from end_date) - extract(month from as_of), 0) as bigint) as months_remaining,
       {{ dec("committed_gpu_hours_month * rate_per_gpu_hour * greatest((extract(year from end_date) - extract(year from as_of)) * 12 + extract(month from end_date) - extract(month from as_of), 0)", 18, 2) }} as remaining_commitment
from c
