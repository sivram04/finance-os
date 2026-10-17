select account_id, account_name, account_type, statement, rollup
from {{ ref('gl_accounts') }}
