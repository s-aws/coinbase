# LOT-BASED PROFIT TRACKING - INTEGRATION CHECKLIST

This checklist guides you through integrating the lot-based profit-aware execution system with the existing order engine.

## Prerequisites
- [ ] Read genai_data/LOT_TRACKING_INTEGRATION_GUIDE.md
- [ ] Read ai-context.md (critical)
- [ ] Read agent.md (code reuse principles)
- [ ] Understand ORDER_ID_HANDLING.md (use client_order_id, not order_id)

## Phase 1: Setup & Initialization

### 1.1 Database Setup
- [ ] Verify PostgreSQL is running on primary port (5432) and test port (9876)
- [ ] Run `python __dangerous_delete_all_tables__.py` to create fresh schema
- [ ] Verify fill_ledger table is created (check via psql)

### 1.2 Import Dependencies
In your order engine initialization (likely main.py or core/order_engine.py):

```python
from business.fill_ledger import FillLedgerRepository
from database.database import DB_CLIENT
from business.post_fill_hook import on_order_filled, initialize_fill_ledger
from business.lot_config import ENABLE_LOT_TRACKING

# Once at startup
if ENABLE_LOT_TRACKING:
    fill_ledger_repo = initialize_fill_ledger(DB_CLIENT)
```

- [ ] Import statements added
- [ ] Initialize fill_ledger_repo at startup
- [ ] Add to any existing initialization order (after DB_CLIENT created)

## Phase 2: Post-Fill Hook Integration

**CRITICAL STEP**: This captures all fills into the immutable ledger.

### 2.1 Locate Fill Detection Points

In core/order_engine.py, find where fills are detected:
- [ ] handle_filled_order() method
- [ ] process_user_order() when fill detected
- [ ] Any fill event processing

### 2.2 Add Post-Fill Hook Call

For each fill detected, add this call:

```python
# After detecting a fill, before any other fill processing
from business.post_fill_hook import on_order_filled

on_order_filled(
    fill_repo=fill_ledger_repo,
    product_id=order.product_id,
    side=order.order_side.name,  # 'BUY' or 'SELL'
    quantity=filled_size,         # Amount actually filled
    price=fill_price,            # Price per unit
    fees=order.fees,             # Fees on this fill
    client_order_id=order.client_order_id,  # CRITICAL: Use client_order_id
    trade_id=trade_id,           # From exchange or generate if needed
    timestamp=fill_timestamp
)
```

- [ ] hook call added to handle_filled_order()
- [ ] hook call added to process_user_order()
- [ ] hook call added to any other fill detection points
- [ ] Using client_order_id (not order_id from exchange)
- [ ] Tested: Created dummy fill and verified it appears in fill_ledger table

### 2.3 Verify Hook Works

```python
# Quick test in Python shell
from business.fill_ledger import FillLedgerRepository
from database.database import PostgresDB

db = PostgresDB()
repo = FillLedgerRepository(db)

fills = repo.get_fills_by_product('BTC-USDC')
print(f"Fills recorded: {len(fills)}")
for fill in fills:
    print(f"  {fill.side} {fill.quantity} @ {fill.price}")
```

- [ ] Test query runs successfully
- [ ] Fills appear in results
- [ ] Quantities and prices are correct

## Phase 3: Order Interception Layer (Optional but Recommended)

This layer provides decision-support for order execution.

### 3.1 Initialize at Startup

```python
from business.order_interception_layer import OrderInterceptionLayer
from business.lot_config import ENABLE_LOT_TRACKING

if ENABLE_LOT_TRACKING:
    order_interception = OrderInterceptionLayer(
        fill_ledger_repo=fill_ledger_repo,
        profit_margin_pct=0.5,
        strategy_mode='ADVISORY'  # 'ADVISORY' or 'ENFORCING'
    )
```

- [ ] OrderInterceptionLayer imported and initialized
- [ ] Assigned to instance variable for use in order submission

### 3.2 Call Before Order Submission

Before placing an order on the exchange:

```python
from core.enums import OrderSide

# Get enriched order with profit metadata
enriched_order, metadata = order_interception.intercept_order(
    product_id=order.product_id,
    side=order.order_side,  # OrderSide.BUY or .SELL
    size=order.size,
    price=order.price,      # Can be None for market orders
    market_price=current_price
)

# If ENFORCING mode, check for errors
if 'error' in enriched_order:
    logger.error(f"Order blocked: {enriched_order['error']}")
    return False  # Don't submit

# Proceed with submission (enriched_order has profit metadata)
rest_result = REST_CLIENT.create_order(**enriched_order)
```

- [ ] intercept_order() called before REST_CLIENT.create_order()
- [ ] Metadata logged or monitored
- [ ] Error checking added if using ENFORCING mode

### 3.3 Test Interception

```python
# In test environment
enriched, meta = order_interception.intercept_order(
    product_id='BTC-USDC',
    side=OrderSide.SELL,
    size=0.1,
    price=50300.0,
    market_price=50300.0
)

print(f"Profit constrained: {meta.is_profit_constrained}")
if meta.execution_targets:
    for target in meta.execution_targets:
        print(f"  Min exit: {target.min_profitable_price}")
```

- [ ] Interception works for BUY orders
- [ ] Interception works for SELL orders
- [ ] Metadata contains execution targets
- [ ] Profit thresholds are computed correctly

## Phase 4: Conditional Execution (Optional but Powerful)

Automatically waits for profitable execution prices.

### 4.1 Initialize at Startup

```python
from business.conditional_execution import ConditionalExecutionWrapper

if ENABLE_CONDITIONAL_EXECUTION:
    conditional_wrapper = ConditionalExecutionWrapper(
        order_interception_layer=order_interception,
        max_queue_size=1000
    )
```

- [ ] ConditionalExecutionWrapper initialized
- [ ] Added to instance variables

### 4.2 Create Conditional Orders

When intercepted order has profit constraints:

```python
if meta.is_profit_constrained and meta.execution_targets:
    # Wrap order with condition
    for target in meta.execution_targets:
        cond = conditional_wrapper.wrap_with_profit_condition(
            product_id=order.product_id,
            side=target.side,
            size=target.quantity,
            price=order.price,
            min_profitable_price=target.min_profitable_price,
            notes=f"Exit {target.lot_id} profitably"
        )

        # Don't submit yet - wait for condition
        logger.info(f"Created conditional order {cond.conditional_order_id}")
```

- [ ] Conditional orders created from execution targets
- [ ] Order NOT submitted to exchange immediately
- [ ] Conditional ID stored for later

### 4.3 Background Evaluation Loop

In a background worker (similar to StealthOrderBridge pattern):

```python
# In a 100ms loop (like existing stealth order evaluation)
import time

while True:
    try:
        # For each product
        for product in PRODUCTS_TO_TRADE:
            # Get current price
            market_price = get_current_market_price(product)

            # Evaluate all conditional orders
            ready_orders = conditional_wrapper.evaluate_condition(
                market_price=market_price,
                product_id=product
            )

            # Submit those that are ready
            for cond_order in ready_orders:
                logger.info(f"Condition met! Submitting {cond_order.conditional_order_id}")

                # Submit to exchange
                result = REST_CLIENT.create_order(
                    product_id=cond_order.product_id,
                    side=cond_order.side.name,
                    order_type='limit',
                    size=cond_order.size,
                    price=cond_order.price
                )

                if result['success']:
                    # Mark as submitted
                    conditional_wrapper.mark_submitted(
                        conditional_order_id=cond_order.conditional_order_id
                    )

                    # Later, when fill is detected, mark as filled
                    conditional_wrapper.mark_filled(
                        conditional_order_id=cond_order.conditional_order_id,
                        execution_price=result['average_price']
                    )

        time.sleep(0.1)  # 100ms evaluation frequency

    except Exception as e:
        logger.error(f"Error in conditional evaluation: {e}")
        time.sleep(0.1)
```

- [ ] Background evaluation loop added
- [ ] Runs every 100ms (like stealth order bridge)
- [ ] Calls evaluate_condition() for each product
- [ ] Submits ready orders
- [ ] Marks orders as submitted/filled

## Phase 5: Configuration

### 5.1 Review Configuration

Check business/lot_config.py:

```python
DEFAULT_PROFIT_MARGIN_PCT = 0.5        # Adjust if needed
LOT_EXIT_STRATEGY = 'FIFO'             # FIFO, LIFO, or BEST_PROFIT
CONDITIONAL_EXECUTION_MODE = 'ADVISORY' # ADVISORY or ENFORCING
ENABLE_LOT_TRACKING = True
ENABLE_CONDITIONAL_EXECUTION = True
```

- [ ] Profit margin set appropriately (e.g., 0.5% for scalping, 2% for swing)
- [ ] Exit strategy matches your preference (FIFO is standard)
- [ ] Mode set correctly (ADVISORY for optional, ENFORCING for strict)
- [ ] Both features enabled

### 5.2 Product-Specific Configuration

Override defaults in business/lot_config.py PRODUCT_PROFIT_TARGETS:

```python
PRODUCT_PROFIT_TARGETS = {
    'BTC-USDC': 0.5,      # Bitcoin: 0.5%
    'ETH-USDC': 0.75,     # Ethereum: 0.75%
    'SOL-USDC': 1.0,      # Solana: 1.0% (more volatile)
}
```

- [ ] Product targets configured
- [ ] Matches your risk/reward preferences

## Phase 6: Testing

### 6.1 Unit Tests

Run existing tests:

```bash
pytest tests/test_lot_tracking_integration.py -v
```

- [ ] All tests pass
- [ ] No import errors
- [ ] Database connectivity works

### 6.2 Manual Integration Test

Create a test order flow:

```python
# 1. Create buy order (add position)
order = create_order('BTC-USDC', 'BUY', 0.1, 50000.0)

# 2. Simulate fill
on_order_filled(
    fill_repo=fill_ledger_repo,
    product_id='BTC-USDC',
    side='BUY',
    quantity=0.1,
    price=50000.0,
    fees=3.0,
    client_order_id=order.client_order_id,
    trade_id='test-fill-1'
)

# 3. Create sell order (exit position)
enriched, meta = order_interception.intercept_order(
    product_id='BTC-USDC',
    side=OrderSide.SELL,
    size=0.05,
    price=50300.0,
    market_price=50300.0
)

# 4. Verify metadata
print(f"Is constrained: {meta.is_profit_constrained}")
print(f"Num targets: {len(meta.execution_targets) if meta.execution_targets else 0}")
if meta.execution_targets:
    for t in meta.execution_targets:
        print(f"  Min profitable: {t.min_profitable_price}")
```

- [ ] Buy order created
- [ ] Fill recorded in ledger
- [ ] Sell order intercepted
- [ ] Metadata contains profit constraints
- [ ] Min profitable price computed correctly

### 6.3 Live Market Test

In a paper trading or small-position scenario:

- [ ] Create live buy order (small size, e.g., 0.01 BTC)
- [ ] Verify fill is recorded in fill_ledger
- [ ] Create exit sell order
- [ ] Check logs for profit constraint evaluation
- [ ] Monitor conditional orders if enabled

## Phase 7: Monitoring & Maintenance

### 7.1 Logging

Check logs for lot-tracking operations:

```python
# Expected log entries:
# "✓ Fill recorded: trade-id BUY 0.1 BTC-USDC @ 50000.0"
# "✓ Execution targets computed: 2 targets, 0.1 qty, profitable: True"
# "Order enriched with profit constraints: 2 targets, min_price: 50280.15"
```

- [ ] Fill recording logs appear
- [ ] Execution target logs appear
- [ ] No error logs from post-fill hook

### 7.2 Database Maintenance

Periodic health checks:

```sql
-- Check fill ledger size
SELECT COUNT(*) FROM fill_ledger;

-- Check for fills in last hour
SELECT COUNT(*) FROM fill_ledger WHERE timestamp > NOW() - INTERVAL 1 HOUR;

-- Verify indexes
SELECT * FROM pg_indexes WHERE tablename = 'fill_ledger';

-- Maintenance (after many operations)
VACUUM ANALYZE fill_ledger;
```

- [ ] Fills are being recorded
- [ ] Indexes are present
- [ ] Database is healthy

### 7.3 Performance Monitoring

Track metrics:

```python
# In your monitoring system:
- "fill_ledger.inserts_per_minute"
- "lot_builder.reconstruction_time_ms"
- "profit_threshold_engine.computation_time_ms"
- "conditional_orders.active_count"
- "conditional_orders.conditions_met_per_minute"
```

- [ ] Metrics collected
- [ ] Performance within expected ranges (<10ms for lot reconstruction)
- [ ] No memory leaks in conditional order queue

## Completion Checklist

Once all phases are complete:

- [ ] Fill ledger records all fills
- [ ] Post-fill hook is integrated
- [ ] Order interception layer works (shows metadata)
- [ ] Conditional execution wrapper evaluates correctly
- [ ] Configuration is set for your strategy
- [ ] All tests pass
- [ ] Live trading verified (small position first)
- [ ] Monitoring in place

## Rollback Plan (If Issues Arise)

If problems occur:

1. Set ENABLE_LOT_TRACKING = False in lot_config.py
2. Set ENABLE_CONDITIONAL_EXECUTION = False
3. This disables the system without breaking existing orders
4. Review logs for specific errors
5. Contact support with:
   - Specific error message
   - Logs from the failure
   - Which phase was being completed

## Support

For issues:
1. Check LOT_TRACKING_INTEGRATION_GUIDE.md
2. Review logs with "FillLedger", "PostFillHook", "OrderInterceptionLayer"
3. Run manual tests to isolate issue
4. Verify database connectivity
5. Check ORDER_ID_HANDLING.md (CRITICAL: use client_order_id!)
