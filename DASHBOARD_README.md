# Trading Engine Dashboard

A lightweight, real-time visual interface for the Coinbase trading engine. Zero build steps, vanilla JavaScript frontend.

## Quick Start

### 1. Start the dashboard server
```bash
python dashboard_server.py
```
This starts a WebSocket server on `ws://localhost:8765` and logs all activity.

### 2. Open the dashboard
Simply open `dashboard.html` in your web browser:
```bash
# Windows
start dashboard.html

# macOS
open dashboard.html

# Linux
xdg-open dashboard.html
```

Or navigate to the file directly in your browser's address bar.

### 3. Monitor your trading engine
The dashboard will now show:
- **Engine Status**: Running state, active threads, event queue depth
- **Active Orders**: Real-time order updates with status badges
- **Current Positions**: P&L tracking, entry prices, current values
- **Engine Logs**: Real-time log stream for debugging

## Integration with Main Engine

To integrate with your trading engine, update `main.py` to start the dashboard server:

```python
from configuration import (
    Subscription,
    ORDERBOOK,
    API_KEY,
    API_SECRET,
    ORDER_POST_ONLY,
)

import database.order as DB_CLIENT
from core.order_engine import OrderEngine
from bridges.engine_orchestrator import OrderEngineOrchestrator
from dashboard_server import start_dashboard_server, update_order, update_position, add_log_entry, update_engine_status


if __name__ == "__main__":
    # Start dashboard server
    start_dashboard_server()
    
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_client=DB_CLIENT,
        subscription=Subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY
    )
    orchestrator = OrderEngineOrchestrator(engine)
    orchestrator.run_forever()
```

## Pushing Data to Dashboard

From your trading engine code, push updates to the dashboard:

```python
from dashboard_server import update_order, update_position, add_log_entry, update_engine_status

# When orders change
update_order(order_id="abc123", order_data={
    "product_id": "BTC-USD",
    "side": "BUY",
    "size": "0.5",
    "price": "50000.00",
    "filled_size": "0.25",
    "status": "FILLED"
})

# When positions change
update_position(product_id="BTC-USD", position_data={
    "type": "SPOT",
    "amount": "0.5",
    "entry_price": "49500.00",
    "current_value": "25000.00",
    "entry_cost": "24750.00"
})

# Log events
add_log_entry("INFO", "Order placed successfully", {"order_id": "abc123"})
add_log_entry("WARN", "Event queue depth critical", {"depth": 500})

# Update engine status periodically
update_engine_status({
    "running": True,
    "threads_active": 5,
    "event_queue_depth": 12
})
```

## Architecture

- **`dashboard_server.py`**: Lightweight WebSocket server (200 lines)
  - Manages connected clients
  - Maintains shared state (orders, positions, logs, engine status)
  - Thread-safe using locks
  - Handles client commands (place order, cancel order)

- **`dashboard.html`**: Single self-contained file (400 lines)
  - Zero build dependencies
  - Responsive dark theme UI
  - Real-time WebSocket updates
  - Auto-reconnect with exponential backoff
  - Tables for orders and positions
  - Live log stream
  - Order placement form

## Features

- ✅ **Real-time Updates**: WebSocket push (no polling)
- ✅ **No Build Step**: Pure HTML/CSS/JS, just open in browser
- ✅ **Thread-Safe**: Uses locks for state synchronization
- ✅ **Auto-Reconnect**: Handles disconnections gracefully
- ✅ **Responsive**: Works on desktop and mobile
- ✅ **Log Streaming**: Tail last 100 log entries
- ✅ **Order Management**: View and create orders from UI
- ✅ **Position Tracking**: Real-time P&L calculation

## Troubleshooting

### Dashboard shows "Disconnected"
- Ensure `python dashboard_server.py` is running
- Check that port 8765 is not in use: `netstat -an | find "8765"`
- Browser must be on same machine (or modify `localhost` in both files)

### Orders not updating
- Verify you're calling `update_order()` from your engine when orders change
- Check console in browser dev tools (F12) for JavaScript errors

### No logs appearing
- Ensure you're calling `add_log_entry()` from your engine
- Check Python console for dashboard server logs

## Next Steps

1. Integrate data feeds from your trading engine
2. Add WebSocket handlers for order placement via UI
3. Add charts (lightweight: Chart.js or Lightweight Charts.js)
4. Add alerts for critical conditions
5. Deploy to web server for remote monitoring
