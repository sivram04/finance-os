-- Monthly tax and FX summary by currency and tax regime: billings, tax collected (a liability to remit by
-- the 20th of the next month), realized FX on cash received in the month, and FX exposure in open AR.
select
    {{ month_start("invoice_date") }} as month,
    currency,
    tax_regime,
    count(*) as invoices,
    {{ dec("sum(amount_usd)", 18, 2) }} as billings_usd,
    {{ dec("sum(amount_local)", 18, 2) }} as billings_local,
    {{ dec("sum(tax_usd)", 18, 2) }} as tax_collected_usd,
    {{ add_days("last_day(" ~ month_start("invoice_date") ~ ")", 20) }} as tax_remit_due,
    {{ dec("coalesce(sum(realized_fx), 0)", 18, 2) }} as realized_fx,
    {{ dec("coalesce(sum(unrealized_fx), 0)", 18, 2) }} as unrealized_fx_on_open_ar
from {{ ref('fct_invoice_tax_fx') }}
group by all
