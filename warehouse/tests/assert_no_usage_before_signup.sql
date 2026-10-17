-- Usage can't start before the customer signed up.
select u.usage_id
from {{ ref('stg_synthetic__usage_daily') }} u
join {{ ref('stg_synthetic__customers') }} c using (customer_id)
where u.usage_date < c.signup_date
