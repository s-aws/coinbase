# Adaptive Fee Regime Integration Map

This document explains where adaptive fee and follow-up spacing logic is integrated in the current codebase.

## Objective

The integration keeps a single follow-up processing path and adds adaptive behavior by changing inputs to existing logic:

- tighter follow-up spacing in overnight or low-volume regimes
- wider follow-up spacing in high-volume regimes
- adaptive effective fee for profitability validation

## Integration Points

### 1. Fee and Regime Source of Truth

File: calculation/fee_manager.py

Core responsibilities:
- fetch Coinbase base taker fee from transaction summary
- track rolling volume regime per product
- track margin window regime (including overnight)
- provide adaptive multipliers consumed by existing engine/validator flow

Key methods:
- update_volume_signal: calculation/fee_manager.py:299
- update_margin_window_type: calculation/fee_manager.py:332
- update_margin_window_from_summary: calculation/fee_manager.py:363
- get_target_movement_multiplier: calculation/fee_manager.py:382
- get_profit_validation_fee_rate: calculation/fee_manager.py:388
- get_fee_info: calculation/fee_manager.py:398

### 2. WebSocket Channel Subscription

File: configuration.py

- Added futures balance summary channel to the existing subscription list so margin-window signals are available to the current worker loop:
  - configuration.py:1041

### 3. OrderEngine Signal Ingestion

File: core/order_engine.py

Ticker path integration:
- ticker product is normalized to trading product
- volume_24_h is forwarded into FeeManager as a regime signal
- location:
  - core/order_engine.py:2508

Futures balance summary integration:
- existing worker switch handles FUTURES_BALANCE_SUMMARY channel
- message is parsed and forwarded to FeeManager margin-window updater
- locations:
  - core/order_engine.py:1085
  - core/order_engine.py:2540
  - core/order_engine.py:2541

### 4. Follow-Up Target Movement Adaptation

File: core/order_engine.py

- Existing resolve_parent_target_movement flow now applies FeeManager target multiplier for percentage targets.
- Absolute targets are unchanged.
- location:
  - core/order_engine.py:1387

This preserves the existing template pipeline:
- resolve parent target movement
- compute order template
- place follow-up through existing path

### 5. Profitability Validation Fee Adaptation

File: calculation/profit_validator.py

- ProfitValidator now requests product-aware adaptive effective fee from FeeManager.
- locations:
  - calculation/profit_validator.py:105
  - calculation/profit_validator.py:108
  - calculation/profit_validator.py:121

### 6. Dashboard/Status Visibility

File: core/order_engine.py

- Engine status payload includes adaptive metrics from FeeManager (effective fee, target factor, fee factor, volume ratio, overnight state, margin window type).
- locations:
  - core/order_engine.py:2601
  - core/order_engine.py:2654
  - core/order_engine.py:2664

## Deadlock-Safety Hardening Applied

File: calculation/fee_manager.py

- Margin window update logging now happens outside FeeManager lock.
- This avoids callback-under-lock risk while preserving behavior.
- location:
  - calculation/fee_manager.py:332

## Tests Covering Integration

Unit tests:
- tests/unit/test_fee_regime_adaptation.py:46
- tests/unit/test_fee_regime_adaptation.py:65
- tests/unit/test_fee_regime_adaptation.py:81
- tests/unit/test_fee_regime_adaptation.py:101
- tests/unit/test_fee_regime_adaptation.py:119

Integration test:
- tests/integration/test_adaptive_follow_up_spacing_integration.py:82

## Notes

- No new parallel execution path was introduced for follow-up creation.
- Adaptive logic is injected through existing target-movement and profitability calculations.
- Existing parent/child tracking semantics and client_order_id usage remain unchanged.
