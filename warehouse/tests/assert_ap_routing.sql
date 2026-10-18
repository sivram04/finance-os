-- AP routing is right when:
--   every document with an injected document issue is in the review queue for the expected reason, and
--   every other document auto-approves, except the subcontractor bill posted without a PO (A-M6-04),
--   which must be in review as missing_po.
with t as (
    select t.*, case t.doc_issue
                    when 'arithmetic_error' then 'arithmetic_mismatch'
                    when 'duplicate_submission' then 'duplicate_invoice'
                    when 'wrong_po' then 'po_vendor_mismatch'
                end as expected_reason
    from {{ ref('stg_synthetic__ap_document_truth') }} t
),

d as (
    select doc_file, route, issues from {{ ref('fct_ap_documents') }}
)

select t.doc_file, t.doc_issue, t.expected_reason, d.route, d.issues
from t
join d using (doc_file)
where
    (t.expected_reason is not null and not {{ array_has("d.issues", "t.expected_reason") }})
    or (t.expected_reason is null and t.po_number is null and t.vendor_id in ('annotate_co', 'fedsec')
        and not {{ array_has("d.issues", "'missing_po'") }})
    or (t.expected_reason is null and not (t.po_number is null and t.vendor_id in ('annotate_co', 'fedsec'))
        and d.route <> 'auto_approve')
