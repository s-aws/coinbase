# Futures Slice 2R9 Terminal Diagnosis

Status: terminal blocked; R9 is consumed and must never be retried.

## Immutable terminal binding

- Artifact: `artifacts/futures_exact_no_live_preview_slice_2r9.jsonl`
- File SHA-256: `5c7dd3f27605b623edc910a87dcc4b6c9ea6621aa9ee63dbfcc4b2994990dacf`
- Evidence SHA-256: `2fd73aa0059da49dfe6c836f6dea29b12158fb3dfbe8abdd6d8f4f0f7d702464`
- Device/inode: `2096` / `401766`
- Size/mode/mtime-ns/nlink: `24406` / `0400` / `1784173141720439487` / `1`
- Preview attempts: `1`
- Retry, fallback, Create, Cancel, Close, and Reduce attempts: `0`
- Exchange submission attempts and submitted/executed notional: `0`

The artifact is persistence-safe and may be model/hash/stat validated. It must
remain byte-for-byte immutable. R8 remains opaque: its recorded SHA-256 is a
documented preexisting binding that is not recomputed, and runtime validation
uses stat metadata only without opening R8.

## Localized boundary

The Coinbase Preview method returned. The first post-return stage,
`preview_response_validation`, then blocked before normalized Preview evidence,
a Preview identifier, or a seal-ready plan could be persisted. The historical
R9 diagnostic contract intentionally collapsed the internal validator reason to
`futures_preview_response_validation_unclassified`; the exact raw response and
withheld exception text are neither available nor recoverable.

R9 performed all six authorized read categories once and made exactly one
Preview call. It made no exchange mutation. Slice 3 remained `not_run` because
R9 was not accepted.

## Official schema comparison

Coinbase's current Preview Order response example and OpenAPI schema list
`current_liquidation_buffer`, `projected_liquidation_buffer`, and
`margin_ratio_data` in the same response object. The description calls
`margin_ratio_data` the new replacement fields, but the schema declares no
mutual exclusion between old and new keys.

Primary references:

- <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders>
- <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/advanced-trade-spec.yaml>

The R7-R9 v1 validator rejected the mere presence of either legacy key before
validating `margin_ratio_data`. That mutual-exclusion rule is stricter than the
published schema and is the strongest source-supported explanation for R9's
boundary. It remains an inference: the raw R9 response was not inspected or
reconstructed, and other strict validator failures cannot be excluded.

## R10 remediation

R7-R9 retain their exact historical v1 binding and validator. R10 uses a new v2
binding that:

- requires valid `margin_ratio_data` as authoritative liquidation evidence;
- permits documented coexistence of the legacy keys;
- ignores legacy liquidation values without parsing or persisting them;
- never falls back to legacy evidence when the replacement is missing or
  invalid;
- preserves the optional predicted-liquidation-price finite-positive rule;
- preserves one contract, the exact V3 profile/state pair, and strict
  `<100 / <150 / <300` USDC caps.

R10 also uses fixed value-blind diagnostic categories for response envelope,
exchange errors, exchange warnings, economics, missing replacement evidence,
invalid replacement evidence, and normalization invariants. Unknown exception
text remains unclassified and is never persisted.

R10 remains preparation-only until focused validation, independent safety
audit, and a fresh blind contextless audit bind a clean implementation commit.
At most one R10 Preview call is authorized, with zero retries, fallbacks,
redirects, or mutations. If R10 is not accepted, no R11 is authorized.

The first R10 safety audit found that predecessor validation still opened R8
to recompute its SHA-256. That base revision is a release-blocking `NO-GO` and
must never be bound for execution. The remediation retains the documented R8
SHA-256 and exact metadata in successor evidence but validates R8 through
stable `lstat` metadata only. Focused tests intercept both descriptor-level and
`Path`-level opens and fail if runtime attempts to read R8 bytes.
