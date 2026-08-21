# Magic Strings to Enums: Comprehensive Analysis

**Date:** April 21, 2026
**Scope:** Full codebase audit for string literals that should use enums
**Priority:** High - Type safety, IDE autocomplete, maintainability improvements

---

## Executive Summary

Found **8 major categories** of magic strings that should use enums, with **50+ occurrences** across the codebase. Most impactful areas:

1. **Stealth Order Status** (CRITICAL) - No enum exists, status strings scattered across 5+ files
2. **Direction Comparisons** (SPOT/FUTURE ProductType strings) - Used in calculation/resolver.py
3. **Reveal Condition Types** - Enum exists but strings used in order.py
4. **Follow-up Reveal Direction** - Enum exists but strings used in order_engine.py
5. **Order Status/Type strings** - Enums exist but not consistently used in tests/configs

---

## 1. STEALTH ORDER STATUS STRINGS (CRITICAL - NO ENUM EXISTS)

**Status:** ⚠️ NEEDS NEW ENUM - No `StealthOrderStatus` enum in core/enums.py

### Recommended Enum:
```python
class StealthOrderStatus(str, Enum):
    """Status of a stealth order throughout its lifecycle."""
    HIDDEN = "HIDDEN"           # Order created, not yet revealed
    PENDING = "PENDING"         # Condition being monitored
    TRIGGERED = "TRIGGERED"     # Condition met, pending confirmation
    REVEALED = "REVEALED"       # Order partially or fully revealed
    EXECUTED = "EXECUTED"       # Order fully executed
    CANCELLED = "CANCELLED"     # Order cancelled without execution
```

### String Usages by File:

#### [core/stealth_order_manager.py](core/stealth_order_manager.py)

| Line | Current String | Context | Replacement |
|------|---|---|---|
| 172 | `"HIDDEN"` | order["status"] = "HIDDEN" in create_stealth_order() | `StealthOrderStatus.HIDDEN.value` |
| 209 | `"pending"` | status="pending" parameter in insert_order_parent call | `StealthOrderStatus.PENDING.value` |
| 241 | `"TRIGGERED"` | order["status"] = "TRIGGERED" in evaluate_conditions() | `StealthOrderStatus.TRIGGERED.value` |
| 247 | `"PENDING"` | order["status"] = "PENDING" in evaluate_conditions() | `StealthOrderStatus.PENDING.value` |
| 266 | `"EXECUTED"` | if order["status"] in ["EXECUTED", "CANCELLED"]: | Use enum in collection comparison |
| 363 | `"REVEALED"` | order["status"] = "REVEALED" in reveal_order_slice() | `StealthOrderStatus.REVEALED.value` |
| 377 | `"EXECUTED"` | def update_execution(..., order_status: str = "EXECUTED") | `StealthOrderStatus.EXECUTED.value` |
| 409 | `"CANCELLED"` | if order["status"] == "CANCELLED": | `StealthOrderStatus.CANCELLED.value` |
| 412 | `"CANCELLED"` | order["status"] = "CANCELLED" in cancel_stealth_order() | `StealthOrderStatus.CANCELLED.value` |
| 515 | `["HIDDEN", "PENDING", "TRIGGERED", "REVEALED"]` | active_statuses list in _get_active_stealth_orders() | Use enum values collection |

#### [order.py](order.py)

| Line | Current String | Context | Replacement |
|------|---|---|---|
| 309 | `"HIDDEN"` | "status": "HIDDEN" in response dict | `StealthOrderStatus.HIDDEN.value` |

#### [dashboard_server.py](dashboard_server.py)

| Line | Current String | Context | Replacement |
|------|---|---|---|
| 374 | `"CANCELLED"` | engine_state["stealth_orders"][id]["status"] = "CANCELLED" | `StealthOrderStatus.CANCELLED.value` |

#### [Tests (NOT CRITICAL but for consistency)](tests/)

| File | Line | Current String | Impact |
|------|---|---|---|
| conftest.py | 79 | `"HIDDEN"` | Test fixture data |
| conftest.py | 103 | `"REVEALED"` | Test fixture data |
| conftest.py | 248 | `"HIDDEN"` | Factory function |
| test_core_functionality.py | 21 | `"HIDDEN"` | Assertion |
| test_core_functionality.py | 61 | `"REVEALED"` | Assertion |
| test_trading_workflows.py | 36, 41, 48, 54, 71, 72 | Multiple status strings | Test data |

---

## 2. PRODUCT TYPE STRINGS (SPOT/FUTURE)

**Status:** ⚠️ Enum exists (`ProductType`) but **strings used instead of enum values**

### File: [calculation/resolver.py](calculation/resolver.py)

| Line | Current Code | Recommended Change |
|------|---|---|
| 31 | `if product_type in {"SPOT", "FUTURE"}:` | `if product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:` |
| 40 | `if configured_product_type in {"SPOT", "FUTURE"}:` | `if configured_product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:` |
| 44 | `return "FUTURE"` | `return ProductType.FUTURE.value` |
| 45 | `return "SPOT"` | `return ProductType.SPOT.value` |

### File: [core/order_engine.py](core/order_engine.py)

| Line | Current Code | Recommended Change |
|------|---|---|
| 1667 | `if product_type in {"SPOT", "FUTURE"}:` | `if product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:` |
| 1674 | `if configured_product_type in {"SPOT", "FUTURE"}:` | `if configured_product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:` |

### File: [dashboard_server.py](dashboard_server.py)

| Line | Current Code | Context | Recommendation |
|------|---|---|---|
| 87, 672 | `"spot"` (dict key) | products_data.get("spot", []) | Keep as-is (dict key, not type enum) |
| 680 | `"spot": []` (dict initialization) | products_data["spot"] = [] | Keep as-is (dict key) |

---

## 3. DIRECTION STRINGS (ABOVE/BELOW)

**Status:** ✅ Enum exists (`Direction`) but **strings used in code**

### File: [core/order_engine.py](core/order_engine.py)

| Line | Current Code | Recommended Change |
|------|---|---|
| 1701 | `follow_up_reveal_condition["direction"] = "above" if ... else "below"` | Use `Direction.ABOVE.value` / `Direction.BELOW.value` |

### File: [business/stealth_condition_evaluator.py](business/stealth_condition_evaluator.py)

| Line | Current Code | Context | Recommendation |
|------|---|---|---|
| 47 | `"direction": "below"` | Comment: "below" or "above" | Use `Direction.BELOW.value` |
| 226 | `"direction": "below"` | Comment: Trigger when ratio falls | Use `Direction.BELOW.value` |

### File: [Tests](tests/)

| File | Line | Current String | Impact |
|------|---|---|---|
| test_condition_evaluators.py | 18, 28 | `"below"` | Test condition setup |
| test_condition_evaluators.py | 38 | `"above"` | Test condition setup |
| test_condition_evaluators.py | 248 | `"below"` | Test comparison |
| test_models.py | 28 | `"below"` | Test fixture |
| test_trading_workflows.py | 23, 103 | `"below"` | Test workflow |

---

## 4. REVEAL CONDITION TYPE STRINGS

**Status:** ⚠️ Enum exists (`RevealConditionType`) but strings used in order.py

### File: [order.py](order.py)

| Line | Current Code | Context | Recommended Change |
|------|---|---|---|
| 109 | `"type": "time_delay"` | Example in docstring | `"type": RevealConditionType.TIME_DELAY.value` |
| 260 | `"type": "time_delay"` | Default reveal condition | `"type": RevealConditionType.TIME_DELAY.value` |

### File: [core/stealth_order_manager.py](core/stealth_order_manager.py)

| Line | Current Code | Context | Notes |
|------|---|---|---|
| Docstring examples | `"type": "price"` | Example reveal conditions | Use `RevealConditionType.PRICE_THRESHOLD.value` |
| Docstring examples | `"type": "composite"` | Example in docstring | Use `RevealConditionType.COMPOSITE.value` |

### File: [Tests](tests/)

| File | Line | Current Usage | Notes |
|------|---|---|---|
| conftest.py | 83 | `"direction": "below"` | In reveal condition dict |
| test_trading_workflows.py | 23 | `"direction": "below"` | In reveal condition |

---

## 5. FOLLOW-UP REVEAL DIRECTION (SAME/OPPOSITE)

**Status:** ✅ Enum exists (`FollowUpRevealDirection`) but **strings used in code**

### File: [core/order_engine.py](core/order_engine.py)

| Line | Current Code | Context | Recommended Change |
|------|---|---|---|
| 1405 | `follow_up_reveal_direction="same"` | In stealth follow-up creation | `FollowUpRevealDirection.SAME.value` |

### File: [core/stealth_order_manager.py](core/stealth_order_manager.py)

| Line | Current Code | Context | Recommendation |
|------|---|---|---|
| 144 | `follow_up_reveal_direction="opposite"` | Example in docstring | `FollowUpRevealDirection.OPPOSITE.value` |
| 180 | `follow_up_reveal_direction or FollowUpRevealDirection.OPPOSITE.value` | Default value handling | ✅ Already using enum! |

---

## 6. ORDER STATUS STRINGS (IN TESTS & CONFIG)

**Status:** ✅ Enum exists (`OrderStatus`) but **strings used in tests**

### File: [tests/conftest.py](tests/conftest.py)

| Line | Current String | Type | Recommendation |
|------|---|---|---|
| 168 | `"order_type": "limit"` | Test fixture - OrderType | Use `OrderType.LIMIT.value` |
| 187 | `"order_type": "limit"` | Test fixture - OrderType | Use `OrderType.LIMIT.value` |

### File: [tests/unit/test_coinbase_api.py](tests/unit/test_coinbase_api.py)

| Line | Current String | Type |
|------|---|---|
| 49 | `"type": "limit"` | Test fixture - OrderType |

### File: [Tests - Order Status](tests/)

| File | Line | Current String | Note |
|------|---|---|---|
| ui_order_manager.html | 497-500 | `value="PENDING"`, `value="OPEN"`, etc. | HTML form - OK to keep strings (UI layer) |
| ui_order_manager.html | 714-717 | `value="PENDING"`, `value="OPEN"`, etc. | HTML form - OK to keep strings (UI layer) |

---

## 7. ORDER TYPE STRINGS (IN TESTS)

**Status:** ✅ Enum exists (`OrderType`) but **lowercase strings in tests**

### File: [tests/conftest.py](tests/conftest.py)

| Line | Current String | Should Be | Notes |
|------|---|---|---|
| 168 | `"order_type": "limit"` | `OrderType.LIMIT.value` | Test fixture |
| 187 | `"order_type": "limit"` | `OrderType.LIMIT.value` | Factory function |

### File: [websocket_reference/](websocket_reference/)

| File | Note | Recommendation |
|------|---|---|
| authenticated/user_message.json | Contains `"order_type": "Limit"` | These are API reference docs - keep as-is |

---

## 8. TIME IN FORCE STRINGS

**Status:** ✅ Enum exists (`TimeInForce`) but **strings in API reference**

### File: [tests/conftest.py](tests/conftest.py)

| Line | Current String | Recommended |
|------|---|---|
| 169 | `"time_in_force": "GOOD_UNTIL_CANCELLED"` | `TimeInForce.GOOD_UNTIL_CANCELLED.value` |

### File: [api_reference/orders/](api_reference/orders/)

| File | Note |
|------|---|
| list_orders_response.json | Contains `"time_in_force": "GTC"` - API reference, keep as-is |

---

## 9. CONFIGURATION DICTIONARY LOOKUPS (ORDER SIDE KEYS)

**Status:** ⚠️ Strings used as dict keys in [configuration.py](configuration.py)

These are configuration dictionaries where the string keys map OrderSide values to config values.

| Lines | Current Usage | Context | Impact |
|------|---|---|---|
| 72-73 | `"BUY": "SELL"`, `"SELL": "BUY"` | Side flip mapping | **Keep as strings** - this is a configuration lookup table |
| 77-78 | `"BUY": False`, `"SELL": False` | Post-only flags | **Keep as strings** - configuration keys |
| 82-85 | `"SHORT": "SELL"`, etc. | Side terminology mapping | **Keep as strings** - configuration lookup |
| 89-90 | `"SELL": 1`, `"BUY": -1` | Direction multipliers | **Keep as strings** - configuration lookup |
| 622 | `round_direction = "up" if order_side == "SELL"` | Rounding logic | **OK** - comparing to OrderSide enum value |
| 711-720 | Fee mapping dicts | Config fees by product and side | **Keep as strings** - configuration structure |

---

## RECOMMENDED IMPLEMENTATION PLAN

### Phase 1: Add Missing Enum (HIGHEST PRIORITY)
- [ ] Create `StealthOrderStatus` enum in [core/enums.py](core/enums.py)
  - **Impact:** 10 usages in core stealth_order_manager.py
  - **Time:** 15 minutes
  - **Risk:** Low - new enum, no breaking changes

### Phase 2: Update Core Modules (HIGH PRIORITY)
- [ ] [core/stealth_order_manager.py](core/stealth_order_manager.py) - Replace 10 magic strings with `StealthOrderStatus` enum
- [ ] [core/order_engine.py](core/order_engine.py) - Update ProductType and Direction string usage
- [ ] [calculation/resolver.py](calculation/resolver.py) - Use `ProductType` enum values instead of string literals
- [ ] [order.py](order.py) - Use `RevealConditionType` enum in default conditions
- [ ] [business/stealth_condition_evaluator.py](business/stealth_condition_evaluator.py) - Use `Direction` enum

### Phase 3: Update Tests & Fixtures (MEDIUM PRIORITY)
- [ ] [tests/conftest.py](tests/conftest.py) - Replace test fixture strings with enum values
- [ ] [tests/unit/test_condition_evaluators.py](tests/unit/test_condition_evaluators.py) - Use Direction enum
- [ ] [tests/e2e/test_trading_workflows.py](tests/e2e/test_trading_workflows.py) - Use Direction enum

### Phase 4: Dashboard & HTML (LOW PRIORITY - UI LAYER)
- [ ] [dashboard_server.py](dashboard_server.py) - Already mostly correct, minor polish
- [ ] [ui_order_manager.html](ui_order_manager.html) - Keep HTML form values as strings (UI layer)

---

## SUMMARY BY FILE

### Critical Files (5+ magic strings):

| File | Count | Enum Needed? | Action |
|------|-------|---|---|
| [core/stealth_order_manager.py](core/stealth_order_manager.py) | 10 | `StealthOrderStatus` | Add enum + replace 10 usages |
| [core/order_engine.py](core/order_engine.py) | 3 | ProductType, Direction | Update 3 usages |
| [order.py](order.py) | 2 | RevealConditionType | Update 2 usages |
| [calculation/resolver.py](calculation/resolver.py) | 4 | ProductType | Update 4 usages |
| [business/stealth_condition_evaluator.py](business/stealth_condition_evaluator.py) | 2 | Direction | Update 2 usages |

### Lower Priority (< 5 usages):
- [dashboard_server.py](dashboard_server.py) - 1 usage (CANCELLED)
- [tests/conftest.py](tests/conftest.py) - Multiple test fixtures
- Test files - Various test data strings

---

## NOTES

1. **Configuration dictionaries** in [configuration.py](configuration.py) correctly use string keys (e.g., `{"BUY": False, "SELL": False}`) - these should remain as strings since they're data structure keys, not type indicators.

2. **HTML forms** in [ui_order_manager.html](ui_order_manager.html) correctly use string values - these are appropriate for the UI layer.

3. **API reference documents** (JSON files) reflect actual Coinbase API responses - keep unchanged.

4. **Database compatibility:** When storing/retrieving from database, always use `.value` property of enums to get string representation (enums already inherit from `str`).

5. **Import all enums** at top of files using them:
   ```python
   from core.enums import (
       StealthOrderStatus, Direction, RevealConditionType,
       FollowUpRevealDirection, OrderStatus, ProductType, OrderType, TimeInForce
   )
   ```

---

## TESTING VALIDATION

After refactoring:
1. Run full test suite: `pytest tests/ -v`
2. Regression tests: `pytest tests/regression/ -v`
3. Check dashboard for order status displays
4. Verify stealth order reveals work with new enum
5. Test follow-up order creation with new enums
