-- How each customer pays, per invoice type (usage and project billing are paid by different people and
-- processes, so a late project payer can hide behind on-time usage payments if they are averaged together).
-- Paid invoices with terms only (self-serve cards excluded: terms are 0 days).
-- Chronic late payer: at least 3 paid invoices of that type and an average of more than 30 days past due.
select
    customer_id,
    invoice_type,
    any_value(segment) as segment,
    count(*) as invoices_paid,
    {{ dec("round(" ~ fdiv("sum(days_to_pay)", "count(days_to_pay)") ~ ", 1)", 9, 1) }} as avg_days_to_pay,
    {{ dec("round(" ~ fdiv("sum(days_paid_late)", "count(days_paid_late)") ~ ", 1)", 9, 1) }} as avg_days_late,
    {{ dec("round(avg(case when days_paid_late > 0 then 1 else 0 end), 4)", 9, 4) }} as pct_paid_late,
    max(days_paid_late) as max_days_late,
    count(*) >= 3 and avg(days_paid_late) > 30 as is_chronic_late
from {{ ref('fct_ar_invoices') }}
where status = 'paid' and segment <> 'self_serve'
group by customer_id, invoice_type
