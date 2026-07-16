# Futures Slice 2R11 Preparation

Goal id: `futures_preview_acceptance_recovery_r11`

Current priority:
`prepare_audit_and_consume_single_r11_preview_then_offline_diagnosis`

Status: `preparing_audit_gate_inactive`

Alignment token: `authorized_r11_preparation_live_gate_inactive`

## Current Posture

Slice 2R11 is the only active successor workflow. Its bounded preparation and
audit work is authorized, but the live-capable runner gate remains inactive.
R11 is unconsumed. This preparation record does not claim that an R11 artifact,
terminal result, or Coinbase call already exists.

The workflow may use at most ten bounded offline or
online-official-documentation-only preparation, integration, remediation,
testing, local deployment-validation, and audit cycles. After focused
validation and independent safety plus blind-contextless audits establish
readiness, it may make exactly one Coinbase Preview-only R11 call. An unknown
outcome consumes R11 and cannot be retried.

## Fixed Authority Boundary

The successor retains all of these exact constraints:

- policy: exact V3;
- product: `AVP-20DEC30-CDE`;
- contract count: one;
- strict caps: `<100 / <150 / <300 USDC`;
- Coinbase Preview attempts: one maximum, currently zero consumed;
- retries, fallbacks, and redirects: zero;
- Create, Cancel, Close, Reduce, and other exchange mutations: zero;
- R12 attempts: zero;
- Slice 3, Slice 4, and Slice 5 activation: zero.

The fixed V3 authoritative preflight reads remain bounded to one invocation per
category. They are eligibility evidence for the one R11 workflow, not another
Preview, retry, fallback, redirect, or mutation path. The browser remains
operator readback only and grants no authority.

## Compatibility Contract

The runtime dependency is exactly `coinbase-advanced-py==1.8.4`. The response
path must validate the shallow raw SDK envelope before any recursive `_plain()`
normalization. It must reject converter-only envelopes rather than treating a
successful arbitrary converter as wire evidence.

The inactive gate also binds the installed Preview-path sources to Coinbase's
official `v1.8.4` tag:

- `coinbase/rest/orders.py`: `c3d34a3583dea07d69f9f06c5691be02f77b08d3a37b102b40666090e40cea06`;
- `coinbase/rest/rest_base.py`: `05708e76001707ea56c45ec680ac5305b2a51061ed0122840f446930845d1cec`;
- `coinbase/rest/types/base_response.py`: `89e40f2f95020a5ea1a4323200a2473c30681b9de4ce8a0de561ec4c739e5989`;
- `coinbase/rest/types/orders_types.py`: `19552322d672d194aad8cf91b7a07038360c6d9504ac4fce1e7524b7728317b2`.

The two validation layers remain separate:

1. The shallow wire-envelope validator checks the attributes present on the raw
   SDK response without calling a recursive converter.
2. Only after that boundary passes may recursive normalization feed the exact
   one-contract V3 project acceptance policy.

The restricted `preview_id` remains ephemeral. Before persistence or readback
it must be hashed or withheld. It must never appear in diagnostics, frontend
payloads, raw logging, or exception text. All terminal classifiers and
post-Preview stage evidence use fixed value-blind diagnostics only.

Official compatibility references are:

- [Coinbase Preview Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [coinbase-advanced-py v1.8.4 BaseResponse](https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/types/base_response.py)
- [coinbase-advanced-py v1.8.4 order response types](https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/types/orders_types.py)

Official documentation may inform synthetic, sanitized fixtures. It cannot be
used to inspect or reconstruct the raw R8 or R11 exchange response.

## Immutable Predecessor Boundary

Every existing Slice 2 and R1-R10 artifact byte and documented SHA-256 hash
must remain unchanged. R8 content and hash remain inaccessible. Only its
existing opaque forensic binding may participate through the already validated
predecessor chain. No preparation or audit step may open, read, hash,
reconstruct, rewrite, move, relink, or replace R8.

The R11 claim must bind the exact immutable R10 terminal predecessor and the
existing chain. Claim reservation must occur before credentials or the Coinbase
client are hydrated. A nonterminal or terminal R11 claim consumes the one-use
path; it must never fall back to R10 or another artifact.

The production R11 artifact path is fixed to the canonical backend `artifacts`
directory. A nonempty artifact-root environment override or a mismatched
imported path fails before predecessor, credential, client, or Coinbase access.
Reservation write, file-`fsync`, close, or directory-`fsync` ambiguity is
reported only as the fixed claim-persistence consumed diagnostic. It cannot
leak an underlying exception or authorize another invocation.

## Readiness And Audit Gate

The one-call runner remains fail-closed until all of the following are true:

- focused backend response, claim, privacy, runner, model, and OpenAPI tests
  pass with synthetic sanitized fixtures;
- focused frontend contract and readback tests pass without action controls;
- local deployment validation passes;
- backend and frontend tracked worktrees are clean, on `main`, and exactly
  synchronized with `origin/main`; the backend permits no untracked file, while
  the frontend permits only the four pre-existing root PNGs bound by exact
  filename and SHA-256 (all other untracked files fail the gate);
- the prepared backend and frontend revisions, normalized runner logic hash,
  audited component hashes, exact SDK pin, and bounded activation expiry are
  fixed;
- one independent safety audit and one independent blind-contextless audit
  return distinct passing receipts;
- the activation commit changes only the runner relative to the prepared
  revision, and a strict source parser proves that the normalized audit-binding
  block contains exactly the ten named literal assignments with no extra
  statement, call, duplicate, or executable expression;
- the production R11 path is absent before reservation and the exact R10
  predecessor validates immediately before the attempt.

Preflight is offline. It must not load credentials, instantiate a live client,
call Coinbase, or create the production artifact. Audit activation does not
itself consume R11; the exclusive claim reservation does.

## Terminal Handling

The authorized call count is global for R11, not per process, command, failure
category, or remediation cycle. There is no retry after a transport-unknown,
validator-blocked, persistence-blocked, or otherwise uncertain result.

After R11 becomes terminal, the workflow continues automatically with bounded
offline diagnosis and remediation. That work may update sanitized diagnostic
classification, backend models and tests, generated contracts, frontend
readback, and documentation, but it may not expose or reconstruct raw
responses, secrets, private identifiers, or withheld exception text. The final
closeout must hard-bind the terminal R11 artifact metadata and hash, permanently
tombstone the runner, revalidate immutable R1-R10 evidence without accessing
R8 content or hash, and report whether the terminal boundary was accepted,
blocked, or unknown.

This goal grants no R12 attempt and no Slice 3, Slice 4, or Slice 5 activation.
It stops only after R11 is terminal and the authorized offline diagnosis and
remediation are complete, or if continuing would require changing the product,
contract count, V3 policy, caps, or one-call limit.

## Validation Scope

Use focused tests during ordinary preparation and remediation. Before live
activation, run the canonical backend and frontend release gates required by
their repository contracts. All fixtures must be synthetic and sanitized.
The frontend gate's measured four-worker Vitest configuration, runner, policy,
and resource record are part of the audited component manifest; changing any
of them invalidates activation. The measured 606-test run remained below the
operator's 60% whole-host CPU and memory threshold.
Tests must prove converter-only rejection, shallow-before-recursive ordering,
hash-or-withhold privacy, fixed value-blind diagnostics, claim-before-client
hydration, exactly one Preview maximum, zero retry/fallback/redirect/mutation
paths, and no accepted handoff into Slice 3.

Historical `origin/prod` lookup was not needed for this preparation record. The
post-R10 compatibility correction concerns the current SDK response envelope
and backend Admin API Preview contract; legacy code has no authoritative R11
claim, Preview-schema, privacy, or audit-gate implementation to translate.
