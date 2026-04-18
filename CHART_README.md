# Lightweight Live Price Chart

A zero-dependency, high-performance price chart for real-time market data visualization.

## Quick Start

### 1. Start your trading engine
```bash
python main.py
```

This automatically starts the dashboard server on `ws://localhost:8765`.

### 2. Open the chart
Simply open `chart.html` in your browser:
```bash
# Windows
start chart.html

# macOS
open chart.html

# Linux
xdg-open chart.html
```

Or navigate directly: `file:///e:/coinbase/chart.html`

### 3. Feed price data

The chart receives ticker data via WebSocket. You need to call `broadcast_ticker()` from your trading engine when you receive price updates.

## Integration Example

### Option A: From Coinbase WebSocket Handler

In your event processing code, when you receive ticker messages from Coinbase:

```python
from dashboard_server import broadcast_ticker

def on_ticker_message(msg):
    """Called when Coinbase sends a ticker update."""
    product_id = msg.get('product_id')
    price = float(msg.get('price'))
    
    # Optional: track 24h price for % change calculation
    price_24h = get_price_24h(product_id)  # Your function
    
    # Broadcast to chart
    broadcast_ticker(product_id, price, price_24h)
```

### Option B: From Your Trading Engine

If you're updating positions or prices in your engine:

```python
from dashboard_server import broadcast_ticker
from core.order_engine import OrderEngine

class OrderEngine:
    def process_ticker_update(self, product_id: str, price: float):
        # ... your logic ...
        
        # Send to chart
        broadcast_ticker(product_id, price)
```

### Option C: Simple Test

To test the chart without live data, add this to `dashboard_server.py`:

```python
if __name__ == "__main__":
    import time
    import random
    
    start_dashboard_server()
    time.sleep(1)  # Wait for server to start
    
    # Simulate ticker data
    price = 42000
    while True:
        price += random.uniform(-100, 100)  # Random walk
        broadcast_ticker('BTC-USDC', price, 41000)
        time.sleep(0.5)
```

Then run: `python dashboard_server.py`

## Features

- **Zero Dependencies**: Uses only native browser Canvas API
- **Lightweight**: ~200 lines of vanilla JavaScript
- **High Performance**: Renders at 60 FPS with frame skipping
- **Responsive**: Automatically resizes to window
- **Multi-Product**: Switch between different trading pairs with buttons
- **Live Stats**: Shows current price and 24h % change
- **Interactive**: Hover over chart to inspect exact prices and timestamps

## Architecture

### Client-Side (chart.html)
- **Canvas Rendering**: Pure Canvas API (no canvas.js, Chart.js, or D3)
- **WebSocket Client**: Connects to `ws://localhost:8765`
- **Data Buffer**: Keeps last 500 price points in memory
- **Auto-Scaling**: Y-axis scales to data min/max with padding

### Server-Side (dashboard_server.py)
- **New Function**: `broadcast_ticker(product_id, price, price_24h=None)`
- **Async Broadcasting**: Uses thread-safe event loop scheduling
- **Existing Infrastructure**: Reuses your dashboard server

## Customization

### Max Data Points
Edit in `chart.html`:
```javascript
const config = {
    maxDataPoints: 500,  // Change this
    ...
};
```

### Colors
```javascript
const config = {
    colors: {
        line: '#3b82f6',      // Main chart line
        positive: '#22c55e',  // Green for gains
        negative: '#ef4444',  // Red for losses
        grid: '#334155',      // Grid lines
        ...
    },
};
```

### Update Rate (FPS)
```javascript
const config = {
    updateRate: 16,  // milliseconds (60 FPS). Increase to reduce CPU.
    ...
};
```

## Performance Tips

1. **Limit Update Frequency**: Don't call `broadcast_ticker()` more than 20 times/second
2. **Use maxDataPoints**: Keep it between 200-1000 for best balance
3. **Reduce Frame Rate**: Increase `updateRate` from 16ms to 50ms for slower updates
4. **Single Product**: If viewing one product, fewer calculations needed

## Troubleshooting

**Chart shows "Waiting for price data..."**
- Make sure `broadcast_ticker()` is being called in your engine
- Check browser console for WebSocket connection errors
- Verify dashboard server is running on port 8765

**Connection shows "Disconnected"**
- Check if `start_dashboard_server()` was called in `main.py`
- Verify no other application is using port 8765
- Check firewall settings (allow localhost)

**Chart is laggy or CPU high**
- Reduce `maxDataPoints` in config
- Increase `updateRate` (slower refresh)
- Close other browser tabs/extensions

## Technical Details

### Message Format

The chart expects WebSocket messages with this structure:

```json
{
    "type": "ticker",
    "data": {
        "product_id": "BTC-USDC",
        "price": 42500.50,
        "price_24h": 41200.00,
        "time": 1713470451.234
    },
    "timestamp": "2026-04-18T14:00:51.234567"
}
```

The `broadcast_ticker()` function automatically wraps your data in this format.

### Canvas Rendering Loop

- Requests animation frame every ~16ms (60 FPS)
- Skips render if called too frequently
- Only redraws if new data received
- GPU-accelerated scaling via CSS

## License

Same as parent project.
