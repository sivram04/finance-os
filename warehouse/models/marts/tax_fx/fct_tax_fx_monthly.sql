-- Monthly tax and FX summary by currency and tax regime: billings, tax collected (a liability to remit by
-- the 20th of the next month), realized FX on cash received in the month, and FX exposure in open AR.
select
    date_trunc('month', invoice_date)::date as month,
    currency,
    tax_regime,
    count(*) as invoices,
    cast(sum(amount_usd) as decimal(18, 2)) as billings_usd,
    cast(sum(amount_local) as decimal(18, 2)) as billings_local,
    cast(sum(tax_usd) as decimal(18, 2)) as tax_collected_usd,
    cast(last_day(date_trunc('month', invoice_date)) + 20 as date) as tax_remit_due,
    cast(coalesce(sum(realized_fx), 0) as decimal(18, 2)) as realized_fx,
    cast(coalesce(sum(unrealized_fx), 0) as decimal(18, 2)) as unrealized_fx_on_open_ar
from {{ ref('fct_invoice_tax_fx') }}
group by all
