select * from {{ ref('fct_order_items') }} where revenue < 0
