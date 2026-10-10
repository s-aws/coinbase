# Adaptive Fee Regime Integration

Reconciled on 2026-10-09. Symbol references replace stale numeric line anchors.

| Source | Current integration |
| --- | --- |
| `calculation/fee_manager.py::FeeManager` | Separate SPOT/CBE and FUTURE/EXPIRING/FCM snapshots, maker/taker quotes, bounded volume/margin factors |
| `configuration.py::Subscription` | Public ticker/heartbeat roles and one private user/futures-balance/heartbeat role |
| `core/order_engine.py::OrderEngine.generate_process_event_worker` | Trading-product normalization and `update_volume_signal` ingestion |
| `core/order_engine.py::OrderEngine.process_futures_balance_summary_event` | Margin-window signal ingestion |
| `core/order_engine.py::OrderEngine.resolve_parent_target_movement` | Adaptive percentage-target multiplier; absolute targets remain absolute |
| `calculation/profit_validator.py::ProfitValidator.validate_order_profitability` | Atomic product/post-only fee quote and round-trip profitability at submitted price |
| `calculation/fee_manager.py::FeeManager.get_fee_info` | Fee source, rate, liquidity, volume/margin regime telemetry |

Base validation multipliers are SPOT 1.1 and FUTURE 1.0, with bounded adaptation;
validation never discounts below the selected exchange rate. Maker applies only
to post-only intent. Fixed CDE per-side cost is separate and resolved through
`core/constants.py::get_derivatives_per_side_fee`.

FeeManager uses an RLock; `update_margin_window_type` logs outside that lock.
Shared instance injection preserves one fee source and one follow-up path.

Relevant checked-in tests include `tests/unit/test_fee_regime_adaptation.py`,
`tests/integration/test_adaptive_follow_up_spacing_integration.py`, and
filtered-fee / two-sided profitability regressions. Run the full local gate
in `genai_data/TESTING_STRATEGY.md`; live diagnostics are separately scoped.
