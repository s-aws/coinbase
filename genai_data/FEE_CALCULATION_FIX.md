# Fee Calculation Fix for Futures Contracts

## Problem
The percentage-based fee calculation in `ProfitValidator.is_profitable()` was incorrectly treating `order_size` as a unit size (BTC/USD) when it was actually a **contract count**. This caused fees to be vastly overestimated for futures contracts.

### Example
For a BIP-20DEC30-CDE futures order:
- **Order size**: 10 contracts
- **Contract size**: 0.01 BTC per contract  
- **Actual position size**: 10 × 0.01 = 0.1 BTC
- **Follow-up price**: $78,375
- **Base fee rate**: 2.4%

**BEFORE FIX (WRONG)**:
```
Fee = $78,375 × 10 (contract count) × 0.024 = $18,810.00 ❌
```
This incorrectly multiplied by the contract count rather than actual BTC amount.

**AFTER FIX (CORRECT)**:
```
Effective size = 10 contracts × 0.01 BTC = 0.1 BTC
Fee = $78,375 × 0.1 (BTC) × 0.024 = $188.10 ✓
```

## Solution
Updated `ProfitValidator.is_profitable()` to:

1. **Accept `contract_size` parameter** - Get contract size (e.g., 0.01 BTC for nano contracts)
2. **Convert order_size to effective_size** - For futures/perpetuals: `effective_size = order_size × contract_size`
3. **Use effective_size in calculations** - Both gross profit and fees now use the actual position size

### Changes Made

#### 1. `calculation/profit_validator.py`
- Added `contract_size: float = None` parameter to `is_profitable()` method
- Added logic to convert contract count to effective size for futures/perpetuals
- Updated gross profit calculation to use effective_size
- Updated percentage fee calculation to use effective_size
- Added debug logging for the conversion

#### 2. `core/order_engine.py`
- Updated the call to `is_profitable()` to extract and pass `contract_size`
- Contract size is extracted from: `product_data["future_product_details"]["contract_size"]`
- Uses `safe_float()` to handle string-to-float conversion with default of 1.0

## Testing
Created `genai_tools/test_fee_calculation_fix.py` which verifies:
- ✓ Percentage fees are now correctly calculated for futures
- ✓ Gross profit calculation accounts for actual position size
- ✓ Net profit is now realistic (not hugely negative due to inflated fees)
- ✓ All 10 regression tests still pass

## Impact
This fix ensures:
- **Futures orders** have correctly calculated profitability checks
- **No false negatives** where profitable orders were rejected due to incorrect fee calculation  
- **Accurate P&L tracking** for follow-up orders
- **Backward compatible** - SPOT orders unaffected (contract_size=None)

## Contract Size Reference
Common contract sizes in Coinbase Futures:
- Nano BTC (BIP): 0.01 BTC per contract
- Micro BTC (BIT): 0.001 BTC per contract
- Full BTC futures: 1.0 BTC per contract
- See `products.json` metadata for `future_product_details.contract_size`
