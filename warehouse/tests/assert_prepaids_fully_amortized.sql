-- Each prepaid contract amortizes to exactly its amount and ends at a zero balance.
select p.prepaid_id
from {{ ref('prepaid_contracts') }} p
join {{ ref('fct_prepaid_schedule') }} s using (prepaid_id)
group by p.prepaid_id, p.amount
having sum(s.amortization) <> p.amount or min(s.closing_balance) <> 0
