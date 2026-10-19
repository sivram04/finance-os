select entity_id, entity_name, country, currency, parent_entity_id, role, markup_pct
from {{ ref('entities') }}
