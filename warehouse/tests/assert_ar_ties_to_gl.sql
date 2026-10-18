-- The AR subledger must equal the GL control account: at every month end, the sum of open invoice
-- balances (overapplied credits included) equals the GL balance of account 1200.
with gl as (
    select last_day(e.entry_month) as month_end, sum(l.amount) as monthly
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id = '1200'
    group by 1
),

gl_cum as (
    select month_end, sum(monthly) over (order by month_end) as gl_balance from gl
),

sub as (
    select s.month_end,
           sum(i.amount) - coalesce((select sum(a.amount) from {{ ref('int_ar_applications') }} a
                                     where a.applied_date <= s.month_end), 0) as subledger_balance
    from (select distinct month_end from gl_cum) s
    join {{ ref('int_ar_invoices') }} i on i.invoice_date <= s.month_end
    group by s.month_end
)

select g.month_end, g.gl_balance, s.subledger_balance
from gl_cum g
join sub s using (month_end)
where g.gl_balance <> s.subledger_balance
