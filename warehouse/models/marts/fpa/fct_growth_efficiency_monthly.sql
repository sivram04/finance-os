-- ARR waterfall and growth efficiency per closed month (MRR here = recognized usage revenue; ARR = MRR × 12).
--   net new ARR      (new + expansion + reactivation + contraction + churn) × 12; contraction and churn are negative
--   quick ratio      (new + expansion + reactivation) / |contraction + churn|: ARR added per ARR lost
--   burn multiple    net cash burned / net new ARR, both over the trailing 3 months (monthly ARR moves are noisy
--                    for a usage business); null when net new ARR is not positive (burning without growing)
with b as (
    select
        m.*,
        (new_mrr + expansion_mrr + reactivation_mrr) * 12 as gross_new_arr,
        (contraction_mrr + churned_mrr) * 12 as lost_arr,
        (new_mrr + expansion_mrr + reactivation_mrr + contraction_mrr + churned_mrr) * 12 as net_new_arr
    from {{ ref('fct_mrr_bridge_monthly') }} m
    where m.month <= {{ closed_through() }}
),

w as (
    select
        b.*,
        c.net_burn,
        sum(b.net_new_arr) over (order by b.month rows between 2 preceding and current row) as net_new_arr_t3m,
        sum(c.net_burn) over (order by b.month rows between 2 preceding and current row) as net_burn_t3m,
        sum(b.gross_new_arr) over (order by b.month rows between 2 preceding and current row) as gross_new_arr_t3m,
        sum(b.lost_arr) over (order by b.month rows between 2 preceding and current row) as lost_arr_t3m
    from b
    left join {{ ref('fct_cash_monthly') }} c on c.month = b.month
)

select
    month,
    {{ dec("opening_mrr * 12", 18, 2) }} as opening_arr,
    {{ dec("new_mrr * 12", 18, 2) }} as new_arr,
    {{ dec("expansion_mrr * 12", 18, 2) }} as expansion_arr,
    {{ dec("reactivation_mrr * 12", 18, 2) }} as reactivation_arr,
    {{ dec("contraction_mrr * 12", 18, 2) }} as contraction_arr,
    {{ dec("churned_mrr * 12", 18, 2) }} as churned_arr,
    {{ dec("closing_mrr * 12", 18, 2) }} as closing_arr,
    {{ dec("net_new_arr", 18, 2) }} as net_new_arr,
    {{ dec("net_burn", 18, 2) }} as net_burn,
    {{ dec("round(" ~ fdiv("gross_new_arr_t3m", "nullif(-lost_arr_t3m, 0)") ~ ", 2)", 9, 2) }} as quick_ratio,
    case when net_new_arr_t3m > 0 then
        {{ dec("round(" ~ fdiv("greatest(net_burn_t3m, 0)", "net_new_arr_t3m") ~ ", 2)", 9, 2) }} end as burn_multiple,
    {{ dec("net_new_arr_t3m", 18, 2) }} as net_new_arr_t3m,
    {{ dec("net_burn_t3m", 18, 2) }} as net_burn_t3m
from w
