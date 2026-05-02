> Documentation status (2026-05-02): **Supplemental (non-canonical active reference)**
> This file is useful operational context but is not the canonical source of truth.
> Canonical living docs remain under genai_data/.
# Coinbase Advanced Trade WebSocket Channels Reference

This directory contains structured documentation of all Coinbase Advanced Trade API WebSocket channels, subscription formats, and message schemas. Use this as the authoritative reference when working with real-time market and account data.

## Directory Structure

```
websocket_reference/
├── public/                              # Unauthenticated channels (public market data)
│   ├── heartbeats_subscription.json
│   ├── heartbeats_message.json
│   ├── candles_subscription.json
│   ├── candles_message.json
│   ├── status_subscription.json
│   ├── status_message.json
│   ├── ticker_subscription.json
│   ├── ticker_message.json
│   ├── ticker_batch_subscription.json
│   ├── ticker_batch_message.json
│   ├── level2_subscription.json
│   ├── level2_message.json
│   ├── market_trades_subscription.json
│   └── market_trades_message.json
├── authenticated/                       # Authenticated channels (user-specific data)
│   ├── user_subscription.json
│   ├── user_message.json
│   ├── futures_balance_summary_subscription.json
│   └── futures_balance_summary_message.json
└── README.md                            # This file
```

## Channel Overview

### Public Channels (No Authentication Required)

| Channel | Purpose | Frequency | Includes |
|---------|---------|-----------|----------|
| **heartbeats** | Keep connections alive | 1 per second | Counter to detect missed messages |
| **candles** | OHLC data | Every second | Open, High, Low, Close, Volume (5-min granules) |
| **status** | Product metadata | Preset interval | Product info, trading status, min/max sizes |
| **ticker** | Real-time prices | Every trade match | Price, volume, bid/ask with depth |
| **ticker_batch** | Batched prices | Every 5 seconds | Same as ticker but lower frequency |
| **level2** | Order book | Every book change | All bid/ask levels (guaranteed delivery) |
| **market_trades** | Executed trades | Every 250ms | All trades on exchange with side & price |

### Authenticated Channels (Requires JWT Token)

| Channel | Purpose | Frequency | Includes |
|---------|---------|-----------|----------|
| **user** | Order & position updates | On change | All open orders, fills, perpetual positions |
| **futures_balance_summary** | Margin & buying power | On change | Margin levels, liquidation buffer, PnL |

## Naming Convention

Each channel has TWO files:

- **`{channel_name}_subscription.json`** - How to subscribe and unsubscribe
- **`{channel_name}_message.json`** - Message structure and field descriptions

### Example: Ticker Channel

```
ticker_subscription.json     → How to send subscribe request
ticker_message.json         → How to parse received messages
```

## Quick Start: Subscription Flow

### 1. Connect to WebSocket

```
wss://advanced-trade-ws.coinbase.com
```

### 2. Send Subscription Request

```json
{
  "type": "subscribe",
  "channel": "ticker",
  "product_ids": ["BTC-USD", "ETH-USD"],
  "jwt": "YOUR_JWT_TOKEN"  // optional for public channels, required for user/futures_balance_summary
}
```

### 3. Handle Heartbeats

```json
{
  "channel": "heartbeats",
  "events": [{
    "heartbeat_counter": "1234"
  }]
}
```

### 4. Parse Channel Messages

See `{channel_name}_message.json` for structure and field descriptions.

## Authentication (JWT Token)

For authenticated channels (`user` and `futures_balance_summary`):

1. Generate JWT token from your CDP API credentials
2. Include `jwt` field in subscription request
3. Optionally include `jwt` in public channel subscriptions for enhanced limits

Example subscription with auth:
```json
{
  "type": "subscribe",
  "channel": "user",
  "product_ids": ["BTC-USD"],
  "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

## Integration Guide for Trading Bot

### 1. Real-Time Order Tracking

Use the **user channel** to receive order updates:

```
Subscription: user_subscription.json
Message Format: user_message.json
  ├── orders array: Track all open orders
  ├── status field: PENDING → OPEN → FILLED
  └── completion_percentage: Fill progress

Use for:
  - Detecting when orders fill
  - Triggering follow-up orders
  - Tracking order cancellations
  - Monitoring fees paid
```

### 2. Order Book Maintenance

Use **level2 channel** for accurate order book:

```
Subscription: level2_subscription.json
Message Format: level2_message.json
  ├── First message: snapshot (full book)
  ├── Updates: Only changed price levels
  └── new_quantity: 0 means remove level

Use for:
  - Maintaining accurate local order book copy
  - Calculating midpoint for pricing
  - Detecting large bids/asks
  - Liquidity analysis
```

### 3. Real-Time Price Tracking

Choose based on needs:

- **ticker**: Every trade (high frequency, full data with best bid/ask)
- **ticker_batch**: Every 5 seconds (reduced bandwidth)
- **candles**: Every second (OHLC, good for indicators)

### 4. Monitoring Margin & Risk

Use **futures_balance_summary channel**:

```
Subscription: futures_balance_summary_subscription.json
Message Format: futures_balance_summary_message.json
  ├── futures_buying_power: Max you can trade
  ├── liquidation_buffer_percentage: Risk indicator
  └── margin_level: Health status

Use for:
  - Preventing overleveraging
  - Detecting liquidation risk
  - Adjusting position sizing
  - Risk alerts
```

### 5. Market Activity Monitoring

Use **market_trades channel**:

```
Subscription: market_trades_subscription.json
Message Format: market_trades_message.json
  ├── trade_id: Unique identifier
  ├── side: BUY or SELL
  └── size: Volume in base currency

Use for:
  - Detecting block trades (large orders)
  - Analyzing market microstructure
  - Building volume indicators
  - Sentiment analysis
```

## Connection Health Management

### Keep-Alive Strategy

1. **Always subscribe to heartbeats** alongside other channels
   ```json
   {
     "type": "subscribe",
     "channel": "heartbeats"
   }
   ```

2. **Monitor heartbeat_counter**
   - Counter increments by 1 each heartbeat
   - Gap indicates missed messages → reconnect

3. **Channels close after 60-90 seconds** of inactivity
   - Heartbeats keep them open
   - Implement reconnection logic

### Recommended Subscription Pattern

```python
# Always start with heartbeats
channels = [
    {"channel": "heartbeats"},           # Essential
    {"channel": "ticker", "product_ids": ["BTC-USD"]},
    {"channel": "user"},                  # Requires JWT
    {"channel": "futures_balance_summary"}  # Requires JWT
]

for subscription in channels:
    send_subscription(subscription)
```

## Message Processing

### Event Deduplication

Each message has:
- `channel`: Identifies channel type
- `sequence_num`: For detecting gaps
- `timestamp`: ISO8601 server time

Track `sequence_num` to detect missed messages.

### Snapshot vs Update Pattern

Most channels follow this pattern:

```
Type: snapshot    →  Initial/complete data
Type: update      →  Incremental changes

Processing:
  1. First message is snapshot
  2. Build full state from snapshot
  3. Apply updates to maintain state
```

Example with level2 order book:
```
Message 1 (snapshot): Full bid/ask book
Message 2 (update): Price level 21900 now has 5.0 quantity
Message 3 (update): Price level 21895 removed (quantity=0)
```

## Field Types Reference

- **string (decimal)**: Numeric values as strings for precision (e.g., "100.50")
- **string (ISO8601)**: Timestamps (e.g., "2023-06-23T20:31:26.122969572Z")
- **string (UUID)**: Identifiers (e.g., "550e8400-e29b-41d4-a716-446655440000")
- **string (enum)**: One of predefined values (see enum array in message files)
- **integer**: Whole numbers
- **boolean**: true/false (in JSON format)

## Common Integration Patterns

### Pattern 1: Order Fill Detection

```python
# From user channel
if previous_status == "OPEN" and new_status == "FILLED":
    # Order filled - calculate PnL
    realized_pnl = calculate_pnl(order)
    # Trigger follow-up order if needed
    place_follow_up_order(order)
```

### Pattern 2: Liquidation Risk Alert

```python
# From futures_balance_summary
if liquidation_buffer_percentage < 5:
    # CRITICAL: Liquidation risk
    log_alert("LIQUIDATION RISK: Buffer at " + liquidation_buffer_percentage + "%")
    reduce_positions()
```

### Pattern 3: Large Order Detection

```python
# From market_trades
for trade in trades:
    if float(trade["size"]) > LARGE_ORDER_THRESHOLD:
        log_block_trade(trade)  # Large order detected
```

### Pattern 4: Order Book Spread Monitoring

```python
# From level2
best_bid = order_book["bids"][0]["price"]
best_ask = order_book["asks"][0]["price"]
spread = float(best_ask) - float(best_bid)
midpoint = (float(best_bid) + float(best_ask)) / 2
```

## Best Practices

1. **Always subscribe to heartbeats** - critical for connection health
2. **Include JWT in public subscriptions** - get higher rate limits
3. **Handle snapshot + update flow** - don't assume snapshot contains everything
4. **Deduplicate using event hashes** - guard against duplicate processing
5. **Monitor sequence numbers** - detect gaps indicating connection issues
6. **Implement exponential backoff** - handle temporary connection failures
7. **Log all order status changes** - maintain audit trail
8. **Track margin metrics continuously** - prevent liquidations
9. **Use ISO8601 timestamps** - always convert to local time for analysis
10. **Rate limit message processing** - don't overload downstream systems

## Troubleshooting

### Connection Closes Unexpectedly
- **Cause**: No heartbeats subscribed or channel timeout (60-90s)
- **Solution**: Subscribe to heartbeats channel

### Missing Messages
- **Cause**: Heartbeat counter has gaps
- **Solution**: Reconnect and replay state from REST API

### Out-of-Sync Order Book
- **Cause**: Missed update messages during lag
- **Solution**: Reset with new snapshot, resync with REST API

### Liquidation Occurred Unexpectedly
- **Cause**: Not monitoring futures_balance_summary
- **Solution**: Subscribe to channel and implement margin alerts

## Related Files in Project

- **main.py**: OrderEngine class subscribes to user channel for order updates
- **configuration.py**: REST API calls for order placement
- **database/order.py**: Persists order updates from WebSocket to PostgreSQL
- **api_reference/**: REST API endpoint documentation (complements WebSocket)

## References

- **Official Docs**: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels
- **Authentication**: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/ws-auth
- **Best Practices**: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/websocket

## Next Steps

1. **Extend with additional channels** - Add webhook/notification channels when available
2. **Create error response schemas** - Document disconnection and error messages
3. **Build client library** - Generate type-safe WebSocket client from these schemas
4. **Add monitoring dashboard** - Visualize real-time channel health and latency
5. **Implement circuit breaker** - Graceful degradation when WebSocket unavailable

## File Generation Timestamps

Generated: 2024
Source: Coinbase Advanced Trade API v1


