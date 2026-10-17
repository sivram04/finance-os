select department_id, department_name, owner_title
from {{ ref('departments') }}
