# Profit Tracking and Validation

Reconciled on 2026-10-09. Profit validation is a pre-placement estimate; it does
not guarantee profitable realized trades. Current implementation lives in
`calculation/fee_manager.py`, `calculation/profit_validator.py`, and
`business/profit_threshold_engine.py`. Earlier close-only fee and 4x-multiplier
notes are historical and must not drive current calculations.

## Fee selection

FeeManager maintains independent immutable SPOT/CBE and
FUTURE/EXPIRING/FCM transaction-summary snapshots under its RLock. Maker rates
are selected only for `post_only=True`; other placements use taker rates. A
failed filtered refresh preserves that schedule's last-known-good/default
snapshot. Futures refresh requires `has_cost_plus_commission=true`.

Current pre-fetch defaults are 0.001 taker and 0.0005 maker. Base validation
multipliers are SPOT 1.1 and FUTURE 1.0, with bounded volume/margin regime
adaptation. The resulting validation rate cannot undercut the selected
exchange rate. These are code defaults, not a statement of the account's live
tier. Public inspection uses `get_fee_schedule_snapshot`,
`get_profit_validation_fee_quote`, and `get_fee_info`.

## Round-trip profitability

ProfitValidator prices both the opening fill and proposed closing fill. For
spot, percentage fees apply to each leg's notional; futures also account for
contract size and fixed cost on each contract side. `core/constants.py` owns the
fixed-cost resolver: default/BIP 0.12 per contract side and the explicitly
retained legacy full-size BTI/ETI/SLC/XRL 0.27 assumption. Actual ledger fees
remain exchange-reported evidence; calculation defaults never rewrite them.

A placement quote must use one atomic fee sample, the actual normalized
submitted price, product classification/contract metadata, and the resolved
parent target movement. `P` is a fractional percentage target; `A` is absolute
quote-unit movement. Position opening/closing classification does not make
an opening fill fee-free.

## Fill accounting

`business/order_progress.py` derives cumulative-quantity/value/fee deltas and
UUID5 `derived_trade_key` values per internal `client_order_id`.
`business/fill_ledger.py` appends WS_DERIVED rows; `business/fill_reconciler.py`
uses owned REST historical fills to stamp exchange trade/entry IDs and
RECONCILED evidence. Submission ownership comes from
`order_event_stream` order_submitted/rest_submit rows.

Lot helpers in `business/position_lot.py`, `business/lot_builder.py`, and
`business/post_fill_hook.py` support lot accounting; historical lot integration
notes do not prove every runtime hook is enabled. Follow current callers and
ledger evidence rather than completion banners.

## Validation navigation

Relevant checked-in coverage includes `test_two_sided_fee_accounting.py`,
`test_profitability_fee_quote_consistency.py`, `test_filtered_fee_schedules.py`,
`test_per_side_mandatory_fee.py`, and `test_cross_source_reconciliation.py` in
`tests/regression/`. Run the complete local gate in `TESTING_STRATEGY.md`;
focused selections require an explicit user request.
