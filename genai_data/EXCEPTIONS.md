# Exception Handling Guide

This document explains how to use the custom exception hierarchy in `core/exceptions.py`.

## Exception Hierarchy

```
CoinbaseEngineError (base)
├── OrderProcessingError
│   ├── OrderCalculationError
│   ├── OrderCreationError
│   ├── OrderCancellationError
│   └── FollowUpOrderError
├── StealthOrderError
│   ├── StealthOrderNotFoundError
│   ├── RevealConditionEvaluationError
│   ├── RevealPricingError
│   ├── RevealOrderSliceError
│   └── StealthOrderPersistenceError
├── DatabaseError
│   ├── OrderPersistenceError
│   ├── DatabaseConnectionError
│   └── DatabaseTransactionError
├── WebSocketError
│   ├── WebSocketConnectionError
│   ├── WebSocketMessageError
│   └── DuplicateEventError
├── APIError
│   └── CoinbaseAPIError
└── StateManagementError
    ├── ThreadLockTimeoutError
    └── StateInconsistencyError
```

## When to Use Each Exception

### OrderProcessingError

Use for order creation, calculation, and lifecycle operations.

**OrderCalculationError**
```python
from core.exceptions import OrderCalculationError

try:
    target_price = calculator.calculate_follow_up_price(parent_order, side, target_movement)
except ValueError as e:
    raise OrderCalculationError(
        f"Cannot calculate follow-up price: {e}",
        client_order_id=parent_order["client_order_id"],
        side=side,
        target_movement=target_movement
    )
```

**OrderCreationError**
```python
from core.exceptions import OrderCreationError

try:
    order = Order.create(client_order_id, product_id, side, size, price)
    orderbook["order"][client_order_id] = order
except Exception as e:
    raise OrderCreationError(
        f"Failed to create order: {e}",
        client_order_id=client_order_id,
        product_id=product_id
    )
```

**FollowUpOrderError**
```python
from core.exceptions import FollowUpOrderError

try:
    parent = orderbook["order"].get(parent_client_order_id)
    if not parent:
        raise FollowUpOrderError(
            "Parent order not found",
            client_order_id=parent_client_order_id
        )
    
    if "target_movement" not in parent.get("metadata", {}):
        raise FollowUpOrderError(
            "Parent order missing target_movement metadata",
            client_order_id=parent_client_order_id
        )
    
    child = create_follow_up_order(parent, filled_size)
except FollowUpOrderError:
    raise  # Re-raise known error
except Exception as e:
    raise FollowUpOrderError(f"Unexpected error: {e}", client_order_id=parent_client_order_id)
```

### StealthOrderError

Use for hidden order reveal, condition evaluation, and pricing.

**StealthOrderNotFoundError**
```python
from core.exceptions import StealthOrderNotFoundError

def get_stealth_order(stealth_order_id: str) -> dict:
    stealth_order = self.stealth_orders.get(stealth_order_id)
    if not stealth_order:
        raise StealthOrderNotFoundError("stealth_order_id", stealth_order_id)
    return stealth_order
```

**RevealConditionEvaluationError**
```python
from core.exceptions import RevealConditionEvaluationError

try:
    is_met = evaluator.evaluate(market_data, stealth_order["reveal_condition"])
    if not is_met:
        return {"condition_met": False}
except TimeoutError:
    raise RevealConditionEvaluationError(
        "Condition evaluation timed out",
        condition_type=stealth_order["reveal_condition"]["type"],
        stealth_order_id=stealth_order["stealth_order_id"]
    )
except Exception as e:
    raise RevealConditionEvaluationError(
        f"Condition evaluation failed: {e}",
        condition_type=stealth_order["reveal_condition"]["type"],
        stealth_order_id=stealth_order["stealth_order_id"]
    )
```

**RevealPricingError**
```python
from core.exceptions import RevealPricingError

try:
    submitted_price = plan.submitted_limit_price
    if submitted_price <= 0:
        raise RevealPricingError(
            "Submitted price invalid",
            configured_price=plan.configured_limit_price,
            fallback_used=plan.fallback_used,
            stealth_order_id=stealth_order["stealth_order_id"]
        )
except RevealPricingError:
    raise  # Re-raise known error
except Exception as e:
    raise RevealPricingError(
        f"Price resolution failed: {e}",
        configured_price=stealth_order["limit_price"],
        fallback_used=False,
        stealth_order_id=stealth_order["stealth_order_id"]
    )
```

### DatabaseError

Use for persistence and transaction failures.

**OrderPersistenceError**
```python
from core.exceptions import OrderPersistenceError

try:
    success = db.execute_query(
        "INSERT INTO order_parent (client_order_id, product_id, side, size, price) "
        "VALUES (%s, %s, %s, %s, %s)",
        (client_order_id, product_id, side, size, price)
    )
except Exception as e:
    raise OrderPersistenceError(
        f"Failed to insert parent order: {e}",
        operation="insert",
        table="order_parent",
        client_order_id=client_order_id
    )
```

**DatabaseTransactionError**
```python
from core.exceptions import DatabaseTransactionError

try:
    success = db.execute_with_transaction([
        ("UPDATE order_parent SET status = %s ...", ("FILLED",)),
        ("INSERT INTO order_child ...", (...)),
    ])
    if not success:
        raise DatabaseTransactionError(
            "Transaction rolled back due to constraint violation"
        )
except DatabaseTransactionError:
    raise
except Exception as e:
    raise DatabaseTransactionError(
        f"Transaction failed: {e}",
        rollback_reason="unknown"
    )
```

### WebSocketError

Use for connection and message handling.

**WebSocketConnectionError**
```python
from core.exceptions import WebSocketConnectionError

try:
    ws = websocket.create_connection(WS_URI)
except ConnectionRefusedError as e:
    raise WebSocketConnectionError(
        f"Cannot connect to WebSocket: {e}",
        retry_count=0
    )
```

**WebSocketMessageError**
```python
from core.exceptions import WebSocketMessageError

try:
    event = json.loads(raw_message)
    if "type" not in event:
        raise WebSocketMessageError("Missing 'type' field in event", raw_data=raw_message)
except json.JSONDecodeError as e:
    raise WebSocketMessageError(f"JSON parse error: {e}", raw_data=raw_message)
```

**DuplicateEventError**
```python
from core.exceptions import DuplicateEventError

if event_processor.is_duplicate_event(event):
    raise DuplicateEventError(
        "Event already processed",
        event_hash=event_hash,
        window_seconds=60
    )
event_processor.mark_event_seen(event)
```

### StateManagementError

Use for thread-safety and consistency issues.

**ThreadLockTimeoutError**
```python
from core.exceptions import ThreadLockTimeoutError

try:
    acquired = state_lock.acquire(timeout=5.0)
    if not acquired:
        raise ThreadLockTimeoutError(
            "Cannot acquire state lock",
            lock_name="orderbook_lock",
            timeout_seconds=5.0
        )
except ThreadLockTimeoutError:
    raise  # Escalate to caller
finally:
    if acquired:
        state_lock.release()
```

### APIError

Use for Coinbase API failures.

**CoinbaseAPIError**
```python
from core.exceptions import CoinbaseAPIError

try:
    response = REST_CLIENT.post_order(product_id=product_id, side=side, ...)
except Exception as e:
    # Extract error details from response
    status = getattr(e, 'status_code', None)
    error_code = getattr(e, 'error_code', None)
    
    raise CoinbaseAPIError(
        f"Order creation failed: {e}",
        status_code=status,
        api_error_code=error_code
    )
```

## Error Handling Patterns

### 1. Catch Specific Errors, Handle Appropriately

```python
from core.exceptions import RevealConditionEvaluationError, RevealPricingError, StealthOrderError

try:
    plan = stealth_manager.build_reveal_execution_plan(stealth_order, market_data)
    submitted_order = api.submit_order(plan.submitted_limit_price, ...)
except RevealConditionEvaluationError as e:
    # Temporary issue - safe to retry
    logger.warning("Condition evaluation failed, will retry", extra={
        "stealth_order_id": e.stealth_order_id,
        "reason": str(e)
    })
    return  # Will retry on next evaluation cycle
except RevealPricingError as e:
    # Pricing issue - may need manual intervention
    logger.error("Pricing failed during reveal", exc_info=True, extra={
        "fallback_used": e.fallback_used,
        "configured_price": e.configured_price
    })
    if e.fallback_used:
        # Fallback was attempted, probably safe to proceed
        pass
    else:
        # No fallback - reject reveal
        raise
except StealthOrderError as e:
    # Critical stealth error - escalate
    logger.critical("Stealth order error", exc_info=True)
    raise
```

### 2. Add Context When Re-raising

```python
from core.exceptions import OrderCalculationError, FollowUpOrderError

try:
    target_price = calculate_follow_up_price(parent)
except OrderCalculationError as e:
    # Re-raise with additional context
    raise FollowUpOrderError(
        f"Cannot calculate follow-up price: {e.message}",
        client_order_id=parent["client_order_id"]
    ) from e
```

### 3. Log Errors with Structured Context

```python
from core.exceptions import RevealPricingError
from logging_service import get_logger

logger = get_logger("StealthOrderManager")

try:
    plan = build_reveal_execution_plan(stealth_order, market_data)
except RevealPricingError as e:
    logger.error("Reveal pricing failed", extra={
        "stealth_order_id": e.stealth_order_id,
        "configured_price": e.configured_price,
        "fallback_used": e.fallback_used,
        "reason": str(e)
    })
```

### 4. Catch Base Class for Broad Error Categories

```python
from core.exceptions import StealthOrderError, CoinbaseEngineError

# Catch all stealth-related errors
try:
    reveal_stealth_order(stealth_order_id)
except StealthOrderError as e:
    logger.error("Stealth order operation failed", exc_info=True)
    # All stealth errors have .stealth_order_id or similar context

# Catch all engine errors at top level
try:
    main_loop()
except CoinbaseEngineError as e:
    logger.critical("Engine error", exc_info=True)
    shutdown_gracefully()
```

## Refactoring Existing Code

When converting existing error handling, follow this pattern:

### Before (Generic Exception)
```python
try:
    child_order = create_follow_up_stealth_order(
        parent_id, side, size, target_movement=target_mv
    )
except Exception as e:
    logger.error(f"Failed to create follow-up: {e}")
    return None
```

### After (Specific Exception)
```python
from core.exceptions import FollowUpOrderError, OrderCalculationError

try:
    child_order = create_follow_up_stealth_order(
        parent_id, side, size, target_movement=target_mv
    )
except OrderCalculationError as e:
    logger.error("Target movement calculation failed", extra={
        "parent_id": parent_id,
        "reason": str(e)
    })
    return None
except FollowUpOrderError as e:
    logger.error("Cannot create follow-up order", exc_info=True, extra={
        "parent_id": e.client_order_id,
        "reason": str(e)
    })
    raise  # Escalate critical error
```

## Testing Exceptions

```python
import pytest
from core.exceptions import RevealPricingError, StealthOrderNotFoundError

def test_reveal_pricing_error_with_fallback():
    with pytest.raises(RevealPricingError) as exc_info:
        raise RevealPricingError(
            "Price too high",
            configured_price=42000.0,
            fallback_used=True
        )
    
    assert exc_info.value.fallback_used is True
    assert exc_info.value.configured_price == 42000.0

def test_stealth_order_not_found():
    with pytest.raises(StealthOrderNotFoundError) as exc_info:
        raise StealthOrderNotFoundError("client_order_id", "nonexistent-uuid")
    
    assert exc_info.value.lookup_type == "client_order_id"
    assert exc_info.value.lookup_value == "nonexistent-uuid"
```

## Type Hints

Use the provided type aliases for functions that may raise multiple related exceptions:

```python
from core.exceptions import RevealRelatedError, OrderRelatedError

def build_reveal_execution_plan(
    stealth_order: dict,
    market_data: dict
) -> dict:
    """
    Returns RevealExecutionPlan or raises RevealRelatedError.
    
    Raises:
        RevealConditionEvaluationError: If condition evaluation fails
        RevealPricingError: If pricing policy cannot be resolved
        RevealOrderSliceError: If order slice operation fails
    """
    # Implementation here
    pass
```

## Migration Checklist

When refactoring a module to use new exceptions:

- [ ] Import exceptions from `core.exceptions`
- [ ] Identify all `except Exception` blocks
- [ ] Determine the specific error type for each block
- [ ] Replace with specific exception class
- [ ] Add context parameters (client_order_id, stealth_order_id, etc.)
- [ ] Update logging to include exception context
- [ ] Add docstring with `Raises:` section
- [ ] Test exception paths (happy path + error cases)
- [ ] Update related error handling in callers

## Common Mistakes to Avoid

### ❌ Generic Exception Swallowing
```python
# BAD - Catches and silently ignores all errors
try:
    reveal_stealth_order(stealth_order_id)
except Exception:
    pass
```

### ✅ Specific Exception Handling
```python
# GOOD - Handles known errors, escalates unknown
try:
    reveal_stealth_order(stealth_order_id)
except RevealConditionEvaluationError:
    logger.warning("Condition not met yet, will retry")
except StealthOrderError as e:
    logger.error("Critical error", exc_info=True)
    raise
```

### ❌ Missing Context
```python
# BAD - No context for debugging
raise RevealPricingError("Pricing failed")
```

### ✅ Rich Context
```python
# GOOD - Includes all relevant context
raise RevealPricingError(
    f"Cannot resolve price with policy {policy}",
    configured_price=order["limit_price"],
    fallback_used=False,
    stealth_order_id=order["stealth_order_id"]
)
```

### ❌ Re-raising Without Information
```python
# BAD - Loses original exception chain
try:
    calculate_price(...)
except OrderCalculationError:
    raise OrderCalculationError("Calculation failed")
```

### ✅ Preserving Exception Chain
```python
# GOOD - Uses 'from' to preserve chain
try:
    calculate_price(...)
except OrderCalculationError as e:
    raise OrderCalculationError("Calculation failed") from e
```
