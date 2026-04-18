# Detailed API Reference - Coinbase Trading Engine

## Table of Contents
1. [configuration.py API](#configurationpy-api)
2. [order.py API](#orderpy-api)
3. [main.py API (OrderEngine)](#mainpy-api-orderengine)
4. [database/database.py API](#databasedatabasepy-api)
5. [database/order.py API](#databaseorderpy-api)
6. [CLI Scripts API](#cli-scripts-api)

---

## configuration.py API

### Module-Level Constants

#### Authentication
```python
API_KEY: str
API_SECRET: str
REST_CLIENT: RESTClient
```

**Description**: Coinbase API credentials loaded from environment variables

**Initialization**: 
```python
API_KEY = getenv("COINBASE_API_KEY")
API_SECRET = getenv("COINBASE_API_SECRET")
REST_CLIENT = RESTClient(api_key=API_KEY, api_secret=API_SECRET, rate_limit_headers=True)
```

---

#### Order Configuration
```python
ORDER_SIDE_SWITCH = {
    "BUY": "SELL",
    "SELL": "BUY"
}

ORDER_POSITION_SIDE = {
    "SHORT": "SELL",
    "LONG": "BUY",
    "SELL": "SHORT",
    "BUY": "LONG"
}

ORDER_DIRECTION = {
    "SELL": 1,    # Price increases for SELL orders
    "BUY": -1     # Price decreases for BUY orders
}
```

**Purpose**: Map order states for follow-up order generation

---

#### Product Lists
```python
SPOT_PRODUCT_IDS: List[str]          # e.g., ['BTC-USDC', 'ETH-USDC', ...]
DERIVATIVES_PRODUCT_IDS: List[str]   # e.g., ['BIP-20DEC30-CDE', 'ETP-20DEC30-CDE', ...]
```

---

#### Fees
```python
DERIVATIVES_MANDATORY_FEE_PER_CONTRACT: float = 0.15  # Base fee per contract
DEFAULT_MAX_ORDER_REPLACEMENT: int = 1                 # Max follow-up orders per parent
```

---

### Utility Functions

#### `safe_float(value, default=0.0) -> float`

**Signature**:
```python
def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on error."""
```

**Purpose**: Type-safe float conversion with fallback

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `value` | Any | Required | Value to convert (str, int, float, None) |
| `default` | float | 0.0 | Return value if conversion fails |

**Returns**: 
- `float`: Converted value or default

**Raises**: 
- None (always returns float)

**Examples**:
```python
safe_float('123.45')          # → 123.45
safe_float(100)               # → 100.0
safe_float(None)              # → 0.0
safe_float('invalid', 10.0)   # → 10.0
```

---

#### `normalize_product_type(order, products=None) -> str`

**Signature**:
```python
def normalize_product_type(order: dict, products: dict = None) -> str:
    """Determine if order is for SPOT or FUTURE trading."""
```

**Purpose**: Classify order trading type with fallback logic

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `order` | dict | Required | Order dict with optional 'product_type', 'product_id' |
| `products` | dict | None | Product metadata keyed by product_id |

**Returns**:
- `str`: Either 'SPOT' or 'FUTURE'

**Resolution Order**:
1. Explicit `product_type` field in order (if valid)
2. `product_type` from products metadata (if available)
3. Product ID suffix pattern (ends with '-CDE' = FUTURE)
4. Default to 'SPOT'

**Examples**:
```python
normalize_product_type({'product_type': 'SPOT'})         # → 'SPOT'
normalize_product_type({'product_id': 'BIP-20DEC30-CDE'})  # → 'FUTURE'
normalize_product_type({})                               # → 'SPOT'
```

---

#### `resolve_order_size(order) -> float`

**Signature**:
```python
def resolve_order_size(order: dict) -> float:
    """Extract order size from multiple possible fields."""
```

**Purpose**: Handle API response variations in size field naming

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `order` | dict | Order data from API |

**Returns**:
- `float`: Order size, or 0.0 if not found

**Field Priority**:
1. `leaves_quantity` (highest priority)
2. `cumulative_quantity`
3. `filled_size`
4. `base_size`
5. `size`
6. 0.0 (default)

**Examples**:
```python
resolve_order_size({'leaves_quantity': 10.5})      # → 10.5
resolve_order_size({'filled_size': '5.0'})          # → 5.0
resolve_order_size({})                             # → 0.0
```

---

#### `resolve_profit_move_pct(order, profits, products) -> float`

**Signature**:
```python
def resolve_profit_move_pct(
    order: dict, 
    profits: dict, 
    products: dict
) -> float:
    """Get configured profit target percentage for an order."""
```

**Purpose**: Lookup profit configuration with fallback to product type

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `order` | dict | Order with 'product_id', 'order_side' |
| `profits` | dict | Config: {product_type: {side: pct}} or {product_id: {side: pct}} |
| `products` | dict | Product metadata keyed by product_id |

**Returns**:
- `float`: Profit percentage (e.g., 0.004 for 0.4%)

**Resolution Order**:
1. Product-specific config (e.g., 'BIP-20DEC30-CDE')
2. Product type config (e.g., 'FUTURE' or 'SPOT')
3. Raises KeyError if not found

**Examples**:
```python
profits = {
    'SPOT': {'BUY': 0.004, 'SELL': 0.004},
    'BIP-20DEC30-CDE': {'BUY': 0.028, 'SELL': 0.028}
}
products = {'BIP-20DEC30-CDE': {'product_type': 'FUTURE'}}

order = {'product_id': 'BIP-20DEC30-CDE', 'order_side': 'BUY'}
resolve_profit_move_pct(order, profits, products)  # → 0.028 (product-specific)

order = {'product_id': 'BTC-USDC', 'order_side': 'BUY'}
resolve_profit_move_pct(order, profits, products)  # → 0.004 (SPOT default)
```

---

#### `format_based_on_reference(value_to_format, reference_float) -> str`

**Signature**:
```python
def format_based_on_reference(value_to_format: float, reference_float: str) -> str:
    """Format float to match decimal places of reference."""
```

**Purpose**: Match price/size precision to exchange increments

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `value_to_format` | float | Numeric value to format |
| `reference_float` | str | Reference string (e.g., '0.01') |

**Returns**:
- `str`: Formatted string with matching decimal places

**Algorithm**:
- Extract decimal place count from reference string
- Format value to that many decimal places
- Apply rounding rules

**Examples**:
```python
format_based_on_reference(123.456, '0.01')    # → '123.46'
format_based_on_reference(123.456, '0.001')   # → '123.456'
format_based_on_reference(123.456, '1')       # → '123'
format_based_on_reference(10.5, '0.0001')     # → '10.5000'
```

---

#### `quantize_to_increment(value, increment, direction='nearest') -> float`

**Signature**:
```python
def quantize_to_increment(
    value: float, 
    increment: str, 
    direction: str = "nearest"
) -> float:
    """Round value to nearest valid increment."""
```

**Purpose**: Ensure prices/sizes comply with exchange minimum requirements

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `value` | float | Required | Value to quantize |
| `increment` | str | Required | Increment step (e.g., '0.01') |
| `direction` | str | 'nearest' | 'nearest', 'up', or 'down' |

**Returns**:
- `float`: Quantized value

**Raises**:
- `ValueError`: If increment ≤ 0 or invalid direction

**Behavior by Direction**:
- `'nearest'`: Round to nearest increment
- `'down'`: Floor to lower increment
- `'up'`: Ceil to higher increment

**Examples**:
```python
quantize_to_increment(100.126, '0.01')                          # → 100.13
quantize_to_increment(100.124, '0.01', direction='down')        # → 100.12
quantize_to_increment(100.126, '0.01', direction='up')          # → 100.13
quantize_to_increment(50.5, '1', direction='down')              # → 50.0
quantize_to_increment(50.5, '1', direction='up')                # → 51.0
```

---

### REST API Wrapper Functions

#### `rest_get_account_wallets() -> dict`

**Signature**:
```python
def rest_get_account_wallets() -> dict:
    """Retrieve all active account wallets."""
```

**Purpose**: Fetch current balances for all currencies

**Returns**:
```python
{
    'BTC': {
        'currency': 'BTC',
        'available_balance': '0.5',
        'total_balance': '0.5',
        'created_at': '2024-01-01T00:00:00Z',
        'updated_at': '2024-04-18T10:30:00Z',
        'deleted_at': None,
        ...
    },
    'USDC': {...},
    ...
}
```

**Raises**:
- `APIError`: If REST call fails

**Example**:
```python
wallets = rest_get_account_wallets()
btc_balance = wallets.get('BTC', {}).get('available_balance')
print(f"BTC Balance: {btc_balance}")
```

---

#### `rest_get_products() -> dict`

**Signature**:
```python
def rest_get_products() -> dict:
    """Retrieve all trading products metadata."""
```

**Purpose**: Fetch increments, fees, product types for all enabled products

**Returns**:
```python
{
    'BTC-USDC': {
        'product_id': 'BTC-USDC',
        'price_increment': '1',
        'base_increment': '0.001',
        'quote_increment': '0.01',
        'product_type': 'SPOT',
        'trading_disabled': False,
        ...
    },
    'BIP-20DEC30-CDE': {
        'product_id': 'BIP-20DEC30-CDE',
        'price_increment': '1',
        'base_increment': '1',
        'quote_increment': '0.01',
        'product_type': 'FUTURE',
        'trading_disabled': False,
        'future_product_details': {
            'contract_size': '1'
        },
        ...
    },
    ...
}
```

**Raises**:
- `APIError`: If REST call fails

**Note**: Filters out products with `trading_disabled=True`

---

#### `get_futures_positions() -> dict`

**Signature**:
```python
def get_futures_positions() -> dict:
    """Retrieve all open futures positions."""
```

**Purpose**: Fetch current perpetual and expiring futures positions

**Returns**:
```python
{
    'BIP-20DEC30-CDE': {
        'product_id': 'BIP-20DEC30-CDE',
        'side': 'LONG',
        'number_of_contracts': '100',
        'current_price': '77000.00',
        'entry_price': '77000.00',
        '...': '...'
    },
    'ETP-20DEC30-CDE': {...},
    ...
}
# Returns {} if no open positions
```

**Raises**:
- `APIError`: If REST call fails

---

#### `get_open_orders() -> dict`

**Signature**:
```python
def get_open_orders() -> dict:
    """Retrieve all OPEN orders."""
```

**Purpose**: Fetch currently active orders for order tracking

**Returns**:
```python
{
    'client_order_id_123': {
        'client_order_id': 'client_order_id_123',
        'product_id': 'BTC-USDC',
        'order_side': 'BUY',
        'base_size': '0.5',
        'limit_price': '40000.00',
        'status': 'OPEN',
        'order_id': 'order_id_abc',
        '...': '...'
    },
    ...
}
# Returns {} if no open orders
```

**Raises**:
- `APIError`: If REST call fails

---

### Order Calculation Functions

#### `calculate_new_order_move_from_snapshot(snapshot, order_id, target_movement=None) -> dict`

**Signature**:
```python
def calculate_new_order_move_from_snapshot(
    snapshot: dict, 
    order_id: str, 
    target_movement: dict = None
) -> dict:
    """Calculate follow-up order template from snapshot."""
```

**Purpose**: Compute price, size, and position updates for next order without API calls

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `snapshot` | dict | Required | State snapshot with order, positions, product, profit, mandatory_fee data |
| `order_id` | str | Required | client_order_id of order to compute for |
| `target_movement` | dict | None | Override movement with {'type': 'P'/'A', 'movement': value} |

**Snapshot Structure**:
```python
snapshot = {
    'order': {
        client_id: {
            'product_id': 'BTC-USDC',
            'status': 'FILLED',
            'order_side': 'BUY',
            'filled_size': '0.5',
            'limit_price': '40000.00'
        }
    },
    'positions': {
        'FUTURE': {
            'BIP-20DEC30-CDE': {
                'side': 'LONG',
                'number_of_contracts': '100'
            }
        }
    },
    'product': {
        'BTC-USDC': {
            'base_increment': '0.001',
            'quote_increment': '0.01',
            'price_increment': '1',
            'product_type': 'SPOT'
        }
    },
    'profit': {
        'SPOT': {'BUY': 0.004, 'SELL': 0.004},
        'FUTURE': {'BUY': 0.002, 'SELL': 0.002}
    },
    'mandatory_fee_per_contract': {
        'BIP-20DEC30-CDE': {'mandatory_fee_per_contract': 15.0}
    }
}
```

**Returns**:
```python
{
    'current_contract_count': '100',    # For FUTURE, 'N/A' for SPOT
    'mandatory_fee': 1500.0,             # Fee amount for FUTURE
    'profit_move_pct': 0.004,            # Profit percentage
    'fee_move_calculated_from_pct': 160.0,  # Profit $ amount
    'minimum_move_amount': 1.0,          # Price increment
    'product_id': 'BTC-USDC',
    'side': 'SELL',                      # Opposite of original
    'order_base_size': '0.50',           # Formatted as string
    'order_price_difference': '160.00',  # Price move in base currency
    'start_price': '40160.00',           # New order price as string
    'position_update': {                 # None if no position change
        'product_type': 'FUTURE',
        'product_id': 'BIP-20DEC30-CDE',
        'fields': {
            'side': 'SHORT',
            'number_of_contracts': '0'
        }
    }
}
# Returns {} if order_id not found
```

**Algorithm**:
1. Flip order_side (BUY → SELL)
2. Lookup profit target % or use provided target_movement
3. Calculate price move: order_price * profit_pct
4. Add mandatory fee (for futures)
5. Quantize to exchange increments
6. Calculate position update if needed
7. Return formatted template

**Examples**:
```python
# Spot order follow-up
result = calculate_new_order_move_from_snapshot(snapshot, 'order_123')
print(f"Sell at ${result['start_price']} for {result['order_base_size']} BTC")

# Override profit target
result = calculate_new_order_move_from_snapshot(
    snapshot, 
    'order_123',
    target_movement={'type': 'A', 'movement': 500.0}  # $500 absolute
)
```

---

#### `apply_calculated_position_update(positions, position_update) -> dict`

**Signature**:
```python
def apply_calculated_position_update(
    positions: dict, 
    position_update: dict
) -> dict:
    """Apply position update from calculate_new_order_move_from_snapshot."""
```

**Purpose**: Mutate positions dict with calculated updates

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `positions` | dict | Position dict (modified in-place) |
| `position_update` | dict | Update dict from calculation |

**Returns**:
- `dict`: The updated positions dict (same object as input)

**Behavior**:
- Creates nested dicts if missing
- Merges field updates
- Mutates input dict

**Examples**:
```python
positions = {'FUTURE': {'BIP-20DEC30-CDE': {'side': 'LONG', 'contracts': '100'}}}
update = {
    'product_type': 'FUTURE',
    'product_id': 'BIP-20DEC30-CDE',
    'fields': {'side': 'SHORT', 'contracts': '50'}
}
apply_calculated_position_update(positions, update)
# positions now has side=SHORT, contracts=50
```

---

### OrderBook Class

#### `class OrderBook`

**Signature**:
```python
class OrderBook:
    """Container for order and position state."""
    
    transaction_summary: dict           # Fee tier info
    should_replace: dict               # {'FILLED': True, 'CANCELLED': True}
    parent_order_ids: dict             # Tracks parent orders
    child_order_ids: dict              # Tracks child→parent mapping
    cancelled: dict                    # Cancelled order dedup
    filled: dict                       # Filled order dedup
    order: dict                        # All orders by client_id
    price: dict                        # Last price by product_id
    product: dict                      # Product metadata
    mandatory_fee_per_contract: dict   # Futures fees
    active: dict                       # Active order processing state
    profit: dict                       # Profit config
    positions: dict                    # Futures positions
    db_client: Optional[object]        # Database client
```

**Purpose**: Single source of truth for trading state

**Initialization**: 
- Automatically fetches products, positions, fees on instantiation
- Lazy - no database connection until `db_client` is set

---

#### `OrderBook.calculate_new_order_move(order_id, target_movement=None) -> dict`

**Signature**:
```python
def calculate_new_order_move(
    self, 
    order_id: str, 
    target_movement: dict = None
) -> dict:
    """Calculate follow-up using current orderbook state."""
```

**Purpose**: Wrapper around `calculate_new_order_move_from_snapshot` using self

**Returns**: Same as `calculate_new_order_move_from_snapshot`

**Thread Safety**: Acquires `orderbook_lock` during deep copy

---

### Subscription Class

#### `class Subscription`

**Signature**:
```python
class Subscription:
    """WebSocket subscription configuration."""
    
    product_ids: List[str]             # All trading pairs
    derivatives_product_ids: List[str] # Futures only
    channels: List[str]                # ['heartbeats', 'user', 'ticker']
```

---

## order.py API

### `generate_float(start, stop=None) -> float`

**Signature**:
```python
def generate_float(start: float, stop: float = None) -> float:
    """Generate random float between two values."""
```

**Purpose**: Randomize order sizes within configured ranges

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `start` | float | Required | Minimum value or exact value |
| `stop` | float | None | Maximum value |

**Returns**:
- `float`: Random value between start and stop, or exact start if stop=None

**Examples**:
```python
generate_float(5.5)          # → 5.5 (exact)
generate_float(10.0, 20.0)   # → 15.347 (random between)
generate_float(1.0, 1.5)     # → 1.234
```

---

### `create_limit_order_span(...) -> List[dict]`

**Signature**:
```python
def create_limit_order_span(
    order_base_size_range: dict = None,
    delay_in_secs: int = 0,
    product_id: str = "NCT-USDC",
    side: str = "SELL",
    max_order_count: int = 1,
    order_base_size: float = 1,
    order_price_difference: float = 0.00001,
    start_price: float = 0.00992,
    post_only: bool = False
) -> list:
    """Place multiple limit orders at price intervals."""
```

**Purpose**: Programmatic market-making or ladder order placement

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `order_base_size_range` | dict | None | {'start': float, 'stop': float} or None for fixed size |
| `delay_in_secs` | int | 0 | Seconds to wait between order placements |
| `product_id` | str | "NCT-USDC" | Trading pair ID |
| `side` | str | "SELL" | 'BUY' or 'SELL' |
| `max_order_count` | int | 1 | Number of orders to place |
| `order_base_size` | float | 1 | Fixed size (used if range not specified) |
| `order_price_difference` | float | 0.00001 | Price gap between consecutive orders |
| `start_price` | float | 0.00992 | Price of first order |
| `post_only` | bool | False | Reject if would immediately fill |

**Returns**:
```python
[
    {
        'success': True,
        'success_response': {
            'order_id': 'abc123',
            'client_order_id': 'uuid-xxx',
            'product_id': 'BTC-USDC',
            'order_side': 'SELL',
            'base_size': '0.5',
            'limit_price': '40000.00',
            'status': 'PENDING',
            ...
        },
        'error_response': None
    },
    # More orders...
]
```

**Behavior**:
1. For count 1 to max_order_count:
   - Randomize size (or use fixed)
   - Calculate price: start_price + (count * price_diff * ORDER_DIRECTION[side])
   - Quantize to exchange increments
   - POST via REST API
   - Retry on INSUFFICIENT_FUND, fail on others
   - Wait delay_in_secs

**Price Calculation**:
- SELL (side=1): Price increases with each order
- BUY (side=-1): Price decreases with each order

**Examples**:
```python
# Simple 5 orders
orders = create_limit_order_span(
    product_id='BTC-USDC',
    side='SELL',
    start_price=42000.0,
    max_order_count=5
)

# Random sizes with delay
orders = create_limit_order_span(
    product_id='ETH-USDC',
    side='BUY',
    order_base_size_range={'start': 0.5, 'stop': 2.0},
    delay_in_secs=2,
    max_order_count=10
)
```

---

## main.py API (OrderEngine)

### `class OrderEngine`

**Full Signature**:
```python
class OrderEngine:
    def __init__(
        self,
        orderbook: OrderBook,
        db_client,
        subscription: Subscription,
        api_key: str,
        api_secret: str,
        order_post_only: dict,
        websocket_thread_maximum: int = 3,
        max_workers: int = 16,
        max_rotate_seen_events_bucket_seconds: int = 60,
        max_seen_event_buckets: int = 3,
        queue_maxsize: int = 10000
    ) -> None:
        """Initialize trading engine."""
```

**Purpose**: Main orchestration class for automated trading

**Attributes**:
| Name | Type | Purpose |
|------|------|---------|
| `orderbook` | OrderBook | State container |
| `event_executor` | ThreadPoolExecutor | Event processing threads |
| `event_queue` | dict | Queues per channel |
| `seen_events` | dict | Hash buckets for dedup |
| `logging_flags` | dict | Enable/disable log types |
| `ticker` | dict | Last price by product_id |
| `websocket_thread_maximum` | int | Number of WS connections |

---

#### `OrderEngine.run_forever() -> None`

**Signature**:
```python
def run_forever(self) -> None:
    """Start all background threads and block forever."""
```

**Purpose**: Begin trading operations

**Behavior**:
1. Start websocket threads
2. Start event processing threads
3. Start reconciliation and dedup threads
4. Enter infinite event loop
5. Block until KeyboardInterrupt

**Side Effects**:
- Spawns multiple daemon threads
- Subscribes to WebSocket channels
- Begins event processing

---

#### `OrderEngine.log_message(log_type, message) -> None`

**Signature**:
```python
def log_message(self, log_type: str, message) -> None:
    """Log message if log type enabled."""
```

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `log_type` | str | Category (key in logging_flags) |
| `message` | str/dict/list | Message to log |

**Format**: `{timestamp} {thread_name} [{LOG_TYPE}] {message}`

**Logging Flags Available**:
```python
logging_flags = {
    'snapshot': False,    # Initial snapshots
    'open': True,        # Order opened events
    'filled': True,      # Order filled events
    'cancelled': True,   # Order cancelled events
    'update': True,      # Order updates
    'user': False,       # Raw user websocket
    'ticker': False,     # Ticker updates
    'connection': True,  # WS connections
    'event': True,       # Event queue activity
    'order': True,       # Order operations
    'database': True,    # DB operations
    'warning': True,     # Warnings
    'error': True,       # Errors
    'reconcile': True    # DB reconciliation
}
```

---

#### `OrderEngine.hash_dict(dictionary) -> str` (static)

**Signature**:
```python
@staticmethod
def hash_dict(dictionary: dict) -> str:
    """Hash dict for event deduplication."""
```

**Purpose**: Create consistent hash for dedup buckets

**Returns**: Hex SHA256 hash

---

#### `OrderEngine.get_orderbook_snapshot() -> dict`

**Signature**:
```python
def get_orderbook_snapshot(self) -> dict:
    """Get thread-safe copy of orderbook state."""
```

**Returns**:
```python
{
    'order': {...},                      # Deep copy
    'positions': {...},                  # Deep copy
    'product': {...},                    # Reference
    'profit': {...},                     # Reference
    'mandatory_fee_per_contract': {...}, # Reference
    'parent_order_ids': {...},          # Deep copy
    'child_order_ids': {...}            # Deep copy
}
```

**Thread Safety**: Acquires `orderbook_lock`

---

#### `OrderEngine.normalize_product_type(order) -> str`

**Signature**:
```python
def normalize_product_type(self, order: dict) -> str:
    """Determine SPOT or FUTURE."""
```

**Purpose**: Classify order (thread-safe)

**Returns**: 'SPOT' or 'FUTURE'

---

#### `OrderEngine.resolve_order_size(order) -> float`

**Signature**:
```python
def resolve_order_size(self, order: dict) -> float:
    """Extract order size."""
```

**Returns**: float order size or 0.0

---

#### `OrderEngine.resolve_profit_target(order) -> float`

**Signature**:
```python
def resolve_profit_target(self, order: dict) -> float:
    """Get configured profit %."""
```

**Returns**: float percentage (e.g., 0.004)

---

#### `OrderEngine.refresh_positions_if_needed(product_id) -> None`

**Signature**:
```python
def refresh_positions_if_needed(self, product_id: str) -> None:
    """Refresh futures positions from API."""
```

**Purpose**: Lazy-load positions on first encounter

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `product_id` | str | Futures product to check |

---

#### `OrderEngine.resolve_parent_client_order_id(client_order_id, order=None, create_parent=False, status=None) -> Tuple[bool, str]`

**Signature**:
```python
def resolve_parent_client_order_id(
    self,
    client_order_id: str,
    order: dict = None,
    create_parent: bool = False,
    status: str = None
) -> tuple:
    """Determine if order is parent or find parent."""
```

**Returns**: `(is_parent: bool, parent_client_order_id: str)`

---

#### `OrderEngine.claim_follow_up_processing(processed_flag_name, client_order_id) -> bool`

**Signature**:
```python
def claim_follow_up_processing(
    self, 
    processed_flag_name: str, 
    client_order_id: str
) -> bool:
    """Atomically claim processing rights."""
```

**Purpose**: Prevent duplicate follow-up creation

**Parameters**:
| Name | Type | Description |
|------|------|-------------|
| `processed_flag_name` | str | 'filled' or 'cancelled' |
| `client_order_id` | str | Order to claim |

**Returns**: `True` if claimed, `False` if already processing/done

---

## database/database.py API

### `class PostgresDB`

**Signature**:
```python
class PostgresDB:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5432,
        database: str = "postgres",
        user: str = "postgres",
        password: str = "postgres"
    ) -> None:
        """Initialize connection parameters."""
```

---

#### `PostgresDB.connect() -> None`

**Purpose**: Establish database connection

**Raises**: `psycopg2.Error` on failure

---

#### `PostgresDB.disconnect() -> None`

**Purpose**: Close connection

**Side Effects**: Prints confirmation message

---

#### `PostgresDB.get_cursor() -> Iterator[psycopg2.cursor]`

**Signature**:
```python
@contextmanager
def get_cursor(self):
    """Context manager for cursor with transaction handling."""
```

**Purpose**: Auto-commit/rollback transactions

**Usage**:
```python
with db.get_cursor() as cursor:
    cursor.execute(query, params)
```

---

#### `PostgresDB.execute_query(query, params=None) -> List[Dict]`

**Signature**:
```python
def execute_query(
    self, 
    query: str, 
    params: Optional[tuple] = None
) -> List[Dict[str, Any]]:
    """Execute SELECT and return rows as dicts."""
```

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | str | Required | SQL with %s placeholders |
| `params` | tuple | None | Parameters to bind |

**Returns**: List of dicts with column names as keys

---

## database/order.py API

### Schema Functions

#### `create_order_parent_table() -> None`

**Purpose**: Create order_parent table if not exists

**Table Schema**:
```sql
CREATE TABLE order_parent (
    id SERIAL PRIMARY KEY,
    target_movement NUMERIC,
    target_movement_type VARCHAR(1),          -- 'P' or 'A'
    max_order_replacement INTEGER DEFAULT 0,
    current_order_replacement INTEGER DEFAULT 0,
    client_order_id VARCHAR(40) UNIQUE NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

---

#### `create_order_child_table() -> None`

**Purpose**: Create order_child table if not exists

**Table Schema**:
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
)
```

---

### Insert Functions

#### `insert_order_parent(...) -> Optional[int]`

**Signature**:
```python
def insert_order_parent(
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    target_movement: float,
    target_movement_type: str = "P",
    max_order_replacement: int = 0,
    current_order_replacement: int = 0,
    status: str = "pending"
) -> Optional[int]:
    """Insert parent order record."""
```

**Returns**: Inserted record ID, or None on error

---

#### `insert_order_child(...) -> Optional[int]`

**Signature**:
```python
def insert_order_child(
    parent_client_order_id: str,
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    status: str = "pending"
) -> Optional[int]:
    """Insert child order record."""
```

**Returns**: Inserted record ID, or None on error

---

### Query Functions

#### `get_order_parent_by_id(id) -> Optional[Dict]`

**Purpose**: Retrieve parent order by database ID

**Returns**: Order dict or None

---

#### `get_order_child_by_id(id) -> Optional[Dict]`

**Purpose**: Retrieve child order by database ID

**Returns**: Order dict or None

---

## CLI Scripts API

### `cli_create_all_tables.py`

**Purpose**: Initialize database schema

**Execution**:
```bash
python cli_create_all_tables.py
```

**Output**:
```
Connected to PostgreSQL at 127.0.0.1:5432
order_parent table done.
order_child table done.
All tables created successfully!
```

---

### `cli_delete_all_tables.py`

**Purpose**: Drop all tables (for reset/testing)

**Execution**:
```bash
python cli_delete_all_tables.py
```

**Output**:
```
Connected to PostgreSQL at 127.0.0.1:5432
Found 2 table(s) to delete:
  - order_parent
  - order_child
Dropped table: order_parent
Dropped table: order_child
All tables deleted successfully!
```

---

### `cli_list_all_orders.py`

**Purpose**: List all orders from database

**Execution**:
```bash
python cli_list_all_orders.py
```

---

## Type Hints Summary

```python
# Common types used throughout
OrderDict = Dict[str, Union[str, float, int, Dict]]
ProductDict = Dict[str, Union[str, float, bool, Dict]]
PositionDict = Dict[str, Union[str, float]]
ProfitConfig = Dict[str, Dict[str, float]]  # {product_type/id: {side: pct}}
PositionUpdate = Dict[str, Union[str, Dict]]  # {product_type, product_id, fields}
APIResponse = Dict[str, Union[bool, OrderDict, Dict[str, str]]]
```

