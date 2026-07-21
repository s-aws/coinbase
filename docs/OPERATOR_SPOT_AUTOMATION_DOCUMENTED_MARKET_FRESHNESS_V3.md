# Operator Spot Automation Documented Market Freshness V3

Goal: `operator_spot_automation_documented_market_freshness_successor_v3`

## Status

V3 is complete and terminal at Coinbase Preview. It is a distinct
preview-gated successor and does not reuse the V1 or V2
definition, plan, run, client identity, eligibility cycles, idempotency keys,
or Preview/Create/Cancel allowances. Creating a V3 definition is permitted only
after the durable V2 run is terminal. V1 and V2 rows are read-only predecessor
evidence.

Status: `complete_terminal_preview_rejected`.
Current action: `complete_v3_terminal_preview_rejected_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The authenticated Admin UI created exactly one V3 definition and one run. Eight
no-retry eligibility cycles made `8, 8, 8, 5, 8, 5, 8, 8` reads (`58` total).
Cycle 8 completed all eight categories and proved exact eligibility. The
backend then claimed and invoked exactly one Coinbase Preview. Coinbase returned
a documented rejection; durable readback is `automation_spot_preview_rejected`,
`REJECTED`, `DOCUMENTED_REJECTION`, warning present, and Preview identity
retention `UNAVAILABLE`. The raw response and withheld text were not persisted
or exposed. Create and Cancel stayed at zero, both allowances remain
unconsumed, no child exists, and the terminal run exposes no action. Total
Coinbase calls are exactly `59`.

Canonical terminal marker: V3 eligibility cycles `8/10`; exact Coinbase reads
`58`; Preview/Create/Cancel calls `1/0/0`; allowances
`consumed/unconsumed/unconsumed`; allowed actions `0`.

Validation evidence: backend full `1182 passed, 6 skipped` parallel and
`669 passed, 150 skipped` serial; frontend full `1565 passed`; E2E `15/15`;
build, typecheck, lint, generated-contract, command-security, and release gates
`PASS`; independent safety and blind-contextless audits `PASS`. The canonical
release/deployment gate passed, and every validation/deployment-smoke phase
reported no live Coinbase execution.

## Coinbase-documented source

V3 uses the authenticated Advanced Trade **Get Market Trades** endpoint for the
exact `BTC-USDC` product with `limit=1`:

- <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-market-trades>
- <https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api>

Coinbase documents the endpoint as a product-scoped snapshot of the latest
trades together with best bid and best ask. Each trade contains its Coinbase
market-event `time`. The pinned `coinbase-advanced-py==1.8.4` SDK exposes this
as `get_market_trades(product_id, limit, start=None, end=None)`.

V3 accepts the market category only when all of these checks pass:

1. Exactly one request is made with `product_id="BTC-USDC"` and `limit=1`.
2. The response has exactly one trade and that trade identifies `BTC-USDC`.
3. The same response has positive, non-crossed best bid and best ask values.
4. The trade `time` is an aware, parseable Coinbase timestamp.
5. That timestamp is no more than 30 seconds old at the backend decision
   boundary. V3 alone permits at most one second of positive Coinbase-to-host
   clock skew; larger future values fail closed. All other market sources keep
   zero future tolerance.
6. The unchanged standing-price policy accepts the immutable candidate against
   the best bid from that same snapshot.

The backend never substitutes request receipt time, host time, a top-level
response timestamp, product metadata, account freshness, or another proxy for
the trade event timestamp. The original Coinbase trade time remains the
persisted and downstream-bound observation. For bounded positive skew, expiry
is clamped to the earlier of trade-time-plus-30-seconds and
validation-time-plus-30-seconds, so the evidence can never outlive the existing
30-second guard. Missing, malformed, wrong-product, more-than-one-second future,
or stale trade evidence fails closed. The category remains one bounded logical
market read with zero retry or pagination.

The older Best Bid/Ask endpoint documents a `pricebooks[].time` field but does
not define that field's event semantics. V1/V2 retain their existing behavior;
only V3 uses the documented trade-event source.

### Audit-closed evidence shape

Independent review identified and closed two pre-candidate defects:

- Missing, malformed, zero, multiple, or unavailable V3 trade evidence now
  persists a fixed rejected market-category result with exact request
  accounting and `observed_at`, `fresh_until`, and `evidence_sha256` all NULL.
  No host or receipt clock is stored as market evidence. The database permits
  this NULL rejection shape only for V3 `BEST_BID_ASK`; the V1/V2 and all other
  category constraints remain unchanged. Idempotent schema initialization and
  backend restart preserve that exact rejected shape instead of applying the
  legacy unknown-evidence migration.
- Preliminary eligibility and exact-child safe-closeout now query eligibility
  cycles with the run's explicit durable goal key. They cannot fall through to
  the V1 default or read another successor's cycle ledger.

Synthetic tests cover missing method, zero/multiple trades, missing/malformed
trade time, wrong product, stale time, bounded clock skew, and excessive future
time. The canonical admission bundle retains the
`coinbase_rest_market_trade_snapshot` source instead of relabeling it as
Best-Bid/Ask evidence. The real-PostgreSQL contract proves the V3-only NULL
rejection and preserves the existing V1 rejection constraint.

## Durable and live boundaries

- The PostgreSQL goal ledger has one separate V3 row and at most one V3
  definition and run.
- V3 keeps the approved Test portfolio, `BTC-USDC`, one child, and the existing
  3.10 USDC submitted / 1.00 USDC possible-execution caps.
- Each eligibility cycle retains the same eight categories and exact call
  accounting. The market category changes only its documented source for V3.
- No Preview claim can be created until an exact fresh eligibility cycle and
  all installed validation and audit gates pass.
- Preview is single use. Create is reachable only after an accepted,
  error-free Preview for the identical candidate. Cancel is reachable only for
  the exact accepted nonterminal child. Unknown outcomes consume the applicable
  allowance.
- Raw responses, raw Preview identity, secrets, private identifiers, and
  exception-carried text are never persisted or returned.

## Historical source comparison

`origin/prod` used the Advanced Trade WebSocket ticker and its upstream event
time for market updates. Coinbase currently documents that public `-USDC`
subscriptions map to corresponding `-USD` products outside the user channel,
so that legacy path would not prove the exact `BTC-USDC` product required by
this goal. V3 therefore uses the exact-product authenticated REST market-trades
snapshot rather than recreating the legacy dashboard WebSocket authority.
