-- AP document intake: one row per vendor bill PDF, with every control applied to what was extracted.
-- The model (or rules) only read the page; these checks decide whether a bill can be approved:
--   unknown_vendor        printed vendor name is not in seeds/ap_vendor_aliases.csv
--   arithmetic_mismatch   printed total ≠ sum of printed lines
--   duplicate_invoice     same vendor + invoice number already seen on an earlier document
--   missing_po            a subcontractor bill with no PO reference
--   po_not_found          PO number cited doesn't exist
--   po_vendor_mismatch    PO exists but belongs to another vendor
--   not_in_erp            no posted bill with this vendor + invoice number
--   amount_mismatch       posted bill amount ≠ document total
-- A document with no issues is auto_approve; anything else needs_review (FR-6.9-style three-way control).
with docs as (
    select
        e.*,
        a.vendor_id,
        (select sum(l.amount) from {{ ref('stg_ap__extraction_lines') }} l where l.doc_file = e.doc_file) as lines_total,
        (select count(*) from {{ ref('stg_ap__extraction_lines') }} l where l.doc_file = e.doc_file) as line_count,
        row_number() over (partition by a.vendor_id, e.vendor_invoice_number order by e.doc_file) as copy_number
    from {{ ref('stg_ap__extractions') }} e
    left join {{ ref('ap_vendor_aliases') }} a on a.printed_name = e.vendor_name
),

erp_bills as (
    select vendor_id, vendor_invoice_number, bill_id, total_amount as amount, null as po_id, 'vendor' as bill_source
    from {{ ref('stg_erp__vendor_bills') }}
    union all
    select vendor_id, vendor_invoice_number, bill_id, amount, po_id, 'subcontractor'
    from {{ ref('stg_projects__subcontractor_bills') }}
),

subcontractors as (
    select vendor_id from {{ ref('stg_projects__subcontractors') }}
),

checked as (
    select
        d.doc_file,
        d.backend,
        d.model,
        d.vendor_name,
        d.vendor_id,
        d.vendor_invoice_number,
        d.invoice_date,
        d.po_number,
        d.total,
        d.lines_total,
        d.line_count,
        b.bill_id as erp_bill_id,
        b.amount as erp_amount,
        po.vendor_id as po_vendor_id,
        {{ array_compact("[
            case when d.vendor_id is null then 'unknown_vendor' end,
            case when d.total is distinct from d.lines_total then 'arithmetic_mismatch' end,
            case when d.copy_number > 1 then 'duplicate_invoice' end,
            case when d.vendor_id in (select vendor_id from subcontractors) and d.po_number is null then 'missing_po' end,
            case when d.po_number is not null and po.po_id is null then 'po_not_found' end,
            case when po.po_id is not null and po.vendor_id <> d.vendor_id then 'po_vendor_mismatch' end,
            case when b.bill_id is null then 'not_in_erp' end,
            case when b.bill_id is not null and b.amount is distinct from d.total then 'amount_mismatch' end
        ]") }} as issues
    from docs d
    left join erp_bills b
        on b.vendor_id = d.vendor_id and b.vendor_invoice_number = d.vendor_invoice_number
    left join {{ ref('stg_projects__purchase_orders') }} po on po.po_id = d.po_number
)

select
    *,
    {{ array_size("issues") }} as issue_count,
    case when {{ array_size("issues") }} = 0 then 'auto_approve' else 'needs_review' end as route
from checked
