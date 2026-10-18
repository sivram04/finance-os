{# Use the configured schema as-is (staging, marts, ...) instead of prefixing the target schema.
   var('dataset_prefix') keeps several copies apart in one BigQuery project: '' for L, 's_' for the S company
   (the one the live simulator runs), e.g. --vars "dataset_prefix: s_". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ var('dataset_prefix', '') ~ (custom_schema_name if custom_schema_name else target.schema) }}
{%- endmacro %}
