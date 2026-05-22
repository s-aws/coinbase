# Audit Report: Product Type Detection Bug in Profit Validator

**Date:** 2026-04-26  
**Status:** 🔧 FIXED  
**Severity:** HIGH  
**Impact:** Incorrect profitability calculations for FUTURE/PERPETUAL orders

---

## Executive Summary

During log audit of a FUTURE order (BIP-20DEC30-CDE), the profit validator was incorrectly logging `Product: SPOT` for follow-up orders, even though they were FUTURE orders. This caused incorrect fee calculations, resulting in wrong profitability assessments.

**Root Cause:** The `validate_order_profitability()` method was not being passed `product_type`, `product_id`, `contract_size`, and `position_side` parameters, causing them to default to SPOT product assumptions.

**Fix Applied:** Updated method signatures and call sites to pass all product-related parameters through the profitability validation chain.

---

## Addendum (2026-04-26): Final Architecture and Data Source Guardrail

The initial fix path above solved the immediate symptom but still spread product-context lookups across callers.
Final implementation moved to Option A architecture:

- `ProfitValidator` is the single information expert for profitability context.
- `OrderEngine` and `StealthOrderManager` pass `product_id` and do not perform local `product_type`/`contract_size` resolution.
- Product context is resolved internally by `ProfitValidator` via injected runtime `orderbook`.

### Guardrail: `products.json` Usage

`products.json` must not be used for execution-critical runtime calculations.

- Allowed: baseline metadata, UI payload shaping, static defaults.
- Not allowed: profitability-critical runtime fields (for example live contract sizing used in fee/profit math).
- Required source for runtime trading context: in-memory runtime product registry (`ORDERBOOK.product`) and related runtime services.

### Why This Guardrail Exists

Static metadata can lag or omit exchange-populated values (for example `contract_size`), producing silent but severe PnL and fee errors.
Centralizing lookup logic in `ProfitValidator` prevents caller drift and eliminates patch-on-patch regressions.

---

## Log Analysis

### Observed Behavior

**Original Log Sequence (from 2026-04-25/26):**

```
23:36:14 BUY 20 @ 77,390 (HIDDEN reveal):
  ✅ Profit validator: Product: FUTURE | Contracts: 20.0 | Fee: $12.77
  ✅ Creates SELL 20 follow-up @ 77,540 (target_movement: 0.002)

00:41:59 SELL 20 condition met @ market 77,545:
  ❌ Profit validator: Product: SPOT ← WRONG! Should be FUTURE
  ❌ Fee rate applied as 0.630% (SPOT rate, not FUTURE)
  ❌ Calculated fee: $975.05 (way too high!)
  ✅ Order reveals @ 77,540 (configured price)

00:43:28 SELL 2 partial follow-up:
  ❌ Profit validator: Product: SPOT ← STILL WRONG
  ❌ Calculated fee: $97.69 (excessive for 2 contracts)
  ✅ Order reveals @ 77,690

00:45:00 SELL 20 filled, BUY 18 follow-up created:
  ✅ Profit validator: Product: FUTURE ← CORRECT (for BUY)
  ✅ Creates BUY 18 @ 77,390 (remaining size)
```

### Root Cause Analysis

**Two-Part Bug:**

1. **In `calculation/profit_validator.py` (line 529):**
   - Method `validate_order_profitability()` receives parameters but doesn't pass them to `is_profitable()`
   - Only passes: `filled_price`, `follow_up_price`, `side`, `order_size`, `min_profit_margin`
   - Missing: `product_type`, `product_id`, `position_side`, `contract_size`
   - `is_profitable()` defaults to `product_type='SPOT'` when not specified

2. **In `core/stealth_order_manager.py` (lines 638, 1056):**
   - Calls to `validate_order_profitability()` don't pass product-related parameters
   - Available in the order dict: `product_id`, `product_type` (inferred), `contract_size` (from metadata)
   - Parameters were simply never extracted and passed

### Impact on Fee Calculation

For SELL order on BIP-20DEC30-CDE (FUTURE):
- **What happened (SPOT logic):**
  - Fee rate: 0.630% (standard SPOT rate)
  - Fee on $77,540 × 20 contracts: $975.05 ❌ WRONG
  - No mandatory contract fee applied

- **What should happen (FUTURE logic):**
  - Contract size: 0.01 BTC per contract
  - Effective size: 20 × 0.01 = 0.2 BTC
  - Fee rate: 0.630% on $77,540 × 0.2 = $9.77
  - Mandatory fee: $0.15 × 20 = $3.00
  - Total fees: $12.77 ✅ CORRECT

**Impact:** Profitability assessment would be dramatically wrong, potentially blocking profitable trades or allowing unprofitable ones.

---

## Fix Implementation

### Change 1: Update `profit_validator.py` Signature

**File:** `calculation/profit_validator.py`  
**Lines:** 481-534

```python
# BEFORE
def validate_order_profitability(self,
                                parent_filled_price: float,
                                parent_side: str,
                                follow_up_price: float,
                                order_size: float,
                                min_margin_pct: float = 0.0) -> Dict[str, Any]:
    # ...
    result = self.is_profitable(
        filled_price=parent_filled_price,
        follow_up_price=follow_up_price,
        side=parent_side,
        order_size=order_size,
        min_profit_margin=min_profit
    )

# AFTER
def validate_order_profitability(self,
                                parent_filled_price: float,
                                parent_side: str,
                                follow_up_price: float,
                                order_size: float,
                                min_margin_pct: float = 0.0,
                                product_type: str = 'SPOT',
                                product_id: str = None,
                                position_side: str = None,
                                contract_size: float = None) -> Dict[str, Any]:
    # ...
    result = self.is_profitable(
        filled_price=parent_filled_price,
        follow_up_price=follow_up_price,
        side=parent_side,
        order_size=order_size,
        min_profit_margin=min_profit,
        product_type=product_type,
        product_id=product_id,
        position_side=position_side,
        contract_size=contract_size
    )
```

### Change 2: Update `stealth_order_manager.py` Imports

**File:** `core/stealth_order_manager.py`  
**Lines:** 68-76

Added `normalize_product_type` to imports from configuration:

```python
from configuration import (
    DEFAULT_MAX_ORDER_REPLACEMENT,
    PRODUCT_METADATA,
    get_trading_product_id,
    normalize_product_type,  # ← NEW
    quantize_to_increment,
    safe_float,
)
```

### Change 3: Extract and Pass Product Type (Anchor Repricing)

**File:** `core/stealth_order_manager.py`  
**Lines:** 643-659

```python
# BEFORE
validation = self.profit_validator.validate_order_profitability(
    parent_filled_price=entry_price,
    parent_side=parent_side.value,
    follow_up_price=follow_up_price,
    order_size=order_size,
    min_margin_pct=0.0,
)

# AFTER
# Extract product type and contract size for FUTURE/PERPETUAL products
product_id = order.get("product_id", "")
product_type = normalize_product_type(order, products=PRODUCT_METADATA)
contract_size = None
if product_type in ('FUTURE', 'PERPETUAL'):
    product_metadata = PRODUCT_METADATA.get(product_id, {})
    contract_size = safe_float(product_metadata.get("contract_size"), default=None)

validation = self.profit_validator.validate_order_profitability(
    parent_filled_price=entry_price,
    parent_side=parent_side.value,
    follow_up_price=follow_up_price,
    order_size=order_size,
    min_margin_pct=0.0,
    product_type=product_type,
    product_id=product_id,
    contract_size=contract_size,
)
```

### Change 4: Extract and Pass Product Type (Reveal Validation)

**File:** `core/stealth_order_manager.py`  
**Lines:** 1063-1079

Same pattern applied to `_validate_reveal_profitability()` method.

### Change 5: Regression Test

**File:** `tests/unit/test_product_type_profitability_fix.py` (NEW)

4 new tests verify:
1. ✅ Anchor repricing passes `product_type=FUTURE` for FUTURE orders
2. ✅ Reveal profitability passes `product_type=FUTURE` for FUTURE orders
3. ✅ Both methods pass `product_type=SPOT` for SPOT orders
4. ✅ All product-related parameters propagate through to `is_profitable()`

---

## Testing

### Test Results

All 35 tests pass:
- 22/22 unit tests (stealth_order_manager) ✅
- 9/9 integration tests (anchor_repricing) ✅
- 4/4 new regression tests (product_type fix) ✅

**Test Coverage:**
- FUTURE product with correct product_type extraction
- SPOT product with correct product_type extraction
- Contract size passed for FUTURE/PERPETUAL
- Product ID passed for fee rate lookup
- Backward compatibility with existing tests

---

## Expected Log Changes

After this fix, logs for FUTURE orders will show:

**BEFORE (INCORRECT):**
```
Open/Close side determination | Product: SPOT | Parent side: SELL
Fee rate applied | Effective fee rate: 0.000630 (0.0630%) | ... | Calculated percentage fee: $975.05
```

**AFTER (CORRECT):**
```
Open/Close side determination | Product: FUTURE | Parent side: SELL
Contract size adjustment | Product: FUTURE | Order size (contracts): 20.0 | Contract size: 0.01 | Effective size (units): 0.2
Fee rate applied | Effective fee rate: 0.000630 (0.0630%) | ... | Calculated percentage fee: $9.77
Mandatory fee applied | Product: FUTURE | Contracts: 20.0 | Fee: $3.00
```

---

## Files Modified

1. **calculation/profit_validator.py** - Method signature update (5 new parameters)
2. **core/stealth_order_manager.py** - Import + 2 call sites updated (8 new lines each)
3. **tests/unit/test_product_type_profitability_fix.py** - New regression test file (262 lines)

**Total Lines Changed:** ~30 lines of production code, 262 lines of test code

---

## Deployment Notes

✅ **Safe to Deploy:**
- Backward compatible (new parameters have defaults)
- All existing tests pass
- No database migrations required
- No config changes needed
- Fixes critical bug without side effects

### Verification Steps

After deployment, verify the fix by:

1. Check server logs for FUTURE orders:
   - Confirm `Product: FUTURE` appears (not SPOT)
   - Confirm contract size adjustment logs appear
   - Confirm mandatory fees are calculated

2. Monitor profitability assessments:
   - FUTURE order fees should be much smaller (~$10-20, not ~$900)
   - Follow-up orders should use correct fee calculations

3. Run regression suite:
   ```bash
   pytest tests/unit/test_stealth_order_manager.py
   pytest tests/integration/test_anchor_repricing_integration.py
   pytest tests/unit/test_product_type_profitability_fix.py
   ```

---

## Lessons Learned

1. **Parameter Propagation:** When a validator or helper method is called, ensure all context needed for correct behavior is passed, not just minimal required parameters.

2. **Product Type as Runtime Context:** The product type (SPOT vs FUTURE) is crucial runtime context that affects fee calculation, margin requirements, and position tracking. Never assume SPOT.

3. **Testing Strategy:** Regression tests should specifically test the data flow from multiple call sites to ensure parameters are threaded correctly through the system.

4. **Log Audit Value:** The user's server logs were instrumental in identifying this bug. Always include product type and fee details in operational logs.
