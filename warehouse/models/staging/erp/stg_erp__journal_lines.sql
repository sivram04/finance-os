-- Journal lines from the NetSuite export, with internal ids mapped back to account numbers, department codes and
-- customer / vendor codes (an entity is one or the other), and the legal entity (NetSuite subsidiary) that booked it.
select
    t.tranid as entry_id,
    l.id as line_no,
    cast(a.acctnumber as {{ t_string() }}) as account_id,
    d.externalid as department_id,
    case when e.type = 'customer' then e.entityid end as customer_id,
    case when e.type = 'vendor' then e.entityid end as vendor_id,
    coalesce(s.externalid, 'US01') as entity_id,
    {{ dec("l.debit", 18, 2) }} as debit,
    {{ dec("l.credit", 18, 2) }} as credit,
    {{ dec("l.debit - l.credit", 18, 2) }} as amount
from {{ source('netsuite', 'transactionline') }} l
join {{ source('netsuite', 'transaction') }} t on t.id = l.transaction
join {{ source('netsuite', 'account') }} a on a.id = l.account
left join {{ source('netsuite', 'department') }} d on d.id = l.department
left join {{ source('netsuite', 'entity') }} e on e.id = l.entity
left join {{ source('netsuite', 'subsidiary') }} s on s.id = l.subsidiary
where l.posting = 'T'
