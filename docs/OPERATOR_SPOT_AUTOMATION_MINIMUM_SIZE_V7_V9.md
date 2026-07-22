# Operator Spot Automation Minimum Size V7-V9

Goal
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`
is active at `materialization_unknown_cycle_6_legacy_cap_schema_remediation_in_progress`.
Current action: `validate_deploy_then_execute_distinct_cycle_7`.
Default action: `complete_readiness_then_execute_first_valid_v7_v9_successor`.

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

Goal-global cycles are `6/10`. Cycles 1–5 are immutable terminal generic
`automation_minimum_size_preparation_unknown` records with zero completed
categories and exact call count conservatively withheld; the first approved
category was not confirmed. Cycle 3 exposed an unprotected REST-client method
lookup, and cycle 4 exposed response processing outside the fixed stage
envelope. The deployed outer-boundary split classified cycle 6 as
`automation_minimum_size_materialization_unknown` after all six read
categories completed. Schema-only inspection localized two obsolete fixed-
1.00-USDC PostgreSQL CHECK constraints beside the dynamic-cap constraints.
The current migration removes only those legacy checks and proves a synthetic
1.01-USDC dynamic-cap row survives startup migration. Coinbase
Preview/Create/Cancel calls are `0/0/0`; every such live allowance is
unconsumed. No V7-V9 candidate currently exists. Remediation retains the fixed
per-category codes and adds
`automation_minimum_size_runner_composition_unknown` for the zero-prefix outer
boundary plus `automation_minimum_size_materialization_unknown` for the
six-category-prefix outer boundary, without retaining response content or
exception text. The readiness backend gate
passed with `1209 passed, 6 skipped` parallel and
`687 passed, 150 skipped` serial. The canonical frontend release gate passed
`1583` Vitest tests, `229` deployment tests, `17` Playwright tests, generated
contract checks, and installed Controlled-live deployment validation with zero
live Coinbase execution. The independent safety audit passed; the
blind-contextless code audit passed for the outer-boundary checkpoint. The
legacy-cap schema migration is now under remediation. Focused and full
validation, installed deployment checks, and both independent audits must pass
before the distinct cycle 7 operator action.

## Legacy comparison

Historical `origin/prod:core/stealth_order_manager.py` supplied useful
top-of-book/post-only context, and `origin/prod:core/order_engine.py` supplied
increment-aware order-construction context. The historical browser/direct
exchange path and its `post_only=false` behavior were not restored. All terms,
policy decisions, persistence, and Coinbase access remain backend-owned.

R1-R12 and all predecessor evidence remain unchanged. R8 content and hash stay
inaccessible and are neither read nor recomputed by this goal.
