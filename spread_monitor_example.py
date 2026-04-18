"""
Example usage of the spread monitor feature.

The spread monitor tracks bid/ask prices to identify arbitrage opportunities
between related products (e.g., BIP-20DEC30-CDE vs BIT-24APR26-CDE).

Usage:
------

1. When you receive bid/ask data from the Coinbase websocket, call:
   
   from dashboard_server import record_spread_tick
   
   record_spread_tick('BIP-20DEC30-CDE', bid=40000.00, ask=40001.50)
   record_spread_tick('BIT-24APR26-CDE', bid=40200.00, ask=40201.50)

2. Open spread.html in your browser to view:
   - All products with 1-second averaged bid/ask prices
   - Spreads and spread percentages
   - Custom comparison between two products
   - Historical ratio tracking over 5 minutes
   - Alert thresholds for price differences/ratios

Example Integration:
--------------------

In your websocket message handler (websocket/on_message/user.py or similar):

    from dashboard_server import record_spread_tick
    
    def handle_ticker(ticker_msg):
        product_id = ticker_msg['product_id']
        best_bid = ticker_msg.get('best_bid')
        best_ask = ticker_msg.get('best_ask')
        
        if best_bid and best_ask:
            record_spread_tick(product_id, float(best_bid), float(best_ask))

Alert Configuration:
-------------------

Set alerts in the spread.html UI:
- Bid Ratio: Set to 1.005 to alert when productA.bid > productB.bid by 0.5%
- Ask Ratio: Set to 0.995 to alert when productA.ask < productB.ask by 0.5%  
- Bid Spread: Set to 200 to alert when bid difference exceeds $200

For your use case (BIP vs BIT):
- Watch for when BIT-BIP spread narrows
- Set Bid Spread Alert to something like 150-220 depending on your preference
- The 5-minute ratio chart shows if the difference is trending wider or narrower
"""

# Example: Manual testing without a websocket
if __name__ == "__main__":
    import time
    from dashboard_server import record_spread_tick, start_dashboard_server
    
    # Start the dashboard server
    start_dashboard_server()
    
    print("Dashboard server started on ws://localhost:8765")
    print("Open spread.html in your browser to view the spread monitor")
    print("Simulating price data...\n")
    
    # Simulate price updates
    try:
        for i in range(300):  # 5 minutes of data
            # BIP prices (slightly lower)
            bip_bid = 40000.00 + (i * 0.05)
            bip_ask = bip_bid + 1.50
            
            # BIT prices (slightly higher)
            bit_bid = 40200.00 + (i * 0.05)
            bit_ask = bit_bid + 1.50
            
            # Occasionally add some variation
            if i % 10 == 0:
                bip_bid += 5
                bip_ask += 5
            
            record_spread_tick('BIP-20DEC30-CDE', bip_bid, bip_ask)
            record_spread_tick('BIT-24APR26-CDE', bit_bid, bit_ask)
            
            # Add some other products
            record_spread_tick('BTC-USDC', 42500.00, 42501.50)
            record_spread_tick('ETH-USDC', 2250.00, 2250.75)
            
            time.sleep(0.1)  # Send multiple ticks per second
            
            if i % 30 == 0:
                print(f"Sent {i} ticks...")
    except KeyboardInterrupt:
        print("Stopped")
