#!/usr/bin/env python3
"""Test script to verify the fee calculation fix for futures contracts.

This test verifies that percentage fees are correctly divided by contract_size
for FUTURE/PERPETUAL products, matching the fix described in the issue.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from calculation.profit_validator import ProfitValidator
from calculation.fee_manager import FeeManager

def test_futures_fee_calculation():
    """Test that futures percentage fee is correctly adjusted for contract_size."""

    # Initialize validator with fee manager
    from configuration import REST_CLIENT
    fee_manager = FeeManager(rest_client=REST_CLIENT)
    validator = ProfitValidator(fee_manager=fee_manager)

    # Test case from logs: BIP-20DEC30-CDE
    # Parent BUY filled at $78,200, Follow-up SELL at $78,375
    # Size: 10.0, Contract size: 0.01 BTC
    # Base fee rate: 0.6% × 4 = 2.4% (0.024)

    filled_price = 78200.0
    follow_up_price = 78375.0
    order_size = 10.0
    contract_size = 0.01
    product_type = 'FUTURE'
    position_side = 'SHORT'  # From logs: "Position side: SHORT"

    # Test WITHOUT contract_size (old behavior - INCORRECT)
    print("=" * 80)
    print("BEFORE FIX (without contract_size adjustment):")
    print("=" * 80)

    result_before = validator.is_profitable(
        filled_price=filled_price,
        follow_up_price=follow_up_price,
        side='BUY',  # Parent order was BUY
        order_size=order_size,
        product_type=product_type,
        position_side=position_side,
        contract_size=None  # OLD BEHAVIOR - no adjustment
    )

    print(f"Filled Price:        ${filled_price:,.2f}")
    print(f"Follow-up Price:     ${follow_up_price:,.2f}")
    print(f"Order Size:          {order_size} contracts")
    print(f"Contract Size:       {contract_size} BTC")
    print(f"Product Type:        {product_type}")
    print(f"Position Side:       {position_side}")
    print()
    print(f"Gross Profit:        ${result_before['gross_profit']:,.2f}")
    print(f"Percentage Fee Rate: {result_before['fee_rate_applied']:.6f} ({result_before['fee_rate_applied']*100:.4f}%)")
    print(f"Percentage Fees:     ${result_before['percentage_fees']:,.2f}")
    print(f"Mandatory Fees:      ${result_before['mandatory_fees']:,.2f}")
    print(f"Total Fees:          ${result_before['total_fees']:,.2f}")
    print(f"Net Profit:          ${result_before['net_profit']:,.2f}")
    print(f"Is Profitable:       {result_before['is_profitable']}")

    # Test WITH contract_size (new behavior - CORRECT)
    print()
    print("=" * 80)
    print("AFTER FIX (with contract_size adjustment):")
    print("=" * 80)

    result_after = validator.is_profitable(
        filled_price=filled_price,
        follow_up_price=follow_up_price,
        side='BUY',  # Parent order was BUY
        order_size=order_size,
        product_type=product_type,
        position_side=position_side,
        contract_size=contract_size  # NEW - contract_size adjustment
    )

    print(f"Filled Price:        ${filled_price:,.2f}")
    print(f"Follow-up Price:     ${follow_up_price:,.2f}")
    print(f"Order Size:          {order_size} contracts")
    print(f"Contract Size:       {contract_size} BTC")
    print(f"Product Type:        {product_type}")
    print(f"Position Side:       {position_side}")
    print()
    print(f"Gross Profit:        ${result_after['gross_profit']:,.2f}")
    print(f"Percentage Fee Rate: {result_after['fee_rate_applied']:.6f} ({result_after['fee_rate_applied']*100:.4f}%)")
    print(f"Percentage Fees:     ${result_after['percentage_fees']:,.2f}")
    print(f"Mandatory Fees:      ${result_after['mandatory_fees']:,.2f}")
    print(f"Total Fees:          ${result_after['total_fees']:,.2f}")
    print(f"Net Profit:          ${result_after['net_profit']:,.2f}")
    print(f"Is Profitable:       {result_after['is_profitable']}")

    # Comparison
    print()
    print("=" * 80)
    print("COMPARISON (Old vs New):")
    print("=" * 80)
    print(f"Percentage Fees Difference: ${result_before['percentage_fees'] - result_after['percentage_fees']:,.2f}")
    print(f"Total Fees Difference:      ${result_before['total_fees'] - result_after['total_fees']:,.2f}")
    print(f"Net Profit Difference:      ${result_after['net_profit'] - result_before['net_profit']:,.2f}")
    print()

    # Calculate expected values manually
    print("=" * 80)
    print("MANUAL VERIFICATION:")
    print("=" * 80)

    base_fee_rate = 0.024  # 2.4%
    print(f"Base fee rate (0.6% × 4): {base_fee_rate:.6f} ({base_fee_rate*100:.4f}%)")
    print()

    # For FUTURES: order_size is in contracts, need to convert to actual units (BTC)
    actual_size = order_size * contract_size  # 10 contracts × 0.01 BTC/contract = 0.1 BTC
    print(f"Order size (contracts): {order_size}")
    print(f"Contract size (BTC): {contract_size}")
    print(f"Actual size (BTC): {order_size} × {contract_size} = {actual_size}")
    print()

    gross_profit = (follow_up_price - filled_price) * actual_size
    print(f"Gross Profit: ({follow_up_price} - {filled_price}) × {actual_size} = ${gross_profit:,.2f}")

    # OLD (WRONG): Used contract count as size
    old_pct_fee = follow_up_price * order_size * base_fee_rate
    print(f"OLD Percentage Fee: {follow_up_price} × {order_size} (contracts) × {base_fee_rate} = ${old_pct_fee:,.2f} ❌ WRONG")

    # NEW (CORRECT): Use actual size (contracts × contract_size)
    new_pct_fee = follow_up_price * actual_size * base_fee_rate
    print(f"NEW Percentage Fee: {follow_up_price} × {actual_size} (BTC) × {base_fee_rate} = ${new_pct_fee:,.2f} ✓ CORRECT")
    print()

    # Mandatory fee is still per contract
    mandatory_fee = 0.15 * order_size
    print(f"Mandatory Fee: $0.15 × {order_size} contracts = ${mandatory_fee:,.2f}")
    print()

    old_total_fee = old_pct_fee + mandatory_fee
    new_total_fee = new_pct_fee + mandatory_fee

    old_net_profit = gross_profit - old_total_fee
    new_net_profit = gross_profit - new_total_fee

    print(f"OLD Total Fees: ${old_pct_fee:,.2f} + ${mandatory_fee:,.2f} = ${old_total_fee:,.2f}")
    print(f"OLD Net Profit: ${gross_profit:,.2f} - ${old_total_fee:,.2f} = ${old_net_profit:,.2f} ❌ WRONG")
    print()
    print(f"NEW Total Fees: ${new_pct_fee:,.2f} + ${mandatory_fee:,.2f} = ${new_total_fee:,.2f}")
    print(f"NEW Net Profit: ${gross_profit:,.2f} - ${new_total_fee:,.2f} = ${new_net_profit:,.2f} ✓ CORRECT")
    print()

    # Verify results match our calculations
    assert abs(result_after['percentage_fees'] - new_pct_fee) < 0.01, f"Percentage fee mismatch: {result_after['percentage_fees']} vs {new_pct_fee}"
    assert abs(result_after['net_profit'] - new_net_profit) < 0.01, f"Net profit mismatch: {result_after['net_profit']} vs {new_net_profit}"

    print("=" * 80)
    print("✓ TEST PASSED: Fee calculation fix is working correctly!")
    print("=" * 80)


if __name__ == '__main__':
    test_futures_fee_calculation()
