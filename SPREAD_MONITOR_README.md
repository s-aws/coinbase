# Spread Monitor

A real-time arbitrage opportunity tracker for identifying and monitoring price spreads between related products.

## Overview

The Spread Monitor tracks bid/ask prices across all trading products and calculates:
- **1-second averaged bid/ask prices** for stable price snapshots
- **Spread width** (ask - bid) and spread percentage
- **Price ratios** between two products (useful for detecting arbitrage)
- **Historical ratio trends** over 5 minutes to spot narrowing/widening spreads

## Features

### Main Table View
Shows all products with:
- **Product ID** (click to select for comparison)
- **Bid (1s avg)** - Average best bid over the last second
- **Ask (1s avg)** - Average best ask over the last second
- **Spread** - Absolute difference (ask - bid)
- **Spread %** - Spread as percentage of ask price
- **Mid Price** - Average of bid/ask

### Spread Comparison
Compare two products side-by-side to identify arbitrage opportunities:
- **Bid Ratio (A/B)** - How much higher/lower product A's bid is
- **Ask Ratio (A/B)** - How much higher/lower product A's ask is
- **Bid Diff (A - B)** - Absolute dollar difference in bid prices
- **Ask Diff (A - B)** - Absolute dollar difference in ask prices
- **Bid Ratio History Chart** - 5-minute trend of the bid ratio

### Alert System
Set thresholds to be notified when conditions are met:

1. **Bid Ratio Alert** - Trigger when bid ratio deviates from 1.0
   - Example: Set to `1.005` to alert if product A's bid is more than 0.5% higher than B's bid
   
2. **Ask Ratio Alert** - Trigger when ask ratio deviates from 1.0
   - Example: Set to `0.995` to alert if product A's ask is more than 0.5% lower than B's ask
   
3. **Bid Spread Alert** - Trigger when absolute bid difference exceeds threshold
   - Example: Set to `200` to alert when the bid difference exceeds $200

**Status**: When any alert is triggered, the "⚠️ Alert Triggered!" message appears in red.

## Usage

### Opening the Page
Simply open `spread.html` in your browser:
```bash
# Windows
start spread.html

# macOS
open spread.html

# Linux
xdg-open spread.html
```

Or navigate directly: `file:///e:/coinbase/spread.html`

### Feeding Price Data
The spread monitor receives bid/ask data via WebSocket from your trading engine.

To send spread data, call `record_spread_tick()` from your order handling code:

```python
from dashboard_server import record_spread_tick

# When you receive a ticker update with bid/ask data
record_spread_tick('BIP-20DEC30-CDE', bid=40000.00, ask=40001.50)
record_spread_tick('BIT-24APR26-CDE', bid=40200.00, ask=40201.50)
```

### Example: BIP vs BIT Monitoring
Monitoring the spread between `BIP-20DEC30-CDE` and `BIT-24APR26-CDE`:

1. Open spread.html
2. Click on "BIP-20DEC30-CDE" in the products table → selects as Product A
3. Click on "BIT-24APR26-CDE" in the products table → selects as Product B
4. Observe:
   - **Bid Ratio**: Should be ~0.995 if BIP is ~$200 cheaper (0.995 = 200/40200)
   - **Bid Diff**: Shows the ~$200 difference
   - The ratio chart shows whether the spread is narrowing or widening
5. Set alerts:
   - Bid Ratio Alert: `1.005` - alerts if BIP gets closer to BIT
   - Bid Spread Alert: `150` - alerts if spread narrows below $150

## Data Flow

```
[Trading Engine]
       ↓
  (bid/ask data)
       ↓
record_spread_tick()
       ↓
  [Dashboard Server]
  (aggregates 1s windows)
       ↓
broadcast_spread()  (every 1 second)
       ↓
  [WebSocket Clients]
       ↓
  spread.html
  (displays & analyzes)
```

## Integration Points

### In your websocket handler (e.g., `websocket/on_message/ticker.py`):

```python
from dashboard_server import record_spread_tick

async def on_ticker_message(msg):
    """Handle incoming ticker messages from Coinbase."""
    product_id = msg['product_id']
    best_bid = msg.get('best_bid')
    best_ask = msg.get('best_ask')
    
    if best_bid and best_ask:
        # Record for spread monitoring
        record_spread_tick(product_id, float(best_bid), float(best_ask))
    
    # ... rest of your handling
```

### In your trade execution logic:

```python
# When monitoring for arbitrage opportunities
from dashboard_server import record_spread_tick

# Record current market prices
record_spread_tick('BIP-20DEC30-CDE', current_bip_bid, current_bip_ask)
record_spread_tick('BIT-24APR26-CDE', current_bit_bid, current_bit_ask)

# The spread monitor will calculate the spread and track trends
# If the spread narrows below your alert threshold, you can execute arbitrage
```

## Performance Considerations

- **Update Frequency**: The frontend aggregates bid/ask data over 1-second windows for stable snapshots
- **Memory**: Tracks last 300 ratio history points (5 minutes) per comparison
- **CPU**: Minimal - chart rendering uses canvas, calculations are simple aggregations
- **Network**: One broadcast per second regardless of tick frequency

## Troubleshooting

**No data showing?**
- Ensure the dashboard server is running: `python dashboard_server.py`
- Check that bid/ask data is being sent via `record_spread_tick()`
- Open browser console (F12) to check for WebSocket connection errors

**Alerts not triggering?**
- Ensure you've selected both Product A and Product B
- Make sure alert thresholds are set (inputs must not be empty)
- Alert logic: Bid Ratio/Ask Ratio compare deviation from 1.0

**Chart not rendering?**
- The chart appears only after you select both products
- History is built over time - wait a few seconds for data points
- The blue line shows the bid ratio history

## Files

- `spread.html` - Frontend UI for the spread monitor
- `dashboard_server.py` - Backend server with spread aggregation
- `spread_monitor_example.py` - Example of how to integrate with your code
