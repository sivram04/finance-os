-- FR-12.6: one table of every reconciliation check × period, standard columns. The "Trust" page reads this.
{% set checks = ['recon_vendor_invoices', 'recon_vendor_bills_gl', 'recon_gl_revenue', 'recon_payroll_gl',
                 'recon_project_billing_gl', 'recon_project_labor', 'recon_usage_events',
                 'recon_stripe_revenue_gl', 'recon_stripe_cash_gl'] %}
{% for c in checks %}
select
    check_name,
    cast(period as date) as period,
    {{ 'vendor_id' if c == 'recon_vendor_invoices' else 'entity_id' }} as entity_id,
    {{ dec("expected", 18, 2) }} as expected,
    {{ dec("actual", 18, 2) }} as actual,
    {{ dec("variance", 18, 2) }} as variance,
    variance_pct,
    tolerance_pct,
    status,
    explanation
from {{ ref(c) }}
where cast(period as date) <= {{ closed_through() }}  -- open months are reconciled once they close
{% if not loop.last %}union all{% endif %}
{% endfor %}
