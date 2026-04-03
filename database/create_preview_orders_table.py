""" Script to create the preview_orders table and insert predefined order types """

import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=3306,
    database="postgres",
    user="postgres",
    password="postgres"
)

cursor = conn.cursor()

create_table = """
CREATE TABLE IF NOT EXISTS preview_orders (
  id SERIAL PRIMARY KEY,
  preview_id UUID UNIQUE,
  product_id VARCHAR(50) NOT NULL,
  side VARCHAR(10) NOT NULL,
  order_configuration_type VARCHAR(100),
  leverage VARCHAR(20),
  margin_type VARCHAR(20),
  order_total NUMERIC(30, 18),
  commission_total NUMERIC(30, 18),
  quote_size NUMERIC(30, 18),
  base_size NUMERIC(30, 18),
  best_bid NUMERIC(30, 18),
  best_ask NUMERIC(30, 18),
  is_max BOOLEAN DEFAULT false,
  order_margin_total NUMERIC(30, 18),
  long_leverage VARCHAR(20),
  short_leverage VARCHAR(20),
  slippage NUMERIC(30, 18),
  current_liquidation_buffer NUMERIC(30, 18),
  projected_liquidation_buffer NUMERIC(30, 18),
  max_leverage VARCHAR(20),
  current_margin_ratio NUMERIC(30, 18),
  projected_margin_ratio NUMERIC(30, 18),
  position_notional_limit NUMERIC(30, 18),
  max_notional_at_requested_leverage NUMERIC(30, 18),
  est_average_filled_price NUMERIC(30, 18),
  
  total_gst_commission NUMERIC(30, 18),
  total_withholding_commission NUMERIC(30, 18),
  total_client_commission NUMERIC(30, 18),
  total_venue_commission NUMERIC(30, 18),
  total_regulatory_commission NUMERIC(30, 18),
  total_clearing_commission NUMERIC(30, 18),
  
  twap_bucket_duration VARCHAR(50),
  twap_bucket_size NUMERIC(30, 18),
  twap_number_buckets INT,
  twap_start_time TIMESTAMP WITH TIME ZONE,
  twap_end_time TIMESTAMP WITH TIME ZONE,
  
  scaled_num_orders INT,
  scaled_min_price NUMERIC(30, 18),
  scaled_max_price NUMERIC(30, 18),
  
  failure_reasons TEXT,
  warning_messages TEXT,
  
  status VARCHAR(50) DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  submitted_order_id VARCHAR(255),
  submitted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_preview_orders_preview_id ON preview_orders(preview_id);
CREATE INDEX idx_preview_orders_product_id ON preview_orders(product_id);
CREATE INDEX idx_preview_orders_status ON preview_orders(status);
CREATE INDEX idx_preview_orders_created_at ON preview_orders(created_at);
"""

cursor.execute(create_table)
conn.commit()
print("Table 'preview_orders' created successfully!")

cursor.close()
conn.close()
