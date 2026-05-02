> Documentation status (2026-05-02): **Supplemental (non-canonical active reference)**
> This file is useful operational context but is not the canonical source of truth.
> Canonical living docs remain under genai_data/.
# Coinbase WebSocket API Reference

**Purpose**: Internal reference documentation for the `coinbase.websocket` module used in the trading engine.

**Location in Project**: Imported and used in `core/order_engine.py`

---

## Overview

`coinbase.websocket` is a Python module provided by the Coinbase Advanced SDK that enables real-time bidirectional communication with Coinbase's trading servers. It's a critical dependency for the OrderEngine as it provides:

- Real-time order updates (OPEN, FILLED, CANCELLED, UPDATE)
- Real-time ticker/price data
- Position snapshots and updates for futures
- Event streaming with automatic reconnection

---

## Key Classes

### `WSClient`

Main class for managing WebSocket connections to Coinbase.

**Constructor:**
```python
WSClient(
    api_key: str,                          # Coinbase API key
    api_secret: str,                       # Coinbase API secret
    verbose: bool = False,                 # Enable verbose logging
    on_open: callable = None,              # Callback when connection opens
    on_message: callable = None,           # Callback when message received
)
```

**Key Methods:**

#### `open()`
```python
ws_client.open()
```
Opens the WebSocket connection to Coinbase. This is a **blocking call** until connection is established.

**Important**: This method connects but does NOT automatically subscribe to channels. You must call `subscribe()` separately.

---

#### `subscribe()`
```python
ws_client.subscribe(
    product_ids: List[str],                # Products to subscribe to (e.g., ['BTC-USDC', 'ETH-USDC'])
    channels: List[str],                   # Channels to subscribe to (e.g., ['user', 'ticker', 'heartbeats'])
)
```

Subscribes to specific product IDs and channels. After calling this, the WebSocket will begin streaming events.

**Supported Channels:**
- `user` - Personal order updates and position snapshots
- `ticker` - Real-time price ticks
- `heartbeats` - Periodic keep-alive messages
- `matches` - Trade execution details
- `full` - Full order book (not recommended for production)

**Example in OrderEngine:**
```python
ws_client.subscribe(
    product_ids=self.subscription.product_ids,
    channels=self.subscription.channels,
)
```

---

#### `sleep_with_exception_check(timeout: float)`
```python
should_break = ws_client.sleep_with_exception_check(1)
```

**Critical Method** - Sleeps for the specified timeout while monitoring for connection errors.

**Returns:**
- `False` (0) - Connection is healthy, continue looping
- `True` (1) - Connection error detected, should break the loop

**Important Behavior**: This method is designed to be called in a loop. It handles internal WebSocket heartbeat/keep-alive and raises `WSClientConnectionClosedException` if the connection dies.

**Usage in OrderEngine:**
```python
try:
    while True:
        if ws_client.sleep_with_exception_check(1):
            break  # Connection closed, exit retry
except WSClientConnectionClosedException as e:
    # Handle reconnection
    pass
```

---

### `WSClientConnectionClosedException`

Exception raised when the WebSocket connection is lost unexpectedly.

**When it occurs:**
- Network disconnection
- Coinbase server closes connection
- Authentication failure
- Rate limiting

**Usage in OrderEngine:**
```python
try:
    while True:
        if ws_client.sleep_with_exception_check(1):
            break
except WSClientConnectionClosedException as e:
    self.log_message(
        "connection",
        self.build_event_log_payload(
            "websocket_connection_closed",
            error=str(e),
        ),
    )
    # Reconnect by creating new WSClient and calling open() again
```

---

## Message Format

Messages received via `on_message()` callback are JSON strings that must be parsed.

**Message Structure:**
```json
{
    "channel": "user",
    "client_id": "uuid-string",
    "timestamp": "2026-04-18T12:34:56Z",
    "sequence_num": 123456,
    "events": [
        {
            "type": "SNAPSHOT",
            "orders": [...],
            "positions": [...]
        },
        {
            "type": "OPEN",
            "orders": [
                {
                    "id": "order-id",
                    "client_order_id": "client-uuid",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "status": "OPEN",
                    "limit_price": "50000.00",
                    "order_quantity": "0.5",
                    "filled_size": "0.0"
                }
            ]
        }
    ]
}
```

**Channel Types:**
- `user` - Contains `events` array with order/position updates
- `ticker` - Contains `tickers` array with price data
- `heartbeats` - Empty events array (keep-alive)
- `subscriptions` - Acknowledgment of subscription (can be ignored)

---

## Callback Functions

### `on_open()`
```python
def on_open():
    # Called when connection is first established
    # Use for initialization, logging, etc.
    pass
```

**Signature**: Takes NO arguments

**Called When**: WebSocket connection successfully opens (after `open()` succeeds)

---

### `on_message(msg: str)`
```python
def on_message(msg: str):
    # msg is a JSON string that must be parsed
    event = json.loads(msg)
    # Process event
    pass
```

**Signature**: Takes EXACTLY ONE argument (`msg` - the JSON string)

**Critical Gotcha**: The signature MUST be `on_message(msg)` with only one parameter. Despite being a method, it cannot accept `self` or other parameters.

**Called When**: Any message arrives on the WebSocket (orders, tickers, heartbeats, etc.)

**Important**: This function is called by the WebSocket client in its internal event loop. Keep it fast - heavy processing should be delegated to thread pools.

---

## Typical Usage Pattern

```python
from coinbase.websocket import WSClient, WSClientConnectionClosedException
import json

def on_open():
    print("Connected!")

def on_message(msg: str):
    data = json.loads(msg)
    channel = data.get("channel")
    events = data.get("events", [])
    
    if channel == "user":
        for event in events:
            print(f"Order update: {event['type']}")

# Create client
ws_client = WSClient(
    api_key="your_key",
    api_secret="your_secret",
    on_open=on_open,
    on_message=on_message,
)

# Connect and subscribe
ws_client.open()
ws_client.subscribe(
    product_ids=["BTC-USDC", "ETH-USDC"],
    channels=["user", "ticker"],
)

# Keep connection alive
try:
    while True:
        if ws_client.sleep_with_exception_check(1):
            break  # Connection closed
except WSClientConnectionClosedException as e:
    print(f"Connection lost: {e}")
    # Reconnect logic here
```

---

## Integration in OrderEngine

**File**: `core/order_engine.py`

**Key Integration Points:**

### 1. **Initialization**
```python
# In connect_to_websocket() method
ws_client = WSClient(
    verbose=True,
    api_key=self.api_key,
    api_secret=self.api_secret,
    on_open=self.on_open,
    on_message=self.on_message,
)
```

### 2. **Connection Loop**
```python
# In connect_to_websocket() method
ws_client.open()
ws_client.subscribe(
    product_ids=self.subscription.product_ids,
    channels=self.subscription.channels,
)

try:
    while True:
        if ws_client.sleep_with_exception_check(1):
            break
except WSClientConnectionClosedException as e:
    self.log_message("connection", ...)
    # Note: This thread will exit and be restarted by start_background_threads()
```

### 3. **Event Processing**
- `on_message()` parses JSON and enqueues events
- Events are deduplicated using `EventBridge`
- Events are enqueued to `self.event_queue[channel]`
- Separate worker threads process queued events

### 4. **Error Handling**
- Connection failures are caught and logged
- Daemon threads are restarted by the OS (or manually if needed)
- No recovery logic in individual threads - let them fail and restart

---

## Important Gotchas & Pitfalls

### ⚠️ 1. **Callback Signature Must Be Exact**

**WRONG:**
```python
def on_message(self, msg):  # Don't do this!
    pass
```

**CORRECT:**
```python
def on_message(msg):  # Exactly one parameter
    pass
```

The WebSocket client's internal code calls the callback directly, not as a method. If you add `self`, it will fail with "unexpected positional argument" errors.

---

### ⚠️ 2. **on_open() Takes No Arguments**

**WRONG:**
```python
def on_open(self):
    pass
```

**CORRECT:**
```python
def on_open():
    pass
```

---

### ⚠️ 3. **Messages Must Be Parsed**

The callback receives a JSON STRING, not a parsed dict.

```python
def on_message(msg: str):
    # msg is a STRING
    event = json.loads(msg)  # Must parse it
```

---

### ⚠️ 4. **Keep Callbacks Fast**

Heavy processing in `on_message()` will block the WebSocket event loop and cause message loss.

**WRONG:**
```python
def on_message(msg: str):
    event = json.loads(msg)
    # Don't do expensive work here
    expensive_computation(event)  # Blocks the loop!
```

**CORRECT:**
```python
def on_message(msg: str):
    event = json.loads(msg)
    # Enqueue for async processing
    self.event_queue[channel].put(event)  # Fast, non-blocking
```

This is why OrderEngine uses a ThreadPoolExecutor for user event processing.

---

### ⚠️ 5. **sleep_with_exception_check() is Essential**

This method must be called regularly to:
1. Keep the connection alive (heartbeat)
2. Detect connection failures
3. Trigger exception raising when connection dies

**WRONG:**
```python
while True:
    time.sleep(1)  # Don't do this, no heartbeat!
```

**CORRECT:**
```python
while True:
    if ws_client.sleep_with_exception_check(1):
        break  # Connection died, exit
```

---

### ⚠️ 6. **Connection Failures Don't Auto-Reconnect**

The WebSocket client does NOT automatically reconnect. If the connection dies:

1. `sleep_with_exception_check()` returns `True` (or raises exception)
2. The loop exits
3. The thread terminates
4. **Your code must handle reconnection** (or rely on daemon thread restart)

In OrderEngine, reconnection is handled by letting the thread die and having the OS/scheduler restart it.

---

## Channel Reference

### `user` Channel

Receives personal order and position updates.

**Event Types:**
- `SNAPSHOT` - Initial state of all orders and positions
- `OPEN` - Order just became open for trading
- `FILLED` - Order was filled (wholly or partially)
- `CANCELLED` - Order was cancelled
- `UPDATE` - Order status changed
- `PENDING` - Order submitted but not yet open

**Message Example:**
```json
{
    "channel": "user",
    "events": [
        {
            "type": "FILLED",
            "orders": [
                {
                    "client_order_id": "uuid",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "status": "FILLED",
                    "limit_price": "50000.00",
                    "filled_size": "0.5",
                    "order_quantity": "0.5"
                }
            ]
        }
    ]
}
```

---

### `ticker` Channel

Receives real-time price ticks (best bid/ask).

**Message Example:**
```json
{
    "channel": "ticker",
    "events": [],
    "tickers": [
        {
            "type": "ticker",
            "product_id": "BTC-USDC",
            "price": "50123.45",
            "time": "2026-04-18T12:34:56Z",
            "best_bid": "50123.00",
            "best_ask": "50124.00"
        }
    ]
}
```

---

### `heartbeats` Channel

Keep-alive messages to detect dead connections.

**Message Example:**
```json
{
    "channel": "heartbeats",
    "timestamp": "2026-04-18T12:34:56Z",
    "sequence_num": 123456,
    "events": []
}
```

---

## Environment Setup

**Required:**
- `coinbase` Python package (installed with `pip install coinbase`)
- Valid Coinbase API credentials with WebSocket access
- API credentials must have appropriate scopes (viewing orders, executing orders, etc.)

**Installation:**
```bash
pip install coinbase
```

---

## Debugging

### Enable Verbose Logging
```python
ws_client = WSClient(
    api_key=key,
    api_secret=secret,
    verbose=True,  # Print all messages to console
    on_message=on_message,
)
```

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Authentication failed` | Invalid API key/secret | Verify credentials |
| `Connection refused` | Coinbase server down | Check Coinbase status page |
| `WebSocket closed` | Network issue | Check network, retry |
| `Rate limit exceeded` | Too many requests | Add delays between API calls |

---

## References

- **Coinbase SDK Docs**: https://docs.cloud.coinbase.com/advanced-trade-api
- **WebSocket Events**: https://docs.cloud.coinbase.com/advanced-trade-api/docs/ws-channels
- **Error Handling**: https://docs.cloud.coinbase.com/advanced-trade-api/docs/error-handling

---

## Checklist for Future Development

When integrating or modifying WebSocket functionality, verify:

- [ ] `on_message()` callback signature is `on_message(msg: str)` (no self)
- [ ] `on_open()` callback takes no arguments
- [ ] Messages are JSON-parsed before use
- [ ] Callbacks are kept fast (no blocking operations)
- [ ] `sleep_with_exception_check()` is called in connection loop
- [ ] `WSClientConnectionClosedException` is caught and handled
- [ ] Reconnection logic is present (thread restart or explicit)
- [ ] Event deduplication is implemented (to prevent duplicate processing)
- [ ] Heavy processing is delegated to ThreadPoolExecutor, not done in callbacks
- [ ] Subscription channels match the expected event types


