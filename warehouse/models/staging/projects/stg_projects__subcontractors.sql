select
    vendor_id,
    vendor_name
from {{ source('projects', 'subcontractors') }}
