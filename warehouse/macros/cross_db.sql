{#- Cross-database helpers so one model compiles for DuckDB (local) and BigQuery (cloud).
    Each dispatches on the adapter: default__ is DuckDB, bigquery__ is BigQuery. -#}

{#- A scalar from a JSON column as text: json_str('data', 'metadata.erp_invoice_ref') -#}
{% macro json_str(column, path) %}{{ return(adapter.dispatch('json_str')(column, path)) }}{% endmacro %}
{% macro default__json_str(column, path) %}json_extract_string({{ column }}, '$.{{ path }}'){% endmacro %}
{% macro bigquery__json_str(column, path) %}json_value({{ column }}, '$.{{ path }}'){% endmacro %}

{#- A JSON integer (Stripe amounts in cents, Unix timestamps) -#}
{% macro json_int(column, path) %}cast({{ json_str(column, path) }} as bigint){% endmacro %}

{#- A JSON boolean -#}
{% macro json_bool(column, path) %}({{ json_str(column, path) }} = 'true'){% endmacro %}

{#- Unix seconds → UTC timestamp (no session time zone involved) -#}
{% macro unix_ts(expr) %}{{ return(adapter.dispatch('unix_ts')(expr)) }}{% endmacro %}
{% macro default__unix_ts(expr) %}(timestamp '1970-01-01 00:00:00' + to_seconds(cast({{ expr }} as bigint))){% endmacro %}
{% macro bigquery__unix_ts(expr) %}timestamp_seconds(cast({{ expr }} as int64)){% endmacro %}

{#- Integer cents → exact dollars (DECIMAL / NUMERIC, never floating point) -#}
{% macro cents_to_usd(expr) %}{{ return(adapter.dispatch('cents_to_usd')(expr)) }}{% endmacro %}
{% macro default__cents_to_usd(expr) %}cast(cast({{ expr }} as decimal(18, 0)) * 0.01 as decimal(18, 2)){% endmacro %}
{% macro bigquery__cents_to_usd(expr) %}cast(cast({{ expr }} as numeric) / 100 as numeric){% endmacro %}

{#- Join clause that unnests a JSON array; each element is available as `alias` (a JSON value) -#}
{% macro json_unnest(column, path, alias) %}{{ return(adapter.dispatch('json_unnest')(column, path, alias)) }}{% endmacro %}
{% macro default__json_unnest(column, path, alias) %}cross join unnest(cast(json_extract({{ column }}, '$.{{ path }}') as json[])) as _u({{ alias }}){% endmacro %}
{% macro bigquery__json_unnest(column, path, alias) %}cross join unnest(json_query_array({{ column }}, '$.{{ path }}')) as {{ alias }}{% endmacro %}
