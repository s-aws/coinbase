# Opposite-Side Order Validation Feature Design

## Executive Summary

This document designs a feature that **rejects order placement** if a pending order of the **opposite side and same bucket** exists, unless the new order meets **profit validation thresholds**.

**Feature Intent**: Prevent contradictory trades (simultaneous BUY/SELL at same price level) while allowing intentional profit-taking on filled orders.

---

## Problem Statement

### Current Behavior
- User can place BUY @ $100 while SELL @ $100 is pending → Creates conflicting orders
- No validation prevents this contradiction

### Desired Behavior
```
Scenario 1: Rejection (contradictory)
Order A: BUY 10 @ $100 [PENDING/OPEN/HIDDEN/REVEALED/FILLED]
Order B: SELL 1 @ $100
Result: REJECTED - Reason: "Opposite side pending at same price"

Scenario 2: Acceptance (profit-taking)
Order A: BUY @ $100 [FILLED]
Order B: SELL @ $200
Result: ACCEPTED - Reason: "Profit validation passed ($2000 gross profit)"
```

---

## Architecture Overview

### 1. Validation Flow (Entry Point)

```
StealthOrderManager.create_stealth_order()
    ↓
1. Validate basic order parameters
    ↓
2. NEW: Query opposite-side pending orders
    ↓
3. NEW: Run conflict detection
    ├─ If NO opposite-side pending → PROCEED
    ├─ If opposite-side pending:
    │   └─ Run profit validation
    │       ├─ If PROFITABLE → PROCEED + log reason
    │       └─ If NOT PROFITABLE → REJECT + raise exception
    ↓
4. Store order in database
    ↓
5. Return stealth_order_id (or raise rejection exception)
```

### 2. Core Components

#### A. **OppositeSideValidator** (NEW CLASS)
**Location**: `calculation/opposite_side_validator.py`

Encapsulates all logic for detecting opposite-side orders and validating profitability.

```python
class OppositeSideValidator:
    """Prevents contradictory trades via opposite-side validation.

    Validates that new orders don't conflict with pending opposite-side orders
    unless the new order is provably profitable.
    """

    def __init__(self, order_repo, profit_validator):
        """
        Args:
            order_repo: OrderRepository for querying pending orders
            profit_validator: ProfitValidator for profitability checks
        """

    def validate_opposite_side_constraints(
        self,
        new_order: dict,
        orderbook: dict,
        market_data: Optional[dict] = None
    ) -> Tuple[bool, str]:
        """
        Validate order against opposite-side pending orders.

        Args:
            new_order: {
                'product_id': 'BTC-USDC',
                'side': 'SELL',              # BUY or SELL
                'limit_price': 100.0,
                'size': 1.0,
                'parent_client_order_id': Optional[str],  # For follow-ups
            }
            orderbook: OrderBook.orderbook dict
            market_data: Optional market context (ticker, etc.)

        Returns:
            (is_valid: bool, reason: str)
            - is_valid=True: Order passes validation
            - is_valid=False: Validation failed, reason explains why

        Examples:
            >>> # Case 1: No conflict
            >>> is_valid, reason = validator.validate_opposite_side_constraints({
            ...     'product_id': 'BTC-USDC',
            ...     'side': 'SELL',
            ...     'limit_price': 100.0,
            ...     'size': 1.0
            ... }, orderbook)
            >>> is_valid
            True
            >>> reason
            "No opposite-side pending orders"

            >>> # Case 2: Conflict but profitable
            >>> is_valid, reason = validator.validate_opposite_side_constraints({
            ...     'product_id': 'BTC-USDC',
            ...     'side': 'SELL',
            ...     'limit_price': 150.0,
            ...     'size': 1.0,
            ...     'parent_client_order_id': 'buy-order-uuid'
            ... }, orderbook)
            >>> is_valid
            True
            >>> reason
            "Opposite BUY found but profit validation passed ($50 gain)"

            >>> # Case 3: Conflict and not profitable
            >>> is_valid, reason = validator.validate_opposite_side_constraints({
            ...     'product_id': 'BTC-USDC',
            ...     'side': 'SELL',
            ...     'limit_price': 100.0,
            ...     'size': 1.0
            ... }, orderbook)
            >>> is_valid
            False
            >>> reason
            "Opposite BUY pending @ $100, sell @ $100 not profitable (0% margin)"
    """

    def find_opposite_side_pending_orders(
        self,
        product_id: str,
        side: str,
        price_bucket: Optional[float] = None,
        price_tolerance: float = 0.01  # Within 1% of price
    ) -> List[dict]:
        """Find opposite-side pending orders in same price bucket.

        Args:
            product_id: e.g., 'BTC-USDC'
            side: 'BUY' or 'SELL' (we look for opposite)
            price_bucket: Target price; if None, skip price check
            price_tolerance: Percentage tolerance for price matching

        Returns:
            List of pending opposite-side orders in price bucket

        Status states considered "pending":
            - PENDING (awaiting API confirmation)
            - OPEN (confirmed but not filled)
            - HIDDEN (stealth order not yet revealed)
            - REVEALED (stealth order revealed but not filled)
        """

    def is_profitable_follow_up(
        self,
        parent_order: dict,
        new_order: dict,
        min_profit_threshold: float = 0.002  # 0.2% minimum
    ) -> Tuple[bool, str]:
        """Check if new order is profitable as follow-up to parent.

        Args:
            parent_order: The existing opposite-side order
            new_order: The new order being validated
            min_profit_threshold: Minimum % profit required

        Returns:
            (is_profitable: bool, reason: str)

        Logic:
        - If parent is BUY @ $100 and new is SELL @ $150:
            profit = $150 - $100 = $50
            profit% = $50 / $100 = 50%
            if profit% >= min_profit_threshold → PROFITABLE

        - If parent is SELL @ $100 and new is BUY @ $80:
            profit = $100 - $80 = $20
            profit% = $20 / $100 = 20%
            if profit% >= min_profit_threshold → PROFITABLE
        """
```

#### B. **Integration Point: StealthOrderManager**
**Location**: `core/stealth_order_manager.py` (MODIFY)

Add validation before persisting order:

```python
class StealthOrderManager:
    def __init__(self, ..., opposite_side_validator=None):
        self.opposite_side_validator = opposite_side_validator or OppositeSideValidator(...)

    def create_stealth_order(
        self,
        product_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        ...,
        parent_client_order_id: Optional[str] = None,
        enforce_opposite_side_validation: bool = True,
    ) -> str:
        """Create a stealth order with opposite-side validation.

        Args:
            enforce_opposite_side_validation: If True, validate against opposite-side orders.
                                              Can be disabled for special cases.

        Returns:
            stealth_order_id (client_order_id)

        Raises:
            OppositeSideValidationError: If validation fails
        """

        # NEW: Run opposite-side validation (if enabled)
        if enforce_opposite_side_validation:
            is_valid, reason = self.opposite_side_validator.validate_opposite_side_constraints(
                new_order={
                    'product_id': product_id,
                    'side': side,
                    'limit_price': limit_price,
                    'size': total_size,
                    'parent_client_order_id': parent_client_order_id,
                },
                orderbook=self.orderbook,  # Access from engine/state
            )

            if not is_valid:
                self.logger.error(f"Order rejected: {reason}")
                raise OppositeSideValidationError(reason)
            else:
                self.logger.info(f"Order passed validation: {reason}")

        # EXISTING: Continue with order creation...
        # (persist to database, cache in memory, return stealth_order_id)
```

#### C. **Exception Class**
**Location**: `core/models.py` or `core/exceptions.py` (NEW)

```python
class OppositeSideValidationError(ValueError):
    """Raised when opposite-side order validation fails.

    Attributes:
        validation_reason: Human-readable rejection reason
        conflicting_order_id: client_order_id of conflicting order (if known)
        suggestion: Optional suggestion for user (e.g., "Use a profit target of 0.5%")
    """

    def __init__(
        self,
        validation_reason: str,
        conflicting_order_id: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        self.validation_reason = validation_reason
        self.conflicting_order_id = conflicting_order_id
        self.suggestion = suggestion
        super().__init__(validation_reason)
```

---

## Data Model Considerations

### 1. Query Requirements
The validator needs **efficient queries** for:

```python
# Query 1: Get all pending opposite-side orders for a product
def get_pending_orders_by_product(
    product_id: str,
    exclude_sides: Optional[List[str]] = None,  # Exclude specific sides
) -> List[dict]:
    """Get PENDING/OPEN/HIDDEN/REVEALED orders for product."""

# Query 2: Get pending orders by product AND side
def get_pending_orders_by_product_and_side(
    product_id: str,
    side: str,  # 'BUY' or 'SELL'
) -> List[dict]:
    """Get pending orders matching product and side."""

# Query 3: Get all pending orders in price bucket (optional optimization)
def get_pending_orders_by_price_bucket(
    product_id: str,
    side: str,
    price: float,
    tolerance_pct: float = 0.01,  # Within 1%
) -> List[dict]:
    """Get pending orders within price tolerance."""
```

### 2. Existing Database Support
The database **already tracks order status** via `order_parent` and `order_child` tables:

```sql
-- Existing schema supports querying:
SELECT * FROM order_parent
WHERE product_id = 'BTC-USDC'
  AND order_side = 'BUY'           -- Opposite of new SELL
  AND order_status IN ('PENDING', 'OPEN', 'HIDDEN', 'REVEALED')
  AND ABS(limit_price - 100.0) / 100.0 <= 0.01;  -- Within 1%
```

**No new database schema needed** — reuse existing columns.

---

## Validation Rules

### Rule 1: Detect Opposite-Side Pending Orders
```
new_order.side = 'SELL' @ $100
Query: SELECT * FROM order_parent
       WHERE product_id = 'BTC-USDC'
       AND order_side = 'BUY'                    # Opposite
       AND order_status IN (...pending states...)
       AND ABS(price - $100) / $100 <= 0.01     # Within bucket

Result: If found → Proceed to Rule 2
```

### Rule 2: Profit Validation (If Opposite Found)
```
IF opposite-side pending order found:

    CASE 1: New order is follow-up of opposite
    ├─ parent_client_order_id = opposite.client_order_id
    └─ This IS the intentional profit-take
        → ACCEPT with reason "Follow-up profit-take order"

    CASE 2: New order is NOT follow-up of opposite
    ├─ Check: is_new_profitable_vs_opposite(new_order, opposite_order)
    │
    ├─ IF profitable >= MIN_PROFIT_THRESHOLD (0.2%)
    │   → ACCEPT with reason "Profit validation passed: ${gross_profit}"
    │
    └─ IF NOT profitable
        → REJECT with reason "Contradictory trade: no profit margin"
```

### Rule 3: Profit Threshold
```
Minimum profit margin = 0.2% (configurable)

For BUY @ $100, SELL @ $X:
    profit_pct = (X - 100) / 100
    if profit_pct >= 0.002 → PROFITABLE
    else → REJECTED

For SELL @ $100, BUY @ $X:
    profit_pct = (100 - X) / 100
    if profit_pct >= 0.002 → PROFITABLE
    else → REJECTED
```

---

## Implementation Plan

### Phase 1: Core Classes (2-3 hours)
**Files to create:**
1. `calculation/opposite_side_validator.py` - Main validator
2. `core/exceptions.py` or extend `core/models.py` - Exception class

**Files to modify:**
1. `core/stealth_order_manager.py` - Wire validation
2. `core/models.py` - Add exception if needed

**Key methods:**
- `OppositeSideValidator.__init__()`
- `OppositeSideValidator.validate_opposite_side_constraints()`
- `OppositeSideValidator.find_opposite_side_pending_orders()`
- `OppositeSideValidator.is_profitable_follow_up()`
- `StealthOrderManager.create_stealth_order()` - Add validation call

### Phase 2: Database Queries (1-2 hours)
**Location**: `database/order.py`

Add helper functions:
- `get_pending_orders_by_product_and_side(product_id, side)`
- `get_pending_orders_by_price_bucket(product_id, side, price, tolerance)`

Use existing orderbook and database; no schema changes.

### Phase 3: Integration (1 hour)
**Locations:**
- `bridges/stealth_order_bridge.py` - Wire in bridge initialization
- `main.py` - Initialize validator with dependencies
- Dashboard error handling (show rejection reason to user)

### Phase 4: Testing (2-3 hours)
**Test files to create:**
- `tests/unit/calculation/test_opposite_side_validator.py`
- `tests/integration/test_opposite_side_validation_flow.py`

**Test scenarios:**
1. No opposite-side orders → Accept
2. Opposite-side pending, not profitable → Reject
3. Opposite-side pending, profitable → Accept
4. Follow-up order (explicitly linked) → Accept
5. Multiple opposite orders → Find highest priority
6. Different price buckets → Don't conflict

---

## Configuration

### Constants
**Location**: `core/constants.py` or `configuration.py`

```python
# Opposite-side validation thresholds
OPPOSITE_SIDE_MIN_PROFIT_THRESHOLD = 0.002  # 0.2% minimum
OPPOSITE_SIDE_PRICE_TOLERANCE_PCT = 0.01   # Within 1%

# Can be disabled per-order
ENFORCE_OPPOSITE_SIDE_VALIDATION = True  # Feature flag
```

### Feature Flag
```python
# In main.py or configuration
if ENFORCE_OPPOSITE_SIDE_VALIDATION:
    opposite_side_validator = OppositeSideValidator(order_repo, profit_validator)
else:
    opposite_side_validator = None  # Disabled
```

---

## Error Handling

### User-Facing Error Messages
```
❌ Order Rejected: Opposite side pending @ $100
   Reason: Sell @ $100 not profitable (0% margin)
   Suggestion: Try Sell @ $100.25 (0.25% profit) or higher

✅ Order Accepted: Profit validation passed
   Opposite BUY @ $100 found
   New SELL @ $150 → $50 gross profit (50% margin)

❌ Order Rejected: Contradictory trade
   BUY @ $100 pending, you tried BUY @ $99.50
   Reason: Same side, not follow-up

✅ Order Accepted: Follow-up profit-take
   Follow-up of BUY @ $100 → SELL @ $150
   Linked via parent_client_order_id
```

### Logging
```python
# Info level (normal operation)
logger.info("Order passed opposite-side validation", extra={
    'new_order_side': 'SELL',
    'new_order_price': 150.0,
    'opposite_side_found': True,
    'conflicting_order_id': 'buy-uuid',
    'profitability_pct': 50.0,
    'validation_result': 'ACCEPTED'
})

# Error level (rejection)
logger.error("Order failed opposite-side validation", extra={
    'new_order_side': 'SELL',
    'new_order_price': 100.0,
    'opposite_side_found': True,
    'conflicting_order_id': 'buy-uuid',
    'profitability_pct': 0.0,
    'validation_result': 'REJECTED',
    'reason': 'No profit margin'
})
```

---

## Examples

### Example 1: Contradictory Trade (Rejected)
```python
# User has pending order
pending_buy = {
    'client_order_id': 'order-1',
    'product_id': 'BTC-USDC',
    'side': 'BUY',
    'limit_price': 100.0,
    'status': 'PENDING'
}

# User tries to place opposite-side at same price
new_sell = {
    'product_id': 'BTC-USDC',
    'side': 'SELL',
    'limit_price': 100.0,
    'size': 1.0
}

# Validation runs
validator = OppositeSideValidator(order_repo, profit_validator)
is_valid, reason = validator.validate_opposite_side_constraints(new_sell, orderbook)

# Result: is_valid=False
# reason="Opposite BUY pending @ $100.00, SELL @ $100.00 not profitable (0% margin)"

# Exception raised:
raise OppositeSideValidationError(
    validation_reason=reason,
    conflicting_order_id='order-1',
    suggestion="Try SELL @ $100.20 or higher (0.2% profit minimum)"
)
```

### Example 2: Profitable Follow-Up (Accepted)
```python
# User has FILLED order
filled_buy = {
    'client_order_id': 'order-1',
    'product_id': 'BTC-USDC',
    'side': 'BUY',
    'avg_price': 100.0,
    'status': 'FILLED'
}

# User creates follow-up SELL at profit
new_sell = {
    'product_id': 'BTC-USDC',
    'side': 'SELL',
    'limit_price': 150.0,
    'size': 1.0,
    'parent_client_order_id': 'order-1'  # Explicitly linked
}

# Validation runs
is_valid, reason = validator.validate_opposite_side_constraints(
    new_sell,
    orderbook,
    parent_client_order_id='order-1'
)

# Result: is_valid=True
# reason="Follow-up profit-take: BUY @ $100 → SELL @ $150 ($50 gross profit, 50% margin)"

# Order accepted and created
```

### Example 3: Profitable But Unlinked (Accepted)
```python
# User has PENDING order (not yet filled)
pending_buy = {
    'client_order_id': 'order-1',
    'product_id': 'BTC-USDC',
    'side': 'BUY',
    'limit_price': 100.0,
    'status': 'PENDING'
}

# User tries SELL at good profit (no explicit link)
new_sell = {
    'product_id': 'BTC-USDC',
    'side': 'SELL',
    'limit_price': 150.0,
    'size': 1.0
    # parent_client_order_id NOT set
}

# Validation checks profitability
is_valid, reason = validator.validate_opposite_side_constraints(new_sell, orderbook)

# Result: is_valid=True
# reason="Opposite BUY found @ $100, SELL @ $150 is profitable ($50 gain, 50% margin)"

# Order accepted (trading strategy, not contradictory)
```

---

## Testing Strategy

### Unit Tests
**File**: `tests/unit/calculation/test_opposite_side_validator.py`

```python
def test_no_opposite_orders_pending():
    """No conflict → Accept"""

def test_opposite_pending_not_profitable():
    """Conflict + not profitable → Reject"""

def test_opposite_pending_profitable():
    """Conflict + profitable → Accept"""

def test_explicit_follow_up():
    """parent_client_order_id set → Accept (always)"""

def test_price_bucket_matching():
    """Orders within tolerance match"""

def test_price_bucket_tolerance():
    """Orders outside tolerance don't match"""

def test_same_side_no_conflict():
    """Same side (both BUY) → No conflict"""

def test_multiple_opposite_orders():
    """Multiple opposites → Find highest margin"""
```

### Integration Tests
**File**: `tests/integration/test_opposite_side_validation_flow.py`

```python
def test_create_stealth_order_with_validation():
    """End-to-end: create order, validation runs, accepted/rejected"""

def test_dashboard_shows_rejection_reason():
    """Dashboard displays rejection reason to user"""

def test_rejection_rollback():
    """Rejected order not stored in database"""

def test_validation_with_market_data():
    """Validator uses current market data for profitability checks"""
```

### Regression Tests
Ensure existing functionality unaffected:
- `tests/regression/test_order_creation.py`
- `tests/regression/test_stealth_order_lifecycle.py`

---

## Migration Strategy

### Backwards Compatibility
```python
# Default: Enable validation (safe)
enforce_opposite_side_validation: bool = True

# Can be disabled per-order if needed:
manager.create_stealth_order(
    ...,
    enforce_opposite_side_validation=False  # For special cases
)

# Can be disabled globally in config:
ENFORCE_OPPOSITE_SIDE_VALIDATION = False
```

### Rollout
1. **Phase 1**: Feature disabled by default in config
2. **Phase 2**: Enable for new orders only
3. **Phase 3**: Enable globally (in main)
4. **Phase 4**: Make mandatory (remove flag)

---

## Performance Considerations

### Query Optimization
```python
# Current: O(n) scan of all orders
# Optimize: Add index on (product_id, order_side, order_status)

CREATE INDEX idx_pending_orders
ON order_parent(product_id, order_side, order_status)
WHERE order_status IN ('PENDING', 'OPEN', 'HIDDEN', 'REVEALED');
```

### Caching
```python
# Cache pending orders per product (60-second TTL)
_pending_orders_cache = {
    'BTC-USDC': {
        'BUY': [...orders...],
        'SELL': [...orders...],
        'cached_at': <timestamp>
    }
}

# On order creation/cancellation: invalidate cache for product
```

### Async Validation (Optional)
For high-frequency trading:
```python
# Run validation in background, allow order pending validation
is_valid = await validator.validate_async(new_order)
if not is_valid:
    cancel_order_async(order_id)
```

---

## Summary: Key Design Principles

1. **DRY**: Reuses existing ProfitValidator and database queries
2. **Single Responsibility**: OppositeSideValidator only does conflict detection
3. **Integration Point**: Hooks into StealthOrderManager.create_stealth_order()
4. **Exception-Based**: Uses clear exception for rejection (not bool return)
5. **User-Facing**: Error messages explain conflict and suggest resolution
6. **Testable**: Pure functions, mockable dependencies, no hidden state
7. **Backwards Compatible**: Can be disabled, doesn't affect existing orders
8. **Extensible**: Profit threshold configurable, logic easy to enhance

---

## Next Steps

1. **Review this design** with your team
2. **Clarify requirements**:
   - Min profit threshold (currently 0.2%)?
   - Price tolerance (currently 1%)?
   - Include HIDDEN/REVEALED orders in validation?
   - Apply to dashboard order creation too?
3. **Implement Phase 1** (core classes)
4. **Create integration tests** to validate flow
5. **Deploy with feature flag disabled**
6. **Gradual rollout** (test with power users first)
