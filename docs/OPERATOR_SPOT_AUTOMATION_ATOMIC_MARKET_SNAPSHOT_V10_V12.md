# Operator Spot Automation Atomic Market Snapshot V10-V12

Goal:
`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`.

Status: active at V12. V10 cycle 1 and V11 cycle 2 each completed all eight
reads exactly, atomically materialized final terms, and consumed one distinct
Preview at a terminal `TRANSPORT_UNKNOWN` boundary. Create and Cancel remain
unconsumed with zero calls and no exchange mutation. V12 is distinct and is
not a retry of V10 or V11.

## Narrow policy

The policy is limited to the approved Test portfolio, `BTC-USDC`, one BUY
child, and sequential candidates V10-V12. Each final candidate is a post-only
limit order at the exact best bid returned in one authenticated Coinbase Get
Market Trades response. The response's trade time supplies the documented
market timestamp; receipt time is not substituted. Product minimums and
increments, wallet evidence, and maker-fee reserve derive the smallest valid
size. Submitted and possible-execution notional must each be strictly below
3.10 USDC.

Coinbase documents Get Market Trades as one product-scoped snapshot containing
the latest trades plus `best_bid` and `best_ask`:
<https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-market-trades>.
Coinbase documents Preview as accepting the order configuration and returning
the allowlisted `errs`, warning, economics, and `preview_id` fields:
<https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders>.

## Atomic binding

`POST /api/v1/automation/atomic-market-snapshot-candidates/authorize` accepts
only fixed operator acknowledgements. Before any read it claims one of ten
goal-global cycles. The backend then performs the approved categories once,
without an individual or page retry:

1. API-key permissions
2. portfolio catalog
3. account/wallet balances
4. product metadata
5. documented Get Market Trades with same-response bid/ask
6. fee summary
7. exact derived-child reconciliation
8. account-wide active Spot-order catalog

Non-market intent may exist before those reads, but price, size, fee-reserved
cap, plan hash, deterministic `client_order_id`, evidence binding, immutable
definition and plan, successful eight-read ledger, run, and consumed one-use
Preview claim are committed together in one PostgreSQL transaction. No term
may change after that transaction. The canonical Preview input and any later
Create input use the same persisted plan. Policy revision 5 revalidates exact
best-bid equality at the canonical command boundary, not merely at-or-below
bid.

A blocked or stale pre-Preview cycle creates no definition, run, plan, child,
or Preview claim and may consume only its state-refresh cycle. A rejected or
unknown Preview consumes only that candidate's Preview allowance. The next
candidate is available only after that terminal result. The first accepted,
error-free Preview ends successor selection and may reach one identical Create
through the existing Spot service. Only its exact authoritatively nonterminal
child may reach one Cancel.

One credential-bound portfolio admission lease is held continuously from the
first authoritative category read through final binding, Preview, conditional
Create, and durable terminal readback. No other canonical Spot placement can
enter between the zero-active-order catalog observation and this candidate's
exchange boundary. A process restart converts a pre-materialization `CLAIMED`
cycle to fixed `automation_atomic_market_snapshot_restart_unknown` evidence;
it does not strand the candidate or create a replayable Preview claim.
If an accepted Preview is durably checkpointed before Create begins, the
recovery path performs a fresh revision-5 eligibility read under the same
exact-bid policy. Both that reader and the canonical admission boundary require
the fee-reserved dynamic cap from wallet evidence before the identical Create.

The control-plane readback derives atomic actionability from the V10-V12 and
ten-cycle ledgers. An accepted Preview, an in-progress materialized candidate,
V12 exhaustion, or cycle exhaustion suppresses the action. The Admin UI
refreshes that authority after every terminal authorization result instead of
locally guessing that another successor exists.
Non-materialized cycles report their request-local eligibility read count as
`PREVIEW_GATED_CREATE` activity. Exact blocked reads retain their exact count;
an unknown boundary remains unknown and is never rendered as a local zero-call
operation. True idempotent replays remain the only local zero-call result.

Before V12, the Preview invocation boundary is split prospectively without
reinterpreting V10 or V11. A pinned-SDK HTTP exception with a returned 4xx,
5xx, or blocked 3xx response proves exactly one Preview call and persists only
the fixed class `HTTP_CLIENT_RESPONSE`, `HTTP_SERVER_RESPONSE`, or
`HTTP_REDIRECT_RESPONSE`. An unexpected response status uses
`HTTP_RESPONSE_INVALID`. No exception message, response body, raw Preview
identifier, or withheld text is read or retained. An exception without a
provable response remains `TRANSPORT_UNKNOWN` with exact call count withheld.
The approved CDP API-key path continues to omit `retail_portfolio_id`; Coinbase
documents that API-key connections derive the portfolio from the key, and V3
already proved this project can reach Preview without adding that field.

## Information and authority boundaries

PostgreSQL retains hashes and fixed sanitized diagnostics, never the raw read
or Preview response, raw Preview identifier, wallet values for browser
readback, secrets, private identifiers, or exception text. The Admin UI sends
acknowledgements only and cannot supply portfolio, price, size, cap, evidence,
candidate identity, or exchange identity.

There is no retry, fallback, redirect, alternate child, fan-out, scheduler,
Futures action, funding or transfer action, product expansion, or parallel
Coinbase placement path. Unknown outcomes consume the applicable allowance.

Historical `origin/prod` references inspected for translation only:
`core/order_engine.py` and `core/stealth_order_manager.py`. The current path
does not reuse the legacy dashboard WebSocket or browser-side trading logic.
