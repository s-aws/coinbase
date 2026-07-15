# Futures Slice 2R7 preparation and terminal closeout

Date: 2026-07-15

## Scope and authority

Slice 2R7 was the single end-to-end Preview-only successor to consumed R6 for
`AVP-20DEC30-CDE`, exactly one contract, under the unchanged V3 exact-pair
margin-window policy and strict `<100 / <150 / <300 USDC` caps. Its one
authorized Preview call is now consumed.

Preparation was limited to offline checks and official online documentation.
The fixed execution path was permitted the bounded permission, portfolio,
product, market, position, and margin/collateral reads required to revalidate
the candidate, followed by at most one Coinbase Preview Order call. It allowed
zero retry, fallback, redirect, Create, Cancel, Close, Reduce, or other exchange
mutation. That call is consumed. No second call, R8, Slice 3 activation, or
other live authority exists.

If preparation, validation, audit, or the terminal result fails, work remains
limited to the authorized offline sanitized diagnosis and remediation surface.
No raw Coinbase response, secret, private identifier, or withheld exception
text may be exposed or reconstructed.

## Corrected response-schema binding

The R7 claim, terminal evidence, and accepted seal bind schema policy
`slice2_preview_liquidation_evidence_schema_v1` with these exact rules:

- Coinbase's documented `margin_ratio_data` replaces the legacy
  `current_liquidation_buffer` and `projected_liquidation_buffer` pair.
- `predicted_liquidation_price` is not required for the replacement path.
- If `predicted_liquidation_price` is present, it must be finite and positive.
- Only the existing sanitized response allowlist may be persisted.

The shared validator remains backward-compatible for immutable R1-R6
evidence. R7 adds an artifact-specific fail-closed validator against the raw
response before shared normalization and again during response-model
validation. It accepts only a
`margin_ratio_data` liquidation source (with the optional predicted-price
variant), rejects legacy-only or mixed legacy/replacement evidence—including
either lone or present-empty legacy key—and
terminalizes any post-Preview schema rejection as sanitized consumed R7
evidence.

Authority is Coinbase's official
[Preview Order documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders),
which describes `margin_ratio_data` as the legacy-buffer replacement and lists
`predicted_liquidation_price` separately as an FCM field.

## Immutable predecessor chain

| Artifact | File SHA-256 |
| --- | --- |
| Slice 2 original | `9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff` |
| R1 | `55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7` |
| R2 | `1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053` |
| R3 | `7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c` |
| R4 | `90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf` |
| R5 | `4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7` |
| R6 | `df5959e95ed4a6027e6c0a6980045fc685e7dd201158b39ff5fcc9577bf73904` |

R7 binds the exact immutable Docker-restored R6 terminal metadata, R6 evidence
SHA-256 `bf26fa6b0f67499dea02f337517c1ebd42ae9a20c88fbb5cfbe45e3f30f9e4f9`,
and R6's complete predecessor chain. R6 claim identifiers are freshness-bound
through non-reversible SHA-256 digests rather than copied into new source or
test fixtures.

## One-use claim and transport posture

The backend-only R7 tool has a fixed artifact path and had only two modes:

- dormant `--preflight`, which validates R6 ancestry and a disposable R7 claim
  without creating an artifact, hydrating credentials, constructing a Coinbase
  client, or calling an endpoint;
- `--confirm-one-r7-preview`, which reserves the immutable R7 claim before any
  credential or endpoint access and can reach only the fixed Preview-only REST
  facade.

The claim fixes the Default/DEFAULT portfolio, product, one-contract candidate,
V3 policy, corrected response schema, caps, allowed reads, one Preview maximum,
and zero mutation/retry/fallback maxima. The reused transport facade requires
zero retry dimensions and zero redirects and does not expose Create, Cancel,
Close, or Reduce methods.

The dormant production preflight completed with `status=ready`, no artifact,
no client, no Coinbase read, no Preview attempt, and no exchange submission.
After the readiness gates passed, the confirmation mode ran exactly once. It
must never be invoked again. The retained CLI is now terminally disabled by a
hard-coded consumed-authority gate: both modes return a sanitized blocker
before claim construction, credential hydration, client construction, or any
Coinbase call, even if the artifact path is unexpectedly absent.

All dormant-preflight validation failures, including path acquisition/state
checks and unexpected model or filesystem exceptions, are converted to the
fixed sanitized blocker `futures_preview_r7_preflight_validation_blocked`.
Exception text and artifact contents are not emitted.

## Readback contract

Generated OpenAPI and TypeScript contracts recognize R7, the exact immutable
R6 predecessor model, and the corrected response-schema binding. The Admin UI
remains display-only. It traverses R6 through R5, R4, R3, R2, R1, and the
original Slice 2 artifact and displays the optional-price rule without adding
buttons, browser-side trading decisions, direct Coinbase calls, or mutation
authority.

The default backend selector checks the fixed R7 path before R6. R7 now exists
and must be the exact completed, chain-valid, response-model-valid terminal or
readback fails closed. A reserved, malformed, tampered, wrong-generation, or
metadata-drifted R7 cannot fall back to R6. The valid blocked terminal is the
default Admin API/UI readback. Its exact file hash, evidence hash, and restored
filesystem metadata are statically bound without altering the artifact.

## Readiness and terminal record

Focused validation and independent safety plus blind contextless audit passed
before the one permitted Preview call. The workflow continued through the
authorized offline terminal diagnosis and remediation without another
Coinbase call.

The first blind readiness audit returned `NO-GO` because the R7 binding was
declared but not artifact-specifically enforced, default readback could not
select R7, and unexpected dormant-preflight exceptions were not uniformly
sanitized. Preparation cycle 2 addressed all three findings with negative
producer/model/privacy tests and a fail-closed conditional selector. Cycle 2
re-audits then found that a lone or present-empty legacy key could be dropped
by shared normalization and that fixed-path state-check exceptions sat outside
the sanitized preflight boundary. Cycle 3 moved R7 validation to the raw
response before shared normalization and enclosed path acquisition and state
checks in the fixed-output boundary.

Final cycle 3 preparation result: independent safety audit `GO`; fresh
blind/contextless audit `GO`. The safety audit observed `354` focused backend
tests and `46` focused frontend tests passing. The blind audit independently
passed `23` adversarial backend selections, `19` frontend readback tests, API
freshness, malformed-readback `503`, raw-schema attacks, privacy attacks,
immutable-chain validation, and no-stale-process checks. Local validation also
passed OpenAPI freshness, ownership, compilation, typecheck, lint, build,
security, goal and queue alignment.

## Terminal result

R7 ran exactly once on 2026-07-15. All six fixed Coinbase reads and exactly one
Preview call occurred. The SDK returned control, then the backend stopped
terminally with status/outcome `blocked` and sanitized blocker
`preflight_or_preview_blocked:ValueError` before accepted Preview evidence was
appended. Preview attempts are `1`; retry, fallback, redirect, Create, Cancel,
Close, Reduce, exchange-submission, and submitted/executed notional counts are
zero. Live execution is `not_run`.

The immutable terminal file is
`artifacts/futures_exact_no_live_preview_slice_2r7.jsonl`, file SHA-256
`8e7bdf1a1efa67df9b1081cc8270dc9607e0b8c7285053d06985dcab195115e4`,
and evidence SHA-256
`65791ec5aae8bd9db7c623042e3238f80a54067209aeeb1916801ca1d02369c3`.
It contains no persisted Preview response or seal-ready plan.

The narrow sanitized diagnostic is
`sdk_returned__post_preview_value_error__before_acceptance`, boundary
`after_preview_return_before_accepted_evidence_append`, exact-reason status
`not_persisted_and_unrecoverable`. It is derived at read time from immutable
terminal structure, not persisted in the R7 artifact, and excluded from the
evidence SHA-256. It does not prove the corrected schema, caps, available
margin, candidate binding, seal construction, or any other exact post-Preview
check caused the failure. Raw responses, exception text, secrets, and private
identifiers remain excluded.

R7 is consumed and cannot be retried. Slice 2 is blocked by
`slice_2r7_consumed_without_accepted_preview_evidence`; remaining Coinbase
Preview-attempt maximum is `0`; the default next action is
`await_operator_scope_change_decision_after_slice_2r7_closeout`. There is no
R8, Slice 3 activation, Coinbase call, or other live authority. The dedicated
diagnosis is `docs/FUTURES_SLICE_2R7_TERMINAL_DIAGNOSIS.md`.

Preparation phase-end subagent sweep: the safety reviewer, blind/contextless
reviewer, and blind backend-trace helper completed; all blocking preparation
findings were consumed and remediated before the one call.
