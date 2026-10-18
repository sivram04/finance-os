-- ASC 606 revenue by performance obligation × month, against what was billed and what the GL booked.
-- Usage (metered, billed monthly in arrears): recognized as delivered = billed, so no contract balance.
-- Projects: revenue follows the transfer of control (fixed fee: cost-to-cost % complete; T&M: hours × rate
-- + ODCs), from fct_project_financials. The GL books services revenue when invoiced, so the difference is
-- the adjusting entry the close needs: earned > billed is a contract asset (unbilled receivable), billed >
-- earned is a contract liability (deferred revenue).
with usage as (
    select
        e.entry_month as month,
        'usage' as obligation,
        l.customer_id,
        cast(null as varchar) as project_id,
        -sum(l.amount) as billed,
        -sum(l.amount) as gl_revenue,
        -sum(l.amount) as recognized,
        0 as contract_asset,
        0 as contract_liability
    from {{ ref('stg_erp__journal_lines') }} l
    join {{ ref('stg_erp__journal_entries') }} e using (entry_id)
    where l.account_id in ('4000', '4010')
    group by all
),

projects as (
    select
        month,
        'project_' || project_type as obligation,
        customer_id,
        project_id,
        billed_to_date - coalesce(lag(billed_to_date) over w, 0) as billed,
        billed_to_date - coalesce(lag(billed_to_date) over w, 0) as gl_revenue,
        earned_to_date - coalesce(lag(earned_to_date) over w, 0) as recognized,
        unbilled as contract_asset,
        deferred as contract_liability
    from {{ ref('fct_project_financials') }}
    window w as (partition by project_id order by month)
)

select
    month,
    obligation,
    customer_id,
    project_id,
    cast(billed as decimal(18, 2)) as billed,
    cast(gl_revenue as decimal(18, 2)) as gl_revenue,
    cast(recognized as decimal(18, 2)) as asc606_revenue,
    cast(recognized - gl_revenue as decimal(18, 2)) as adjustment_needed,
    cast(contract_asset as decimal(18, 2)) as contract_asset,
    cast(contract_liability as decimal(18, 2)) as contract_liability
from (select * from usage union all select * from projects)
