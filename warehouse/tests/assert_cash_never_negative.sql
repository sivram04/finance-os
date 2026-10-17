-- The company can't spend cash it doesn't have. A negative month means the generator's funding is too small
-- or a cash posting has the wrong sign.
select month, closing_cash
from {{ ref('fct_cash_monthly') }}
where closing_cash < 0
