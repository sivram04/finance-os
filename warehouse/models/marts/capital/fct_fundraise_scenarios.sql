-- Fundraise scenarios (seeds/fundraise_scenarios.csv) with the option-pool shuffle: the pool is topped up
-- pre-money so unallocated options equal the target % of post-money fully diluted shares.
--   k = target × (pre + raise) / pre;  top-up = (k × FD − unallocated) / (1 − k), floored at 0
--   price = pre ÷ (FD + top-up); new shares = raise ÷ price
-- Runway uses the base forecast: cash at close + raise, burning the forecast EBITDA from then on.
with fd as (
    select sum(shares) as fd_shares,
           sum(shares) filter (where security_class = 'options_unallocated') as unallocated,
           sum(shares) filter (where security_class = 'common') as founder_shares
    from {{ ref('cap_table') }}
),

calc as (
    select
        s.*,
        f.fd_shares, f.unallocated, f.founder_shares,
        greatest((s.option_pool_target_pct * (s.pre_money + s.raise_amount) / s.pre_money * f.fd_shares - f.unallocated)
                 / (1 - s.option_pool_target_pct * (s.pre_money + s.raise_amount) / s.pre_money), 0) as pool_topup
    from {{ ref('fundraise_scenarios') }} s
    cross join fd f
),

priced as (
    select *, pre_money / (fd_shares + pool_topup) as price
    from calc
),

cash as (
    select p.scenario, f.closing_cash as cash_at_close
    from priced p
    join {{ ref('fct_forecast_monthly') }} f
        on f.is_latest and f.scenario = 'base' and f.month = p.close_month - interval 1 month
),

runway as (
    select p.scenario,
           min(f.month) filter (where c.cash_at_close + p.raise_amount
               + (f.closing_cash - c.cash_at_close) < 0 and f.month >= p.close_month) as cash_out_month_after_raise
    from priced p
    join cash c using (scenario)
    join {{ ref('fct_forecast_monthly') }} f on f.is_latest and f.scenario = 'base'
    group by p.scenario
)

select
    p.scenario,
    p.round_name,
    p.close_month,
    cast(p.pre_money as decimal(18, 2)) as pre_money,
    cast(p.raise_amount as decimal(18, 2)) as raise_amount,
    cast(p.pre_money + p.raise_amount as decimal(18, 2)) as post_money,
    cast(round(p.price, 4) as decimal(18, 4)) as price_per_share,
    cast(round(p.pool_topup) as bigint) as option_pool_topup,
    cast(round(p.raise_amount / p.price) as bigint) as new_shares,
    cast(round(p.fd_shares + p.pool_topup + p.raise_amount / p.price) as bigint) as post_fd_shares,
    cast(round(p.raise_amount / p.price / (p.fd_shares + p.pool_topup + p.raise_amount / p.price), 4) as decimal(9, 4)) as new_investor_pct,
    cast(round(p.founder_shares / p.fd_shares, 4) as decimal(9, 4)) as founders_pct_before,
    cast(round(p.founder_shares / (p.fd_shares + p.pool_topup + p.raise_amount / p.price), 4) as decimal(9, 4)) as founders_pct_after,
    cast(c.cash_at_close as decimal(18, 2)) as forecast_cash_before_close,
    c.cash_at_close < 0 as runs_out_before_close,
    r.cash_out_month_after_raise
from priced p
left join cash c using (scenario)
left join runway r using (scenario)
