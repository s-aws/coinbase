"""Order Placement Hooks - Architecture & Data Flow

This document explains how OrderPlacementHookRegistry integrates with the
stealth order system and where hooks fit in the complete order pipeline.
"""

# ============================================================================
# ARCHITECTURE OVERVIEW
# ============================================================================

"""
The complete order flow in the system:

┌─────────────────────────────────────────────────────────────────────────┐
│ USER DASHBOARD / API                                                    │
│  - Create stealth order                                                 │
│  - Set reveal condition (time, price, etc.)                             │
│  - Specify target movement, sizing strategy                             │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
        ┌───────────────────────────────────┐
        │  StealthOrderManager               │
        │  .create_stealth_order()          │
        └────────────┬──────────────────────┘
                     │
                     ▼ (Order stored in HIDDEN state)
        ┌───────────────────────────────────┐
        │  Database: stealth_orders table   │
        │  - stealth_order_id               │
        │  - product_id, side, size         │
        │  - reveal_condition               │
        │  - status: HIDDEN/REVEALED/...    │
        └───────────────────────────────────┘
                     │
                     │ (Condition evaluator runs periodically)
                     ▼
        ┌───────────────────────────────────┐
        │  Reveal Condition Evaluator       │
        │  - Time elapsed?                  │
        │  - Price hit target?              │
        │  - Volume condition met?          │
        └────────────┬──────────────────────┘
                     │
                     ├─ Condition NOT met ──→ Try again later
                     │
                     └─ Condition MET ──────→
                               │
                               ▼
        ┌────────────────────────────────────────────────────┐
        │  StealthOrderManager.reveal_order_slice()          │
        │                                                    │
        │  1. Get stealth order from database               │
        │  2. Calculate slice size (adaptive sizing)        │
        │  3. Build order dict for REST API                │
        │                                                    │
        │  ⚡ PRE-SUBMISSION HOOKS EXECUTE HERE ⚡           │
        │     - Validate order                             │
        │     - Modify price/size                          │
        │     - Check profitability                        │
        │     - Can BLOCK submission (raise exception)     │
        │                                                    │
        │  4. If hooks pass:                                │
        │     REST_CLIENT.place_limit_order()              │
        │                                                    │
        │  5. Update stealth_orders table                  │
        │     - Record revealed_orders event               │
        │     - Update status to REVEALED                  │
        │                                                    │
        │  ⚡ POST-SUBMISSION HOOKS EXECUTE HERE ⚡          │
        │     - Log submission                             │
        │     - Send webhooks                              │
        │     - Update dashboard                           │
        │     - Exceptions don't affect placement          │
        │                                                    │
        │  6. Return placed_order_id                        │
        └────────────┬─────────────────────────────────────┘
                     │
                     ├─ Hooks blocked: return None, log warning
                     │
                     └─ Hooks passed: continue
                               │
                               ▼
        ┌────────────────────────────────────────────────────┐
        │  Coinbase REST API                                │
        │  POST /orders                                     │
        │  - Receives order with client_order_id            │
        │  - Validates and accepts                          │
        │  - Returns exchange order_id                      │
        └────────────┬─────────────────────────────────────┘
                     │
                     ▼ (Order submitted to exchange)
        ┌────────────────────────────────────────────────────┐
        │  Coinbase Order Book & Matching Engine            │
        │  - Order enters matching engine                   │
        │  - Sits at limit_price waiting for fills          │
        │  - Or fills immediately if price met             │
        └────────────┬─────────────────────────────────────┘
                     │
                     ▼ (WebSocket event stream)
        ┌────────────────────────────────────────────────────┐
        │  WebSocket Message: USER channel                  │
        │  - Event type: OPEN / FILLED / CANCELLED          │
        │  - client_order_id (matches what we sent)        │
        │  - order_id (exchange ID)                        │
        │  - filled_size, avg_price, etc.                  │
        └────────────┬─────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────────────────────────────┐
        │  OrderEngine.process_user_order()                 │
        │  - Update orderbook with fill/cancel event        │
        │  - Create follow-up child orders if needed        │
        │  - Record in order_parent table                   │
        │  - Update dashboard with status                   │
        │                                                    │
        │  ⚡ WEBSOCKET HOOKS (EXISTING SYSTEM) ⚡           │
        │     - PRE-hooks on RAW Coinbase fields           │
        │     - Normalizers transform fields               │
        │     - POST-hooks on NORMALIZED data              │
        │                                                    │
        └────────────────────────────────────────────────────┘
"""

# ============================================================================
# ORDER PLACEMENT HOOKS - DETAILED FLOW
# ============================================================================

"""
PRE-SUBMISSION HOOKS FLOW:
════════════════════════════════════════════════════════════════════════

Input Order (before hooks):
{
    "product_id": "BTC-USDC",
    "side": "BUY",
    "limit_price": 42500.0,
    "base_size": 0.5,
    "client_order_id": "550e8400-e29b-41d4-a716-446655440000",
    "post_only": False,
    "stealth_order_id": "550e8400-e29b-41d4-a716-446655440000"  # = client_order_id
}

                           ▼

Hook 1: Validate Price
  ├─ Check if limit_price > 0
  ├─ Check if limit_price within market range
  └─ ✓ PASS (42500.0 is valid)

                           ▼

Hook 2: Check Profitability
  ├─ Calculate expected profit
  ├─ Compare against minimum threshold
  └─ ✓ PASS (profit 0.5% > minimum 0.2%)

                           ▼

Hook 3: Position Limits
  ├─ Get current BTC position (5.0 BTC)
  ├─ New position would be 5.0 + 0.5 = 5.5 BTC
  ├─ Max allowed is 50 BTC
  └─ ✓ PASS (5.5 < 50)

                           ▼

Hook 4: Market Price Adjustment
  ├─ Fetch current market bid/ask
  ├─ Current bid is 42475, ask is 42525
  ├─ Order price 42500.0 is competitive
  └─ ✓ NO MODIFICATION NEEDED

                           ▼

Hook 5: Format Rounding
  ├─ Round price to 2 decimals: 42500.0 → 42500.00 ✓
  ├─ Round size to 8 decimals: 0.5 → 0.50000000 ✓
  └─ ✓ PASS

                           ▼

Output Order (after all hooks pass):
{
    "product_id": "BTC-USDC",
    "side": "BUY",
    "limit_price": 42500.00,      # Potentially modified
    "base_size": 0.50000000,       # Potentially modified
    "client_order_id": "550e8400-e29b-41d4-a716-446655440000",
    "post_only": False,
    "stealth_order_id": "550e8400-e29b-41d4-a716-446655440000"
}

                           ▼

✓ ALL PRE-HOOKS PASSED → Proceed to REST_CLIENT.place_limit_order()


FAILURE SCENARIO:
════════════════════════════════════════════════════════════════════════

If any hook raises an exception:

Hook 3: Position Limits
  ├─ Get current BTC position (48.5 BTC)
  ├─ New position would be 48.5 + 0.5 = 49.0 BTC
  ├─ Max allowed is 50 BTC... but we have another order pending (0.3 BTC)
  ├─ Effective position is 48.5 + 0.3 + 0.5 = 49.3 > 50 BTC
  └─ ✗ RAISE EXCEPTION: "Position limit exceeded"

                           ▼

RestOrderManager.reveal_order_slice() catches exception:
  ├─ Logs warning: "stealth_order_submission_blocked_by_hook"
  ├─ Records reveal event with placement_success = False
  ├─ Updates stealth_orders table
  └─ Returns None (no order placed)

                           ▼

✗ NO ORDER SUBMITTED TO COINBASE
✗ NO POST-HOOKS EXECUTED
✓ Stealth order remains in HIDDEN state
✓ Reveal will be retried on next condition evaluation
"""

# ============================================================================
# POST-SUBMISSION HOOKS FLOW
# ============================================================================

"""
POST-SUBMISSION HOOKS - After REST_CLIENT.place_limit_order() succeeds

Input to POST-hooks:
  - order: Order dict that was submitted (may have been modified by pre-hooks)
  - result: Return value from REST_CLIENT.place_limit_order()
    {
        "order_id": "7c4a3d3e-e8f2-4e7a-9c1d-5a6e9f2b8c1d",  # Exchange ID
        "status": "PENDING",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.5",
        "price": "42500.00",
        ...
    }

                           ▼

Hook 1: Log Submission
  ├─ Record order to database for audit trail
  └─ ✓ COMPLETE

                           ▼

Hook 2: Send Webhook
  ├─ POST to external system (Slack, webhook, etc.)
  └─ ✗ WEBHOOK TIMEOUT ERROR
      (But order is already placed, so exception is logged and ignored)

                           ▼

Hook 3: Update Dashboard
  ├─ Send WebSocket message to UI clients
  └─ ✓ COMPLETE

                           ▼

✓ ALL POST-HOOKS EXECUTED (even though one failed)
✓ ORDER IS ON EXCHANGE - CANNOT BE UNDONE
"""

# ============================================================================
# INTEGRATION POINTS
# ============================================================================

"""
ORDER PLACEMENT HOOK REGISTRY INTEGRATION:

1. Location: integration/order_placement_hooks.py
   - OrderPlacementHookRegistry class
   - Global singleton: get_global_placement_hook_registry()

2. Used by: core/stealth_order_manager.py
   - __init__ accepts optional order_placement_hooks parameter
   - Defaults to global registry
   - Hooks called in reveal_order_slice() method

3. Call sites in reveal_order_slice():
   - Line ~350: self.order_placement_hooks.call_pre_submission_hooks(order_for_submission)
   - Line ~385: REST_CLIENT.place_limit_order(...)
   - Line ~395: self.order_placement_hooks.call_post_submission_hooks(order_for_submission, order_result)

4. Extension point:
   from integration.order_placement_hooks import get_global_placement_hook_registry
   registry = get_global_placement_hook_registry()
   registry.register_pre_submission(my_validator)
   registry.register_post_submission(my_logger)

5. Testing:
   genai_tools/test_order_placement_hooks.py - 18 comprehensive tests
"""

# ============================================================================
# COMPARISON: WEBSOCKET HOOKS vs ORDER PLACEMENT HOOKS
# ============================================================================

"""
WEBSOCKET HOOKS (Existing system)
─────────────────────────────────
Purpose:         Handle INCOMING order events from Coinbase
Timing:          After REST response received, before orderbook update
Location:        integration/websocket_hooks.py
Called by:       core/order_engine.py.process_user_order()
Flow:
  1. WebSocket message arrives (OPEN, FILLED, CANCELLED)
  2. PRE-hooks called on raw Coinbase fields
  3. Normalizers transform fields
  4. Core engine processes (fill detection, follow-ups)
  5. POST-hooks called on normalized data

Examples:
  - Transform field names for consistency
  - Enrich order data with computed fields
  - Validate fill quantities
  - Update external systems with fills


ORDER PLACEMENT HOOKS (New system)
──────────────────────────────────
Purpose:         Handle OUTGOING orders before REST submission
Timing:          Immediately before REST_CLIENT.place_limit_order()
Location:        integration/order_placement_hooks.py
Called by:       core/stealth_order_manager.py.reveal_order_slice()
Flow:
  1. Stealth reveal condition is met
  2. PRE-hooks called on order before REST submission
  3. REST_CLIENT.place_limit_order() sends to Coinbase
  4. POST-hooks called with result after submission

Examples:
  - Validate profitability before sending
  - Adjust price based on live market
  - Enforce position limits
  - Block orders based on business rules
  - Log all submissions for compliance


KEY DIFFERENCES:
┌──────────────────────┬──────────────────────────┬────────────────────────┐
│ Aspect               │ WebSocket Hooks          │ Order Placement Hooks   │
├──────────────────────┼──────────────────────────┼────────────────────────┤
│ Direction            │ INCOMING (responses)     │ OUTGOING (requests)    │
│ Timing               │ After REST response      │ Before REST submission │
│ Can block?           │ No (event already done)  │ YES (raise exception)  │
│ Can modify?          │ YES (transform data)     │ YES (adjust fields)    │
│ Exception handling   │ PRE stops, POST doesn't  │ PRE blocks, POST logged│
│ Order state          │ Already on exchange      │ Not yet on exchange    │
│ Control              │ Reactive (what happened) │ Proactive (should it?) │
└──────────────────────┴──────────────────────────┴────────────────────────┘
"""

# ============================================================================
# ERROR HANDLING PATTERNS
# ============================================================================

"""
HOW ERRORS ARE HANDLED IN ORDER PLACEMENT:

PRE-SUBMISSION HOOK EXCEPTION:
───────────────────────────────
def my_validator(order):
    if order['limit_price'] < 0:
        raise ValueError("Invalid price")  # ← Exception raised here

                           ▼

StealthOrderManager.reveal_order_slice():
  ├─ try:
  │   self.order_placement_hooks.call_pre_submission_hooks(order)
  │ except Exception as hook_error:
  │   ├─ Set placement_success = False
  │   ├─ Set placement_error = str(hook_error)
  │   ├─ Log warning with details
  │   ├─ Record reveal event (placement_success=False)
  │   └─ Return None (no order placed)
  │
  └─ ✓ Order NOT submitted to Coinbase
    ✓ Stealth order remains HIDDEN
    ✓ Reveal will be retried later


POST-SUBMISSION HOOK EXCEPTION:
───────────────────────────────
def my_logger(order, result):
    send_webhook(...)  # ← Exception raised here

                           ▼

StealthOrderManager.reveal_order_slice():
  ├─ try:
  │   self.order_placement_hooks.call_post_submission_hooks(...)
  │ except Exception as hook_error:
  │   ├─ Log warning: "post_submission_hook_exception"
  │   └─ Continue (don't propagate)
  │
  └─ ✓ Order is already on Coinbase (cannot be undone)
    ✓ Exception is logged for debugging
    ✓ Stealth order marked as REVEALED (placement_success=True)


THREAD SAFETY:
──────────────
- Hook registry is thread-safe (uses RLock)
- Hook lists are copied before iteration (prevents concurrent modification)
- stealth_order_manager instance has one registry per instance
- Multiple reveals can run concurrently with same registry safely
"""

# ============================================================================
# BEST PRACTICES
# ============================================================================

"""
1. PRE-HOOK DESIGN
   ✓ DO: Raise exceptions to block invalid orders
   ✓ DO: Modify order fields in-place (price, size)
   ✓ DO: Use specific exception types (ValueError, RuntimeError, etc.)
   ✓ DON'T: Make slow API calls (will block submission)
   ✓ DON'T: Modify order fields randomly

2. POST-HOOK DESIGN
   ✓ DO: Log, track, webhook, notify
   ✓ DO: Handle your own exceptions (don't expect caller to)
   ✓ DO: Use result dict to verify order was placed
   ✓ DON'T: Raise critical exceptions (won't stop placement)
   ✓ DON'T: Try to cancel order (too late, market might fill it)

3. REGISTRATION
   ✓ DO: Register hooks once at startup
   ✓ DO: Use global registry for system-wide hooks
   ✓ DO: Reset registry in tests (reset_global_placement_hook_registry())
   ✓ DON'T: Register/unregister hooks dynamically during runtime

4. TESTING
   ✓ DO: Test hooks in isolation with OrderPlacementHookRegistry
   ✓ DO: Test happy path and error cases
   ✓ DO: Mock external dependencies (API calls, etc.)
   ✓ DON'T: Integration test against real Coinbase API
"""
