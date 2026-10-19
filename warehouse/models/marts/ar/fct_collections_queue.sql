-- FR-8.3: who to call first, as of the last day of data. Overdue open invoices, ranked by
-- balance × days overdue × segment weight. Disputed invoices are listed but not chased (they need the
-- dispute resolved, not a reminder). The action and tone come from seeds/collection_tiers.csv and feed
-- the reminder drafter (FR-8.4), which only drafts — a person approves and sends.
-- Customers with an open cash-application exception are held too: the "overdue" invoice may already be
-- paid (cash applied to the wrong invoice), so AR fixes the application before anyone is chased.
-- Route (seeds/ar_policy.csv): card customers are handled by automatic dunning (card retries), never by a
-- person; balances under the segment's minimum aren't worth a call. Only 'manual' rows get a queue rank.
with cash_app_holds as (
    select distinct customer_id from {{ ref('fct_cash_application_exceptions') }}
)

select
    i.invoice_ref,
    i.customer_id,
    i.segment,
    i.invoice_type,
    i.project_id,
    i.invoice_date,
    i.due_date,
    i.balance,
    i.days_past_due,
    i.is_disputed,
    h.customer_id is not null as is_cash_app_hold,
    i.is_disputed or h.customer_id is not null as is_on_hold,
    case when i.is_disputed or h.customer_id is not null then 'on_hold'
         when p.collection_method = 'dunning' then 'dunning'
         when i.balance < p.min_chase_amount then 'below_threshold'
         else 'manual' end as route,
    {{ dec("i.balance * i.days_past_due * p.collection_weight", 18, 2) }} as priority_score,
    case when i.is_disputed or h.customer_id is not null or p.collection_method = 'dunning'
              or i.balance < p.min_chase_amount then null
         else rank() over (partition by (i.is_disputed or h.customer_id is not null or p.collection_method = 'dunning'
                                         or i.balance < p.min_chase_amount)
                           order by i.balance * i.days_past_due * p.collection_weight desc)
    end as queue_rank,
    case when i.is_disputed then 'Resolve dispute before collecting'
         when h.customer_id is not null then 'Fix cash application first; invoice may already be paid'
         when p.collection_method = 'dunning' then 'Automatic card retry (dunning); no manual follow-up'
         when i.balance < p.min_chase_amount then 'Below the chase threshold; include in the next statement'
         else t.action end as recommended_action,
    case when i.is_disputed or h.customer_id is not null or p.collection_method = 'dunning'
              or i.balance < p.min_chase_amount then null else t.tone end as reminder_tone,
    t.tier as reminder_tier
from {{ ref('fct_ar_invoices') }} i
join {{ ref('ar_policy') }} p using (segment)
left join cash_app_holds h using (customer_id)
left join {{ ref('collection_tiers') }} t
    on i.days_past_due between t.min_days_overdue and t.max_days_overdue
where i.status = 'open' and i.days_past_due > 0
