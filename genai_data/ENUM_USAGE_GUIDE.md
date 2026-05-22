# Enum Usage Guide

## Overview

This project now uses comprehensive enums for all fixed sets of values, improving type safety, IDE autocomplete, and code maintainability. All enums are defined in `core/enums.py` and exported from `core/__init__.py`.

## Enum Categories

### 1. Order Attributes

#### OrderSide
- **Values**: `BUY`, `SELL`
- **Usage**: All order creation and processing
- **Already used in**: `core/models.py`, `core/constants.py`, `business/order_calculator.py`

#### OrderStatus
- **Values**: `PENDING`, `OPEN`, `FILLED`, `CANCELLED`, `EXPIRED`, `FAILED`, `CANCEL_QUEUED`
- **Source**: Coinbase API order states
- **Usage**: Order state tracking, filtering, database queries
- **Already used in**: `business/order_processor.py`, `core/models.py`

#### OrderType
- **Values**: `LIMIT`, `MARKET`, `STOP_LIMIT`
- **Source**: Coinbase API order types
- **Usage**: Order placement, order configuration
- **Potential usage locations**:
  - `external/coinbase_client.py` (line 233: hardcoded "LIMIT")
  - Tests that create mock orders

#### TimeInForce
- **Values**: `GOOD_UNTIL_CANCELLED` (alias: `GTC`), `IMMEDIATE_OR_CANCEL` (alias: `IOC`), `FILL_OR_KILL` (alias: `FOK`), `GOOD_UNTIL_DATE_TIME` (alias: `GTD`)
- **Source**: Coinbase API order duration settings
- **Usage**: Limit order configuration
- **Recently updated**: `external/coinbase_client.py` (line 199 default parameter)

#### TriggerStatus
- **Values**: `UNKNOWN_TRIGGER_STATUS`, `INVALID_ORDER_TYPE`, `STOP_PENDING`, `STOP_TRIGGERED`
- **Source**: Coinbase API stop order status
- **Usage**: Stop order monitoring

### 2. Product & Market Attributes

#### ProductType
- **Values**: `SPOT`, `FUTURE`
- **Usage**: Product identification, spot vs futures trading logic
- **Already used in**: `calculation/resolver.py`, `business/order_calculator.py`, `core/models.py`

#### ProductStatus
- **Values**: `OPEN`, `CLOSED`, `POST_ONLY`, `LIMIT_ONLY`
- **Source**: Coinbase API product status
- **Usage**: Product availability checks, order type restrictions

#### ContractExpiryType
- **Values**: `PERPETUAL`, `EXPIRING`, `UNKNOWN_CONTRACT_EXPIRY_TYPE`
- **Source**: Coinbase API futures contract info
- **Usage**: Futures contract classification

#### Direction
- **Values**: `ABOVE`, `BELOW`
- **Usage**: Price threshold and ratio comparisons
- **Recently updated**: `business/stealth_condition_evaluator.py` (lines 51, 232)

### 3. Stealth Order Conditions

#### RevealConditionType
- **Values**: `PRICE_THRESHOLD`, `CUMULATIVE_VOLUME`, `TIME_DELAY`, `SPREAD`, `PRODUCT_RATIO`, `COMPOSITE`
- **Source**: Stealth order reveal mechanism
- **Usage**: Condition type identification and factory function
- **Recently updated**: `business/stealth_condition_evaluator.py` (get_evaluator function)

### 4. WebSocket & Event Types

#### WebSocketEventType
- **Values**: `SNAPSHOT`, `UPDATE`, `PATCH`
- **Source**: Coinbase WebSocket message types
- **Usage**: Message routing, event processing
- **Potential usage locations**:
  - `core/order_engine.py` (websocket event parsing)
  - `external/coinbase_websocket.py` (message type detection)

#### ChannelType
- **Values**: 
  - Public: `TICKER`, `LEVEL2`, `MARKET_TRADES`, `CANDLES`, `HEARTBEATS`, `STATUS`, `TICKER_BATCH`
  - Authenticated: `USER`, `FUTURES_BALANCE_SUMMARY`
- **Source**: Coinbase WebSocket subscription channels
- **Usage**: Channel subscription, message routing

#### RiskManagementType
- **Values**: `MANAGED_BY_FCM`, `MANAGED_BY_VENUE`, `UNKNOWN_RISK_MANAGEMENT_TYPE`
- **Source**: Coinbase API futures risk management
- **Usage**: Futures order risk configuration

### 5. Profit Targets

#### TargetMovementType
- **Values**: `PERCENTAGE` (value: `"P"`), `ABSOLUTE` (value: `"A"`)
- **Usage**: Profit target specification
- **Already used in**: `core/models.py`

## Migration Checklist

### High Priority (In Progress)
- [x] Created comprehensive enums in `core/enums.py`
- [x] Updated `core/__init__.py` to export all enums
- [x] Updated `external/coinbase_client.py` to import and use `TimeInForce`
- [x] Updated `business/stealth_condition_evaluator.py` to use `Direction` and `RevealConditionType`

### Medium Priority (Can be done)
- [ ] Update `external/coinbase_client.py` to use `OrderType` enum (currently hardcoded "LIMIT")
- [ ] Update WebSocket handlers to use `WebSocketEventType`
- [ ] Update order creation in tests to use enums
- [ ] Update UI form defaults to reference enum values

### Low Priority (Nice to have)
- [ ] Add validation methods in models to check enum values
- [ ] Update database queries to use enum `.value` property
- [ ] Add type hints using enums throughout codebase

## Best Practices

### Using Enums in Code

```python
from core import OrderStatus, TimeInForce, RevealConditionType

# Option 1: Use enum directly (recommended for validation)
if order.status == OrderStatus.FILLED:
    process_filled_order()

# Option 2: Use enum value for API calls or database
api_call(status=order.status.value)

# Option 3: Accept string but validate against enum
def place_order(time_in_force: str = TimeInForce.GOOD_UNTIL_CANCELLED.value):
    # time_in_force is a string (for API compatibility)
    pass

# Option 4: Use enum for factory/routing
evaluator = get_evaluator(condition_type)  # expects RevealConditionType.value
```

### Type Hints

```python
from core import OrderStatus, OrderSide

def process_order(
    order_id: str,
    side: OrderSide,
    status: OrderStatus
) -> bool:
    """Process an order with enum type hints."""
    if status == OrderStatus.FILLED:
        return True
    return False
```

### Database & API Integration

```python
# When writing to database (store as string)
INSERT INTO orders (status) VALUES (%s, %s)
params = (order.order_id, order.status.value)

# When reading from database/API (convert to enum)
order_status = OrderStatus(api_response['status'])

# When building query filters
query.where(Order.status.in_([
    OrderStatus.PENDING.value,
    OrderStatus.OPEN.value
]))
```

## References

- **API Reference**: `api_reference/` directory for request/response structures
- **WebSocket Reference**: `websocket_reference/` directory for message formats
- **Source of Truth**: `core/enums.py` for all enum definitions
- **Exports**: `core/__init__.py` for public API

## Common Mistakes to Avoid

1. ❌ Mixing enum and string: `if status == "OPEN" and status == OrderStatus.OPEN`
2. ❌ Forgetting `.value` for API calls: `api_call(status=OrderStatus.OPEN)` → should be `OrderStatus.OPEN.value`
3. ❌ Not importing from right place: `from core.enums import ...` (not `from core import ...` for direct use in type hints only)
4. ❌ Creating magic strings when enum exists: `direction = "below"` → should be `Direction.BELOW.value`

## Contributing

When adding new fixed value sets:

1. Add enum to `core/enums.py` with documentation
2. Export from `core/__init__.py`
3. Update this guide with usage location
4. Update code to use the enum
5. Consider adding validation if used in critical paths
