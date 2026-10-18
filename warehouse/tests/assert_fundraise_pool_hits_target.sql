-- After the option-pool shuffle, unallocated options are the target share of post-money FD shares.
select f.scenario
from {{ ref('fct_fundraise_scenarios') }} f
join {{ ref('fundraise_scenarios') }} s using (scenario)
cross join (select sum(shares) as unallocated from {{ ref('cap_table') }} where security_class = 'options_unallocated') c
where abs((c.unallocated + f.option_pool_topup) / f.post_fd_shares - s.option_pool_target_pct) > 0.0005
