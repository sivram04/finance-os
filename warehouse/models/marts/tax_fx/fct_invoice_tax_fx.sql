-- Every AR invoice in the customer's billing currency, with sales tax / VAT / GST and FX.
-- Prices are set in USD and converted at the invoice-month rate (seeds/fx_rates.csv: USD per unit).
-- Tax is charged on top in local currency (reverse-charge and exempt regimes charge 0).
-- Paid invoices: realized FX = local amount × payment-month rate − USD booked.
-- Open invoices: unrealized FX = local balance × latest rate − USD balance (the month-end revaluation).
with profile as (
    select i.*,
           coalesce(p.country, 'US') as country,
           coalesce(p.currency, 'USD') as currency,
           coalesce(p.tax_regime, 'us_saas_exempt') as tax_regime,
           coalesce(p.tax_rate, 0) as tax_rate
    from {{ ref('fct_ar_invoices') }} i
    left join {{ ref('customer_billing_profile') }} p using (customer_id)
),

latest as (
    select max(month) as m from {{ ref('fx_rates') }}
    where month <= (select max(entry_month) from {{ ref('stg_erp__journal_entries') }})
)

select
    p.invoice_ref,
    p.customer_id,
    p.country,
    p.currency,
    p.tax_regime,
    p.invoice_date,
    p.status,
    cast(p.amount as decimal(18, 2)) as amount_usd,
    cast(r.usd_per_unit as decimal(18, 6)) as invoice_rate,
    cast(round(p.amount / r.usd_per_unit, 2) as decimal(18, 2)) as amount_local,
    cast(p.tax_rate as decimal(9, 4)) as tax_rate,
    cast(round(p.amount / r.usd_per_unit * p.tax_rate, 2) as decimal(18, 2)) as tax_local,
    cast(round(p.amount * p.tax_rate, 2) as decimal(18, 2)) as tax_usd,
    case when p.status = 'paid' and p.currency <> 'USD'
         then cast(round(p.amount / r.usd_per_unit * pr.usd_per_unit - p.amount, 2) as decimal(18, 2)) end as realized_fx,
    case when p.status = 'open' and p.currency <> 'USD'
         then cast(round(p.balance / r.usd_per_unit * lr.usd_per_unit - p.balance, 2) as decimal(18, 2)) end as unrealized_fx
from profile p
join {{ ref('fx_rates') }} r on r.currency = p.currency and r.month = date_trunc('month', p.invoice_date)
left join {{ ref('fx_rates') }} pr on pr.currency = p.currency and pr.month = date_trunc('month', p.paid_date)
cross join latest l
join {{ ref('fx_rates') }} lr on lr.currency = p.currency and lr.month = l.m
