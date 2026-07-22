# Operator Spot Automation Near-Market V4-V6

Goal ID:
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`

Checkpoint status: `ready_for_bounded_operator_proof`.

No goal-scoped Coinbase call has run at this checkpoint. V4-V6 preparation,
eligibility, Preview, Create, and Cancel allowances remain unconsumed in the
installed operator database until an authenticated operator explicitly starts
the workflow after validation and both independent audits pass.

## Narrow policy boundary

Policy revision `BTC_USDC_POST_ONLY_BEST_BID_V1` applies only to the distinct
V4-V6 successor ledgers for the approved Test portfolio and `BTC-USDC`. It does
not change direct Spot orders, V1-V3, follow-up orders, Futures, schedulers,
ladders, sweeps, or any global standing-order rule.

The backend derives every order term. It accepts no browser-supplied portfolio
identifier, price, size, child identity, Preview identity, or exchange order
identity. From one documented Get Market Trades response it validates exactly
one `BTC-USDC` trade event time and the response's same-snapshot `best_bid` and
`best_ask`. The trade time must be aware, no more than 30 seconds old, and no
more than one second in the future.

The limit is:

`floor(best_bid / price_increment) * price_increment`

It must be positive and strictly below the same-snapshot best ask. The child is
a `BUY` `LIMIT` / `GOOD_UNTIL_CANCELLED` order with `post_only=true`.

The backend reserves the documented maker fee and computes:

`notional_budget = min(3.10, 1.00, available_USDC / (1 + maker_fee_rate))`

It then floors `notional_budget / limit_price` to `base_increment`. The result
must meet `base_min_size` and `quote_min_size`, remain within both installed
caps, and remain covered by the observed USDC wallet after the maker-fee
reserve. `near_market_no_valid_size` is terminal for candidate preparation and
leaves Preview, Create, and Cancel unconsumed.

Coinbase documents the product increments and minimums in
[Get Product](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-product),
the trade timestamp plus same-response best bid/ask in
[Get Market Trades](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-market-trades),
and `limit_limit_gtc.post_only` plus Preview response fields in
[Preview Order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders).

## Durable preparation and call accounting

`POST /api/v1/automation/near-market-candidates` requires authenticated
`automation:configure`, `automation:trigger`, `automation:resume`, and
`account_reality:refresh` authority plus exact acknowledgement literals. Before
the first external read, PostgreSQL claims one goal-global cycle and selects
only the next sequential V4, V5, or V6 ledger.

One preparation cycle invokes the approved read subset in fixed order, once
each and without retry: API-key permissions, portfolio catalog, strict paged
wallet balances, product metadata, Get Market Trades, and Spot fee summary.
Wallet pagination may complete its logical category, but no page is retried.
The durable count includes every underlying request. A transport ambiguity
records an unknown count and consumes the cycle.

Successful derivation atomically creates the immutable definition and plan,
binds the approved portfolio hash and near-market goal ledger, and finalizes
the preparation record. A near-market definition cannot be created through
the generic definition endpoint or directly in the repository without the
matching claimed materialization evidence. Preparation and the existing
eight-category run eligibility allocator share one goal-global ten-cycle
namespace across V4-V6.

The canonical preparation evidence hash covers the exact diagnostic, outcome,
call count, ordered completed categories, policy revision, and every persisted
plan term, including both caps and both notional values. The repository
independently recomputes that hash before the atomic definition/plan insert;
shape-valid but unrelated hashes fail closed. PostgreSQL triggers make the
claim identity and correlation binding immutable, permit only one
`CLAIMED`-to-terminal transition, and reject deletion. Restart recovery turns
an interrupted claimed preparation into `UNKNOWN` with unknown call count and
no candidate.

The resulting run reuses the canonical Preview-gated single-child coordinator.
Its final eligibility cycle performs the approved eight categories, including
exact-order reconciliation and the account-wide active Spot-order catalog. A
fresh plan at or below the current same-snapshot bid and below the ask may
reach one durable Preview claim. Only an accepted response with no `errs` may
reach the identical one-use Create claim. The canonical exact-child safe
closeout path can claim at most one Cancel only when authoritative readback
still shows that child nonterminal.

Every unknown outcome consumes its applicable claim. There is no retry,
fallback, redirect, alternate child, second Create, fan-out, scheduler,
Futures action, product expansion, or parallel Coinbase path.

The control-plane readback exposes a separate
`near_market_candidate_preparation_allowed` decision. It is true only for an
active control posture, locally ready execution runtime, and an actor holding
all four permissions required by the preparation route. The generic
definition-create request contract separately fixes `post_only=false`; only
backend-derived V4-V6 readback can contain `post_only=true`.

## Privacy and compatibility

Only fixed diagnostics, exact-or-unknown call accounting, hashes, immutable
plan terms, and approved operator readback are persisted. Raw Coinbase
responses, raw Preview identifiers, credentials, private portfolio identifiers,
and exception text are not persisted or rendered. Predecessor evidence and
R1-R12 artifacts are not rewritten; R8 content and hash remain inaccessible.

The historical `origin/prod` comparison used
`core/stealth_order_manager.py` for its top-of-book post-only concept and
`core/order_engine.py` for increment-aware order construction. The legacy
`dashboard_server.py` direct path used `post_only=false` and was not reused.
The current backend-owned Admin API, PostgreSQL claims, generated contracts,
canonical Spot services, and BFF remain authoritative.

## Validation checkpoint

Focused backend policy, preparation, eligibility, command-safety,
orchestration, route, model, and repository coverage passes. The repository
tests cover preparation through revision-3 eligibility, exact evidence
binding, immutable/delete-proof storage, restart recovery, the shared ten-cycle
budget, V4 rejection, V5 unknown, V6 acceptance, Preview claims, Create claim,
and exact-child Cancel finalization without an external call.
Frontend component, runtime, API-client, mutation-contract, BFF-route, typecheck,
generated-contract, and routed Playwright checks pass. Complete backend
regression passed `1195` with `6` skipped in parallel and `676` with `150`
skipped in serial isolation. The canonical frontend release gate passed,
including `229` deployment-focused tests, `1573` full Vitest tests, installed
deployment smoke, and routed Playwright E2E. Independent safety and
blind-contextless audits returned `PASS`. No Coinbase call ran during
validation. Exact-commit Controlled-live deployment and the bounded operator
proof remain.
