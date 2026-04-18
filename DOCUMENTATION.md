# Coinbase Advanced Trading Engine - Complete Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Module Breakdown](#module-breakdown)
4. [API Reference](#api-reference)
5. [Usage Examples](#usage-examples)
6. [Configuration Guide](#configuration-guide)
7. [Database Schema](#database-schema)
8. [Testing & Validation](#testing--validation)

---

## Project Overview

### Purpose
This project implements an **advanced automated trading engine** for the Coinbase API that:
- Maintains real-time websocket connections for live order updates
- Manages parent-child order relationships and their complete lifecycle
- Automatically generates follow-up orders based on fills and cancellations
- Tracks futures positions with accurate contract and fee calculations
- Persists order data to PostgreSQL for reconciliation and historical analysis
- Deduplicates events using hash-based bucketing to prevent race conditions

### Technology Stack
- **Language**: Python 3.x
- **Exchange**: Coinbase Advanced API (REST + WebSocket)
- **Database**: PostgreSQL (localhost, Docker-based)
- **Concurrency**: ThreadPoolExecutor, Thread Locks, Queue-based event processing
- **Libraries**: 
  - `coinbase-advanced-py`: Official Coinbase SDK
  - `psycopg2`: PostgreSQL adapter
  - Standard library: threading, json, uuid, hashlib

### Current State (Pre-Refactor)
The project currently has:
- **7 Python modules** with mixed responsibilities
- **~800 lines** of core OrderEngine logic in `main.py`
- **~600 lines** of configuration/utility functions in `configuration.py`
- **~150 lines** of order placement logic in `order.py`
- **Database layer** split across `database.py` and `database/order.py`
- **CLI scripts** for table creation/deletion and order listing
- **Minimal separation** between API calls, business logic, and state management

---

## Architecture

### High-Level System Design

```
┌─────────────────────────────────────────────────────────────┐
│                    OrderEngine (main.py)                    │
│  - Coordinates all threads & event processing               │
│  - Manages state mutations & synchronization                │
│  - Implements deduplication & follow-up logic               │
└─────┬────────────────┬────────────────┬─────────────────────┘
      │                │                │
      ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ WebSocket    │ │ Event Queue  │ │ OrderBook    │
│ Threads      │ │ & Events     │ │ (State)      │
│ (x3 default) │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
      │                │                │
      └────────────────┼────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │   Event Processing Threads   │
        │   (ThreadPoolExecutor)       │
        │   - User events (orders)     │
        │   - Ticker (prices)          │
        │   - Heartbeats              │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │   Follow-up Order Creation   │
        │   - calculate_new_order_move │
        │   - REST API placement       │
        │   - Database persistence    │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │   Database (PostgreSQL)      │
        │   - order_parent table       │
        │   - order_child table        │
        └──────────────────────────────┘
```

### Threading Model

**Main Thread**:
- Runs `OrderEngine.run_forever()` which blocks indefinitely
- Spawns all background threads
- Handles main event loop (none - runs async)

**WebSocket Threads** (default: 3):
- Each maintains a live connection to Coinbase WebSocket API
- Receives SNAPSHOT, OPEN, FILLED, CANCELLED, UPDATE events
- Routes events to per-channel queues
- Auto-reconnects on disconnection

**Event Processing Threads** (ThreadPoolExecutor, default: 16 workers):
- Pull from event queues (ticker, user, heartbeats)
- Process user events to create follow-up orders
- Update orderbook state atomically
- Insert records into database

**Reconciliation Thread** (background):
- Periodically syncs parent/child orders from database
- Rebuilds in-memory state if inconsistencies detected

**Deduplication Thread** (background):
- Rotates event deduplication hash buckets
- Prevents processing duplicate events from multiple websocket sources

### State Management

**OrderBook** (Central State Container):
- `order`: Dict of all orders by client_order_id
- `parent_order_ids`: Dict mapping parent_id → {orders, target_movement, ...}
- `child_order_ids`: Dict mapping child_id → parent_id
- `positions`: Dict of futures positions {'FUTURE': {product_id: {...}}}
- `product`: Product metadata (increments, fees, etc.)
- `profit`: Configured profit targets by product/type
- Thread-safe access via `orderbook_lock`

**Synchronization Primitives**:
- `orderbook_lock`: RwLock-like lock (acquired during mutations)
- `ticker_lock`: Lock for ticker price updates
- `seen_events_lock`: Lock for dedup bucket rotation
- Event queues: FIFO order preservation, backpressure via max size

### Event Deduplication

**Problem**: Multiple websocket threads may receive the same event → duplicate follow-up orders

**Solution**: Hash-based bucketing with timestamp rotation
- Create SHA256 hash of event JSON
- Store hash in rotating bucket (3 buckets by default)
- Bucket rotation every 60 seconds (configurable)
- Event considered duplicate if hash found in any active bucket
- Prevents processing same event for ~3 minutes

---

## Module Breakdown

### 1. `configuration.py` (~600 lines)
**Purpose**: Configuration, API initialization, utility functions, OrderBook class

**Key Components**:

#### Constants
```python
API_KEY, API_SECRET                 # Coinbase credentials from env
REST_CLIENT                         # RESTClient instance
ORDER_SIDE_SWITCH = {"BUY": "SELL", "SELL": "BUY"}
ORDER_POSITION_SIDE = {"SHORT": "SELL", "LONG": "BUY", ...}
ORDER_DIRECTION = {"SELL": 1, "BUY": -1}
DERIVATIVES_PRODUCT_IDS             # Futures contracts
SPOT_PRODUCT_IDS                    # Spot trading pairs
```

#### Utility Functions

**Type Conversion**:
- `safe_float(value, default=0.0)` → Safely convert to float
- `format_based_on_reference(value, reference)` → Match decimal precision
- `quantize_to_increment(value, increment, direction)` → Round to exchange increments

**Product/Order Resolution**:
- `normalize_product_type(order, products)` → Return 'SPOT' or 'FUTURE'
- `resolve_order_size(order)` → Extract size from multiple possible fields
- `resolve_profit_move_pct(order, profits, products)` → Get configured profit %

**REST API Wrappers**:
- `rest_get_account_wallets()` → Dict of {currency: wallet_data}
- `rest_get_products()` → Dict of {product_id: product_data}
- `get_futures_positions()` → Dict of {product_id: position_data}
- `get_open_orders()` → Dict of {client_order_id: order_data}

**Order Computation**:
- `calculate_new_order_move_from_snapshot(snapshot, order_id, target_movement)` → Template for follow-up order
- `apply_calculated_position_update(positions, update)` → Apply position changes

#### OrderBook Class
**State container**: Maintains all trading state in memory
- **Initialization**: Fetches products, positions, fees on instantiation
- **Method**: `calculate_new_order_move(order_id)` → Convenience wrapper

#### Subscription Class
**Configuration**: Which channels and products to subscribe to
- `product_ids`: All derivatives + spot products
- `channels`: ["heartbeats", "user", "ticker"]

### 2. `main.py` (~800 lines)
**Purpose**: OrderEngine orchestration, event processing, thread management

**Key Classes**:

#### OrderEngine
**Responsibility**: Coordinate all trading operations
- Initialize and manage background threads
- Process incoming websocket events from queues
- Create follow-up orders after fills/cancellations
- Maintain thread-safe state mutations
- Log structured events

**Core Methods**:
- `__init__(...)` → Initialize state, start threads
- `run_forever()` → Main blocking loop
- `log_message(log_type, message)` → Structured logging
- `hash_dict(dict)` → SHA256 for deduplication
- `get_orderbook_snapshot()` → Thread-safe state copy
- `normalize_product_type(order)` → SPOT vs FUTURE
- `resolve_order_size(order)` → Extract order quantity
- `resolve_profit_target(order)` → Get profit % config
- `claim_follow_up_processing(flag, order_id)` → Atomic lock for follow-up
- `resolve_parent_client_order_id(order_id, ...)` → Parent/child relationship
- (Plus 50+ additional helper methods for event processing)

**Background Threads**:
- WebSocket threads: Receive events and enqueue them
- Event worker threads: Process from queues, create follow-ups
- Reconciliation thread: Sync database state periodically
- Deduplication thread: Rotate hash buckets

### 3. `order.py` (~200 lines)
**Purpose**: Utility for creating multiple orders at price intervals

**Key Functions**:

#### `generate_float(start, stop=None)` 
Generates random float between two values (or exact value if stop=None)

**Input**: 
- `start: float` - Minimum value or exact value
- `stop: float` - Maximum value (optional)

**Output**: Random float between start and stop

**Examples**:
```python
generate_float(10.0, 20.0)  # ~15.3
generate_float(5.5)         # 5.5
```

#### `create_limit_order_span(...)`
Places multiple limit orders at specified price intervals

**Parameters**:
- `order_base_size_range` (dict): {'start': float, 'stop': float} or None for fixed size
- `delay_in_secs` (int): Delay between order placements (default: 0)
- `product_id` (str): Trading pair (e.g., 'BTC-USDC')
- `side` (str): 'BUY' or 'SELL'
- `max_order_count` (int): Number of orders to place
- `order_base_size` (float): Fixed size per order (used if range not specified)
- `order_price_difference` (float): Price gap between consecutive orders
- `start_price` (float): Price of first order
- `post_only` (bool): Reject if would immediately fill

**Algorithm**:
1. For order_count = 1 to max_order_count:
   - Randomize size from range (or use fixed size)
   - Calculate price = start_price + (order_count * price_difference * direction)
   - Quantize to exchange increments
   - Place via REST API
   - Retry on INSUFFICIENT_FUND, fail on other errors
   - Wait delay_in_secs

**Returns**: List of order response dicts

**Examples**:
```python
orders = create_limit_order_span(
    product_id='BTC-USDC',
    side='SELL',
    start_price=42000.0,
    max_order_count=5
)
```

### 4. `database/database.py` (~150 lines)
**Purpose**: PostgreSQL connection management

**PostgresDB Class**:
- `__init__(host, port, database, user, password)` → Store connection params
- `connect()` → Establish connection
- `disconnect()` → Close connection
- `get_cursor()` → Context manager for transactions
- `execute_query(query, params)` → Run SELECT, return list of dicts
- `execute_update(query, params)` → Run INSERT/UPDATE/DELETE, return row count

**Example**:
```python
db = PostgresDB(host="127.0.0.1", port=5432)
db.connect()
results = db.execute_query("SELECT * FROM order_parent WHERE id = %s", (1,))
db.disconnect()
```

### 5. `database/order.py` (~300 lines)
**Purpose**: Order-specific database operations

**Tables Created**:
- `order_parent`: Parent orders with replacement tracking
- `order_child`: Child (follow-up) orders linked to parents

**Functions**:
- `create_order_parent_table()` → Schema for parent orders
- `create_order_child_table()` → Schema for child orders
- `add_missing_order_parent_replacement_columns()` → Migration
- `insert_order_parent(...)` → Add parent order record
- `insert_order_child(...)` → Add child order record
- `get_order_parent_by_id(id)` → Retrieve parent by ID
- `get_order_child_by_id(id)` → Retrieve child by ID
- `update_order_parent_status(...)` → Update parent status
- (Plus additional query functions)

**Example**:
```python
parent_id = insert_order_parent(
    client_order_id="uuid-123",
    product_id="BTC-USDC",
    side="BUY",
    size=0.5,
    price=40000.0,
    target_movement=0.004,
    max_order_replacement=1
)
```

### 6. `cli_create_all_tables.py`
**Purpose**: Initialize database schema
**Function**: `main()` → Creates order_parent and order_child tables

### 7. `cli_delete_all_tables.py`
**Purpose**: Drop all tables (for testing/reset)
**Function**: `main()` → Deletes all tables from public schema

---

## API Reference

### OrderEngine Public API

#### Initialization
```python
engine = OrderEngine(
    orderbook=ORDERBOOK,
    db_client=DB_CLIENT,
    subscription=Subscription,
    api_key=API_KEY,
    api_secret=API_SECRET,
    order_post_only={"BUY": False, "SELL": False},
    websocket_thread_maximum=3,
    max_workers=16
)
```

#### Running
```python
engine.run_forever()  # Blocks indefinitely, runs all threads
```

#### Configuration
```python
# Enable/disable logging categories
engine.logging_flags['order'] = True
engine.logging_flags['user'] = False
engine.logging_flags['ticker'] = False

# Enable debug logging
engine.debug_logging_enabled = True
```

#### Logging
```python
engine.log_message("order", "Order placed successfully")
engine.log_message("error", {"reason": "insufficient_funds"})
```

### Configuration API

```python
from configuration import (
    rest_get_account_wallets,
    rest_get_products,
    get_futures_positions,
    get_open_orders,
    calculate_new_order_move_from_snapshot,
    normalize_product_type,
    resolve_order_size,
    safe_float,
    format_based_on_reference,
    quantize_to_increment,
    ORDERBOOK,
    Subscription
)

# Fetch data from API
wallets = rest_get_account_wallets()           # {currency: wallet_data}
products = rest_get_products()                 # {product_id: product_data}
positions = get_futures_positions()            # {product_id: position_data}
orders = get_open_orders()                     # {client_id: order_data}

# Utility functions
product_type = normalize_product_type(order)   # 'SPOT' or 'FUTURE'
size = resolve_order_size(order)               # float
price_str = format_based_on_reference(100.123, "0.01")  # "100.12"
quantized = quantize_to_increment(100.126, "0.01")      # 100.13
```

### Order Placement API

```python
from order import create_limit_order_span, generate_float

# Simple order placement
orders = create_limit_order_span(
    product_id="BTC-USDC",
    side="SELL",
    start_price=42000.0,
    max_order_count=5
)

# With random size and delay
orders = create_limit_order_span(
    product_id="ETH-USDC",
    side="BUY",
    start_price=2000.0,
    order_base_size_range={"start": 0.5, "stop": 2.0},
    max_order_count=3,
    delay_in_secs=2
)
```

### Database API

```python
from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    create_order_child_table,
    insert_order_parent,
    insert_order_child
)

# Database connection
db = PostgresDB()
db.connect()

# Setup tables
create_order_parent_table()
create_order_child_table()

# Insert orders
parent_id = insert_order_parent(
    client_order_id="id-123",
    product_id="BTC-USDC",
    side="BUY",
    size=0.5,
    price=40000.0,
    target_movement=0.004
)

child_id = insert_order_child(
    parent_client_order_id="id-123",
    client_order_id="id-124",
    product_id="BTC-USDC",
    side="SELL",
    size=0.5,
    price=41200.0
)

db.disconnect()
```

---

## Usage Examples

### Example 1: Basic Setup and Startup

```python
# setup_and_run.py
import os
from main import OrderEngine
from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
import database.order as DB_CLIENT

# Initialize database
DB_CLIENT.create_order_parent_table()
DB_CLIENT.create_order_child_table()

# Create and configure engine
engine = OrderEngine(
    orderbook=ORDERBOOK,
    db_client=DB_CLIENT,
    subscription=Subscription,
    api_key=API_KEY,
    api_secret=API_SECRET,
    order_post_only=ORDER_POST_ONLY,
    websocket_thread_maximum=2,
    max_workers=8
)

# Configure logging
engine.logging_flags['order'] = True
engine.logging_flags['filled'] = True
engine.logging_flags['cancelled'] = True
engine.logging_flags['error'] = True

# Run forever (blocks)
engine.run_forever()
```

**Expected Output**:
```
2026-04-18T10:30:45.123456 MainThread [CONNECTION] Connected to Coinbase WebSocket
2026-04-18T10:30:46.456789 user_event_thread_1 [ORDER] Parent order entry created
2026-04-18T10:30:47.789012 user_event_thread_2 [FILLED] Order filled: BTC-USDC BUY
2026-04-18T10:30:48.012345 user_event_thread_3 [ORDER] Follow-up order placed: SELL
```

### Example 2: Placing Orders with create_limit_order_span

```python
# place_orders.py
from order import create_limit_order_span
import json

# Place 10 buy orders for a derivative
orders = create_limit_order_span(
    product_id="BIP-20DEC30-CDE",
    side="BUY",
    start_price=77000,
    order_base_size=10,
    order_price_difference=150,
    max_order_count=10,
    delay_in_secs=0,
    post_only=True
)

# Print results
for i, order in enumerate(orders, 1):
    if order['success']:
        result = order['success_response']
        print(f"Order {i}: {result['client_order_id']}")
        print(f"  Product: {result['product_id']}")
        print(f"  Side: {result['order_side']}")
        print(f"  Size: {result['base_size']}")
        print(f"  Price: {result['limit_price']}")
    else:
        error = order['error_response']
        print(f"Order {i} FAILED: {error['error']}")

print(f"\nTotal orders placed: {len([o for o in orders if o['success']])}")
```

**Input**:
```python
product_id="BIP-20DEC30-CDE"
side="BUY"
start_price=77000
max_order_count=10
order_price_difference=150
```

**Expected Output**:
```
Order 1: uuid-1234
  Product: BIP-20DEC30-CDE
  Side: BUY
  Size: 10.0
  Price: 77000.0
Order 2: uuid-5678
  Product: BIP-20DEC30-CDE
  Side: BUY
  Size: 10.0
  Price: 77150.0
...
Total orders placed: 10
```

### Example 3: Order Calculation (Follow-up Generation)

```python
# calculate_follow_up.py
from configuration import (
    calculate_new_order_move_from_snapshot,
    rest_get_products,
    get_futures_positions
)

# Build a snapshot
snapshot = {
    'order': {
        'client_123': {
            'product_id': 'BTC-USDC',
            'status': 'FILLED',
            'order_side': 'BUY',
            'filled_size': '0.5',
            'limit_price': '40000.00'
        }
    },
    'positions': {'FUTURE': {}},
    'product': rest_get_products(),
    'profit': {'SPOT': {'BUY': 0.004, 'SELL': 0.004}},
    'mandatory_fee_per_contract': {}
}

# Calculate follow-up
result = calculate_new_order_move_from_snapshot(snapshot, 'client_123')

print(f"Follow-up order template:")
print(f"  Product: {result['product_id']}")
print(f"  Side: {result['side']}")  # Opposite of original
print(f"  Price: {result['start_price']}")
print(f"  Size: {result['order_base_size']}")
print(f"  Profit Move %: {result['profit_move_pct']}")
```

**Output**:
```
Follow-up order template:
  Product: BTC-USDC
  Side: SELL
  Price: 40160.00
  Size: 0.50
  Profit Move %: 0.004
```

### Example 4: Database Operations

```python
# db_operations.py
from database.database import PostgresDB
from database.order import (
    insert_order_parent,
    insert_order_child,
    get_order_parent_by_id
)

# Setup
db = PostgresDB()
db.connect()

# Create tables
from database import order as db_module
db_module.create_order_parent_table()
db_module.create_order_child_table()

# Insert parent order
parent_id = insert_order_parent(
    client_order_id="parent_123",
    product_id="BTC-USDC",
    side="BUY",
    size=0.5,
    price=40000.0,
    target_movement=0.004,
    max_order_replacement=3,
    status="OPEN"
)
print(f"Created parent order ID: {parent_id}")

# Insert child order
child_id = insert_order_child(
    parent_client_order_id="parent_123",
    client_order_id="child_124",
    product_id="BTC-USDC",
    side="SELL",
    size=0.5,
    price=40160.0,
    status="OPEN"
)
print(f"Created child order ID: {child_id}")

# Retrieve
parent = get_order_parent_by_id(parent_id)
print(f"Retrieved parent: {parent}")

db.disconnect()
```

**Input/Output**:
```
Created parent order ID: 1
Created child order ID: 2
Retrieved parent: {
    'id': 1,
    'client_order_id': 'parent_123',
    'product_id': 'BTC-USDC',
    'side': 'BUY',
    'size': 0.5,
    'price': 40000.0,
    'status': 'OPEN',
    'target_movement': 0.004,
    'max_order_replacement': 3,
    'current_order_replacement': 0
}
```

---

## Configuration Guide

### Environment Variables
```bash
export COINBASE_API_KEY="your-api-key"
export COINBASE_API_SECRET="your-api-secret"
```

### OrderEngine Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `websocket_thread_maximum` | 3 | Number of WebSocket connections |
| `max_workers` | 16 | Thread pool size for event processing |
| `max_rotate_seen_events_bucket_seconds` | 60 | Dedup bucket rotation interval |
| `max_seen_event_buckets` | 3 | Number of rolling dedup buckets |
| `queue_maxsize` | 10000 | Max events in each channel queue |

### Logging Configuration

```python
# Enable specific log types
engine.logging_flags = {
    "snapshot": False,      # Initial order/position snapshot
    "open": True,          # Order opened
    "filled": True,        # Order filled
    "cancelled": True,     # Order cancelled
    "update": True,        # Order updated
    "user": False,         # Raw user events
    "ticker": False,       # Price ticks
    "connection": True,    # WebSocket connections
    "event": True,         # Event queue activity
    "order": True,         # Order operations
    "database": True,      # Database operations
    "warning": True,       # Warnings
    "error": True,         # Errors
    "reconcile": True      # Database reconciliation
}

# Include verbose debug information
engine.debug_logging_enabled = True
```

### Product Configuration

Products are managed in `configuration.py`:

```python
SPOT_PRODUCT_IDS = [
    "BTC-USDC",
    "ETH-USDC",
    "DOT-BTC",
    # ... more spot pairs
]

DERIVATIVES_PRODUCT_IDS = [
    "BIP-20DEC30-CDE",  # BTC perpetual
    "ETP-20DEC30-CDE",  # ETH perpetual
    # ... more derivatives
]
```

### Profit Target Configuration

Configured in `OrderBook.profit`:

```python
profit = {
    "SPOT": {
        "BUY": 0.004,   # 0.4% for spot buys
        "SELL": 0.004   # 0.4% for spot sells
    },
    "FUTURE": {
        "BUY": 0.002,   # 0.2% for futures buys
        "SELL": 0.002   # 0.2% for futures sells
    },
    "BIP-20DEC30-CDE": {
        "BUY": 0.028,   # Override for specific product
        "SELL": 0.028
    }
}
```

---

## Database Schema

### order_parent Table
Tracks parent orders and their follow-up strategy

```sql
CREATE TABLE order_parent (
    id SERIAL PRIMARY KEY,
    target_movement NUMERIC,
    target_movement_type VARCHAR(1),  -- 'P' for %, 'A' for absolute
    max_order_replacement INTEGER NOT NULL DEFAULT 0,
    current_order_replacement INTEGER NOT NULL DEFAULT 0,
    client_order_id VARCHAR(40) UNIQUE NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Example Row**:
```
id                          1
client_order_id            "parent_123"
product_id                 "BTC-USDC"
side                       "BUY"
size                       0.5
price                      40000.0
status                     "FILLED"
target_movement            0.004
target_movement_type       "P"
max_order_replacement      3
current_order_replacement  1
created_at                 2026-04-18 10:30:45
```

### order_child Table
Tracks follow-up orders created from parent fills/cancellations

```sql
CREATE TABLE order_child (
    id SERIAL PRIMARY KEY,
    parent_client_order_id VARCHAR(40) NOT NULL,
    client_order_id VARCHAR(40) UNIQUE NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_client_order_id) REFERENCES order_parent(client_order_id)
);
```

**Example Row**:
```
id                         2
parent_client_order_id     "parent_123"
client_order_id            "child_124"
product_id                 "BTC-USDC"
side                       "SELL"
size                       0.5
price                      40160.0
status                     "OPEN"
created_at                 2026-04-18 10:30:46
```

---

## Testing & Validation

### Unit Tests for Utility Functions

#### Test safe_float
```python
# test_configuration.py
from configuration import safe_float

def test_safe_float():
    assert safe_float('123.45') == 123.45
    assert safe_float(None) == 0.0
    assert safe_float('') == 0.0
    assert safe_float('invalid') == 0.0
    assert safe_float('99.99', default=1.0) == 99.99
    assert safe_float('invalid', default=1.0) == 1.0
    print("✓ safe_float tests passed")
```

#### Test format_based_on_reference
```python
from configuration import format_based_on_reference

def test_format_based_on_reference():
    assert format_based_on_reference(123.456, '0.01') == '123.46'
    assert format_based_on_reference(123.456, '0.001') == '123.456'
    assert format_based_on_reference(123.456, '1') == '123'
    assert format_based_on_reference(10.5, '0.0001') == '10.5000'
    print("✓ format_based_on_reference tests passed")
```

#### Test quantize_to_increment
```python
from configuration import quantize_to_increment

def test_quantize_to_increment():
    assert quantize_to_increment(100.126, '0.01') == 100.13
    assert quantize_to_increment(100.124, '0.01', direction='down') == 100.12
    assert quantize_to_increment(100.126, '0.01', direction='up') == 100.13
    assert quantize_to_increment(50.5, '1', direction='down') == 50.0
    assert quantize_to_increment(50.5, '1', direction='up') == 51.0
    print("✓ quantize_to_increment tests passed")
```

#### Test generate_float
```python
from order import generate_float

def test_generate_float():
    # Fixed value
    result = generate_float(5.5)
    assert result == 5.5
    
    # Range (check it's between bounds)
    result = generate_float(10.0, 20.0)
    assert 10.0 <= result <= 20.0
    
    print("✓ generate_float tests passed")
```

#### Test normalize_product_type
```python
from configuration import normalize_product_type

def test_normalize_product_type():
    # Explicit type in order
    order = {'product_type': 'SPOT', 'product_id': 'BTC-USDC'}
    assert normalize_product_type(order) == 'SPOT'
    
    # Inferred from product_id suffix
    order = {'product_id': 'BIP-20DEC30-CDE'}
    assert normalize_product_type(order) == 'FUTURE'
    
    # Default to SPOT
    order = {'product_id': 'BTC-USDC'}
    assert normalize_product_type(order) == 'SPOT'
    
    print("✓ normalize_product_type tests passed")
```

### Integration Test: Order Follow-up Flow

```python
# test_integration_follow_up.py
from configuration import (
    calculate_new_order_move_from_snapshot,
    rest_get_products,
    OrderBook
)

def test_follow_up_order_generation():
    """Test generating a follow-up order after a fill"""
    
    # Create snapshot with a filled order
    snapshot = {
        'order': {
            'order_123': {
                'product_id': 'BTC-USDC',
                'status': 'FILLED',
                'order_side': 'BUY',
                'filled_size': '0.5',
                'limit_price': '40000.00'
            }
        },
        'positions': {'FUTURE': {}},
        'product': {
            'BTC-USDC': {
                'base_increment': '0.001',
                'quote_increment': '0.01',
                'price_increment': '1',
                'product_type': 'SPOT'
            }
        },
        'profit': {
            'SPOT': {'BUY': 0.004, 'SELL': 0.004}
        },
        'mandatory_fee_per_contract': {}
    }
    
    # Calculate follow-up
    result = calculate_new_order_move_from_snapshot(snapshot, 'order_123')
    
    # Validate results
    assert result['product_id'] == 'BTC-USDC'
    assert result['side'] == 'SELL'  # Opposite of BUY
    assert float(result['order_base_size']) == 0.5
    assert float(result['start_price']) == 40160.0  # 40000 * 1.004
    assert result['profit_move_pct'] == 0.004
    
    print("✓ Follow-up order generation test passed")
    print(f"  Product: {result['product_id']}")
    print(f"  Side: {result['side']}")
    print(f"  Price: {result['start_price']}")
    print(f"  Size: {result['order_base_size']}")
```

### Database Integration Test

```python
# test_database_integration.py
from database.database import PostgresDB
from database.order import (
    create_order_parent_table,
    insert_order_parent,
    insert_order_child,
    get_order_parent_by_id
)

def test_database_flow():
    """Test complete database write/read cycle"""
    
    db = PostgresDB()
    db.connect()
    
    # Setup
    create_order_parent_table()
    
    # Insert parent
    parent_id = insert_order_parent(
        client_order_id='test_parent_001',
        product_id='BTC-USDC',
        side='BUY',
        size=0.5,
        price=40000.0,
        target_movement=0.004,
        max_order_replacement=1
    )
    
    assert parent_id is not None
    print(f"✓ Inserted parent order with ID: {parent_id}")
    
    # Retrieve
    parent = get_order_parent_by_id(parent_id)
    assert parent is not None
    assert parent['client_order_id'] == 'test_parent_001'
    assert parent['product_id'] == 'BTC-USDC'
    assert parent['side'] == 'BUY'
    print(f"✓ Retrieved parent order: {parent}")
    
    db.disconnect()
```

---

## Next Steps for Refactoring

Based on this documentation, the project should be refactored into:

1. **api_client.py**: Coinbase API wrapper (REST calls)
2. **models.py**: Order, Position, Product dataclasses
3. **orderbook.py**: State management (separate from configuration)
4. **calculator.py**: Order computation logic (separate from configuration)
5. **database_layer.py**: Repository pattern for database operations
6. **websocket_handler.py**: WebSocket event processing
7. **event_processor.py**: Event queue and threading logic
8. **order_engine.py**: Clean orchestration layer
9. **utils/**: Utility functions (safe_float, quantize, format, etc.)
10. **config/**: Configuration classes and constants

This separation would enable:
- Independent testing of each layer
- Easier debugging and maintenance
- Clear dependency boundaries
- Reusability of components
- Better concurrent modification handling

