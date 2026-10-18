-- Deferred revenue roll-forward: opening + billings − ASC 606 revenue = closing, every month.
select * from {{ ref('fct_revenue_rollforward_monthly') }}
where abs(opening_net_deferred + billings - asc606_revenue - closing_net_deferred) > 0.05
