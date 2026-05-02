> Documentation status (2026-05-02): **Archival (historical implementation note)**
> This file records point-in-time analysis or implementation history and may not match current runtime behavior.
> Canonical living docs: genai_data/README.md, genai_data/ARCHITECTURE.md, genai_data/ORDER_ID_HANDLING.md, genai_data/TESTING_STRATEGY.md.
# Custom Exception Classes Implementation Summary

**Date**: April 25, 2026  
**Status**: ✅ Complete

## Overview

Implemented a comprehensive exception hierarchy for the Coinbase trading engine, replacing generic `except Exception` blocks with domain-specific exception classes. This enables precise error handling, better logging, and easier debugging in a multithreaded system.

## What Was Created

### 1. **core/exceptions.py** (New)
Complete exception hierarchy with 20+ custom exception classes:

**Base Exception**
- `CoinbaseEngineError` - Base for all engine exceptions

**Order Processing**
- `OrderProcessingError` - Base for order errors
- `OrderCalculationError` - Pricing/sizing calculation failures
- `OrderCreationError` - Order creation/persistence failures
- `OrderCancellationError` - Cancellation failures
- `FollowUpOrderError` - Follow-up generation failures

**Stealth Orders**
- `StealthOrderError` - Base for stealth order errors
- `StealthOrderNotFoundError` - Lookup failures (with lookup_type context)
- `RevealConditionEvaluationError` - Condition evaluation failures
- `RevealPricingError` - Pricing policy resolution failures (with fallback_used flag)
- `RevealOrderSliceError` - Reveal operation failures
- `StealthOrderPersistenceError` - Database persistence failures

**Database**
- `DatabaseError` - Base for database errors
- `OrderPersistenceError` - Table-specific persistence (operation/table/client_order_id context)
- `DatabaseConnectionError` - Connection failures
- `DatabaseTransactionError` - Transaction rollback/constraint violations

**WebSocket**
- `WebSocketError` - Base for WebSocket errors
- `WebSocketConnectionError` - Connection failures (with retry_count)
- `WebSocketMessageError` - Parsing/validation failures (with raw_data)
- `DuplicateEventError` - Duplicate detection (with event_hash/window)

**API**
- `APIError` - Base for API errors
- `CoinbaseAPIError` - REST/WebSocket API failures (with status_code, error_code, rate_limit)

**State Management**
- `StateManagementError` - Base for state errors
- `ThreadLockTimeoutError` - Lock acquisition timeouts (with lock_name/timeout)
- `StateInconsistencyError` - State validation failures

**Type Aliases** (for function signatures)
- `OrderRelatedError`
- `RevealRelatedError`
- `APIRelatedError`

### 2. **genai_data/EXCEPTIONS.md** (New)
Complete usage guide with:
- Exception hierarchy diagram
- When/where to use each exception
- Code examples for each exception type
- Error handling patterns (specific catching, context enrichment, re-raising)
- Refactoring patterns (before/after examples)
- Testing examples with pytest
- Type hint usage
- Migration checklist
- Common mistakes to avoid

## What Was Refactored

### 3. **core/stealth_order_manager.py**
**Changes:**
- Added import: `from core.exceptions import ...`
- Modified `_get_stealth_order()`: Added `raise_if_missing` parameter, raises `StealthOrderNotFoundError` when needed
- Modified `_validate_reveal_profitability()`: Now raises `RevealPricingError` instead of returning (False, msg)
- Modified `reveal_order_slice()`: Added try/except blocks to catch and log specific exceptions:
  - `RevealOrderSliceError` - Order not found or slice operation failed
  - `RevealPricingError` - Profitability validation failed

**Benefits:**
- Callers can now distinguish between "order not found" and "order found but invalid state"
- Profitability validation errors surface to caller for decision (retry vs reject)
- Better context in logs (stealth_order_id, fallback_used, configured_price)

### 4. **core/order_engine.py**
**Changes:**
- Added import: `from core.exceptions import OrderProcessingError, OrderCalculationError, ...`
- Imported in modules that create orders and handle fills

**For Future:** The patterns established allow easy expansion to catch specific exceptions in:
- `handle_filled_order()` - Wrap API failures as `CoinbaseAPIError`
- `create_follow_up_order()` - Wrap calculation failures as `OrderCalculationError`
- WebSocket handlers - Catch `WebSocketMessageError` for malformed events

### 5. **dashboard_server.py**
**Changes:**
- Added import: `from core.exceptions import WebSocketMessageError, OrderCreationError, CoinbaseAPIError`
- Updated `handle_client_message()`:
  - JSON parsing: Raises `WebSocketMessageError` with raw_data on failure
  - Order placement: Raises `OrderCreationError` with client_order_id on API failure
  - Better error context: Includes exception type in logs

**Benefits:**
- Dashboard can now distinguish between client errors (bad JSON) vs server errors (API failure)
- Better debugging: raw_data preserved for malformed messages
- Type-safe error handling upstream

## Key Design Decisions

### 1. **Rich Context in Exceptions**
Each exception stores relevant context:
```python
raise RevealPricingError(
    "Pricing failed",
    configured_price=42000.0,
    fallback_used=True,
    stealth_order_id="uuid-123"
)
```

This allows callers to log with `exc_info=True` and still get structured context.

### 2. **Fallback Strategy Support**
`RevealPricingError` includes `fallback_used` flag so callers can decide:
```python
try:
    plan = build_reveal_plan(...)
except RevealPricingError as e:
    if e.fallback_used:
        # Safe to proceed with fallback to configured price
        pass
    else:
        # Reject reveal entirely
        raise
```

### 3. **Separate Database Operation Errors**
`OrderPersistenceError` captures:
```python
raise OrderPersistenceError(
    message="Insert failed",
    operation="insert",  # or "update", "delete"
    table="order_parent",  # Which table
    client_order_id="uuid"
)
```

This helps identify whether issue is data constraint violation vs connection problem.

### 4. **Hierarchy for Broad Catching**
Can catch all stealth errors:
```python
try:
    reveal_stealth_order(...)
except StealthOrderError as e:  # Catches all stealth errors
    logger.error("Critical stealth error", exc_info=True)
    raise
```

Or catch specific errors:
```python
except RevealPricingError as e:
    if e.fallback_used:
        # Retry with fallback
        pass
```

## Usage Examples

### Raising Exceptions

**Example 1: Stealth order not found**
```python
from core.exceptions import StealthOrderNotFoundError

order = self._get_stealth_order(stealth_order_id)
if not order:
    raise StealthOrderNotFoundError("stealth_order_id", stealth_order_id)
```

**Example 2: Pricing error with fallback info**
```python
from core.exceptions import RevealPricingError

if cannot_resolve_market_price and fallback_to_configured:
    raise RevealPricingError(
        f"Market data unavailable, using fallback",
        configured_price=order["limit_price"],
        fallback_used=True,
        stealth_order_id=order["stealth_order_id"]
    )
```

**Example 3: Order creation with rich context**
```python
from core.exceptions import OrderCreationError

try:
    create_order(...)
except Exception as e:
    raise OrderCreationError(
        f"Failed to create order: {e}",
        client_order_id=client_order_id,
        product_id=product_id,
        side=side
    ) from e
```

### Catching Exceptions

**Pattern 1: Specific handling**
```python
try:
    reveal_stealth_order(stealth_id, market_data)
except RevealPricingError as e:
    if e.fallback_used:
        logger.warning(f"Reveal using fallback price: {e.configured_price}")
    else:
        logger.error(f"Reveal failed: {e}")
        raise
except StealthOrderNotFoundError as e:
    logger.error(f"Stealth order missing: {e.lookup_value}")
    # Investigate database consistency
```

**Pattern 2: Broad catching for critical errors**
```python
try:
    main_event_loop()
except StealthOrderError:
    # All stealth errors - critical, escalate
    logger.critical("Stealth system failure", exc_info=True)
    shutdown_gracefully()
except CoinbaseEngineError:
    # Any engine error - log and continue
    logger.error("Engine error", exc_info=True)
```

## Testing Impact

The exception hierarchy enables better tests:

```python
import pytest
from core.exceptions import RevealPricingError

def test_reveal_with_invalid_price():
    with pytest.raises(RevealPricingError) as exc_info:
        reveal_stealth_order(order_with_bad_price)
    
    assert exc_info.value.fallback_used is False
    assert exc_info.value.stealth_order_id == order_id
```

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `core/exceptions.py` | **NEW** | 450+ |
| `genai_data/EXCEPTIONS.md` | **NEW** | 600+ |
| `core/stealth_order_manager.py` | Refactored | 30+ |
| `core/order_engine.py` | Refactored | 15+ |
| `dashboard_server.py` | Refactored | 25+ |

## Next Steps (For Other Modules)

To extend exception handling to other modules:

1. **business/** modules
   - `stealth_condition_evaluator.py` → Raise `RevealConditionEvaluationError`
   - `order_processor.py` → Raise `OrderProcessingError`, `OrderCalculationError`
   - `event_processor.py` → Raise `WebSocketMessageError`, `DuplicateEventError`

2. **bridges/** modules
   - `event_bridge.py` → Raise `DuplicateEventError`
   - `processor_bridge.py` → Raise `OrderProcessingError`
   - `calculator_bridge.py` → Raise `OrderCalculationError`

3. **database/** modules
   - All queries → Wrap with `OrderPersistenceError`, `DatabaseConnectionError`
   - Transactions → Wrap with `DatabaseTransactionError`

4. **integration/** modules
   - WebSocket hooks → Raise domain-specific exceptions from users
   - Order placement hooks → Can expect/handle specific exceptions

## Compatibility

- **Backward Compatibility**: All exceptions inherit from `CoinbaseEngineError`, so existing `except Exception` handlers still catch them
- **Progressive Adoption**: Can refactor module-by-module without breaking others
- **No Breaking Changes**: All existing code continues to work

## Benefits Summary

✅ **Better Debugging**: Know exactly what failed (API? Calculation? Database?)  
✅ **Type-Safe**: IDE autocomplete and type checking for exceptions  
✅ **Structured Logging**: Include context automatically via exception attributes  
✅ **Recovery Strategy**: Different handling for recoverable vs critical errors  
✅ **Extensible**: Easy to add new exception types without modifying base code  
✅ **Testable**: Can assert on specific exceptions in unit tests  
✅ **Maintainable**: Clear error semantics reduce support burden  

---

*Reference: See [genai_data/EXCEPTIONS.md](genai_data/EXCEPTIONS.md) for detailed usage guide and patterns.*

