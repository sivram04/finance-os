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

{#- ---- dates (DuckDB date arithmetic and argument orders differ from BigQuery's) ---- -#}

{#- First day of the month, as a DATE on both engines -#}
{% macro month_start(d) %}{{ return(adapter.dispatch('month_start')(d)) }}{% endmacro %}
{% macro default__month_start(d) %}cast(date_trunc('month', {{ d }}) as date){% endmacro %}
{% macro bigquery__month_start(d) %}date_trunc(cast({{ d }} as date), month){% endmacro %}

{% macro add_days(d, n) %}{{ return(adapter.dispatch('add_days')(d, n)) }}{% endmacro %}
{% macro default__add_days(d, n) %}cast({{ d }} + cast({{ n }} as integer) * interval 1 day as date){% endmacro %}
{% macro bigquery__add_days(d, n) %}date_add(cast({{ d }} as date), interval cast({{ n }} as int64) day){% endmacro %}

{% macro add_months(d, n) %}{{ return(adapter.dispatch('add_months')(d, n)) }}{% endmacro %}
{% macro default__add_months(d, n) %}cast({{ d }} + cast({{ n }} as integer) * interval 1 month as date){% endmacro %}
{% macro bigquery__add_months(d, n) %}date_add(cast({{ d }} as date), interval cast({{ n }} as int64) month){% endmacro %}

{#- Whole days from a to b (b − a) -#}
{% macro days_between(a, b) %}{{ return(adapter.dispatch('days_between')(a, b)) }}{% endmacro %}
{% macro default__days_between(a, b) %}date_diff('day', cast({{ a }} as date), cast({{ b }} as date)){% endmacro %}
{% macro bigquery__days_between(a, b) %}date_diff(cast({{ b }} as date), cast({{ a }} as date), day){% endmacro %}

{#- 'YYYY-MM' -#}
{% macro fmt_month(d) %}{{ return(adapter.dispatch('fmt_month')(d)) }}{% endmacro %}
{% macro default__fmt_month(d) %}strftime({{ d }}, '%Y-%m'){% endmacro %}
{% macro bigquery__fmt_month(d) %}format_date('%Y-%m', cast({{ d }} as date)){% endmacro %}

{#- Day of week, 0 = Sunday … 6 = Saturday -#}
{% macro day_of_week(d) %}{{ return(adapter.dispatch('day_of_week')(d)) }}{% endmacro %}
{% macro default__day_of_week(d) %}dayofweek({{ d }}){% endmacro %}
{% macro bigquery__day_of_week(d) %}(extract(dayofweek from {{ d }}) - 1){% endmacro %}

{#- A derived table of integers lo..hi in column n:  cross join {{ int_series('h', 1, 18) }}  then use h.n -#}
{% macro int_series(alias, lo, hi) %}{{ return(adapter.dispatch('int_series')(alias, lo, hi)) }}{% endmacro %}
{% macro default__int_series(alias, lo, hi) %}(select range as n from range({{ lo }}, {{ hi }} + 1)) as {{ alias }}{% endmacro %}
{% macro bigquery__int_series(alias, lo, hi) %}(select n from unnest(generate_array({{ lo }}, {{ hi }})) as n) as {{ alias }}{% endmacro %}

{#- ---- aggregates ---- -#}
{% macro bool_or(x) %}{{ return(adapter.dispatch('bool_or')(x)) }}{% endmacro %}
{% macro default__bool_or(x) %}bool_or({{ x }}){% endmacro %}
{% macro bigquery__bool_or(x) %}logical_or({{ x }}){% endmacro %}

{% macro bool_and(x) %}{{ return(adapter.dispatch('bool_and')(x)) }}{% endmacro %}
{% macro default__bool_and(x) %}bool_and({{ x }}){% endmacro %}
{% macro bigquery__bool_and(x) %}logical_and({{ x }}){% endmacro %}

{% macro median(x) %}{{ return(adapter.dispatch('median')(x)) }}{% endmacro %}
{% macro default__median(x) %}median({{ x }}){% endmacro %}
{#- exact (interpolated) median, like DuckDB's: the middle value, or the mean of the two middle values -#}
{% macro bigquery__median(x) %}(select avg(v) from (
    select v, row_number() over (order by v) as rn, count(*) over () as c
    from unnest(array_agg({{ x }} ignore nulls)) as v) where rn in (div(c + 1, 2), div(c + 2, 2))){% endmacro %}

{#- ---- types ---- -#}
{% macro t_string() %}{{ return(adapter.dispatch('t_string')()) }}{% endmacro %}
{% macro default__t_string() %}varchar{% endmacro %}
{% macro bigquery__t_string() %}string{% endmacro %}

{% macro t_float() %}{{ return(adapter.dispatch('t_float')()) }}{% endmacro %}
{% macro default__t_float() %}double{% endmacro %}
{% macro bigquery__t_float() %}float64{% endmacro %}

{#- ---- arrays ---- -#}
{#- An array literal with the NULLs removed: array_compact("['a', case ... end]") -#}
{% macro array_compact(items) %}{{ return(adapter.dispatch('array_compact')(items)) }}{% endmacro %}
{% macro default__array_compact(items) %}list_filter({{ items }}, x -> x is not null){% endmacro %}
{% macro bigquery__array_compact(items) %}array(select x from unnest({{ items }}) as x where x is not null){% endmacro %}

{% macro array_size(a) %}{{ return(adapter.dispatch('array_size')(a)) }}{% endmacro %}
{% macro default__array_size(a) %}len({{ a }}){% endmacro %}
{% macro bigquery__array_size(a) %}array_length({{ a }}){% endmacro %}

{% macro array_has(a, v) %}{{ return(adapter.dispatch('array_has')(a, v)) }}{% endmacro %}
{% macro default__array_has(a, v) %}list_contains({{ a }}, {{ v }}){% endmacro %}
{% macro bigquery__array_has(a, v) %}({{ v }} in unnest({{ a }})){% endmacro %}

{#- Join clause: one row per element of an array column, available as `alias` -#}
{% macro array_rows(a, alias) %}{{ return(adapter.dispatch('array_rows')(a, alias)) }}{% endmacro %}
{% macro default__array_rows(a, alias) %}cross join unnest({{ a }}) as _ar({{ alias }}){% endmacro %}
{% macro bigquery__array_rows(a, alias) %}cross join unnest({{ a }}) as {{ alias }}{% endmacro %}

{#- Exact decimal at a fixed scale. DuckDB: cast to decimal(p, s), which rounds to s places. BigQuery doesn't allow
    parameterized types in CAST, so: round to s places as NUMERIC (BIGNUMERIC past 9 places). Same values both ways. -#}
{% macro dec(expr, p, s) %}{{ return(adapter.dispatch('dec')(expr, p, s)) }}{% endmacro %}
{% macro default__dec(expr, p, s) %}cast({{ expr }} as decimal({{ p }}, {{ s }})){% endmacro %}
{% macro bigquery__dec(expr, p, s) %}round(cast({{ expr }} as {{ 'bignumeric' if s > 9 else 'numeric' }}), {{ s }}){% endmacro %}

{% macro try_cast_date(x) %}{{ return(adapter.dispatch('try_cast_date')(x)) }}{% endmacro %}
{% macro default__try_cast_date(x) %}try_cast({{ x }} as date){% endmacro %}
{% macro bigquery__try_cast_date(x) %}safe_cast({{ x }} as date){% endmacro %}

{#- Exact median of x over a window partition (BigQuery has no median aggregate; percentile_cont is analytic) -#}
{% macro median_over(x, partition) %}{{ return(adapter.dispatch('median_over')(x, partition)) }}{% endmacro %}
{% macro default__median_over(x, partition) %}median({{ x }}) over (partition by {{ partition }}){% endmacro %}
{% macro bigquery__median_over(x, partition) %}percentile_cont({{ x }}, 0.5) over (partition by {{ partition }}){% endmacro %}

{#- Number formatting for messages: thousands separators, no decimals; and a signed one-decimal number -#}
{% macro fmt_int_commas(x) %}{{ return(adapter.dispatch('fmt_int_commas')(x)) }}{% endmacro %}
{% macro default__fmt_int_commas(x) %}format('{:,.0f}', {{ x }}){% endmacro %}
{% macro bigquery__fmt_int_commas(x) %}format("%'.0f", cast({{ x }} as float64)){% endmacro %}

{% macro fmt_signed_1dp(x) %}{{ return(adapter.dispatch('fmt_signed_1dp')(x)) }}{% endmacro %}
{% macro default__fmt_signed_1dp(x) %}format('{:+.1f}', {{ x }}){% endmacro %}
{% macro bigquery__fmt_signed_1dp(x) %}format('%+.1f', cast({{ x }} as float64)){% endmacro %}

{#- Exact division to 9 decimal places, the same on both engines. BigQuery divides NUMERICs exactly (9 places);
    DuckDB divides decimals in double precision, so its quotient is put straight back into decimal(38, 9), which
    gives the same 9-place value. Results are then rounded as decimals (half away from zero) on both, so a rate
    like salary ÷ 2,080 hours lands on the same cent, and no money passes through a float. -#}
{% macro fdiv(a, b) %}{{ return(adapter.dispatch('fdiv')(a, b)) }}{% endmacro %}
{% macro default__fdiv(a, b) %}cast(cast({{ a }} as double) / cast({{ b }} as double) as decimal(38, 9)){% endmacro %}
{% macro bigquery__fdiv(a, b) %}(cast({{ a }} as numeric) / cast({{ b }} as numeric)){% endmacro %}

{#- ---- GCP billing export helpers (nested key/value labels, repeated credits) ---- -#}
{% macro kv_value(arr, key) %}{{ return(adapter.dispatch('kv_value')(arr, key)) }}{% endmacro %}
{% macro default__kv_value(arr, key) %}list_extract(list_transform(list_filter({{ arr }}, x -> x.key = '{{ key }}'), x -> x.value), 1){% endmacro %}
{% macro bigquery__kv_value(arr, key) %}(select l.value from unnest({{ arr }}) as l where l.key = '{{ key }}' limit 1){% endmacro %}

{% macro sum_credits(arr) %}{{ return(adapter.dispatch('sum_credits')(arr)) }}{% endmacro %}
{% macro default__sum_credits(arr) %}coalesce(list_sum(list_transform({{ arr }}, c -> cast(c.amount as decimal(18, 6)))), 0){% endmacro %}
{% macro bigquery__sum_credits(arr) %}coalesce((select sum(round(cast(c.amount as numeric), 6)) from unnest({{ arr }}) as c), 0){% endmacro %}

{#- 'YYYYMM' -> first day of that month -#}
{% macro yyyymm_to_date(s) %}{{ return(adapter.dispatch('yyyymm_to_date')(s)) }}{% endmacro %}
{% macro default__yyyymm_to_date(s) %}cast(strptime({{ s }} || '01', '%Y%m%d') as date){% endmacro %}
{% macro bigquery__yyyymm_to_date(s) %}parse_date('%Y%m%d', {{ s }} || '01'){% endmacro %}

{#- Whole hours from a timestamp to now -#}
{% macro hours_since(ts) %}{{ return(adapter.dispatch('hours_since')(ts)) }}{% endmacro %}
{% macro default__hours_since(ts) %}date_diff('hour', cast({{ ts }} as timestamp), cast(current_timestamp as timestamp)){% endmacro %}
{% macro bigquery__hours_since(ts) %}timestamp_diff(current_timestamp(), cast({{ ts }} as timestamp), hour){% endmacro %}
