# Futures Post-R10 Preview Compatibility And Direction

Goal id:
`futures_post_r10_preview_compatibility_and_direction_selection`

Status: complete, no live authority. Cross-repository alignment token:
`official_wire_schema_and_project_acceptance_separated_prospectively`.

## Safety Boundary

This was a bounded offline and official-documentation-only compatibility goal.
Every R1-R10 artifact remains immutable. R8 content and its hash remain
inaccessible; nothing in this analysis opens, hashes, reconstructs, or infers
that content. Raw Coinbase responses, secrets, private identifiers, and
withheld exception text are outside the evidence set.

The goal made zero Coinbase API or Preview calls, retries, fallbacks,
redirects, Create, Cancel, Close, Reduce, or other exchange mutations. It
grants no R11 authority, no Slice 3/4/5 activation, and no live authority.
No R11 exists. The R10 terminal remains exactly the immutable, value-blind
result recorded in
[Futures Slice 2R10 Terminal Diagnosis](FUTURES_SLICE_2R10_TERMINAL_DIAGNOSIS.md).
The prospective compatibility work does not reclassify or retry R10.

## Official Source Baseline

The primary response authority is Coinbase's official
[Preview Order reference](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
and the official
[Advanced Trade OpenAPI specification](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/advanced-trade-spec.yaml).
The specification was retrieved on 2026-07-16 and had SHA-256
`7115b6b13132565a0a65371aadc9a0e09c725860ae5119655d8cd4d8c226a6b7`.
The installed official `coinbase-advanced-py 1.8.4` SDK was compared with its
[tagged Preview response model](https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/types/orders_types.py#L124-L171)
and
[BaseResponse behavior](https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/types/base_response.py#L10-L36).

The official OpenAPI response requires these top-level fields:

- `order_total`
- `commission_total`
- `errs`
- `warning`
- `quote_size`
- `base_size`
- `best_bid`
- `best_ask`
- `is_max`

It does not require `order_margin_total`, `preview_id`,
`margin_ratio_data`, or `predicted_liquidation_price`. The official
`MarginRatioData` schema also has no required-child list. The reference page's
example renders `quote_size` and `base_size` as numeric values even though the
published schema describes them as strings. The prospective wire validator
therefore follows the published OpenAPI type and records the example mismatch
instead of silently broadening accepted types.

`is_max` is official wire evidence about maximum-balance sizing. For this
project's exact one-contract candidate it must be exactly `false` at the
project-policy layer; that stricter rule is not represented as an official
Coinbase schema requirement.

## Localized Compatibility Boundary

The historical R10 validator combined two different questions:

1. Is the SDK result compatible with Coinbase's documented wire shape?
2. Does that compatible result satisfy this project's stricter Preview
   acceptance and liquidation-evidence policy?

It required officially optional `preview_id`, `order_margin_total`, and
`margin_ratio_data`, while it did not require the officially required
`is_max`. That does not prove which withheld R10 field or value caused the
historical `futures_preview_response_economics_invalid` category. In
particular, omission of `order_margin_total` is the strongest source-supported
hypothesis because it is the only economics-bucket field used by R10 that is
optional in the official response schema, but it remains a hypothesis and must
not be written back into R10 evidence.

The prospective correction separates the boundaries:

- The official wire layer validates Coinbase-required field presence and
  published types. It also validates policy-relevant optional field types when
  those fields are present. Other additive and legacy optional fields are
  intentionally ignored without traversing their values. The layer emits no
  raw values, and required error/warning arrays require string items.
- The project acceptance layer then requires empty `errs` and `warning`, exact
  `is_max=false`, a bounded safe `preview_id`, bounded plain-decimal economics,
  positive `order_margin_total`, and the project's replacement liquidation
  evidence. These are fail-closed project rules.
- Fixed, value-blind rejection categories identify the exact field/predicate
  boundary without persisting a response value or exception text.
- Legacy liquidation keys remain ignored: they are neither parsed nor used as
  fallback evidence.
- Plain decimal tokens are capped at 128 characters and cannot use exponent
  syntax; allowed signed zero is canonicalized to `0` before sanitized output.
- No prospective binding grants attempt, runner, selector, Slice, or exchange
  authority.

The SDK comparison also confirms that a synthetic response object preserves
declared and undeclared fields through `BaseResponse`. Compatibility tests pin
the installed package metadata to `coinbase-advanced-py 1.8.4`, exercise the
real SDK object, and prove that the prospective validator selects its shallow
attribute envelope without recursively normalizing an unknown field.

## No-Live Successor Integration Invariants

The prospective validator is not wired to a claim, runner, model, selector,
route, or readback. No successor exists. Before any separately authorized
successor preparation may wire it:

- A future successor must pass the raw SDK envelope to the shallow validator
  before any recursive `_plain()` normalization. Mapping inputs and the
  shallow attribute envelope of the exactly pinned `coinbase-advanced-py
  1.8.4` response are supported; a converter-only envelope is rejected without
  invoking arbitrary `to_dict()` behavior.
- `preview_id` must remain ephemeral and restricted, then be hashed or withheld
  before persistence or readback. The integration must never place the
  identifier in a diagnostic or frontend payload.
- Other optional or unknown fields must remain uninspected unless a future
  official-source review deliberately promotes one into a separately tested
  policy-relevant field.
- These are preparation preconditions only. They grant no R11, Preview,
  retry, runner, Slice, or exchange authority.

## Validation And Audit Scope

The focused tests cover every official required field for missing/wrong-type
behavior; present optional-field types versus project-required presence;
`is_max=true`; error/warning array item types and nonempty policy; bounded
non-exponent decimal tokens and signed-zero canonicalization; replacement
liquidation evidence; fixed diagnostic classification; SDK 1.8.4 unknown-field
retention; and proof that the prospective binding carries no attempt, runner,
Slice, or live authority. Cross-repository goal-alignment and ownership checks
cover the durable no-live posture.

Deployment validation for this goal was local Linux Docker validation only;
no hosted workflow or Coinbase client/runner was invoked. The recorded results
are:

- The focused post-R10 synthetic/SDK matrix passed after each remediation.
- The canonical backend gate passed: 1,017 parallel and 456 serial regression
  cases passed with `live_coinbase_execution=false` and notional `0`.
- The frontend baseline passed typecheck, lint, generated API freshness for
  138 routes, build, security, release readiness; 604 unit/component tests and
  8 Playwright scenarios passed. The canonical `npm run release:gate` also passed and
  repeatedly reported live Coinbase execution `not_run`, notional `0`.
- Post-gate process checks found no stale repository-owned workers. R1-R7,
  R9, and R10 hashes plus all R1-R10 metadata matched the opening baseline; R8
  remained stat-only and was never opened or rehashed.

The first independent safety and blind-contextless passes identified
prospective-only integration guard gaps. Those findings were remediated before
closeout by narrowing the optional-field claim, rejecting converter-only
envelopes, recording identifier-handling invariants, pinning SDK 1.8.4, and
aligning both machine contracts to an empty active-blocker set. Final
independent safety and blind-contextless audits passed after the focused
remediation rerun; neither found a remaining safety, privacy, authority, or
contract-alignment issue.

The legacy `origin/prod` branch was not consulted. This task compares a current
official Coinbase wire contract with a prospective validator; it does not
recreate legacy account, order, or dashboard behavior.

## Ranked Direction

1. **One future successor, only after all no-live gates pass.** If the
   prospective implementation, local deployment validation, independent
   safety audit, and blind-contextless audit all pass, consider one separately
   authorized, single-use successor. It must preserve the exact V3 policy,
   `AVP-20DEC30-CDE`, one contract, strict `<100 / <150 / <300 USDC` caps,
   zero retries/fallbacks/redirects/mutations, and automatic offline
   post-terminal diagnosis. This document does not authorize it.
   Any such preparation must first implement and test every no-live successor
   integration invariant above.
2. **Seek official clarification.** If a published-schema discrepancy or
   policy interpretation remains material, ask Coinbase for authoritative
   clarification before allocating another single-use attempt.
3. **Park the sequence.** If neither condition is met, retain the current
   immutable no-live state.

Ten future attempts are not warranted. The evidence supports, at most, one
future successor after the prospective correction and all gates pass; ten
attempts would turn a fail-closed single-use proof into iterative live schema
discovery. Consequently this goal produces no ten-attempt authorization set.

The current next action is
`await_operator_decision_on_one_post_r10_successor_or_official_clarification`.
It is an operator decision point, not permission to prepare or execute a new
claim.
