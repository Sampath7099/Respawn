{% macro generate_schema_name(custom, node) -%}{{ custom if custom else target.schema }}{%- endmacro %}
