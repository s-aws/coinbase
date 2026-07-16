# Futures Slice 2R11 Terminal Diagnosis

Last reviewed: 2026-07-16 UTC.

## Terminal result

Goal `futures_preview_acceptance_recovery_r11` is complete with alignment
`r11_terminal_pre_preview_v3_operator_policy_rejection`, slice status
`complete_terminal_no_retry`, and default action
`stop_and_await_operator_direction`.

R11 is terminally consumed, terminal `blocked`, and cannot be retried. The
single-use workflow reserved its immutable claim and stopped during
`remaining_margin_validation`, before candidate construction or Coinbase
Preview. Its fixed stage reason is
`futures_preview_margin_windows_ambiguous`; the attached structured evidence
localizes the boundary to
`margin_window_type_documented_but_operator_rejected`.

The second policy row was the recognized
`retail_intraday_margin_1` profile. Its documented margin-window token did not
match the exact V3 operator policy, which requires the intraday profile to be
in the intraday state. The failing row index is `1`, the failing field is
`margin_window_type`, and the recorded value type is `string`. A token being
documented by Coinbase is wire compatibility evidence; it is not permission
to relax this project's stricter V3 acceptance rule.

This is an operator-policy rejection, not a Preview-response schema failure.
No backend acceptance change, V3 policy broadening, product change, contract
count change, or cap change is warranted by this result.
The unchanged scope remains V3 policy, product `AVP-20DEC30-CDE`, one
contract, and strict `<100 / <150 / <300 USDC` caps.

## Immutable evidence

The canonical artifact is
`artifacts/futures_exact_no_live_preview_slice_2r11.jsonl`.

- File SHA-256:
  `effb4bd037b853e06da14a0327d71eb8104e2b7edb2f56970b4c47ef855b6061`
- Evidence SHA-256:
  `548bbb02709c70dc320219bc15520b40ed948309ad09ec0f8af8f812d63bedea`
- File binding: device `2096`, inode `221385`, size `24610`, mode `0400`,
  modification time `1784233044565789650` ns, link count `1`

The production validator binds those bytes and metadata to the exact immutable
R10 predecessor. R1-R10 remain byte-for-byte unchanged. R8 remains opaque: its
content and hash are not read or recomputed during R11 closeout.

## Bounded-call proof

Each authorized preflight read ran exactly once:

- API-key permissions
- portfolio catalog
- product
- best bid/ask
- Futures positions
- Futures margin/collateral

Coinbase Preview, retry, fallback, redirect, submission, Create, Cancel, Close,
Reduce, and every other exchange-mutation counter is `0`. Submitted and
executed notional are `0 USDC`. No raw response, restricted Preview identifier,
private identifier, exception text, or secret was persisted or returned.

- R11 workflow claims consumed: `1`
- Preview attempts: `0`
- Exchange submission attempts: `0`
- Terminal before Preview: `true`
- Successor authorized: `false`

The R11 runner is permanently tombstoned after this terminal claim. The
artifact's existence and terminal binding are evidence, not reusable call
authority.

## Offline diagnosis and readback remediation

Synthetic, sanitized regression coverage reproduces the same row-1 V3 policy
rejection and proves zero Preview or mutation activity. Admin API readback
continues to expose only fixed stage and policy evidence, counter summaries,
and hashes while withholding private values. The frontend foregrounds the
exact failing row/profile/field/type and the six one-time reads so operators do
not have to infer the boundary from the coarser stage reason.

Coinbase's official Get Current Margin Window documentation defines the two
queried profiles, and the pinned `coinbase-advanced-py==1.8.4` documentation
describes the endpoint's intraday/overnight state role. Neither source grants
authority to replace the project's exact V3 profile/state mapping.

## Stop state

The authorized R11 workflow and its bounded offline terminal diagnosis are
complete. There is no second R11 call, R12 attempt, Slice 3/4/5 activation, or
other live authority. Any successor requires a distinct operator decision;
the default action is to preserve the terminal evidence and stop. There is no
retry, no R12 attempt, and no Slice 3, Slice 4, or Slice 5 activation.
