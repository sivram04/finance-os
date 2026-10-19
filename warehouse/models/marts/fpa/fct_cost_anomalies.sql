-- Daily cloud and GPU cost anomalies: each vendor x service day against its own trailing 28 days (mean and standard
-- deviation, excluding the day itself). Flagged when the cost is more than 3 standard deviations from the mean and
-- at least 500 USD away from it, so tiny services page nobody. Owner = the team label on the spend.
with daily as (
    select spend_date, vendor_id, coalesce(service, category) as service, max(coalesce(team, 'untagged')) as team, sum(cost) as cost
    from {{ ref('fct_tech_spend_daily') }} group by 1, 2, 3
),

stats as (
    select *,
           avg(cost) over (partition by vendor_id, service order by spend_date rows between 28 preceding and 1 preceding) as mean_28d,
           stddev_samp(cost) over (partition by vendor_id, service order by spend_date rows between 28 preceding and 1 preceding) as sd_28d,
           count(*) over (partition by vendor_id, service order by spend_date rows between 28 preceding and 1 preceding) as n
    from daily
)

select spend_date, vendor_id, service, team,
       {{ dec("round(cost, 2)", 18, 2) }} as cost,
       {{ dec("round(mean_28d, 2)", 18, 2) }} as expected,
       {{ dec("round(cost - mean_28d, 2)", 18, 2) }} as deviation,
       {{ dec("round(" ~ fdiv("cost - mean_28d", "nullif(sd_28d, 0)") ~ ", 2)", 9, 2) }} as z_score,
       case when cost > mean_28d then 'spike' else 'drop' end as direction
from stats
where n >= 14 and sd_28d > 0 and abs(cost - mean_28d) > 3 * sd_28d and abs(cost - mean_28d) >= 500
