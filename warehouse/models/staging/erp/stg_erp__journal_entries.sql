-- Journal entries from the NetSuite export: one row per posted transaction. NetSuite's document number (tranid)
-- is our entry id; the posting rule and source reference come from the implementation's custom body fields.
select
    t.tranid as entry_id,
    cast(t.trandate as date) as entry_date,
    {{ month_start("t.trandate") }} as entry_month,
    t.custbody_echo_entry_type as entry_type,
    t.memo,
    t.custbody_echo_source_ref as source_ref,
    t.type as netsuite_type,
    t.postingperiod as netsuite_period_id
from {{ source('netsuite', 'transaction') }} t
where t.posting = 'T'
