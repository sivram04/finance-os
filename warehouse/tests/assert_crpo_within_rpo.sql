-- Current RPO is the part of RPO due in the next 12 months, so it can never exceed RPO.
select month, contract_id, rpo, crpo
from {{ ref('fct_contract_revenue_monthly') }}
where crpo > rpo + 0.01
