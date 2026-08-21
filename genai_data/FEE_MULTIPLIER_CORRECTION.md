# Fee Multiplier Correction & Open vs Close Order Fees

## The Critical Distinction: OPEN vs CLOSE Orders

When trading, there are two distinct order events:
1. **OPEN order** (parent): The order that opens/establishes the position
   - NO FEE charged when this order fills
   - This is just the beginning of the trade

2. **CLOSE order** (follow-up): The order that closes/exits the position
   - FEE IS CHARGED when this order fills
   - This is when Coinbase assesses the transaction fee

**This is fundamentally different from what the original code did:**
- ❌ OLD: Applied fees to both parent and follow-up (WRONG)
- ✓ NEW: Apply fees ONLY to follow-up (CORRECT)

## The Solution We Implemented

**Single 4x multiplier, applied ONCE to the CLOSE order:**

```python
# ✓ CORRECT: Fee on close order only
base_fee_rate = 0.006              # From Coinbase API (0.6%)
multiplier = 4                      # Our markup
effective_fee_rate = base_fee_rate * multiplier  # 0.024 (2.4%)

# When parent opens (fills) - NO FEE
fee_on_parent = 0.0  # Parent order has NO fee

# When follow-up closes (fills) - FEE CHARGED
fee_on_followup = followup_price * size * effective_fee_rate

# Total = 1 × effective_fee_rate (charged on close only)
total_fees = fee_on_parent + fee_on_followup
```

## Why This Matters

**What Coinbase actually charges you:**
- When parent order fills: 0% fee (order is open, not closed)
- When follow-up order fills: 0.6% fee (order is closing the position)
- Total: 0.6% for the round-trip (charged on the close order only)

**What you need to profit:**
- Gross profit must be > 2.4% (our 4x multiplier on the 0.6% close fee)
- This covers our infrastructure, risk, and margin

**How we calculate it:**
- Take Coinbase's 0.6% base fee
- Multiply by 4x: 0.6% × 4 = 2.4%
- Apply ONLY to the close order: fee = close_price × size × 2.4%
- Total for round-trip: 1 × 2.4% (not 2×)

## How It's Implemented

### FeeManager (`calculation/fee_manager.py`)
```python
class FeeManager:
    """Fetches base fee from API, returns (base × 4)"""

    def get_taker_fee_rate(self) -> float:
        """Returns base fee (e.g., 0.006)"""
        return self._taker_fee_rate

    def get_profit_validation_fee_rate(self) -> float:
        """Returns base × 4 (e.g., 0.024) - applied to close order only"""
        return self._taker_fee_rate * 4.0
```

### ProfitValidator (`calculation/profit_validator.py`)
```python
class ProfitValidator:
    """Uses FeeManager to validate profitability"""

    def is_profitable(self, filled_price, follow_up_price, side, order_size):
        # Get effective fee (already multiplied by 4)
        fee_rate = self._get_fee_rate()  # Returns 0.024

        # Fee on OPEN (parent): $0
        fee_on_open = 0.0

        # Fee on CLOSE (follow-up): Applied to follow_up_price
        fee_on_close = follow_up_price * order_size * fee_rate

        # Total = close fee only (not both)
        total_fees = fee_on_open + fee_on_close

        # For BUY parent @ 50K, SELL follow-up @ 52.5K:
        # total_fees = 0 + (52500 × 1 × 0.024) = $1,260 ✓ CORRECT
```

## Verification Methods

### 1. Check Fee Multiplier
```python
fee_manager = FeeManager(REST_CLIENT)
info = fee_manager.explain_fee_multiplier()

print(info['base_fee_from_coinbase'])  # 0.006
print(info['multiplier_applied'])      # 4.0
print(info['effective_fee_rate'])      # 0.024
print(info['calculation_method'])      # "applied ONCE on the close order"
```

### 2. Check Profit Validator
```python
validator = ProfitValidator(fee_manager)
explanation = validator.explain_fee_calculation(50000, 52500, 1.0)

print(explanation['breakdown'])
# Shows:
# - Fee on open order: $0.00 (parent not charged)
# - Fee on close order: $1,260 (follow-up charged)
# - Total: $1,260 (close only, not both)
```

### 3. Run Tests
```bash
pytest tests/test_fee_multiplier_correctness.py -v

# Tests verify:
# ✓ Effective fee = base × 4
# ✓ Fee applied ONLY to close order
# ✓ Total = 2.4% for round-trip (charged on close price only)
```

## Code Review Checklist

When reviewing profit validation code, look for:

- [ ] FeeManager returns `base_fee × 4` from `get_profit_validation_fee_rate()`
- [ ] ProfitValidator applies fee to follow_up_price ONLY (not filled_price)
- [ ] Comments explain "fee charged on close order only"
- [ ] Example calculations show $0 on open, fee on close
- [ ] Test `test_fee_not_doubled_per_side` passes
- [ ] Explanation methods output: "Fee is charged ONLY when orders close"

## Red Flags (Things That Would Indicate A Bug)

If you see any of these, it's wrong:
```
❌ "fee_on_open = filled_price × size × fee_rate"
❌ "fee_on_filled" or "fee_on_parent"
❌ total_fees = fee_on_open + fee_on_close
❌ "charges both sides"
❌ "parent and follow-up both have fees"
❌ "0.006 × 2 on buy, 0.006 × 2 on sell"
❌ Total fees > 4.8% for simple round-trip
❌ Breakeven price > 4.8% above filled price (for simple case)
```

Correct indicators:
```
✓ "effective = base × 4"
✓ "fee_on_buy = price × size × effective_fee"
✓ "fee_on_sell = price × size × effective_fee"
✓ "total = 2 × effective_fee"
✓ Total fees ≈ 4.8% for simple round-trip
✓ Breakeven ≈ 4.8% above filled price (for simple case)
```

## For Future Developers

When adding MORE trades (not just parent→follow-up), remember:
- Each trade close incurs ONE fee
- Fee is charged based on the close price of that specific trade
- Apply 4x multiplier to Coinbase's base rate
- Do NOT multiply by 4 separately for each trade direction

Example with 3 trades:
```
Trade 1 (BUY): Fee = buy_price × size × (base × 4)
Trade 2 (SELL): Fee = sell_price × size × (base × 4)
Trade 3 (BUY again): Fee = buy_price × size × (base × 4)
Total: 3 × (base × 4) fees

NOT:
❌ (base × 2 × 2) × 3 = 3 × base × 4  (happens to be right, but wrong logic)
```

## Summary

**The Key Insight:** We charge 4x the Coinbase fee rate, applied ONCE per trade execution, not multiplied separately on each side.

```
Coinbase fee: 0.6% per trade
Our effective fee: 2.4% per trade (0.6% × 4)
Round-trip (2 trades): 4.8% total

This is achieved by:
1. FeeManager fetches 0.6%, returns 0.6% × 4 = 2.4%
2. ProfitValidator applies 2.4% to each trade once
3. Result: 2 × 2.4% = 4.8% (correct!)

NOT by:
1. Applying 2.4% to buy AND 2.4% to sell separately (would be 4.8%, but confusing)
2. Applying 0.6% × 2 to each side (1.2% per side = 2.4% total, not enough!)
3. Applying 0.6% × 2 × 2 to each side (2.4% per side = 4.8%, but suggests double-multiply)
```
