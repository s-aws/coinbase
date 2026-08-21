# Product-Specific Profitability Considerations

## Overview

Profitability calculations must account for fundamental differences in how products work:

| Aspect | SPOT | FUTURE | PERPETUAL |
|--------|------|--------|-----------|
| **What it is** | Direct asset purchase/sale | Contract settlement at expiry | Perpetual contract (no expiry) |
| **Leverage** | 1x (no margin) | Up to 20x | Up to 20x |
| **Liquidation** | No liquidation | Yes, if margin below maintenance | Yes, if margin below maintenance |
| **Funding rates** | None | None (expiry-based) | Yes (continuous) |
| **Settlement** | Immediate | At contract expiry | Continuous |
| **Fee structure** | Taker/maker on trade | Taker/maker on trade | Taker/maker + funding |
| **Position risk** | Limited to stake | Can exceed stake (margin call) | Can exceed stake (margin call) |

## SPOT Products

### How Profitability Works
- **Simple**: Buy low, sell high
- **No leverage**: Can only invest what you have
- **No margin calls**: Worst case is loss of entire stake
- **No liquidation**: Position holds until you close it

### Profit Calculation
```
Profit = (sell_price - buy_price) × quantity - fees
Risk: Limited to initial investment
```

### Profitability Validation
- Only need to ensure: profit > fee_on_close
- No additional margin/liquidation checks needed
- All positions are fully secured

## FUTURE Products

### How Profitability Works
- **Leverage-based**: Can control larger positions with less capital
- **Margin requirement**: Need minimum margin to hold position
- **Liquidation risk**: If margin falls below maintenance level, position liquidates
- **Expiry dates**: Contracts expire and settle

### Profit Calculation
```
Profit = (close_price - open_price) × quantity × leverage - fees
Risk: Can lose more than invested (margin call)
Risk: Position auto-closes at liquidation price
```

### Profitability Validation Requirements
1. **Basic profitability**: profit > fee_on_close ✓ (same as SPOT)
2. **Margin sufficiency**: Ensure margin > maintenance margin
3. **Liquidation distance**: Follow-up price shouldn't trigger liquidation
4. **Expiry awareness**: Trade must close before contract expiry

### Example Risk Scenario
```
Position: LONG 10 BTC contracts @ $50,000 with 20x leverage
Leverage: 20x (posted margin = $50,000/20 = $2,500)
Maintenance margin: 0.5% of position notional = $2,500

Follow-up order: SELL @ $49,875
Liquidation price: $50,000 × (1 - 0.005) = $49,750

⚠️ PROBLEM: Follow-up price $49,875 is ABOVE liquidation $49,750
Position could liquidate before follow-up order fills!
Minimum safe price: > $49,750 + buffer
```

## PERPETUAL Products

### How Profitability Works
- **Leverage-based**: Can control larger positions with less capital
- **Margin requirement**: Need minimum margin to hold position
- **Liquidation risk**: Same as FUTURE
- **No expiry**: Positions can be held indefinitely
- **Funding rates**: Continuous payments between long/short
  - If rate > 0: Longs pay shorts (bullish sentiment)
  - If rate < 0: Shorts pay longs (bearish sentiment)

### Profit Calculation
```
Profit = (close_price - open_price) × quantity × leverage - fees - funding_costs
Funding cost = size × funding_rate × time_held
```

### Profitability Validation Requirements
1. **Basic profitability**: profit > fee_on_close ✓ (same as SPOT)
2. **Margin sufficiency**: Ensure margin > maintenance margin
3. **Liquidation distance**: Follow-up price shouldn't trigger liquidation
4. **Funding rate consideration**: Account for funding costs over holding period
5. **Time sensitivity**: Longer hold = higher funding cost

### Example: Funding Rate Impact
```
Position: LONG 1 BTC @ $50,000 perpetual with 10x leverage
Posted margin: $50,000 / 10 = $5,000
Funding rate: +0.01% per 8 hours (longs pay shorts, bullish market)

Holding for 24 hours:
Funding cost = $50,000 × 10 (contracts) × 0.01% × 3 (periods)
            = $50,000 × 10 × 0.0001 × 3 = $15

Expected profit to close at $51,000: $10,000
After funding: $10,000 - $15 = $9,985 (still profitable)
```

## Product-Specific Validation Matrix

### SPOT
- [x] Profitability: profit > fee
- [ ] Margin validation (N/A)
- [ ] Liquidation validation (N/A)
- [ ] Funding rates (N/A)
- [ ] Expiry dates (N/A)

### FUTURE
- [x] Profitability: profit > fee
- [x] Margin validation: ensure adequate margin
- [x] Liquidation validation: safe distance from liquidation
- [ ] Funding rates (N/A)
- [x] Expiry validation: trade closes before expiry

### PERPETUAL
- [x] Profitability: profit > fee
- [x] Margin validation: ensure adequate margin
- [x] Liquidation validation: safe distance from liquidation
- [x] Funding rates: account for expected funding costs
- [ ] Expiry dates (N/A)

## Implementation Implications

### Current Status
✅ **SPOT profitability**: Fully implemented
✅ **FUTURE/PERPETUAL open/close logic**: Fully implemented with position context
⚠️ **FUTURE margin/liquidation validation**: Not yet implemented
⚠️ **PERPETUAL funding rate accounting**: Not yet implemented

### Next Steps (Future Work)
1. Add margin validation for FUTURE/PERPETUAL
2. Calculate and validate liquidation distance
3. Fetch and account for funding rates in PERPETUAL
4. Add expiry date validation for FUTURE
5. Create product-specific validator subclasses:
   - `SpotProfitValidator`
   - `FutureProfitValidator`
   - `PerpetualProfitValidator`

### Data Needed for Complete Validation

**For FUTURE/PERPETUAL:**
- Current margin: Available margin balance
- Maintenance margin ratio: Typically 0.5-2% depending on exchange
- Position size: In contracts or USD notional
- Current fill prices: For calculating PnL
- Liquidation price: Calculated from margin and leverage
- Contract multiplier: Converts contracts to USD (e.g., 1 contract = 0.001 BTC)
- Expiry date: For FUTURE contracts only

**For PERPETUAL only:**
- Current funding rate: % per funding period
- Funding period: Typically 8 hours
- Expected holding time: To calculate total funding cost

## Example: Complete Product-Specific Check

```python
def validate_profitability_by_product(product_type, order_data):
    """Validate profitability considering product-specific risks."""

    # Step 1: Basic profitability check (all products)
    result = profit_validator.is_profitable(...)
    if not result['is_profitable']:
        return False, "Basic profitability check failed"

    # Step 2: Product-specific checks
    if product_type == 'SPOT':
        return True, "SPOT: Profitability verified"

    elif product_type == 'FUTURE':
        # Validate margin isn't consumed
        if order_data['margin'] < order_data['maintenance_margin']:
            return False, "Insufficient margin for FUTURE"

        # Validate liquidation distance
        if abs(follow_up_price - liquidation_price) < liquidation_buffer:
            return False, f"Too close to liquidation at {liquidation_price}"

        # Validate contract hasn't expired
        if current_time > contract_expiry:
            return False, "Contract expired"

        return True, "FUTURE: All validations passed"

    elif product_type == 'PERPETUAL':
        # Validate margin isn't consumed
        if order_data['margin'] < order_data['maintenance_margin']:
            return False, "Insufficient margin for PERPETUAL"

        # Validate liquidation distance
        if abs(follow_up_price - liquidation_price) < liquidation_buffer:
            return False, f"Too close to liquidation at {liquidation_price}"

        # Account for funding costs
        holding_hours = order_data['expected_holding_hours']
        funding_periods = holding_hours / 8
        funding_cost = notional * funding_rate * funding_periods

        if result['net_profit'] < funding_cost:
            return False, f"Profit {result['net_profit']} insufficient for funding costs {funding_cost}"

        return True, "PERPETUAL: All validations passed including funding"
```

## Conclusion

While the core profitability logic (price difference - fees) is universal, the risk assessment and validation requirements are **strongly product-specific**:

- **SPOT**: Simplest, just check profit > fees
- **FUTURE**: Must validate margin and liquidation risk
- **PERPETUAL**: Must additionally account for continuous funding costs

The current implementation handles the open/close logic correctly for each product type, but additional product-specific validations should be added as the system matures.
