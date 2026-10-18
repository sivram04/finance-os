select
    po_id,
    project_id,
    vendor_id,
    po_date,
    amount,
    description
from {{ source('projects', 'purchase_orders') }}
