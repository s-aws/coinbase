# Operator Spot Automation Minimum Size V7-V9

Goal
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`
is complete at `complete_terminal_eligibility_cycles_exhausted_v7`.
Current action: `complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

## Boundary and policy

The terminal V4 `near_market_no_valid_size` record remains immutable. This
successor does not reinterpret V4 or reuse any V4-V6 identity or allowance.
It adds policy `BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` for exactly the
approved Test portfolio, `BTC-USDC`, one BUY child, and candidates V7-V9.

The pure backend policy:

- floors the fresh same-snapshot Get Market Trades best bid to the documented
  price increment and requires the result to remain post-only;
- chooses the smallest base-increment multiple satisfying both documented
  base and quote minimums;
- keeps submitted notional strictly below 3.10 USDC;
- derives the smallest quote-increment cap covering submitted notional and
  worst-case maker-fee evidence, also strictly below 3.10 USDC; and
- rounds the fee-reserved requirement upward to the documented quote
  increment and requires authoritative USDC wallet evidence to cover that
  exact rounded dynamic cap.

Fixed value-blind policy failures distinguish product metadata, increment,
submitted-cap, fee-reserve-cap, wallet, and market-freshness boundaries. A
successful proposal records exactly one of these prospective V4 explanations:
`minimum_size_v4_base_minimum_conflict`,
`minimum_size_v4_quote_minimum_conflict`,
`minimum_size_v4_increment_conflict`,
`minimum_size_v4_fee_reserve_conflict`, or
`minimum_size_v4_boundary_not_reproduced`. No raw response, private balance,
portfolio identifier, Preview identifier, secret, or withheld text is stored
or returned.

## Durable workflow

`POST /api/v1/automation/minimum-size-candidates` accepts only the fixed
operator acknowledgements. The backend claims the next sequential V7-V9
preparation and one goal-global cycle before invoking the six approved
no-retry categories: API-key permissions, portfolio catalog, account/wallet
balances, product metadata, documented market trades with same-snapshot
bid/ask, and fee summary. An unknown call outcome makes accounting
conservative and consumes that cycle.

Valid terms, evidence hash, definition, plan revision, portfolio hash, and
candidate identity commit atomically in PostgreSQL. Generic definition
creation and direct repository calls cannot create a policy-revision-4 plan
without the exact preparation record. V7-V9 preparation and the existing
eight-category final eligibility flow share one ten-cycle budget. V8 can
follow only a terminal rejected or unknown V7 Preview; V9 has the equivalent
V8 predecessor condition. An accepted Preview blocks every later candidate.

Each candidate has one durable Preview claim. The first accepted error-free
Preview permits one identical canonical Spot Create; only its exact
authoritatively nonterminal child can use the single safe-closeout Cancel.
There are no retries, fallback identities, alternate children, fan-out,
Futures actions, scheduler activation, funding/transfer actions, or parallel
placement paths. The typed approval, cap guard, wallet check, admission,
reconciliation plan, exchange-call ledger, and readback all retain the exact
dynamic cap, including the zero-maker-fee edge where that cap equals 1.00
USDC.

The strict submitted ceiling is independently revalidated by preparation,
the immutable PostgreSQL plan, the eight-category eligibility reader, runtime
admission construction, and the final typed command-service admission. A
submitted notional equal to 3.10 USDC is invalid at every V7-V9 boundary.
Dynamic cap records cannot authorize the ordinary manual-order route: that
route and the canonical command service accept only the installed fixed
1.00-USDC possible-execution cap unless exact policy-revision-4 typed
Automation admission is present.

Definition detail readback durably projects only the policy revision, fixed V4
boundary classification, preparation cycle, completed category names, exact
call count, strict submitted ceiling, and derived possible-execution cap. It
does not project the preparation evidence hash, raw response, private wallet
balance, portfolio identifier, Preview identifier, or withheld text. Focused
PostgreSQL coverage proves V7 rejected to V8 unknown to V9 accepted sequencing,
shared ten-cycle exhaustion, conservative CLAIMED-to-UNKNOWN restart recovery,
and one-winner concurrent preparation claiming.

## Current accounting

Goal-global cycles are `10/10`. Cycles 1–5 are immutable terminal generic
`automation_minimum_size_preparation_unknown` records with zero completed
categories and exact call count conservatively withheld; the first approved
category was not confirmed. Cycle 3 exposed an unprotected REST-client method
lookup, and cycle 4 exposed response processing outside the fixed stage
envelope. The deployed outer-boundary split classified cycle 6 as
`automation_minimum_size_materialization_unknown` after all six read
categories completed. Schema-only inspection localized two obsolete fixed-
1.00-USDC PostgreSQL CHECK constraints beside the dynamic-cap constraints.
The completed migration removed only those legacy checks and proved a
synthetic 1.01-USDC dynamic-cap row survives startup migration. Cycle 7 used
six exact reads and atomically materialized immutable V7 with the validated
1.01-USDC dynamic cap. The operator enabled that exact definition and claimed
one one-shot run; both local mutations made zero Coinbase calls. Eligibility
cycles 8–10 each used five exact reads. Permissions, portfolio, wallet, and
product passed, then the Get Market Trades `BEST_BID_ASK` category rejected
the immutable best-bid term. The goal-global budget is exhausted and durable
readback projects `automation_spot_eligibility_cycles_exhausted` with no
allowed action. Coinbase Preview/Create/Cancel calls are `0/0/0`; every live
allowance is unconsumed, no child exists, and V8–V9 were not created.
Remediation retains the fixed stage codes and adds no raw response, private
balance, identifier, evidence hash, or exception-text path.

## Legacy comparison

Historical `origin/prod:core/stealth_order_manager.py` supplied useful
top-of-book/post-only context, and `origin/prod:core/order_engine.py` supplied
increment-aware order-construction context. The historical browser/direct
exchange path and its `post_only=false` behavior were not restored. All terms,
policy decisions, persistence, and Coinbase access remain backend-owned.

R1-R12 and all predecessor evidence remain unchanged. R8 content and hash stay
inaccessible and are neither read nor recomputed by this goal.

## Closeout validation

Backend regression passed `1209` tests with `6` skipped in the parallel-safe
group and `687` tests with `150` skipped in the serial group. Frontend
validation passed `1584` Vitest tests, `229` deployment-focused tests, `17`
Playwright tests, generated-contract checks, the canonical release gate, and
installed deployment checks. Every validation artifact records zero live
Coinbase execution. Independent safety and blind-contextless audits returned
`PASS` with no actionable finding.
