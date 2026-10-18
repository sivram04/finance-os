-- One row per document × reason it needs a human, plus documents the extractor couldn't read at all.
-- An AP specialist works this queue; nothing here is paid until a person clears it.
select
    doc_file,
    vendor_id,
    vendor_invoice_number,
    total,
    erp_bill_id,
    unnest(issues) as reason,
    case unnest(issues)
        when 'arithmetic_mismatch' then 'Printed total ' || total || ' ≠ sum of lines ' || lines_total
        when 'duplicate_invoice' then 'Invoice ' || vendor_invoice_number || ' already received'
        when 'po_vendor_mismatch' then 'PO ' || po_number || ' belongs to ' || po_vendor_id
        when 'po_not_found' then 'PO ' || po_number || ' does not exist'
        when 'missing_po' then 'Subcontractor bill with no PO'
        when 'not_in_erp' then 'No posted bill for this vendor invoice number'
        when 'amount_mismatch' then 'Posted ' || erp_amount || ' vs document ' || total
        when 'unknown_vendor' then 'Unknown vendor "' || vendor_name || '"'
    end as detail
from {{ ref('fct_ap_documents') }}
where route = 'needs_review'

union all

select doc_file, null, null, null, null, 'extraction_failed', error
from {{ ref('stg_ap__extraction_errors') }}
