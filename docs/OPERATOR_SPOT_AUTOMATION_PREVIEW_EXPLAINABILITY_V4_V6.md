# Operator Spot Automation Preview Explainability V4-V6

Goal:
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`

Status: `complete_no_documented_successor_correction`

Current action:
`complete_preview_explainability_v4_v6_allowances_unconsumed`

Default action: `await_operator_policy_decision`

## Outcome

The Preview boundary now reads only the shallow
`coinbase-advanced-py==1.8.4` `PreviewOrderResponse` fields documented by
Coinbase. The `errs` array is checked against an exact allowlist from the
[Preview Order response schema](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders).
An undocumented value, including a syntactically plausible future
`PREVIEW_*` value, is `UNCLASSIFIED_REJECTION` rather than documented evidence.

One documented error is mapped to a fixed value-blind category such as
`LIMIT_PRICE`, `SIZE_PRECISION`, `BASE_SIZE_TOO_SMALL`,
`INSUFFICIENT_FUNDS`, or `MARKET_TRADE_DATA_MISSING`. Multiple documented
errors collapse to `MULTIPLE_DOCUMENTED`, which is intentionally not enough to
select a term correction. The backend persists and projects only this fixed
category, broad failure class, warning-present boolean, exact call accounting,
and hashed-or-withheld Preview identity. Raw responses, raw Preview ids,
private values, and exception text remain unavailable.

The PostgreSQL column is additive and nullable. It does not rewrite any V1-V3
row. Existing idempotency JSON lacking the new field remains readable as a
historical null value. OpenAPI, the generated frontend client, strict browser
runtime validation, and Automation run detail readback carry the same bounded
enum.

## Why no V4 candidate was created

V3 durably retained `REJECTED` / `DOCUMENTED_REJECTION`, warning present, and
no exact rejection category. The raw response was deliberately not retained,
so the exact Coinbase enum cannot be recovered or retroactively classified.

Sanitized V3 plan evidence is a `BTC-USDC` BUY, base size `0.0001`, limit
price `10,000 USDC`, submitted and possible-execution notional `1.00 USDC`,
and `post_only=false`. The installed backend standing-price rule admits a BUY
only at or below 50% of a fresh bid. Coinbase documents price-band and
too-far-from-market Preview errors, while its
[Get Product schema](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-product)
documents increments and minimum sizes but no numeric replacement price for a
rejected standing order.

Changing V4 to a near-market limit would broaden the installed admission
policy. Selecting another far-standing limit without the V3 enum or a
documented numeric price-band rule would be guesswork and could amount to a
disguised retry. The authorized stop condition `no documented correction
remains` therefore applies before candidate creation.

## Exact goal accounting

- V4-V6 eligibility cycles: `0/10`
- goal-scoped Coinbase reads: `0`
- V4 candidates created: `0`
- V5 candidates created: `0`
- V6 candidates created: `0`
- Preview calls: `0`
- Create calls: `0`
- Cancel calls: `0`
- all V4-V6 Preview/Create/Cancel allowances: unconsumed
- predecessor V1-V3 rows, claims, identities, calls, and allowances: unchanged

No Coinbase call or exchange mutation occurred in this goal.

## Validation and audit evidence

- focused backend classifier, orchestration, repository, and route validation:
  `259 passed`
- full backend regression: `1182 passed, 6 skipped` parallel and
  `670 passed, 150 skipped` serial
- focused frontend validation: `112 passed`, with typecheck, lint, generated
  schema freshness, and all `169` route-coverage entries passing
- full frontend validation: `1566 passed`; isolated and canonical release-gate
  E2E: `15/15 passed`
- installed deployment and canonical release gate: `PASS`, with zero live
  Coinbase execution and `0 USDC` notional
- independent safety audit and blind contextless audit: `PASS` after correcting
  three documentation-only capability-matrix route suffixes

## Next decision boundary

A successor requires an explicit policy decision supported by a backend rule,
not another attempt authorization alone. The safe choices are to document and
approve a bounded near-market price policy compatible with the existing
`1.00 USDC` possible-execution cap, or to retain the standing-price policy and
stop live Preview proofs for this candidate shape. No V4-V6 allowance grants
authority to change that policy.
