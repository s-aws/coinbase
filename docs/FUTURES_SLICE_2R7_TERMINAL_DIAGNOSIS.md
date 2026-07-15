# Futures Slice 2R7 terminal diagnosis

Date: 2026-07-15

## Authority boundary

This record closes the authorized offline diagnosis/remediation after the sole
Slice 2R7 Coinbase Preview-only call. It preserves the exact V3 policy,
`AVP-20DEC30-CDE`, one-contract scope, and strict `<100 / <150 / <300 USDC`
caps. It grants no additional Coinbase call, retry, fallback, redirect, Create,
Cancel, Close, Reduce, exchange mutation, R8 attempt, Slice 3 activation, or
other live authority.

Diagnosis used only the immutable artifact store's validated, sanitized model
and code-path structure. It did not inspect, expose, or reconstruct the raw R7
file contents, raw Coinbase response, secrets, private identifiers, or withheld
exception text.

## Immutable terminal evidence

The consumed terminal is
`artifacts/futures_exact_no_live_preview_slice_2r7.jsonl`:

- file SHA-256:
  `8e7bdf1a1efa67df9b1081cc8270dc9607e0b8c7285053d06985dcab195115e4`;
- evidence SHA-256:
  `65791ec5aae8bd9db7c623042e3238f80a54067209aeeb1916801ca1d02369c3`;
- status/outcome: `blocked` / `blocked`;
- sanitized blocker: `preflight_or_preview_blocked:ValueError`;
- all six fixed permission, portfolio, product, market, position, and
  margin/collateral read counters: `1`;
- Preview attempts: `1`;
- retry, fallback, Create, Cancel, Close, Reduce, and exchange-submission
  attempts: `0`;
- submitted and executed notional: `0 USDC`;
- live execution: `not_run`;
- persisted Preview response and seal-ready plan: absent.

R7 remains byte-immutable, read-only, and bound to the exact R6-through-original
predecessor chain. The diagnostic below does not alter the artifact or its
documented hashes.

## Localized boundary

The narrowest classification supported by the sanitized evidence is:

| Field | Value |
| --- | --- |
| classification | `sdk_returned__post_preview_value_error__before_acceptance` |
| failure boundary | `after_preview_return_before_accepted_evidence_append` |
| exact reason status | `not_persisted_and_unrecoverable` |
| Coinbase Preview method returned | `true` |
| retry allowed | `false` |
| additional Coinbase call allowed | `false` |
| sanitized | `true` |
| raw response included | `false` |
| external exception text included | `false` |
| identifier values included | `false` |

This boundary follows from the fixed evidence shape:

1. All fixed pre-Preview reads, candidate evidence, request evidence, and V3
   policy evidence are present, with no persisted pre-Preview stage failure.
2. The Preview counter is exactly one.
3. The terminal is `blocked`, not `unknown`. In this path an SDK exception
   would terminalize as unknown, so the Preview method returned control.
4. No accepted Preview response or seal-ready plan was appended before the
   sanitized `ValueError` terminal.

The exact failing check was deliberately not persisted and cannot be recovered
without prohibited raw material or another exchange call. The evidence cannot
distinguish response validation/normalization, candidate or cap binding,
available-margin evaluation, seal construction, or terminal transition. It is
therefore not proof that Coinbase's corrected Preview schema, a cap, available
margin, or any other specific check caused R7 to stop.

## Readback and hash semantics

The Admin API derives the classification from validated immutable terminal
structure. The diagnostic object returns only the fixed sanitized fields above;
it adds no response, exception, secret, or identifier values. The classification
is not present in R7, is not part of the stored evidence payload, and is
excluded from `evidence_sha256`. The evidence hash continues to authenticate
only the immutable persisted evidence it originally covered.

Default readback selects the exact statically bound R7 terminal. Missing,
malformed, reserved, tampered, wrong-generation, or metadata-drifted R7 state
fails closed and cannot fall back to R6. Readback is display-only and makes no
Coinbase call.

## Terminal project state

- `slice_status`: `blocked`
- blocker: `slice_2r7_consumed_without_accepted_preview_evidence`
- default next action:
  `await_operator_scope_change_decision_after_slice_2r7_closeout`
- remaining Coinbase Preview-attempt maximum: `0`
- exchange-mutation-attempt maximum: `0`
- product, policy, contract count, and caps: unchanged
- R8 authority: none
- Slice 3 activation: none
- live authority: none

The R7 workflow is terminal and its authorized offline diagnosis/remediation is
complete. Continuing now requires a distinct operator decision that explicitly
changes scope; the R7 runner must never be invoked again. Its retained CLI is
terminally disabled and fails closed before client construction or Coinbase
access even if the artifact path is unexpectedly absent.
