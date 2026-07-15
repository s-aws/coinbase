# Futures Slice 2R6 terminal diagnosis

Date: 2026-07-15

## Scope and authority

This is an offline, sanitized diagnosis of the consumed Slice 2R6 Preview-only
attempt for `AVP-20DEC30-CDE`, one contract, under the V3 policy and strict
`<100 / <150 / <300 USDC` caps. It grants no retry, R7 attempt, Slice 3
activation, Coinbase call, or exchange mutation.

No raw Preview response, exception text, secret, private identifier, or
withheld value was inspected or reconstructed. The R1-R6 artifacts were not
modified.

## Immutable evidence

| Artifact | SHA-256 |
| --- | --- |
| Slice 2 original | `9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff` |
| R1 | `55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7` |
| R2 | `1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053` |
| R3 | `7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c` |
| R4 | `90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf` |
| R5 | `4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7` |
| R6 | `df5959e95ed4a6027e6c0a6980045fc685e7dd201158b39ff5fcc9577bf73904` |

R6 records one `preview_order` attempt, all six authorized reads once, a
terminal `blocked` outcome, and the allowlisted blocker
`preflight_or_preview_blocked:ValueError`. It contains neither accepted Preview
evidence nor a seal-ready plan.

## Localized failure boundary

The failure is localized to **post-SDK-return, pre-acceptance backend
processing**:

1. The Preview SDK method returned control. An SDK exception would have used
   the distinct terminal outcome `unknown` and blocker prefix
   `preview_order_unknown`.
2. A `ValueError` then arose between initial Preview-response validation and
   final predecessor validation, before accepted evidence was appended.
3. The sanitized R6 catch path deliberately removed any normalized Preview
   evidence before persisting the terminal record. Consequently, the immutable
   record cannot distinguish response-shape validation, candidate/cap binding,
   available-margin comparison, seal construction, or final predecessor
   validation. The exact rejected field/reason is intentionally unrecoverable.

Sanitized classification:

```text
sdk_returned__post_preview_value_error__before_acceptance
exact_reason_status=not_persisted_and_unrecoverable
retry_allowed=false
```

## Schema incompatibility candidate (not an R6 finding)

Coinbase's current Preview Order schema describes `margin_ratio_data` as the
replacement for `current_liquidation_buffer` and
`projected_liquidation_buffer`. It documents `predicted_liquidation_price`
separately as an FCM field. The backend validator currently treats the
replacement path as complete only when both `margin_ratio_data` and
`predicted_liquidation_price` are present.

That coupling is stricter than the documented replacement relationship and is
a concrete validator incompatibility candidate. It must not be reported as
the exact R6 cause because R6 retained no response-shape evidence capable of
proving which field or later checkpoint raised the `ValueError`.

Primary references:

- Coinbase Preview Order schema:
  <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders>
- Installed official Python SDK: `coinbase-advanced-py==1.8.4`; its response
  base class retains fields not explicitly declared by `PreviewOrderResponse`,
  so SDK conversion itself does not prove that replacement fields were lost.

## Required next decision

Slice 2 remains unaccepted, R6 remains consumed, and Slice 3 remains inactive.
Any validator correction and any synthetic replay against a sanitized fixture
must receive a separate authorization. Any new Coinbase Preview attempt needs
an additional, still more explicit one-use authorization after the offline
correction is independently validated.

Recommended next-step authorization wording:

> I authorize one bounded, offline-only Slice 2R6 follow-up to correct the
> backend Preview-response validator so that its liquidation evidence rules
> match Coinbase's documented schema, and to validate that correction using
> synthetic, sanitized fixtures only. The work may update backend tests,
> models, generated OpenAPI/client contracts, frontend readback, and
> documentation as necessary. It must preserve every existing Slice 2 and
> R1-R6 artifact byte and documented SHA-256 hash; must not inspect, expose, or
> reconstruct the raw R6 response, secrets, private identifiers, or withheld
> exception text; and must not broaden the V3 policy, product, one-contract
> scope, or strict `<100 / <150 / <300 USDC` caps. This authorization permits
> zero Coinbase API or Preview calls, retries, fallbacks, redirects, Create,
> Cancel, Close, Reduce, or other exchange mutations. It grants no R7 attempt,
> no Slice 3 activation, and no live authority. After focused validation and
> independent safety plus blind contextless audit, report the correction and
> stop for a distinct operator decision.
