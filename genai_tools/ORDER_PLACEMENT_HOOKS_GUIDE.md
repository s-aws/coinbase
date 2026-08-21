"""Order Placement Hooks - Usage Guide and Examples

This guide shows how to use the OrderPlacementHookRegistry to extend the order
placement pipeline for validation, modification, and logging.

The hooks run at the final submission step, right before/after the REST API call
to Coinbase, giving you complete control over what orders actually get placed.
"""

# ============================================================================
# QUICK START
# ============================================================================

"""
1. Get the global hook registry:

   from integration.order_placement_hooks import get_global_placement_hook_registry
   registry = get_global_placement_hook_registry()

2. Define a validation hook:

   def validate_order(order):
       '''Validate order before submission'''
       if order['limit_price'] <= 0:
           raise ValueError("Price must be positive")

3. Register the hook:

   registry.register_pre_submission(validate_order)

4. When stealth orders are revealed, hooks run automatically!
"""


# ============================================================================
# EXAMPLE 1: Price Validation
# ============================================================================

from integration.order_placement_hooks import get_global_placement_hook_registry


def example_price_validation():
    """Block orders with unrealistic prices."""

    registry = get_global_placement_hook_registry()

    def validate_price(order):
        """Ensure price is within reasonable bounds."""
        price = float(order.get('limit_price', 0))

        # Reject prices outside 1% of current market
        if price < 0.99 * 50000 or price > 1.01 * 50000:  # Assuming market ~50k
            raise ValueError(
                f"Price {price} outside acceptable range for {order['product_id']}"
            )

    registry.register_pre_submission(validate_price)

    # Now all orders will be validated before submission


# ============================================================================
# EXAMPLE 2: Profitability Check
# ============================================================================

def example_profitability_check():
    """Only place orders that meet minimum profit threshold."""

    registry = get_global_placement_hook_registry()

    # Simulate having entry price information
    order_context = {
        "BTC-USDC": {"entry_price": 42500.0},
        "ETH-USDC": {"entry_price": 2200.0}
    }

    def check_min_profit(order):
        """Block orders below minimum profit threshold."""
        MIN_PROFIT_PERCENT = 0.5  # Must be profitable by at least 0.5%

        product = order['product_id']
        entry_price = order_context.get(product, {}).get('entry_price', 0)

        if not entry_price:
            return  # Skip check if we don't have entry price

        exit_price = float(order['limit_price'])

        if order['side'] == 'BUY':
            # For BUY orders, exit_price should be > entry_price
            profit_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # SELL
            # For SELL orders, exit_price should be < entry_price
            profit_pct = ((entry_price - exit_price) / entry_price) * 100

        if profit_pct < MIN_PROFIT_PERCENT:
            raise ValueError(
                f"Order profit {profit_pct:.2f}% below minimum {MIN_PROFIT_PERCENT}%"
            )

    registry.register_pre_submission(check_min_profit)


# ============================================================================
# EXAMPLE 3: Position Size Limits
# ============================================================================

def example_position_limits():
    """Prevent exceeding maximum position size per product."""

    registry = get_global_placement_hook_registry()

    # Track current positions
    current_positions = {
        "BTC-USDC": {"BUY": 5.0, "SELL": 0},
        "ETH-USDC": {"BUY": 10.0, "SELL": 0},
    }

    MAX_POSITION = 50.0  # Max 50 units per product/side

    def enforce_position_limits(order):
        """Block orders that would exceed position limits."""
        product = order['product_id']
        side = order['side']
        size = float(order.get('base_size', 0))

        if product not in current_positions:
            current_positions[product] = {"BUY": 0, "SELL": 0}

        current_position = current_positions[product].get(side, 0)
        new_position = current_position + size

        if new_position > MAX_POSITION:
            raise ValueError(
                f"Position limit for {product} {side}: "
                f"{current_position} + {size} = {new_position} > {MAX_POSITION}"
            )

    registry.register_pre_submission(enforce_position_limits)


# ============================================================================
# EXAMPLE 4: Price Adjustment Based on Market Data
# ============================================================================

def example_market_price_adjustment():
    """Adjust order prices to be competitive based on current market."""

    registry = get_global_placement_hook_registry()

    # Simulate market data feed
    market_data = {
        "BTC-USDC": {"bid": 42450.0, "ask": 42550.0, "last": 42500.0},
        "ETH-USDC": {"bid": 2190.0, "ask": 2210.0, "last": 2200.0},
    }

    def adjust_to_market(order):
        """Adjust limit price to be competitive."""
        product = order['product_id']
        side = order['side']
        market = market_data.get(product)

        if not market:
            return  # No market data, skip adjustment

        current_price = float(order.get('limit_price', 0))

        if side == 'BUY':
            # For BUY, use bid as reference, maybe 0.2% better
            competitive_price = market['bid'] * 1.002
            # Only adjust if current price is too low
            if current_price < competitive_price:
                order['limit_price'] = round(competitive_price, 2)
        else:  # SELL
            # For SELL, use ask as reference, maybe 0.2% better
            competitive_price = market['ask'] * 0.998
            # Only adjust if current price is too high
            if current_price > competitive_price:
                order['limit_price'] = round(competitive_price, 2)

    registry.register_pre_submission(adjust_to_market)


# ============================================================================
# EXAMPLE 5: Rounding & Format Validation
# ============================================================================

def example_format_validation():
    """Ensure orders are properly formatted for Coinbase API."""

    registry = get_global_placement_hook_registry()

    def format_order(order):
        """Round and format order fields."""
        # Round price to 2 decimal places (Coinbase requirement)
        if 'limit_price' in order:
            order['limit_price'] = round(float(order['limit_price']), 2)

        # Round size to 8 decimal places (standard crypto precision)
        if 'base_size' in order:
            order['base_size'] = round(float(order['base_size']), 8)

        # Validate product_id format
        if 'product_id' not in order or not isinstance(order['product_id'], str):
            raise ValueError("product_id is required and must be a string")

        # Validate side
        if order.get('side') not in ('BUY', 'SELL'):
            raise ValueError("side must be BUY or SELL")

    registry.register_pre_submission(format_order)


# ============================================================================
# EXAMPLE 6: Post-Submission Logging & Analytics
# ============================================================================

def example_post_submission_logging():
    """Log all orders that are successfully placed."""

    registry = get_global_placement_hook_registry()

    # Track submission metrics
    submissions_log = []

    def log_submission(order, result):
        """Log successful order submissions."""
        import json
        from datetime import datetime

        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "product_id": order['product_id'],
            "side": order['side'],
            "size": float(order.get('base_size', 0)),
            "price": float(order.get('limit_price', 0)),
            "exchange_order_id": result.get('order_id') if result else None,
            "status": result.get('status') if result else 'unknown',
        }
        submissions_log.append(log_entry)
        print(f"Order placed: {json.dumps(log_entry)}")

    registry.register_post_submission(log_submission)


# ============================================================================
# EXAMPLE 7: Complex Multi-Hook Validation Chain
# ============================================================================

def example_validation_chain():
    """Multiple hooks that run in sequence for comprehensive validation."""

    registry = get_global_placement_hook_registry()

    # Hook 1: Size validation
    def validate_size(order):
        size = float(order.get('base_size', 0))
        if size <= 0:
            raise ValueError("Size must be positive")
        if size > 100:
            raise ValueError("Size exceeds maximum of 100")

    # Hook 2: Price validation
    def validate_price(order):
        price = float(order.get('limit_price', 0))
        if price <= 0:
            raise ValueError("Price must be positive")

    # Hook 3: Format rounding
    def format_fields(order):
        order['limit_price'] = round(float(order['limit_price']), 2)
        order['base_size'] = round(float(order['base_size']), 8)

    # Hook 4: Business logic check
    def check_business_rules(order):
        if order['product_id'] == 'BTC-USDC' and order['side'] == 'BUY':
            # BTC buys require minimum 0.1
            if float(order['base_size']) < 0.1:
                raise ValueError("BTC buy orders require minimum size of 0.1")

    # Register all in sequence
    registry.register_pre_submission(validate_size)
    registry.register_pre_submission(validate_price)
    registry.register_pre_submission(format_fields)
    registry.register_pre_submission(check_business_rules)


# ============================================================================
# EXAMPLE 8: Conditional Hook Registration
# ============================================================================

def example_conditional_hooks():
    """Register hooks based on configuration/strategy."""

    registry = get_global_placement_hook_registry()

    # Configuration
    config = {
        "enable_price_validation": True,
        "enable_position_limits": True,
        "enable_market_adjustment": False,
        "enable_logging": True,
    }

    if config["enable_price_validation"]:
        def validate_price(order):
            if float(order['limit_price']) <= 0:
                raise ValueError("Price must be positive")
        registry.register_pre_submission(validate_price)

    if config["enable_position_limits"]:
        def check_positions(order):
            # ... position check logic ...
            pass
        registry.register_pre_submission(check_positions)

    if config["enable_market_adjustment"]:
        def adjust_price(order):
            # ... market adjustment logic ...
            pass
        registry.register_pre_submission(adjust_price)

    if config["enable_logging"]:
        def log_order(order, result):
            print(f"Placed: {order['product_id']} {order['side']}")
        registry.register_post_submission(log_order)


# ============================================================================
# IMPORTANT PATTERNS & BEST PRACTICES
# ============================================================================

"""
PATTERN 1: Pre-hooks for Validation & Modification
- Pre-hooks run BEFORE REST API submission
- Raise exceptions to BLOCK submission
- Modify order fields to adjust before sending
- All pre-hooks must execute for order to be placed
- If any raises exception, submission is blocked

PATTERN 2: Post-hooks for Logging & Analytics
- Post-hooks run AFTER REST API submission
- Order is already placed - can't block it
- Exceptions in post-hooks don't affect placement
- Use for logging, analytics, webhooks, etc.

PATTERN 3: Order Reference Access
- Hooks receive order by reference
- Can modify order fields in-place
- Changes persist through to REST API call
- Pre-hook modifications apply to REST submission

PATTERN 4: Hook Execution Order
- Pre-hooks execute in registration order
- First exception stops further pre-hooks
- Post-hooks always execute (exception in one doesn't stop others)
- Use to control validation sequence

PATTERN 5: Error Handling
- Pre-hook exceptions BLOCK submission (desired behavior)
- Post-hook exceptions are logged but don't affect placement
- Hook should be responsible for its own error handling
- Use specific exception types for better debugging

PATTERN 6: Access to Order Context
- All order fields are available to hooks
- Hooks can add custom fields for POST-hooks to use
- Use for passing validation context between hooks
"""


# ============================================================================
# TESTING YOUR HOOKS
# ============================================================================

"""
Test your hooks in isolation:

from integration.order_placement_hooks import OrderPlacementHookRegistry

def test_my_hook():
    registry = OrderPlacementHookRegistry()

    def my_hook(order):
        # Your validation logic
        pass

    registry.register_pre_submission(my_hook)

    # Test valid order
    order = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": 100.0}
    registry.call_pre_submission_hooks(order)

    # Test invalid order
    order_bad = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": -50.0}
    with pytest.raises(ValueError):
        registry.call_pre_submission_hooks(order_bad)
"""


# ============================================================================
# HOW STEALTH ORDER MANAGER USES HOOKS
# ============================================================================

"""
The StealthOrderManager automatically calls hooks when revealing orders:

1. User creates stealth order via dashboard
2. Reveal condition is met (time, price, etc.)
3. StealthOrderManager.reveal_order_slice() is called
4. PRE-SUBMISSION HOOKS RUN on order data
   - Can validate, modify, or block order
   - If exception: placement blocked, logged, return None
5. REST_CLIENT.place_limit_order() is called (if hooks pass)
6. POST-SUBMISSION HOOKS RUN with result
   - Can log, track, webhook, etc.
   - Exceptions logged but don't affect placement
7. Order placed on Coinbase exchange

To intercept orders before Coinbase:

from integration.order_placement_hooks import get_global_placement_hook_registry

registry = get_global_placement_hook_registry()
registry.register_pre_submission(my_validator)
registry.register_post_submission(my_logger)

# Now all stealth order reveals will use your hooks!
"""
