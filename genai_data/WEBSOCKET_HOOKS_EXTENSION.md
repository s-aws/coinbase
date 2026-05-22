# WebSocket Hooks Extension Pattern

This document explains how to extend the OrderEngine's websocket message handling using pre/post hooks and normalizers without modifying core engine code.

## Overview

The WebSocketHookRegistry provides a clean extension point for core features:

- **Pre-hooks**: Run BEFORE normalization on RAW Coinbase fields (validation, early detection)
- **Normalizers**: Transform RAW fields into engine-friendly format (field mapping, type coercion)
- **Post-hooks**: Run AFTER normalization on NORMALIZED fields (notifications, workflows)
- **Hook types**: Order status changes (OPEN, FILLED, CANCELLED, etc.) and position snapshots

## Processing Flow

The complete order processing flow:

```
WebSocket Event (Raw Coinbase Fields)
        ↓
PRE-hooks run (see raw fields as-is)
        ↓
Normalizers run (transform to engine format)
        ↓
Engine processing (handle_filled_order, etc.)
        ↓
POST-hooks run (see normalized, consistent data)
        ↓
Dashboard broadcast
```

## Normalizers: Handle Field Variations

Coinbase sends different fields for different order types. Normalizers solve this problem:

**Problem:**
- Spot orders use `limit_price`, futures use different fields
- Some orders have `trigger_status`, others don't
- Position snapshots need computed fields (notional value, leverage exposure)

**Solution:**
Register normalizers to transform raw Coinbase fields into a consistent format:

```python
def normalize_spot_order(order: dict) -> None:
    """Convert spot-specific fields to standard format."""
    if 'limit_price' in order and 'start_price' not in order:
        order['start_price'] = float(order['limit_price'])

def normalize_futures_order(order: dict) -> None:
    """Convert futures-specific fields to standard format."""
    if 'contract_expiry_type' in order:
        order['_is_expiring'] = order['contract_expiry_type'] == 'EXPIRING'

# Register
hooks.register_order_normalizer(normalize_spot_order)
hooks.register_order_normalizer(normalize_futures_order)
```

### Why Normalizers Matter

1. **Early extensions** see raw Coinbase format (PRE-hooks)
2. **Core engine** works with consistent, normalized data
3. **Later extensions** see clean, predictable fields (POST-hooks)
4. **No coupling** between spot/futures/future-product logic

## Quick Start

### 1. Define Your Hook Functions

Create a module with hook handlers. Hooks receive the full websocket event dict:

```python
# my_extension.py
import logging

logger = logging.getLogger(__name__)


def validate_filled_order(order: dict) -> None:
    """Pre-processor: Validate filled orders early."""
    client_order_id = order.get('client_order_id')
    quantity = float(order.get('cumulative_quantity', 0))
    
    if quantity == 0:
        logger.warning(f"Order {client_order_id} filled with zero quantity")


def notify_fill_service(order: dict) -> None:
    """Post-processor: Send filled order to external system."""
    client_order_id = order.get('client_order_id')
    product_id = order.get('product_id')
    quantity = float(order.get('cumulative_quantity', 0))
    price = float(order.get('avg_price', 0))
    
    # Send to external API, database, notification service, etc.
    logger.info(f"Fill completed: {product_id} {quantity} @ {price}")
    # external_api.log_fill(client_order_id, product_id, quantity, price)
```

### 2. Register Hooks

Register your hooks with the engine's hook registry:

```python
# In your startup code (e.g., main.py)
from my_extension import validate_filled_order, notify_fill_service

# Get the engine's hook registry
hooks = engine.websocket_hooks

# Register hooks for FILLED orders
hooks.register_pre_order_status('FILLED', validate_filled_order)
hooks.register_post_order_status('FILLED', notify_fill_service)
```

### 3. That's It!

Your hooks will now run automatically whenever the specified order status is processed.

## Hook Types

### Order Status Hooks

For individual order events (OPEN, FILLED, CANCELLED, etc.):

```python
def my_pre_processor(order: dict) -> None:
    """Runs before order status is processed by engine."""
    client_order_id = order.get('client_order_id')
    status = order.get('status')
    # Do something with the order


def my_post_processor(order: dict) -> None:
    """Runs after order status is processed by engine."""
    # Can access updated orderbook state via engine.orderbook
```

**Supported Statuses:**
- `PENDING` - Order placed, not yet in book
- `OPEN` - Order in book, waiting for fills
- `FILLED` - Order 100% filled
- `CANCELLED` - Order cancelled
- `CANCEL_QUEUED` - Cancellation requested, pending
- `FAILED` - Order could not be placed

### Snapshot Hooks

For position snapshots (futures positions):

```python
def my_pre_snapshot_hook(snapshot: dict) -> None:
    """Runs before snapshot positions are processed."""
    positions = snapshot.get('positions', {})
    # Can inspect position data before it updates orderbook


def my_post_snapshot_hook(snapshot: dict) -> None:
    """Runs after snapshot positions are processed."""
    # Can access updated positions via engine.orderbook.positions
```

## Normalizers: Transform Raw to Normalized

Normalizers run between PRE-hooks and POST-hooks. They transform raw Coinbase fields into a consistent format.

### Order Normalizers

Register normalizers to handle product-type-specific field variations:

```python
def normalize_spot_orders(order: dict) -> None:
    """Transform spot order fields."""
    # Spot orders use 'limit_price', standardize to 'start_price'
    if 'limit_price' in order and 'start_price' not in order:
        order['start_price'] = float(order['limit_price'])
    
    # Ensure consistent field names and types
    if 'order_side' in order:
        order['order_side'] = order['order_side'].upper()

def normalize_futures_orders(order: dict) -> None:
    """Transform futures order fields."""
    if 'contract_expiry_type' in order:
        # Add computed field
        order['_is_expiring'] = order['contract_expiry_type'] == 'EXPIRING'
        order['_is_perpetual'] = order['contract_expiry_type'] == 'PERPETUAL'

# Register both normalizers
hooks.register_order_normalizer(normalize_spot_orders)
hooks.register_order_normalizer(normalize_futures_orders)
```

### Snapshot Normalizers

Enrich position snapshots with computed fields:

```python
def enrich_positions(snapshot: dict) -> None:
    """Add computed fields to position snapshots."""
    perpetual_positions = snapshot.get('positions', {}).get('perpetual_futures_positions', [])
    
    for pos in perpetual_positions:
        # Compute notional value
        net_size = float(pos.get('net_size', 0))
        mark_price = float(pos.get('mark_price', 0))
        pos['_notional_value'] = net_size * mark_price
        
        # Flag losing positions
        unrealized_pnl = float(pos.get('unrealized_pnl', 0))
        pos['_is_losing'] = unrealized_pnl < 0

hooks.register_snapshot_normalizer(enrich_positions)
```

### When to Use Normalizers

**Use normalizers to:**
- Handle product-type-specific field variations
- Coerce string values to proper types
- Add computed fields
- Ensure consistent field names across message types

**PRE-hooks** see raw Coinbase fields  
**Normalizers** transform fields  
**POST-hooks** see consistent, normalized fields

## Common Use Cases

### 1. Real-Time Alerts

```python
def alert_on_large_fill(order: dict) -> None:
    """Alert when a large order fills."""
    quantity = float(order.get('cumulative_quantity', 0))
    MIN_ALERT_SIZE = 10.0
    
    if quantity >= MIN_ALERT_SIZE:
        # Send alert to Slack, Discord, email, etc.
        send_alert(f"Large fill: {quantity} filled")

hooks.register_post_order_status('FILLED', alert_on_large_fill)
```

### 2. Order Completion Workflows

```python
def trigger_pnl_calculation(order: dict) -> None:
    """Calculate PnL after order fills."""
    client_order_id = order.get('client_order_id')
    quantity = float(order.get('cumulative_quantity', 0))
    filled_value = float(order.get('filled_value', 0))
    fees = float(order.get('total_fees', 0))
    
    pnl = filled_value - fees
    # Update PnL tracker, persist to database, etc.

hooks.register_post_order_status('FILLED', trigger_pnl_calculation)
```

### 3. Validation & Rejection

```python
def prevent_undesired_status(order: dict) -> None:
    """Reject certain order statuses."""
    client_order_id = order.get('client_order_id')
    product_id = order.get('product_id')
    
    # Block orders on certain products
    BLOCKED_PRODUCTS = ['DOGE-USD', 'SHIB-USD']
    if product_id in BLOCKED_PRODUCTS:
        logger.error(f"Blocking order on {product_id}")
        # Could trigger manual review, emergency halt, etc.

hooks.register_pre_order_status('OPEN', prevent_undesired_status)
```

### 4. Audit Logging

```python
def audit_log_fill(order: dict) -> None:
    """Log every fill to audit trail."""
    client_order_id = order.get('client_order_id')
    quantity = float(order.get('cumulative_quantity', 0))
    price = float(order.get('avg_price', 0))
    timestamp = order.get('creation_time')
    
    audit_db.log({
        'event': 'order_filled',
        'client_order_id': client_order_id,
        'quantity': quantity,
        'price': price,
        'timestamp': timestamp,
    })

hooks.register_post_order_status('FILLED', audit_log_fill)
```

### 5. Position Reconciliation

```python
def reconcile_positions(snapshot: dict) -> None:
    """Verify positions after snapshot update."""
    positions = snapshot.get('positions', {})
    futures_positions = positions.get('perpetual_futures_positions', [])
    
    for pos in futures_positions:
        product_id = pos.get('product_id')
        net_size = float(pos.get('net_size', 0))
        
        if net_size != 0:
            # Positions exist, do reconciliation
            verify_margin_requirements(product_id, net_size)

hooks.register_post_snapshot(reconcile_positions)
```

## Hook Lifecycle

### Execution Order

For an order fill event:

1. Engine receives websocket message
2. **PRE-HOOK** runs for status
3. Engine processes order (updates orderbook, calls handlers)
4. **POST-HOOK** runs for status

```
WebSocket Event
     ↓
Deduplication (EventBridge)
     ↓
process_user_order()
     ↓
PRE-hook (call_pre_order_status)  ← Can validate, inspect
     ↓
Status dispatch (FILLED → handle_filled_order)
     ↓
POST-hook (call_post_order_status)  ← Can trigger workflows
     ↓
Dashboard broadcast
```

### Error Handling

Hooks should not raise exceptions. If they do, the error is logged but **does not stop execution**:

```python
def safe_hook(order: dict) -> None:
    """Hook with error handling."""
    try:
        client_order_id = order.get('client_order_id')
        # Do something
    except Exception as e:
        # Log the error locally, don't raise
        logger.error(f"Hook failed for order {client_order_id}: {e}")
```

## Advanced Usage

### Multiple Hooks for Same Status

Multiple hooks can register for the same status. They execute in order:

```python
hooks.register_post_order_status('FILLED', hook_a)  # Runs first
hooks.register_post_order_status('FILLED', hook_b)  # Runs second
hooks.register_post_order_status('FILLED', hook_c)  # Runs third
```

### Chaining Normalizers

Multiple normalizers can run in sequence. They modify the order in-place:

```python
# Normalizers run in registration order
hooks.register_order_normalizer(normalize_common_fields)      # All products
hooks.register_order_normalizer(normalize_spot_specific)      # Spot orders
hooks.register_order_normalizer(normalize_futures_specific)   # Futures orders
hooks.register_order_normalizer(add_computed_fields)          # All products

# By the time POST-hooks run, order has all normalizations applied
```

**Key difference from hooks:**
- Normalizers modify order dict in-place (they're "pure" transformations)
- Hooks trigger side effects (notifications, logging, etc.)
- Normalizers ensure consistent field names and types
- POST-hooks work with the normalized fields

### Normalizer Best Practices

1. **Keep normalizers focused** - One product type or concern per normalizer
2. **Use predictable field names** - Avoid creating new variations
3. **Log transformation decisions** - Help with debugging
4. **Test with real Coinbase data** - Field variations can be tricky
5. **Add computed fields** - Use `_prefix` to mark computed/derived values

```python
def best_practices_normalizer(order: dict) -> None:
    """Example following best practices."""
    try:
        # 1. Focused: only handle spot-specific fields
        if 'order_type' in order and order.get('product_type') == 'SPOT':
            # 3. Log decision
            logger.debug(f"Normalizing spot order {order['client_order_id']}")
            
            # 2. Predictable names
            order['order_type'] = order['order_type'].upper()
            
            # 5. Mark computed with _prefix
            order['_is_limit_order'] = order['order_type'] == 'LIMIT'
    except Exception as e:
        # 4. Log errors
        logger.warning(f"Normalization failed: {e}")
```

### Modifying Order Data

Hooks can modify order data in-place (modifying the dict):

```python
def enrich_order(order: dict) -> None:
    """Add custom fields to order for later use."""
    order['_custom_metadata'] = {
        'processed_at': datetime.now(),
        'source': 'websocket',
    }
```

However, note that:
- Modifications don't affect the original trade/fill
- They're useful for tracking metadata or internal state
- Database persistence is handled separately

### Accessing Engine State

Post-processors can access the engine's orderbook and state:

```python
def access_engine_state(order: dict, engine) -> None:
    """Access engine state from hook."""
    # This requires the engine as a closure or parameter
    client_order_id = order.get('client_order_id')
    orderbook = engine.orderbook
    
    # Check if this is a parent order
    if orderbook.parent_order_ids.get(client_order_id):
        # Handle parent-child logic
        pass
```

To use this pattern, create a closure:

```python
def create_state_aware_hook(engine):
    def hook(order: dict) -> None:
        # Can access engine here
        if engine.is_parent_order(order.get('client_order_id')):
            # Do something
            pass
    return hook

hooks.register_post_order_status('FILLED', create_state_aware_hook(engine))
```

### Conditional Hook Registration

Register hooks conditionally based on configuration:

```python
if config.ENABLE_AUDIT_LOGGING:
    hooks.register_post_order_status('FILLED', audit_log_fill)

if config.ENABLE_ALERTS:
    hooks.register_post_order_status('FILLED', alert_on_large_fill)

if config.ENVIRONMENT == 'production':
    hooks.register_pre_order_status('OPEN', security_validation)
```

## Testing

### Unit Testing Hooks

Test hooks in isolation:

```python
def test_alert_on_large_fill():
    """Test large fill detection."""
    from my_extension import alert_on_large_fill
    
    order = {
        'client_order_id': 'test-123',
        'cumulative_quantity': '15.0',
        'product_id': 'BTC-USD',
    }
    
    # Should trigger alert
    alert_on_large_fill(order)
```

### Integration Testing

Test hooks with the engine:

```python
def test_hook_integration(engine):
    """Test hooks integrate with engine."""
    from integration.websocket_hooks import WebSocketHookRegistry
    
    # Create custom registry for test
    test_hooks = WebSocketHookRegistry()
    
    # Register test hook
    called = []
    def test_hook(order):
        called.append(order)
    
    test_hooks.register_post_order_status('FILLED', test_hook)
    
    # Create engine with test hooks
    engine = OrderEngine(
        # ... args ...
        websocket_hooks=test_hooks,
    )
    
    # Trigger order event
    engine.process_user_order({
        'client_order_id': 'test-123',
        'status': 'FILLED',
        # ...
    })
    
    # Verify hook was called
    assert len(called) == 1
```

## Performance Considerations

- Hooks run synchronously in the event processing thread
- Keep hooks fast - avoid blocking I/O
- For slow operations (API calls, database writes), use async tasks:

```python
def async_notification_hook(order: dict) -> None:
    """Offload slow work to thread pool."""
    from concurrent.futures import ThreadPoolExecutor
    
    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(slow_api_call, order)
    # Don't wait for result
```

## Best Practices

1. **Keep hooks focused** - One responsibility per hook
2. **Log errors** - Don't raise exceptions
3. **Use type hints** - Help with IDE support and documentation
4. **Document side effects** - What does this hook do to external systems?
5. **Test in isolation** - Test the hook function separately from the engine
6. **Avoid tight coupling** - Don't import engine internals
7. **Use closures** - Capture configuration or engine reference if needed
8. **Monitor performance** - Hooks run on critical path

## Troubleshooting

### Hook Not Called

Check that:
1. Hook is registered with correct status name (case-sensitive)
2. Order status matches exactly (e.g., `'FILLED'` not `'filled'`)
3. Hook function has correct signature: `(order: dict) -> None`

```python
# ✅ Correct
hooks.register_post_order_status('FILLED', my_hook)

# ❌ Wrong - status name is case-sensitive
hooks.register_post_order_status('filled', my_hook)
```

### Hook Raises Exception

Exceptions in hooks are caught and logged, but don't stop execution:

```
ERROR - Post-processor for status FILLED failed: TypeError: ...
```

Ensure your hook handles errors gracefully.

### Hook Sees Old Data

Pre-hooks run BEFORE processing, so they see the order as it arrived:
- Post-hooks run AFTER processing, so they see the updated orderbook state

```python
# PRE-hook sees order as it was received
# POST-hook can access engine.orderbook for updated state
```

## Summary

The WebSocket hooks system provides:

✅ Clean extension points for core features  
✅ No need to modify OrderEngine code  
✅ Support for pre/post processing workflows  
✅ Error isolation (hooks don't crash engine)  
✅ Easy testing and conditional registration  
✅ Supports alerts, audit logging, workflows, and more  

See [integration/websocket_hooks.py](../integration/websocket_hooks.py) for API reference.
