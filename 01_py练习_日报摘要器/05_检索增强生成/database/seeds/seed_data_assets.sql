INSERT INTO data_assets (asset_type, name, description, business_domain, parent_name, synonyms, formula, related_table, related_columns, example_values) VALUES
('metric', '销售额', '计算销售总额的指标', 'sales', NULL, ARRAY['营业收入', '销售收入', 'revenue'], 'SUM(订单金额)', 'sales_orders', ARRAY['order_amount'], '{"order_amount": [10000, 15000, 20000]}'::JSONB),
('table', '销售订单表', '存储销售订单的主表', 'sales', NULL, ARRAY['订单表', '订单'], NULL, NULL, ARRAY['order_id', 'customer_id', 'order_amount', 'order_date'], NULL),
('column', '订单金额', '订单的金额字段', 'sales', '销售订单表', ARRAY['金额', 'order_amount'], NULL, 'sales_orders', ARRAY['order_amount'], '{"min": 100, "max": 1000000}'::JSONB),
('case', '液压滤器堵塞', '液压系统压力不足的常见原因', 'equipment', '液压系统维护手册', ARRAY['滤油', '阻塞'], NULL, NULL, NULL, NULL),
('case', '油液液位低', '液压泵压力不足的另一个原因', 'equipment', '液压系统维护手册', ARRAY['加油', '液位'], NULL, NULL, NULL, NULL);