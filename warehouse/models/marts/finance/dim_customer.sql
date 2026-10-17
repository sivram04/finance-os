select
    customer_id,
    customer_name,
    segment,
    signup_date
from {{ ref('stg_synthetic__customers') }}
