-- Design §8 M3 check: each vendor invoice ↔ modeled cost for the same month, within 1%.
-- Modeled = GPU job cost at seed rates + commit shortfall (+ cloud lines for GCP).
-- Standard recon columns (design §7.3): check, period, expected, actual, variance, tolerance, status, explanation.
with modeled as (
    select vendor_id, job_month as month, sum(gpu_cost) as amount
    from {{ ref('int_gpu_cost_jobs') }}
    group by all

    union all

    select vendor_id, month, shortfall_cost
    from {{ ref('int_gpu_commit_shortfall_monthly') }}

    union all

    select 'gcp', usage_month, sum(cost)
    from {{ ref('stg_infra__cloud_costs_daily') }}
    group by all
),

modeled_total as (
    select vendor_id, month, sum(amount) as modeled_amount
    from modeled
    group by all
),

compared as (
    select
        coalesce(b.vendor_id, m.vendor_id) as vendor_id,
        coalesce(b.service_month, m.month) as period,
        b.bill_id,
        b.total_amount as expected,
        {{ dec("round(m.modeled_amount, 2)", 18, 2) }} as actual
    from {{ ref('stg_erp__vendor_bills') }} b
    full outer join modeled_total m
        on m.vendor_id = b.vendor_id and m.month = b.service_month
)

select
    'vendor_invoice_vs_modeled' as check_name,
    period,
    vendor_id,
    bill_id,
    expected,
    actual,
    actual - expected as variance,
    {{ dec("round((actual - expected) / nullif(expected, 0), 4)", 9, 4) }} as variance_pct,
    {{ dec("0.01", 9, 4) }} as tolerance_pct,
    case
        when expected is null then 'fail'
        when actual is null then 'fail'
        when abs(actual - expected) <= 0.01 * abs(expected) then 'pass'
        else 'fail'
    end as status,
    case
        when expected is null then 'Modeled cost with no vendor invoice'
        when actual is null then 'Vendor invoice with no modeled cost'
        when abs(actual - expected) <= 0.01 * abs(expected) then 'Within tolerance (metering differences)'
        else 'Outside tolerance: investigate'
    end as explanation
from compared
