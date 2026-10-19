-- Proposed vendor payment runs for unpaid bills: pay on the discount date when an early-pay discount is
-- worth taking (seeds/vendor_payment_terms.csv), otherwise on the due date; batched into the weekly run
-- (Thursday) on or before that date. Overdue bills go in the next run, flagged.
with as_of as (
    select max(entry_date) as d from {{ ref('stg_erp__journal_entries') }}
),

open_bills as (
    select f.reference as bill_ref, -f.amount as amount, f.flow_date as due_date
    from {{ ref('int_cash_flows_forecast') }} f
    where f.category = 'vendor_bills'
),

detail as (
    select
        o.bill_ref,
        coalesce(b.vendor_id, sb.vendor_id, lower({{ dbt.split_part("o.bill_ref", "'-'", 2) }})) as vendor_id,
        b.bill_date,
        o.due_date,
        o.amount,
        coalesce(t.early_pay_discount_pct, 0) as discount_pct,
        case when t.discount_days > 0 then {{ add_days("b.bill_date", "t.discount_days") }} end as discount_date,
        coalesce(t.priority, 'normal') as priority
    from open_bills o
    left join {{ ref('stg_erp__vendor_bills') }} b on b.bill_id = o.bill_ref
    left join {{ ref('stg_projects__subcontractor_bills') }} sb on sb.bill_id = o.bill_ref
    left join {{ ref('vendor_payment_terms') }} t on t.vendor_id = b.vendor_id
),

planned as (
    select
        d.*,
        case when d.discount_pct > 0 and d.discount_date > a.d then d.discount_date else d.due_date end as target_date,
        a.d as as_of_date
    from detail d cross join as_of a
)

select
    bill_ref,
    vendor_id,
    bill_date,
    due_date,
    {{ dec("amount", 18, 2) }} as amount,
    priority,
    -- weekly run: the Thursday on or before the target date, never before the next Thursday after as-of
    greatest({{ add_days("target_date", "-mod(" ~ day_of_week("target_date") ~ " + 3, 7)") }},
             {{ add_days("as_of_date", "mod(11 - " ~ day_of_week("as_of_date") ~ ", 7) + 1") }}) as payment_run_date,
    {{ dec("amount * discount_pct", 18, 2) }} as discount_captured,
    {{ dec("amount * (1 - discount_pct)", 18, 2) }} as amount_to_pay,
    due_date <= as_of_date as is_overdue
from planned
