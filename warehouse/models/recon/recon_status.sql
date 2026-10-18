-- FR-12.6: one table of every reconciliation check × period, standard columns. The "Trust" page reads this.
{% set checks = ['recon_vendor_invoices', 'recon_vendor_bills_gl', 'recon_gl_revenue', 'recon_payroll_gl',
                 'recon_project_billing_gl', 'recon_project_labor', 'recon_usage_events',
                 'recon_stripe_revenue_gl', 'recon_stripe_cash_gl'] %}
{% for c in checks %}
select
    check_name,
    period,
    {{ 'vendor_id' if c == 'recon_vendor_invoices' else 'entity_id' }} as entity_id,
    cast(expected as decimal(18, 2)) as expected,
    cast(actual as decimal(18, 2)) as actual,
    cast(variance as decimal(18, 2)) as variance,
    variance_pct,
    tolerance_pct,
    status,
    explanation
from {{ ref(c) }}
where period <= {{ closed_through() }}  -- open months are reconciled once they close
{% if not loop.last %}union all{% endif %}
{% endfor %}
