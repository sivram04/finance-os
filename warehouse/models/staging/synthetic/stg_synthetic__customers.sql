select
    customer_id,
    customer_name,
    segment,
    signup_date
from {{ source('synthetic', 'customers') }}
