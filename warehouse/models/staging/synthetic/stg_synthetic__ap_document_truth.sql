select
    doc_file,
    erp_bill_id,
    vendor_id,
    vendor_name,
    vendor_invoice_number,
    invoice_date,
    po_number,
    total,
    doc_issue
from {{ source('synthetic', 'ap_document_truth') }}
