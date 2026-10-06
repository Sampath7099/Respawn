-- fct_orders must account for every line item exactly once.
select items, summed from (
    select (select count(*) from {{ ref('fct_order_items') }}) as items,
           (select coalesce(sum(items), 0) from {{ ref('fct_orders') }}) as summed
) t
where items <> summed
