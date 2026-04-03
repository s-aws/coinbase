""" Create order_configurations table and insert order configuration types """
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
CREATE TABLE IF NOT EXISTS order_configurations (
  id SERIAL PRIMARY KEY,
  config_type VARCHAR(100) UNIQUE NOT NULL,
  description TEXT,
  order_type_category VARCHAR(50),
  time_in_force VARCHAR(20),
  supports_post_only BOOLEAN,
  supports_limit_price BOOLEAN,
  supports_stop_price BOOLEAN,
  supports_quote_size BOOLEAN,
  supports_base_size BOOLEAN,
  supports_start_time BOOLEAN,
  supports_end_time BOOLEAN,
  supports_stop_direction BOOLEAN,
  supports_number_buckets BOOLEAN,
  supports_bucket_size BOOLEAN,
  supports_bucket_duration BOOLEAN,
  supports_price_distribution BOOLEAN,
  supports_size_distribution BOOLEAN,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

cursor.execute(create_table)

insert_configs = """
INSERT INTO order_configurations (config_type, description, order_type_category, time_in_force, 
                                  supports_post_only, supports_limit_price, supports_stop_price, 
                                  supports_quote_size, supports_base_size, supports_start_time,
                                  supports_end_time, supports_stop_direction, supports_number_buckets,
                                  supports_bucket_size, supports_bucket_duration, 
                                  supports_price_distribution, supports_size_distribution)
VALUES
  ('market_market_ioc', 'Buy or sell a specified quantity at current best market price. Order fills immediately or is canceled.', 'MARKET', 'IOC', false, false, false, true, true, false, false, false, false, false, false, false, false),
  ('market_market_fok', 'Buy or sell at current best market price. Order must completely fill immediately or is rejected.', 'MARKET', 'FOK', false, false, false, true, true, false, false, false, false, false, false, false, false),
  ('sor_limit_ioc', 'Buy or sell at a specified price with smart order routing. Must fill immediately or remaining qty is canceled.', 'LIMIT', 'IOC', false, true, false, true, true, false, false, false, false, false, false, false, false),
  ('limit_limit_gtc', 'Buy or sell at a specified price. Remains on order book until filled or canceled.', 'LIMIT', 'GTC', true, true, false, true, true, false, false, false, false, false, false, false, false),
  ('limit_limit_gtd', 'Buy or sell at a specified price. Remains on order book until end time or cancellation.', 'LIMIT', 'GTD', true, true, false, true, true, false, true, false, false, false, false, false, false),
  ('limit_limit_fok', 'Buy or sell at a specified price. Must completely fill immediately or is rejected.', 'LIMIT', 'FOK', false, true, false, true, true, false, false, false, false, false, false, false, false),
  ('twap_limit_gtd', 'Time-weighted average price order. Executes in buckets over a specified duration until end time.', 'TWAP', 'GTD', false, true, false, true, true, true, true, false, true, true, true, false, false),
  ('stop_limit_stop_limit_gtc', 'Posts a limit order when last trade price reaches stop price. Remains on book until canceled.', 'STOP_LIMIT', 'GTC', false, true, true, false, true, false, false, true, false, false, false, false, false),
  ('stop_limit_stop_limit_gtd', 'Posts a limit order when last trade price reaches stop price. Remains on book until end time.', 'STOP_LIMIT', 'GTD', false, true, true, false, true, false, true, true, false, false, false, false, false),
  ('trigger_bracket_gtc', 'Limit order with embedded stop loss and take profit. Remains on book until canceled.', 'BRACKET', 'GTC', false, true, true, false, true, false, false, false, false, false, false, false, false),
  ('trigger_bracket_gtd', 'Limit order with embedded stop loss and take profit. Remains on book until end time.', 'BRACKET', 'GTD', false, true, true, false, true, false, true, false, false, false, false, false, false),
  ('scaled_limit_gtc', 'Divides a large order into multiple smaller limit orders placed incrementally across a price range.', 'SCALED', 'GTC', false, true, false, true, true, false, false, false, true, true, false, true, true)
ON CONFLICT (config_type) DO NOTHING;
"""

cursor.execute(insert_configs)
conn.commit()

print("Table 'order_configurations' created successfully!")
print("Inserted 12 order configuration types")

cursor.close()
conn.close()
