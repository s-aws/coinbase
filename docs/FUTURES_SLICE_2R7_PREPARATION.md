# Futures Slice 2R7 preparation

Date: 2026-07-15

## Scope and authority

Slice 2R7 is a single end-to-end Preview-only successor to consumed R6 for
`AVP-20DEC30-CDE`, exactly one contract, under the unchanged V3 exact-pair
margin-window policy and strict `<100 / <150 / <300 USDC` caps.

Preparation may use offline checks and official online documentation only. The
fixed execution path may perform the same bounded permission, portfolio,
product, market, position, and margin/collateral reads required to revalidate
the candidate, followed by at most one Coinbase Preview Order call. It permits
zero retry, fallback, redirect, Create, Cancel, Close, Reduce, or other exchange
mutation. An unknown Preview outcome consumes R7. It grants no second call, R8,
Slice 3 activation, or other live authority.

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
evidence. R7 adds an artifact-specific fail-closed validator after shared
normalization and again during response-model validation. It accepts only a
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

The backend-only R7 tool has a fixed artifact path and only two modes:

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
The production R7 artifact remained absent after preflight.

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

The default backend selector checks the fixed R7 path before R6. While R7 is
absent it continues serving the exact immutable R6 terminal. Once R7 exists,
it must be a completed, chain-valid, response-model-valid R7 terminal or
readback fails closed; a reserved, malformed, tampered, or wrong-generation R7
cannot fall back to R6. A valid terminal is selected immediately for Admin API
and UI readback. The authorized post-terminal closeout then records and binds
its exact file hash, evidence hash, and restored filesystem metadata without
altering the artifact.

## Readiness and terminal record

Focused validation and independent safety plus blind contextless audit must
pass before the one permitted Preview call. Their final results and the
sanitized R7 terminal classification are recorded here before closeout. The
workflow does not stop for another authorization if authorized offline
diagnosis or remediation is needed after the terminal attempt.

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

Final cycle 3 result: independent safety audit `GO`; fresh blind/contextless
audit `GO`. The safety audit observed `354` focused backend tests and `46`
focused frontend tests passing. The blind audit independently passed `23`
adversarial backend selections, `19` frontend readback tests, API freshness,
malformed-readback `503`, raw-schema attacks, privacy attacks, immutable-chain
validation, and no-stale-process checks. Local validation also passed OpenAPI
freshness, ownership, compilation, typecheck, lint, build, security, goal and
queue alignment. Dormant production preflight remains `ready`, with no client,
Coinbase read, Preview attempt, exchange submission, or R7 artifact. The
one-use confirmation mode has not run.

Phase-end subagent sweep: the safety reviewer, blind/contextless reviewer, and
blind backend-trace helper are complete; all blocking findings were consumed
and remediated, and no preparation reviewer remains active.
