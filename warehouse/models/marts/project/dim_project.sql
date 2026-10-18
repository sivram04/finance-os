select
    p.project_id,
    p.project_name,
    p.project_type,
    p.customer_id,
    p.contract_id,
    p.start_date,
    p.planned_end_date,
    k.contract_value,
    k.ceiling,
    k.funded_amount,
    k.payment_terms_days,
    k.is_federal
from {{ ref('stg_projects__projects') }} p
join {{ ref('stg_projects__contracts') }} k using (contract_id)
