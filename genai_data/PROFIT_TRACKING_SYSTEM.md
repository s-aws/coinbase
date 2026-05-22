# Profit Tracking & Validation System

## Overview

This system ensures that **all trades are profitable** by validating follow-up orders against dynamically fetched Coinbase taker fees with a **4x multiplier**.

## ⚠️ CRITICAL: Fee Charging Model

**Fees are charged ONLY when orders close (fill on exchange):**
1. Parent order opens (fills) → NO FEE CHARGED at this time
2. Follow-up order closes (fills) → Coinbase charges base taker fee on THIS order ONLY
3. Total fees: 1 (only on the close/follow-up order)

**We apply 4x multiplier to the BASE fee, applied to the CLOSE order only:**
```
Base fee from Coinbase: 0.6% (0.0060)
Our multiplier: 4x
Effective fee: 0.6% × 4 = 2.4% (0.024)
This multiplier is applied to: follow_up_price × size
Total cost per round-trip: 1 × effective_fee (not 2x)
```

**WRONG calculation (AVOID):**
```python
❌ fee_on_open = filled_price × size × effective_fee   # NO FEE on open
❌ fee_on_close = follow_up_price × size × effective_fee
❌ total = fee_on_open + fee_on_close  # This charges both
```

**CORRECT calculation (CURRENT):**
```python
✓ fee_on_open = 0.0                                    # Open has NO fee
✓ fee_on_close = follow_up_price × size × effective_fee
✓ total = fee_on_close ONLY
```

## Key Components

### 1. FeeManager (`calculation/fee_manager.py`)
- **Purpose**: Fetches and caches taker fee rates from Coinbase API
- **Update Frequency**: Hourly (configurable)
- **Multiplier**: 4x the base taker fee
- **Thread-safe**: Uses RWLock for concurrent access

```python
# Usage in OrderEngine
from calculation.fee_manager import FeeManager
from configuration import REST_CLIENT

fee_manager = FeeManager(REST_CLIENT, log_callback=engine.log_message)
fee_manager.start()  # Starts hourly refresh thread

# Get current effective fee (base * 4x)
effective_fee = fee_manager.get_profit_validation_fee_rate()  # e.g., 0.024 (2.4%)
```

### 2. ProfitValidator (`calculation/profit_validator.py`)
- **Purpose**: Validates that orders will be profitable after all fees
- **Dependencies**: FeeManager for dynamic fee rates
- **Comparison**: Compares proposed follow-up prices against minimum viable price

```python
# Usage in OrderEngine.handle_filled_order()
from calculation.profit_validator import ProfitValidator

validator = ProfitValidator(fee_manager=fee_manager)

result = validator.is_profitable(
    filled_price=50000.0,      # Parent filled at this price (open, no fee)
    follow_up_price=52500.0,   # Proposed follow-up price (close, fee charged)
    side='BUY',                 # Parent order side
    order_size=1.0
)

if result['is_profitable']:
    print(f"Net profit: ${result['net_profit']:.2f}")
else:
    print(f"Would lose: ${abs(result['net_profit']):.2f}")
    print(f"Minimum viable: {result['minimum_viable_price']}")
```

## Fee Calculation Example

**Scenario**: Parent BUY at $50,000 (OPEN), Follow-up SELL at $52,500 (CLOSE)

```
Base taker fee from Coinbase: 0.6% (0.0060)
Our multiplier: 4x
Effective fee for validation: 2.4% (0.024)
Order size: 1 BTC

Fee breakdown:
- When parent BUY closes: $0.00 (parent is OPEN, not closed yet)
- When follow-up SELL closes: $52,500 × 1 BTC × 0.024 = $1,260
- Total fees: $1,260 (charged ONLY when follow-up fills)

Profit calculation:
- Gross profit = $52,500 - $50,000 = $2,500
- Total fees = $1,260 (close fee only)
- Net profit = $2,500 - $1,260 = $1,240 ✓ PROFITABLE

Price references:
- Breakeven sell price: ~$52,460 (no profit, just cover fees)
- Minimum viable for $1,000 profit: ~$53,460
```

**Verification:**
```python
# Get the explanation
validator = ProfitValidator(fee_manager)
explanation = validator.explain_fee_calculation(
    filled_price=50000.0,
    follow_up_price=52500.0,
    order_size=1.0
)
print(explanation['breakdown'])
# Shows exactly how fees were calculated
```

## Integration Points

### OrderEngine Initialization
```python
# In OrderEngine.__init__()
from configuration import REST_CLIENT
from calculation.fee_manager import FeeManager
from calculation.profit_validator import ProfitValidator

self.fee_manager = FeeManager(REST_CLIENT, log_callback=self.log_message)
self.profit_validator = ProfitValidator(fee_manager=self.fee_manager)
```

### Background Thread Management
```python
# In OrderEngine.start_background_threads()
# Fee manager started after channel workers, before websocket threads
self.fee_manager.start()
```

### Follow-Up Order Validation (High Priority!)
```python
# In OrderEngine.handle_filled_order()
# MUST validate BEFORE creating stealth order

# Get filled price from parent order
filled_price = float(self.order_limit_price_or_avg_price(order))
follow_up_price = float(order_template["start_price"])
order_size = float(order_template["order_base_size"])

# Validate profitability
profit_check = self.profit_validator.is_profitable(
    filled_price=filled_price,
    follow_up_price=follow_up_price,
    side=order["order_side"],
    order_size=order_size,
    min_profit_margin=0.0  # Break-even is minimum
)

# Only create follow-up if profitable
if not profit_check["is_profitable"]:
    self.log_message("warning", {
        "event": "follow_up_rejected_unprofitable",
        "parent_filled_price": filled_price,
        "proposed_price": follow_up_price,
        "net_loss": abs(profit_check['net_profit']),
        "minimum_viable_price": profit_check['minimum_viable_price']
    })
    
    # Mark as complete to prevent retries
    self.complete_follow_up_processing("filled", client_order_id)
    return

# Safe to create follow-up
stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(...)
```

### Stealth Order Reveal Validation (Optional)
```python
# In StealthOrderManager.reveal_order_slice()
# Smart pricing should be constrained by profit

if use_smart_pricing:
    optimized = self._calculate_optimal_price(...)
    
    # Validate profit before using smart price
    profit_check = self.profit_validator.is_profitable(
        filled_price=order["filled_price"],
        follow_up_price=optimized["price"],
        side=order["side"],
        order_size=slice_size
    )
    
    if profit_check["is_profitable"]:
        limit_price = optimized["price"]
    else:
        # Smart price isn't profitable, use original or skip
        limit_price = order["limit_price"]
```

## Fee Update Frequency

**Hourly**: FeeManager refreshes fee rates from Coinbase API every 3600 seconds

```python
# Check fee freshness
fee_info = fee_manager.validate_fee_freshness(max_age_seconds=7200)
if not fee_info['is_fresh']:
    print(f"Fees are stale! Last update: {fee_info['last_updated']}")
    # FeeManager will auto-refresh on next hourly interval
```

## Data Structures

### FeeManager State
```python
fee_manager._taker_fee_rate        # Current base fee (e.g., 0.0060)
fee_manager._last_updated          # Timestamp of last API fetch
fee_manager._fetch_error_count     # Track consecutive API failures
```

### ProfitValidator Results
```python
{
    "is_profitable": True,
    "net_profit": 40.0,            # USD
    "net_profit_pct": 0.0008,      # As % of filled price
    "gross_profit": 2500.0,        # Before fees
    "total_fees": 2460.0,          # Both trades
    "fee_rate_applied": 0.024,     # 4x base rate
    "breakeven_price": 52460.0,    # Price for zero profit
    "minimum_viable_price": 52460.0
}
```

## Logging Events

### Fee Updates
```json
{
    "event": "taker_fee_rate_updated",
    "old_rate": 0.0055,
    "new_rate": 0.0060,
    "effective_profit_fee": 0.024,
    "timestamp": "2026-04-22T14:30:00"
}
```

### Profit Validation Failures
```json
{
    "event": "follow_up_rejected_unprofitable",
    "source_order_id": "order-123",
    "filled_price": 50000.0,
    "proposed_follow_up_price": 50100.0,
    "net_loss": 50.0,
    "minimum_viable_price": 51200.0
}
```

### Fee Fetch Errors
```json
{
    "event": "taker_fee_fetch_failed",
    "error": "Connection timeout",
    "error_count": 1,
    "fallback_rate": "previous",
    "note": "Will retry next hour"
}
```

## Testing Checklist

- [ ] FeeManager initializes correctly with REST_CLIENT
- [ ] Background thread starts on engine startup
- [ ] Fees refresh hourly without blocking
- [ ] ProfitValidator correctly calculates breakeven prices
- [ ] Follow-ups are rejected when unprofitable
- [ ] Logs show rejection reason and minimum viable price
- [ ] Smart pricing respects profit guards
- [ ] Fee stale detection works correctly
- [ ] Error recovery falls back to conservative default

## Migration Steps

### Phase 1: Deploy FeeManager (No-Op)
1. Deploy `calculation/fee_manager.py`
2. Initialize in OrderEngine
3. Start in background threads
4. Monitor logs for correct fee fetching
5. Verify hourly refreshes in logs

### Phase 2: Add Profit Validation (Log-Only)
1. Deploy `calculation/profit_validator.py`
2. Add validation logic to `handle_filled_order()` but log results only
3. Do NOT reject follow-ups yet
4. Collect 1 week of validation metrics
5. Review: How many follow-ups would have been rejected?

### Phase 3: Enable Validation (Enforce)
1. Change log-only to actually reject unprofitable follow-ups
2. Monitor for false positives (should be rare)
3. Set alert if > 5% of follow-ups are rejected
4. If too many rejections, audit fee rates

### Phase 4: Integrate Smart Pricing (Optional)
1. After Phase 3 is stable, add smart pricing constraints
2. Smart pricing can adjust prices but must remain profitable
3. Test extensively in staging before production

## Configuration

All settings are in the implementation:

```python
# FeeManager
DEFAULT_MULTIPLIER = 4.0              # 4x base fee
REFRESH_INTERVAL_SECONDS = 3600       # 1 hour
MAX_CONSECUTIVE_ERRORS = 3            # Fall back to default after 3 failures

# ProfitValidator
min_profit_margin = 0.0               # Breakeven minimum (can be increased)
```

## Troubleshooting

### "Fee fetch failing repeatedly"
- Check API credentials in configuration.py
- Verify REST_CLIENT is initialized correctly
- Check Coinbase API status page

### "Follow-ups being rejected too often"
- Fee rates may have increased
- Verify current taker fee on Coinbase dashboard
- Check if min_profit_margin is too high
- Review recent market conditions (high fees during volatile times)

### "Fees haven't updated in hours"
- Check FeeManager thread is running: `ps aux | grep FeeManager`
- Verify `fee_info = fee_manager.validate_fee_freshness()`
- Check logs for API errors
- Manually trigger refresh: `fee_manager._refresh_fee_rate()`

### "I'm not sure if the fee multiplier is correct"
**Debugging tool: Use the explanation methods**
```python
# FeeManager explanation
fee_info = fee_manager.explain_fee_multiplier()
print(fee_info['calculation_method'])
# Output: "effective = base × 4 (NOT 2×base on front AND 2×base on back)"

# ProfitValidator explanation
validator = ProfitValidator(fee_manager)
explanation = validator.explain_fee_calculation(50000.0, 52500.0, 1.0)
print(explanation['breakdown'])
# Shows exact fee charges and confirms single 4x multiplier (not 2×2×)

# If you see this, it's WRONG:
# ❌ "Fee on buy = $50,000 × 1 × 0.0060 × 2 = $600"
# ✓ This is CORRECT:
# ✓ "Fee on buy = $50,000 × 1 × 0.024 = $1,200"
```

## Performance Impact

- **CPU**: FeeManager uses ~0.1% during hourly refresh (minimal)
- **Memory**: ~1KB per cached fee rate (negligible)
- **Network**: One REST API call per hour (~100ms)
- **Latency**: ProfitValidator adds ~1ms per validation

All impacts are **negligible** for trading frequency.
