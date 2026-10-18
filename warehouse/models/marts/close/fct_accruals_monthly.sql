-- Month-end accruals: vendor costs booked in the month whose invoice had not arrived by month end
-- (accrued from metered usage), i.e. the accrued-liability balance the close must support. When the bill
-- arrives, true_up = billed − accrued.
select
    e.entry_month as month,
    b.vendor_id,
    b.bill_id,
    b.bill_date,
    cast(sum(l.credit) as decimal(18, 2)) as accrued_amount,
    cast(b.total_amount as decimal(18, 2)) as billed_amount,
    cast(b.total_amount - sum(l.credit) as decimal(18, 2)) as true_up
from {{ ref('stg_erp__journal_entries') }} e
join {{ ref('stg_erp__journal_lines') }} l using (entry_id)
join {{ ref('stg_erp__vendor_bills') }} b on b.bill_id = e.source_ref
where e.entry_type = 'vendor_bill'
  and l.account_id = '2000'
  and b.bill_date > last_day(e.entry_month)
group by e.entry_month, b.vendor_id, b.bill_id, b.bill_date, b.total_amount
