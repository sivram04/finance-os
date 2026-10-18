-- Fully diluted cap table today (seeds/cap_table.csv): shares and ownership per holder and class.
select
    holder,
    security_class,
    shares,
    cast(round(shares / sum(shares) over (), 6) as decimal(9, 6)) as fully_diluted_pct,
    price_per_share,
    invested,
    issue_date
from {{ ref('cap_table') }}
