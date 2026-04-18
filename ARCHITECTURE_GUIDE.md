"""Comprehensive Architecture Guide - Coinbase Advanced Trading Engine Refactoring

This document describes the complete architecture of the refactored Coinbase
Advanced Trading Engine across all phases.

## Architecture Overview

The refactored system is organized into 4 layers:

```
┌─────────────────────────────────────────────────────────┐
│ Application Layer (main.py - OrderEngine)               │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ Integration Layer (Phase 4 - Bridges)                   │
│  ├─ CalculatorBridge   (OrderCalculator wrapper)        │
│  ├─ ProcessorBridge    (OrderProcessor wrapper)         │
│  ├─ EventBridge        (EventProcessor wrapper)         │
│  └─ OrderEngineIntegration (Main coordinator)           │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ Business Logic Layer (Phase 3 - Core Logic)             │
│  ├─ business/order_calculator.py     (Order calculations)
│  ├─ business/order_processor.py      (Order processing)  │
│  └─ business/event_processor.py      (Event handling)    │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ Data Access Layer (Phase 2 - Infrastructure)            │
│  ├─ external/coinbase_client.py      (REST API wrapper) │
│  ├─ external/coinbase_websocket.py   (WebSocket wrapper)│
│  ├─ data/state_manager.py            (State management) │
│  └─ data/repositories/                (Persistence)     │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ Core Layer (Phase 1 - Foundations)                      │
│  ├─ core/models.py         (Order, Position, Product)   │
│  ├─ core/enums.py          (OrderSide, OrderStatus)     │
│  ├─ core/constants.py      (Configuration constants)    │
│  ├─ calculation/formatter.py   (Format utilities)       │
│  └─ calculation/resolver.py    (Resolution utilities)   │
└─────────────────────────────────────────────────────────┘
                  │
┌─────────────────────────────────────────────────────────┐
│ External Systems                                         │
│  ├─ Coinbase Advanced API (REST)                        │
│  ├─ Coinbase WebSocket      (Real-time events)          │
│  └─ PostgreSQL Database     (Persistence)               │
└─────────────────────────────────────────────────────────┘
```

## Data Flow Diagrams

### Order Processing Flow

```
WebSocket Message
    ↓
on_message() [OrderEngine]
    ↓
Hash event (deduplication) → EventBridge.hash_event()
    ↓
Check duplicate → EventBridge.is_duplicate_event()
    ↓
Enqueue to channel
    ↓
Channel Worker Thread
    ↓
process_user_event()
    ↓
For each order: process_user_order()
    ↓
Update orderbook state
    ↓
Check order status
    ├─ FILLED → handle_filled_order()
    ├─ CANCELLED → handle_cancelled_order()
    └─ Other → skip
    ↓
Claim processing flag → OrderEngine.claim_follow_up_processing()
    ↓
Compute follow-up template → OrderEngine.compute_order_template()
    │
    ├─ Uses: CalculatorBridge.calculate_follow_up_price()
    └─ Uses: OrderProcessor.validate_order_fields()
    ↓
Create follow-up order → create_limit_order_span()
    ↓
Record follow-up → OrderEngine.record_follow_up_order()
    │
    ├─ ProcessorBridge.build_order_context()
    ├─ CalculatorBridge.calculate_position_change()
    └─ Database persistence
    ↓
Mark complete → OrderEngine.complete_follow_up_processing()
```

### Event Deduplication Flow

```
WebSocket Message
    ↓
on_message()
    ↓
Extract events
    ↓
For each event:
    ├─ EventBridge.hash_event() → Compute SHA256 hash
    │
    ├─ EventBridge.is_duplicate_event()
    │   ├─ Check current bucket
    │   ├─ Check rotating buckets
    │   └─ Return True if found
    │
    ├─ If NOT duplicate:
    │   ├─ EventBridge.mark_event_seen() → Add to current bucket
    │   └─ Enqueue event
    │
    └─ If duplicate:
        └─ Skip (prevent processing)

Periodically (every 60 seconds):
    ↓
EventBridge.rotate_dedup_buckets()
    ├─ Shift buckets: bucket[i] = bucket[i-1]
    ├─ Clear oldest bucket: bucket[0] = {}
    └─ Prevents memory growth while maintaining dedup window
```

### Follow-up Order Calculation Flow

```
Parent Order Filled (e.g., BUY at $100)
    ↓
CalculatorBridge.should_create_follow_up()
    └─ Check: status=FILLED AND filled_size > 0
    ↓
CalculatorBridge.calculate_follow_up_price()
    ├─ Input: parent_order={order_side:'BUY', avg_price:100.00}, side:'SELL', profit_pct:0.01
    ├─ Logic: SELL price = 100.00 × (1 + 0.01) = 101.00
    └─ Output: 101.00
    ↓
CalculatorBridge.calculate_follow_up_size()
    ├─ Extract from multiple fields: filled_size, cumulative_quantity, base_size
    └─ Output: 1.0
    ↓
CalculatorBridge.calculate_position_change()
    ├─ Apply fill to position
    ├─ Update net_size and entry_vwap
    └─ Output: position update
    ↓
Create follow-up order [SELL 1.0 at $101.00]
```

## Module Responsibilities

### Phase 1: Core Foundation

**Purpose**: Provide fundamental data types and utilities

**core/models.py**
- Order: Represents a single order
- Position: Futures position with P&L tracking
- Product: Trading product metadata
- Wallet: Account balance information
- FollowUpOrderTemplate: Follow-up order parameters

**core/enums.py**
- OrderSide: BUY/SELL
- OrderStatus: OPEN/FILLED/CANCELLED/PENDING
- ProductType: SPOT/FUTURE
- TargetMovementType: Profit target type

**core/constants.py**
- ORDER_SIDE_SWITCH: Reverse side mapping
- ORDER_DIRECTION: Side-to-direction mapping
- Product lists and metadata

**calculation/formatter.py**
- safe_float(): Type-safe float conversion
- format_based_on_reference(): Format numbers to precision
- quantize_to_increment(): Quantize to product increment

**calculation/resolver.py**
- normalize_product_type(): Determine SPOT vs FUTURE
- resolve_order_size(): Extract size from multiple fields
- resolve_profit_move_pct(): Get profit target percentage

### Phase 2: Dependency Injection

**Purpose**: Externalize dependencies and enable testing

**external/coinbase_client.py** (280 lines)
- RESTful API wrapper for Coinbase Advanced API
- Methods: get_account_wallets, get_product, place_limit_order, cancel_order, etc.
- Thread-safe with response typing
- Replaces direct API usage in original code

**external/coinbase_websocket.py** (220 lines)
- WebSocket connection wrapper
- Methods: connect, disconnect, subscribe, on_message
- Manages connection state and threading
- Encapsulates WSClient complexity

**data/state_manager.py** (410 lines)
- Thread-safe state management
- Replaces global OrderBook singleton
- Methods: add_active_order, mark_order_filled, get_order_stats, etc.
- Optional repository integration for persistence

**data/repositories/** (200+ lines)
- OrderRepository protocol and PostgreSQL implementation
- save_order(), get_order(), update_order()
- Abstracts database persistence

### Phase 3: Business Logic

**Purpose**: Encapsulate domain-specific business logic

**business/order_calculator.py** (220 lines)
- Pure functional calculations
- Methods:
  - calculate_follow_up_price(): Compute follow-up order price
  - calculate_follow_up_size(): Extract filled quantity
  - calculate_position_change(): Update position from fill
  - calculate_fees(): Commission and mandatory fees
  - should_create_follow_up(): Eligibility check

**business/order_processor.py** (210 lines)
- Order validation and enrichment
- Methods:
  - build_order_context(): Concise logging context
  - is_filled_order(), is_cancelled_order(), is_open_order(): State detection
  - validate_order_fields(): Required field validation
  - enrich_order_with_calculated_fields(): Merge data
  - order_matches_product(): Product matching

**business/event_processor.py** (220 lines)
- Event deduplication and routing
- Methods:
  - hash_event(): SHA256 hashing
  - is_duplicate_event(): Duplicate detection
  - rotate_dedup_buckets(): Rolling window management
  - filter_events_by_channel(): Channel filtering
  - extract_orders_from_event(): Order extraction
  - should_process_event(): Processing validation

### Phase 4: Integration

**Purpose**: Bridge OrderEngine with Phase 3 business logic

**integration/calculator_bridge.py** (180 lines)
- Wraps OrderCalculator
- Provides interface OrderEngine expects
- Methods delegate to OrderCalculator

**integration/processor_bridge.py** (170 lines)
- Wraps OrderProcessor
- Provides interface OrderEngine expects
- Methods delegate to OrderProcessor

**integration/event_bridge.py** (200 lines)
- Wraps EventProcessor
- Provides interface OrderEngine expects
- Methods delegate to EventProcessor

**integration/engine_integration.py** (350 lines)
- Main integration wrapper
- Coordinates all bridges
- Delegates all OrderEngine methods
- Provides backward compatibility

## Control Flow: Order Placement to Follow-up

```
1. User places order via OrderEngine
   └─ OrderEngine.place_limit_order()

2. Order confirmation received via WebSocket
   └─ WebSocket callback: on_message(msg)

3. Message processing
   └─ OrderEngine.on_message()
      ├─ Parse JSON
      ├─ Extract channel and events
      └─ For each event:
         ├─ Hash for deduplication
         ├─ Check if duplicate (EventBridge)
         └─ Enqueue if new

4. Event worker thread
   └─ Channel worker processes event
      ├─ OrderEngine.process_user_event()
      └─ For FILLED order:
         └─ OrderEngine.process_user_order()
            ├─ Update orderbook
            └─ Call handle_filled_order()

5. Follow-up creation
   └─ OrderEngine.handle_filled_order()
      ├─ Claim processing flag
      ├─ Compute order template
      │  └─ Uses: CalculatorBridge.calculate_follow_up_price()
      ├─ Create new order
      └─ Record follow-up
         └─ Database persistence

6. Follow-up order placed
   └─ Same as step 1, creating a chain
```

## Concurrency Model

The refactored system uses a thread-per-channel model:

```
Main Thread (run_forever)
    │
    ├─ WebSocket Thread 1 ─→ WSClient.open() → WebSocket connection
    │
    ├─ WebSocket Thread 2 ─→ WSClient.open() → WebSocket connection (backup)
    │
    ├─ WebSocket Thread 3 ─→ WSClient.open() → WebSocket connection (backup)
    │
    ├─ User Event Worker Thread ─→ Process user events from queue
    │  └─ Uses ThreadPoolExecutor for async processing_user_event()
    │
    ├─ Ticker Event Worker Thread ─→ Process ticker events from queue
    │
    ├─ Heartbeat Event Worker Thread ─→ Process heartbeat events from queue
    │
    ├─ Reconciliation Thread ─→ Periodically sync parent/child orders from DB
    │
    └─ Deduplication Thread ─→ Periodically rotate event dedup buckets

Each thread is daemon=True, allowing graceful shutdown
```

### Thread Safety

Thread-safe operations protected by locks:

```
orderbook_lock
├─ Protects: orderbook.order, positions, parent_order_ids, child_order_ids
├─ Acquired in: process_user_order, claim_follow_up_processing, etc.
└─ Duration: Brief (microseconds)

ticker_lock
├─ Protects: ticker dict
├─ Acquired in: Event worker ticker processing
└─ Duration: Brief (microseconds)

seen_events_lock
├─ Protects: seen_events dict (dedup buckets)
├─ Acquired in: on_message, rotate_dedup_buckets
└─ Duration: Brief (microseconds)
```

## State Management

The orderbook maintains complete trading state:

```
orderbook = {
    order: {},                      # client_order_id → order dict
    positions: {
        'SPOT': {},                 # spot positions by product_id
        'FUTURE': {}                # futures positions by product_id
    },
    product: {},                    # product_id → product metadata
    profit: {},                     # profit targets by product or type
    parent_order_ids: {},           # parent mapping with targets
    child_order_ids: {},            # child mapping to parents
    filled: {},                     # filled order processing flags
    cancelled: {},                  # cancelled order processing flags
    # ... other fields
}
```

## Performance Characteristics

### Time Complexity

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Order lookup | O(1) | Hash table access |
| Duplicate event check | O(1) avg | Bloom filter-like bucketing |
| Product lookup | O(1) | Hash table access |
| Profit target resolution | O(1) avg | Dict lookup |
| Follow-up calculation | O(1) | Fixed number of fields |
| Position update | O(1) | Single position update |

### Space Complexity

| Data Structure | Complexity | Notes |
|---|---|---|
| orderbook.order | O(n) | n = active orders |
| positions | O(m) | m = products with positions |
| seen_events | O(e) | e = events in dedup window (capped) |
| parent_order_ids | O(p) | p = parent orders (grows over time) |
| child_order_ids | O(c) | c = child orders (grows over time) |

### Optimization Opportunities

1. **LRU Cache**: Cache product metadata to reduce lookups
2. **Batch Operations**: Process multiple events atomically
3. **Connection Pooling**: Reuse API connections
4. **Lazy Loading**: Load positions only when needed
5. **Metrics**: Add instrumentation for performance monitoring

## Error Handling Strategy

```
WebSocket Connection Errors
├─ WSClientConnectionClosedException
├─ Retry logic in connect_to_websocket()
└─ Daemon thread auto-restart

API Request Failures
├─ Caught in external/coinbase_client.py
├─ Logged with context
└─ Caller can retry

Database Operation Failures
├─ Logged in OrderEngine
├─ Processing flag released for retry
└─ Order state may be partially updated

Message Processing Errors
├─ Caught in on_message()
├─ Logged with raw message for debugging
└─ Event dropped (not re-enqueued)

Order Calculation Failures
├─ Caught in handle_filled_order()
├─ Processing flag released
└─ Logged for manual investigation
```

## Testing Architecture

```
tests/
├─ test_phase1.py         # 45 tests - Core utilities
├─ test_phase2.py         # 29 tests - External clients, state, repos
├─ test_api_reference.py  # 21 tests - API reference schema validation
├─ test_phase3.py         # 46 tests - Business logic isolation
├─ test_integration.py    # 48 tests - Bridge integration
└─ fixtures.py            # Shared fixtures (APIReferenceLoader, etc.)

Test Strategy:
├─ Unit: Test each module in isolation
├─ Integration: Test module interactions
└─ Workflow: Test complete business processes
```

## Monitoring and Observability

### Logging Points

```
orderbook.log_message(log_type, message)

Log Types:
├─ 'order' - Order state changes
├─ 'database' - Database operations
├─ 'event' - Event processing
├─ 'user' - User channel events
├─ 'ticker' - Ticker events
├─ 'connection' - WebSocket connection events
├─ 'warning' - Warnings and non-fatal errors
├─ 'error' - Fatal errors requiring attention
├─ 'reconcile' - Database reconciliation
└─ 'snapshot' - Position snapshots
```

### Metrics to Track

```
Performance:
├─ Orders processed per second
├─ Average order processing latency
├─ Follow-up order creation rate
└─ Event deduplication hit rate

Health:
├─ WebSocket connection uptime
├─ Order success rate
├─ Database operation latency
└─ Event queue depth

Business:
├─ Total follow-ups created
├─ Replacement count distribution
├─ Position changes by product
└─ Fee calculations accuracy
```

## Security Considerations

```
API Credentials:
├─ Stored in configuration.py (should use env vars)
├─ Passed to external/coinbase_client.py
├─ Not logged or printed

Database:
├─ PostgreSQL local connection (production should use credentials)
├─ Should use connection pooling
└─ Should validate inputs

WebSocket:
├─ Authenticated with API key/secret
├─ TLS by default with Coinbase
└─ Reconnects on disconnect (automatic)

Order Data:
├─ Contains user balances and positions (keep private)
├─ Logged with level control (debug vs info)
└─ Should not expose in external APIs
```

---

**Document Version**: 1.0
**Last Updated**: April 2026
**Status**: Phase 4 Complete (189/189 tests)
