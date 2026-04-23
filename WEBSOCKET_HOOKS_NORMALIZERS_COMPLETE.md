# WebSocket Hooks + Normalizers: Complete Implementation

## What Was Implemented

A comprehensive extension system for websocket message handling that separates concerns:

1. **Normalizers** - Transform raw Coinbase fields → normalized format
2. **PRE-hooks** - Validate/inspect raw fields before normalization  
3. **Engine Processing** - Core order handling with consistent fields
4. **POST-hooks** - Trigger workflows with normalized fields

## Architecture Decision: Order Matters

### Processing Flow

```
Raw Coinbase Message (field variations)
        ↓
PRE-hooks (see raw Coinbase format)
        ↓
Normalizers (handle field variations)
        ↓
Engine Processing (work with normalized data)
        ↓
POST-hooks (see consistent fields)
```

### Why This Order?

1. **PRE-hooks** run BEFORE normalization
   - See raw Coinbase fields as-is
   - Can detect product-specific patterns
   - Can validate before transformation
   - Can trigger early alerts/metrics

2. **Normalizers** transform fields
   - Handle spot vs futures differences
   - Coerce types (string → float)
   - Add computed fields
   - Ensure consistent field names

3. **Engine processing** works with normalized data
   - Assumes fields are present and correctly typed
   - Doesn't need product-specific logic
   - Maintains single code path

4. **POST-hooks** run AFTER normalization
   - See clean, consistent data
   - Can trigger confident workflows
   - Can access updated orderbook state
   - Don't need to handle field variations

## Files Modified

### 1. `integration/websocket_hooks.py` (+200 lines)
- Added `_order_normalizers` and `_snapshot_normalizers` lists
- Added `register_order_normalizer()` - Register order field transformers
- Added `register_snapshot_normalizer()` - Register snapshot transformers
- Added `call_order_normalizers()` - Execute order normalizers with error handling
- Added `call_snapshot_normalizers()` - Execute snapshot normalizers with error handling
- Added `unregister_*_normalizer()` - Remove normalizers
- Updated `clear_all()` to clear normalizers
- Updated `get_hook_count()` to include normalizers

### 2. `core/order_engine.py` (refactored flow)
- Moved PRE-hooks to BEFORE normalization
- Added `call_order_normalizers()` after creating normalized order
- Updated `process_user_snapshot()` to call normalizers
- Improved docstrings with processing flow diagram

### 3. `genai_tools/test_websocket_hooks.py` (+5 new tests)
- `test_order_normalizers()` - Verify order field transformation
- `test_snapshot_normalizers()` - Verify snapshot enrichment
- `test_normalizer_error_handling()` - Error isolation works
- `test_normalizer_unregistration()` - Can remove normalizers
- `test_complete_flow_with_normalizers()` - PRE → Normalize → POST order

**Result: All 13 tests passing** ✅

### 4. `genai_data/WEBSOCKET_HOOKS_EXTENSION.md` (updated guide)
- Added "Processing Flow" diagram
- Added "Normalizers" section with examples
- Added "Chaining Normalizers" guidance
- Added "Normalizer Best Practices"

### 5. `genai_tools/websocket_hook_examples.py` (new examples)
- `SpotOrderNormalizer` - Handle spot-specific fields
- `FuturesOrderNormalizer` - Handle futures-specific fields
- `PositionNormalizer` - Enrich positions with computed fields

## Normalizer Interface

```python
# Register order normalizers (transform individual orders)
hooks.register_order_normalizer(callback: Callable[[dict], None])

# Register snapshot normalizers (enrich position snapshots)
hooks.register_snapshot_normalizer(callback: Callable[[dict], None])

# Normalizers modify dict in-place
def my_normalizer(order: dict) -> None:
    order['start_price'] = float(order['limit_price'])  # Transform
    order['_computed_field'] = value                    # Enrich
```

## Common Normalizer Patterns

### 1. Handle Product-Type Differences

```python
def normalize_by_product_type(order: dict) -> None:
    """Handle different field names per product type."""
    product_type = order.get('product_type', '').upper()
    
    if product_type == 'SPOT':
        # Spot orders use 'limit_price'
        if 'limit_price' in order:
            order['start_price'] = float(order['limit_price'])
    
    elif product_type == 'FUTURE':
        # Futures orders might use different fields
        if 'mark_price' in order:
            order['current_price'] = float(order['mark_price'])
```

### 2. Coerce String Values to Types

```python
def normalize_numeric_types(order: dict) -> None:
    """Ensure numeric fields are float, not string."""
    numeric_fields = [
        'avg_price', 'limit_price', 'stop_price',
        'total_fees', 'filled_value', 'outstanding_hold_amount'
    ]
    
    for field in numeric_fields:
        if field in order and order[field]:
            try:
                order[field] = float(order[field])
            except (ValueError, TypeError):
                logger.warning(f"Could not convert {field} to float")
```

### 3. Add Computed Fields

```python
def add_computed_fields(order: dict) -> None:
    """Add derived/computed fields for post-hooks."""
    # Mark computed fields with _ prefix
    quantity = float(order.get('cumulative_quantity', 0))
    order['_is_partially_filled'] = 0 < quantity < float(order.get('order_quantity', 0))
    
    # Compute fill rate
    order['_fill_percentage'] = float(order.get('completion_percentage', 0))
    
    # Flag by status patterns
    status = order.get('status', '').upper()
    order['_is_terminal'] = status in ['FILLED', 'CANCELLED', 'FAILED']
```

### 4. Enrich Position Snapshots

```python
def enrich_position_snapshot(snapshot: dict) -> None:
    """Add computed fields to positions."""
    perpetual_positions = snapshot.get('positions', {}).get('perpetual_futures_positions', [])
    
    for pos in perpetual_positions:
        # Notional value = position size × mark price
        net_size = float(pos.get('net_size', 0))
        mark_price = float(pos.get('mark_price', 0))
        pos['_notional_value'] = net_size * mark_price
        
        # Leverage exposure = notional × leverage
        leverage = float(pos.get('leverage', 1))
        pos['_leverage_exposure'] = pos['_notional_value'] * leverage
        
        # Risk flag
        unrealized_pnl = float(pos.get('unrealized_pnl', 0))
        pos['_is_losing'] = unrealized_pnl < 0
```

## Usage Example: Complete Extension

```python
from integration.websocket_hooks import get_global_hook_registry

# Get the hook registry
hooks = get_global_hook_registry()

# 1. Register normalizers to handle field variations
def normalize_orders(order):
    """Handle spot/futures field differences."""
    if 'limit_price' in order:
        order['start_price'] = float(order['limit_price'])
    if 'contract_expiry_type' in order:
        order['_is_expiring'] = order['contract_expiry_type'] == 'EXPIRING'

hooks.register_order_normalizer(normalize_orders)

# 2. Register PRE-hooks to validate raw data
def validate_order(order):
    """Validate before processing."""
    if not order.get('client_order_id'):
        logger.error("Missing client_order_id")

hooks.register_pre_order_status('OPEN', validate_order)

# 3. Register POST-hooks to trigger workflows
def notify_on_fill(order):
    """Notify after fill is processed."""
    client_order_id = order.get('client_order_id')
    quantity = float(order.get('cumulative_quantity', 0))
    price = float(order.get('avg_price', 0))
    
    notification_service.send(f"Order {client_order_id} filled: {quantity} @ {price}")

hooks.register_post_order_status('FILLED', notify_on_fill)

# Now all extensions are active!
```

## Testing

Run the comprehensive test suite:

```bash
cd e:\coinbase
pytest genai_tools/test_websocket_hooks.py -v
```

**Results:**
- ✅ 13 tests pass
- ✅ All hook types tested
- ✅ All normalizer patterns tested
- ✅ Error handling verified
- ✅ Complete flow validated

## Key Benefits

✅ **Separation of Concerns**
- Normalizers handle field variations
- PRE-hooks handle validation
- Engine handles core logic
- POST-hooks handle workflows

✅ **No Core Modifications**
- Add extensions without touching OrderEngine
- Future field additions don't break extensions
- Multiple extensions can coexist

✅ **Testable**
- Normalizers testable in isolation
- Hooks testable independently
- Complete flow testable end-to-end

✅ **Extensible**
- Register unlimited normalizers
- Chain normalizers for complex logic
- Conditional registration based on config

✅ **Maintainable**
- Clear extension points
- Consistent interface
- Well-documented patterns
- Error isolation (failing normalizer doesn't crash engine)

## Next Steps

1. **Read** [genai_data/WEBSOCKET_HOOKS_EXTENSION.md](../genai_data/WEBSOCKET_HOOKS_EXTENSION.md)
2. **Copy examples** from [genai_tools/websocket_hook_examples.py](../genai_tools/websocket_hook_examples.py)
3. **Register normalizers** for your product types
4. **Register hooks** for your workflows
5. **Test** with real Coinbase data

## Reference

### Normalizer API

```python
hooks = engine.websocket_hooks

# Register normalizers
hooks.register_order_normalizer(callback: Callable[[dict], None])
hooks.register_snapshot_normalizer(callback: Callable[[dict], None])

# Execute normalizers (called by engine automatically)
hooks.call_order_normalizers(order: dict)
hooks.call_snapshot_normalizers(snapshot: dict)

# Unregister
hooks.unregister_order_normalizer(callback)
hooks.unregister_snapshot_normalizer(callback)
```

### Hook API (unchanged, but timing matters)

```python
# PRE-hooks: Run BEFORE normalization
hooks.register_pre_order_status(status: str, callback)
hooks.call_pre_order_status(status: str, order: dict)

# POST-hooks: Run AFTER normalization and processing
hooks.register_post_order_status(status: str, callback)
hooks.call_post_order_status(status: str, order: dict)

# Snapshot hooks
hooks.register_pre_snapshot(callback)
hooks.register_post_snapshot(callback)
```

## Architecture Diagram

```
┌─────────────────────────────────────┐
│   WebSocket Message (Coinbase)      │
│   - Field variations                │
│   - Type inconsistencies            │
│   - Product-type differences        │
└────────────────┬────────────────────┘
                 ↓
         ┌───────────────┐
         │  PRE-hooks    │
         │ (see raw)     │
         └───────┬───────┘
                 ↓
       ┌─────────────────────┐
       │   Normalizers       │
       │ - Handle variations │
       │ - Add computed      │
       │ - Coerce types      │
       └────────┬────────────┘
                ↓
        ┌──────────────────┐
        │ OrderEngine      │
        │ - Consistent API │
        │ - Single path    │
        └────────┬─────────┘
                 ↓
         ┌───────────────┐
         │ POST-hooks    │
         │ (see normalized)
         └───────┬───────┘
                 ↓
        ┌──────────────────┐
        │  Workflows       │
        │  Notifications   │
        │  Updates         │
        └──────────────────┘
```

---

**Status:** ✅ Complete, tested, production-ready
