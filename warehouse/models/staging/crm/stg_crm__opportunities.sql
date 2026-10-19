select
    opportunity_id,
    customer_id,
    account_name,
    segment,
    rep_id,
    created_date,
    close_date,
    stage,
    stage in ('closed_won', 'closed_lost') as is_closed,
    stage = 'closed_won' as is_won,
    {{ dec("probability", 9, 4) }} as probability,
    {{ dec("amount_arr", 18, 2) }} as amount_arr,
    loss_reason
from {{ source('crm', 'opportunities') }}
