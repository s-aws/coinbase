# Futures Slice 2R10 Terminal Diagnosis

## Terminal Result

R10 is consumed and immutable. The authorized composite workflow ran exactly
once and returned `terminal_no_mutation`: R10 finished `blocked`, Slice 3 was
`not_run`, and no exchange mutation path activated. R10 must never be retried,
and no R11 authority exists.

The fixed terminal artifact is
`artifacts/futures_exact_no_live_preview_slice_2r10.jsonl`:

- file SHA-256:
  `5dd010a706c61e78454caeec478e05cafb1a50761e9e5a9a3d485051c4efee64`;
- evidence SHA-256:
  `5121e980ec9da81f44d9a3b14b9bbcaa7bdaf41c99189cd9234cedc08d652005`;
- post-Preview stage-evidence SHA-256:
  `271826bb4bd2f3cac54be3209da3b910ebb798381c0f1c41ed335e76d20eb8ad`;
- device/inode: `2096/221388`;
- size: `26144` bytes;
- mode: `0400`;
- link count: `1`; and
- mtime-ns: `1784179469052389092`.

The production readback now model-, hash-, and stat-binds that exact terminal.
Metadata, link, symlink, byte, evidence-hash, predecessor, counter, privacy, or
diagnostic drift fails closed. Validation reaches R8 only through its existing
documented-SHA/stat-metadata-only contract: R8 bytes are never opened or
rehashed.

## Localized Failure Boundary

All six fixed read categories completed exactly once and the Coinbase Preview
method returned exactly once. The first post-return stage then stopped:

- stage: `preview_response_validation`;
- status: `blocked`;
- fixed sanitized category:
  `futures_preview_response_economics_invalid`.

This establishes the boundary after the SDK returned and before candidate-cap
binding, available-margin validation, seal-ready plan construction, accepted
evidence construction, or terminal-predecessor validation. No normalized
Preview response, Preview identifier, or seal-ready plan was persisted.

The category is deliberately value-blind. It covers a missing or invalid
economics field among the bounded response-validation inputs, including
notional, fee, size, bid/ask, or order-margin evidence. The exact field and
value were not persisted and are intentionally unrecoverable. The raw Coinbase
response, private identifiers, and withheld exception text were not inspected,
exposed, or reconstructed. Consequently this evidence does not justify another
validator change, a fallback, or a broader schema assumption.

## Exact Accounting

- API-key permissions, portfolio catalog, product, best bid/ask, Futures
  positions, and Futures margin/collateral reads: `1` each.
- Preview: `1`.
- Retry, fallback, Create, Cancel, Close, and Reduce: `0` each.
- Redirect allowance: `0`.
- Exchange submission attempts: `0`.
- Submitted and executed notional: `0 USDC`.
- Execution marker, attempt ledger, and replacement runtime: absent.
- Live Coinbase execution: `not_run`.
- Slice 3 accepted handoff, admission, activation, action journal, read journal,
  and terminal artifacts: absent.

The standalone R10 tool remains hard-false. The composite runner's audit
bindings are cleared and its readiness bit is permanently hard-false, so a
future confirmation is rejected before preflight, credential hydration, client
construction, artifact reservation, or any Coinbase access.

Local packaged deployments do not copy immutable Preview artifacts. They set
the absolute
`COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_ROOT` to the persistent
backend artifact directory and validate the same fixed hashes and filesystem
metadata in place. This migration-aware indirection never opens or rehashes R8;
an absent, relative, or drifted binding fails the readback closed.

## Scope And Stop State

The immutable terminal retains the exact V3 profile/state policy,
`AVP-20DEC30-CDE`, BUY, one contract, and strict `<100 / <150 / <300 USDC`
caps. R1-R10 evidence remains immutable. R10 was not accepted, so conditional
Slice 3 never became eligible and no Create/Cancel/Close authority was used.

The authorized recovery goal is complete with terminal non-acceptance. There
is no default successor, no R11, no Slice 3 activation, and no remaining live
authority. Any future work must begin as a separately selected and explicitly
authorized goal; this diagnosis does not supply that authority.
