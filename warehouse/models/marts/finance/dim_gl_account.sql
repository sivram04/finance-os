select account_id, account_name, account_type, statement, {{ adapter.quote('rollup') }}
from {{ ref('gl_accounts') }}
