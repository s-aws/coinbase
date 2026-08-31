# Changelog

This changelog records major operator-visible changes and major defect fixes on
`origin/prod`. It begins with the production revival on 2026-08-13; earlier
history is not reconstructed here.

## Unreleased

- No operator-visible runtime changes recorded yet.

## Production revival — 2026-08-13 through 2026-08-29

Scope: commits after the prior 2026-05-04 `prod` baseline through
`e264793f7` (`part 13 - ui button add`). Context-only, repository-graph,
test-only, and live-evidence commits are intentionally omitted below.

### Added

- Declared the Python 3.13 installable runtime and its production dependencies
  in `pyproject.toml`, and refreshed the configured Coinbase product catalog.
- Added one canonical exchange-bound limit-price normalizer and one fail-closed
  Coinbase placement-response classifier. Direct, stealth, hotpoint, and move
  paths now share explicit tick-rounding and acceptance semantics.
- Added configurable non-negative price-hold duration to both the order-span
  builder and stealth manager UIs. Zero seconds now means trigger on the first
  qualifying price event instead of inheriting a hidden two-second delay.
- Added a centralized event/deadline scheduler for stealth decisions. Ordered
  product ticker evidence, generational monotonic deadlines, continuous hold
  reset, time wakes, admission retries, and anchor wakes replace blanket
  polling for the conditions they own; compatibility-only evaluators retain a
  bounded recheck path.
- Added fail-closed runtime startup and shutdown states with atomic
  admission/in-flight accounting, startup readiness publication, single-owner
  drain, and cooperative admin/signal shutdown. Startup now defaults to
  `PAUSED`; automatic `RUNNING` requires `ENGINE_START_PAUSED=false`.
- Split transport ownership into redundant public ticker/heartbeat clients and
  exactly one authenticated private client. The private path now has
  connection-global sequence fencing, paginated snapshot bootstrap, bounded
  whole-envelope reduction, keyed FIFO lifecycle completion, and fail-closed
  reconnect on corruption, malformed payloads, overflow, or timeout.
- Added authoritative engine-state display and a confirmed, fail-closed
  **Resume Engine** control to `ui_stealth_orders_manager.html`.

### Changed

- Fee telemetry now keeps independent filtered Coinbase schedules for
  `SPOT/CBE` and `FUTURE/EXPIRING/FCM`. Maker pricing is selected only for
  `post_only=true`; every other placement assumes taker pricing.
- Profitability validation now uses one atomic fee quote at the actual
  submitted price and charges both sides of the projected trade. The
  settlement-reconciled default CFM fixed cost is `$0.12` per contract per
  side; full-size `BTI`/`ETI`/`SLC`/`XRL` retain the explicitly isolated legacy
  `$0.27` assumption pending separate reconciliation.
- Startup now hydrates local stealth state, requires an authoritative
  exchange/local reconciliation unless explicitly bypassed, builds derived
  schedules, and starts required workers before opening admission. Periodic
  drift and missed-fill reconciliation uses the same exchange-truth model.

### Fixed

- Malformed or Cloudflare-style 5xx product responses no longer abort product
  initialization. Startup falls back to the validated local product catalog,
  and an unavailable futures-position read falls back to an empty snapshot
  with an explicit error.
- Corrected off-tick and path-dependent prices: the effective normalized price
  is now consistently used for persistence, in-memory state, profitability,
  and REST submission. Missing or invalid product metadata fails closed.
- Corrected false placement success. A non-raising SDK call, malformed success
  envelope, missing exchange order ID, mismatched client order ID, rejection,
  or transport exception can no longer silently advance revealed size or
  active-placement state as though Coinbase accepted the order.
- Corrected continuous-condition durability. `PENDING` and `TRIGGERED`
  transitions persist before lifecycle publication; failed persistence rolls
  memory back and pauses decision processing instead of revealing from
  uncommitted state.
- Corrected redundant-public-socket ticker handling. Fan-out duplicates are
  deduplicated before socket-specific timestamps are attached, and a late
  out-of-order observation can only invalidate a temporally relevant hold; it
  cannot replace current market, anchor, or dashboard state.
- Corrected paused-trigger retry flooding. A `TRIGGERED` stealth order no
  longer rearms a 100 ms retry loop while admission is closed; opening
  admission publishes exactly one immediate retry per eligible order with one
  successor owner.
- Persisted and hydrated `reveal_pricing_policy`, so `top_of_book` and
  `midpoint` intent survives a manager/process restart. Rows without historical
  policy truth safely retain `configured_limit`.
- Cancellation-created stealth follow-ups now claim the original root's
  replacement budget atomically, create no child when the cap is exhausted,
  and release the pending claim when creation returns no ID or raises.
- `EXPIRED` private order updates now receive terminal cleanup only and no
  longer enter filled/cancelled replacement behavior.

### Validation status at the revival boundary

- The latest runtime/UI commit completed the full local non-external suite with
  1,552 passing tests and 11 external tests deselected.
- External and live-exchange validation remains opt-in and is not implied by
  the local result.
