{#- The last closed month: the latest month whose usage invoices have been posted (the live company bills on
    the 1st for the month before). KPIs, the P&L that feeds the forecasts, and reconciliations use closed months
    only; day-by-day views (AR, AP, cash, 13-week forecast) see everything up to today. -#}
{% macro closed_through() %}(select max(entry_month) from {{ ref('stg_erp__journal_entries') }} where entry_type = 'revenue'){% endmacro %}
