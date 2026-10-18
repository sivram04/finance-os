-- Driving transactions for each BvA alert: the largest journal lines in that department × account × month.
-- Feeds the variance explainer (FR-5.4, FR-11.6) so commentary cites real postings, not guesses.
with lines as (
    select
        e.entry_month as month,
        coalesce(l.department_id, 'NONE') as department_id,
        l.account_id,
        e.entry_id,
        e.entry_date,
        e.entry_type,
        e.memo,
        l.customer_id,
        l.vendor_id,
        case when a.account_type = 'revenue' then -l.amount else l.amount end as natural_amount
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    join {{ ref('gl_accounts') }} a using (account_id)
),

ranked as (
    select
        al.alert_id,
        l.*,
        row_number() over (partition by al.alert_id order by abs(l.natural_amount) desc, l.entry_id) as driver_rank,
        l.natural_amount / nullif(sum(l.natural_amount) over (partition by al.alert_id), 0) as share_of_actual
    from {{ ref('fct_bva_alerts') }} al
    join lines l using (month, department_id, account_id)
)

select
    alert_id,
    driver_rank,
    entry_id,
    entry_date,
    entry_type,
    memo,
    customer_id,
    vendor_id,
    {{ dec("natural_amount", 18, 2) }} as amount,
    {{ dec("round(share_of_actual, 4)", 9, 4) }} as share_of_actual
from ranked
where driver_rank <= 5
