# Futures Slice 2R12 Preparation

Goal id: `futures_preview_acceptance_recovery_r12`

Current action: `complete_no_live_validation_and_independent_audits`

Status: `prepared_release_disabled`

Alignment token: `r12_separate_eligibility_and_single_use_attempt_v1`

## Current Posture

Slice 2R12 has a prepared backend workflow, but production Coinbase access is
source-disabled. `tools/run_admin_api_futures_r12_workflow.py` binds
`R12_RELEASE_READY` to literal `False`; neither environment variables nor CLI
arguments can activate it. The only CLI confirmation flag is not an activation
mechanism.

This preparation record grants no readiness conclusion. Before that literal
can be changed in a separately reviewed release step, focused validation,
local deployment validation, an independent safety audit, and a blind
contextless audit must all pass against the final bytes. This documentation
change performs no Coinbase call, state-refresh read, claim creation, or
Preview attempt.

The existing R1-R11 artifacts remain immutable. Their bytes and documented
hashes must not change. R8 remains a metadata-only restricted predecessor: its
content and hash must not be read, recomputed, compared, copied, displayed, or
logged.

The default Admin API/UI Preview readback is R12-singleton-only while this
successor is active. Its dependency constructs the fixed R12 store with latest
historical selection disabled. Before a complete R12 terminal exists, including
when R12 is absent or claim-only, the route returns one fixed sanitized `503`;
it does not select, open, parse, model-validate, copy, or project R11 or any
earlier artifact. A complete terminal is serialized only through the strict R12
response model.

## Cross-Layer Contract Hardening

The final no-live conformance pass binds the producer, terminal model, OpenAPI
contract, and frontend projection to the same rules:

- candidate opening, maximum exposure, and the fixed policy's
  `observed_concurrent_exposure_usdc` are the same positive reference notional;
  buffered close is that value times `1.20`, and turnover is opening plus
  buffered close;
- the local candidate/portfolio observation may differ from the exchange book
  timestamp only within the existing `-5` through `+30` second window; the
  eligibility cycle remains bounded to 300 seconds and the eligible-to-claim
  transition to 10 seconds;
- a returned Preview book may move from the eligibility book, but it must stay
  positive and uncrossed, and the cap binding is recomputed from the Preview
  ask and accepted economics;
- positive fractional product increments are accepted only when one contract
  is at least the minimum size and is an exact increment multiple;
- available margin is positive, maintenance margin and liquidation buffer are
  nonnegative, and accepted `order_margin_total` is positive and no greater
  than available margin;
- decimal tokens remain plain, non-exponent strings bounded to 128 characters;
- the precise `terminal_predecessor_validation_blocked` outcome can be
  persisted with its one fixed sanitized stage instead of degrading to a less
  specific recovery result.

The backend strict response model remains the canonical hash and privacy
verification boundary. It recomputes the terminal and nested canonical hashes
before the route returns a terminal. The frontend is a read-only projection:
it enforces the complete generated nested shape, exact fixed policy fields,
cross-object bindings, freshness, caps, and privacy flags, but does not create
an independent browser trading or cryptographic authority.

The final cross-layer audit also probes canonical-hash-rebound synthetic
terminals. Every R12 decimal-bearing backend field now uses the same typed
plain-decimal boundary, and generated OpenAPI exposes its 128-character maximum
and non-exponent pattern. Exponent-form or overlong product, candidate, margin,
request, or sanitized Preview economics therefore fail at the backend contract
instead of becoming a backend-valid terminal that the frontend must reject.

## Fixed Authorization Boundary

The prepared workflow retains all of these exact constraints:

- policy: the existing exact V3 profile/state policy, without broadening;
- product: `AVP-20DEC30-CDE`;
- contract count: one;
- strict caps: opening reference `<100 USDC`, concurrent exposure and buffered
  close reference `<150 USDC`, and branch turnover `<300 USDC`;
- close-buffer multiplier: `1.20` inside the existing cap binding;
- SDK: exactly `coinbase-advanced-py==1.8.4`;
- eligibility state refreshes: at most ten durably counted cycles;
- R12 attempts: at most one, beginning only when the durable claim is created;
- Preview calls after claim: at most one;
- Preview retries, fallbacks, and redirects: zero;
- Create, Cancel, Close, Reduce, submission, and every other exchange mutation:
  zero;
- post-claim Coinbase reads: zero, other than the one authorized Preview call;
- R13 attempts and Slice 3, Slice 4, or Slice 5 activation: zero.

An eligibility cycle is not an R12 attempt. An ineligible, ambiguous, stale,
incomplete, or internally blocked eligibility cycle consumes only one of the
ten state-refresh cycles. It must not create an R12 claim or idempotency key and
must leave R12 unconsumed. Offline diagnosis and remediation may occur before
another remaining cycle.

## Phase 1: Non-Attempt Eligibility

The eligibility phase uses a distinct owner-only JSONL ledger and a separate
non-attempt correlation. A cycle-start row is appended and `fsync`ed before a
Coinbase read can occur. The raw correlation value is withheld; only its
SHA-256 binding is stored. A normally returned cycle appends at most one
sanitized completion row; an interrupted start remains durably counted and
cannot be completed twice.

The ledger provides these fail-closed properties:

- no more than ten `eligibility_cycle_started` rows;
- one nonblocking workflow lease across the read-to-attempt transition;
- owner-only `0600` files, no-follow opens, identity checks, file `fsync`, and
  parent-directory `fsync`;
- a canonical append-only hash chain;
- no duplicate start/completion, no noncanonical JSON, and no records after an
  R12-attempt marker;
- a maximum of 21 records: ten start/completion pairs plus one attempt marker;
- an eligible completion only when all six category counters equal exactly
  one and the evidence remains within the fixed freshness windows;
- refusal before client or correlation creation whenever the canonical R12
  attempt artifact already exists.

The only successful eligibility classification is `exact_v3_eligible`.
Fail-closed completion classifications are fixed to
`permission_or_portfolio_ineligible`,
`product_contract_ineligible`, `market_book_ineligible`,
`position_exposure_ineligible`, `candidate_caps_ineligible`,
`margin_collateral_ineligible`, `read_outcome_unknown`, and
`internal_validation_blocked`. They contain no external exception text or raw
values. The earlier `product_or_market_or_position_ineligible` umbrella remains
accepted only so an already durable pre-remediation completion row stays
readable; new candidate-validation failures map exact internal reason constants
to one of the four fixed boundaries above. Unknown or nonconstant exception
shapes collapse to `internal_validation_blocked` without persisting their text.

### Nine Authenticated GETs Across Six Categories

Each state-refresh cycle can attempt each of the six categories at most once.
The margin/collateral category expands to four authenticated GETs, so a complete
cycle totals exactly nine GETs:

| Category | Count | Fixed authenticated GET |
| --- | ---: | --- |
| API-key permissions | 1 | `/api/v3/brokerage/key_permissions` |
| Portfolio catalog | 1 | `/api/v3/brokerage/portfolios` |
| Product | 1 | `/api/v3/brokerage/products/AVP-20DEC30-CDE` |
| Best bid/ask | 1 | `/api/v3/brokerage/best_bid_ask` for only `AVP-20DEC30-CDE` |
| Futures positions | 1 | `/api/v3/brokerage/cfm/positions` |
| Futures margin/collateral | 4 | balance summary once, intraday setting once, and current margin window once for each of the two fixed profiles |

The two current-window reads are exactly:

1. `MARGIN_PROFILE_TYPE_RETAIL_REGULAR`;
2. `MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1`.

No Futures sweep endpoint is part of R12 eligibility. In particular,
`list_futures_sweeps`, schedule-sweep, and cancel-sweep are outside the
authorized endpoint set. The R12 client uses the dedicated no-sweep margin
snapshot rather than the broader account-read snapshot.

### Exact V3 Pair

Coinbase documents the available margin-setting and profile/window tokens, but
the following exact mapping remains an operator-defined Slice 2 Preview-only
policy rather than a Coinbase recommendation:

- account setting: `INTRADAY_MARGIN_SETTING_INTRADAY`;
- regular profile: `MARGIN_PROFILE_TYPE_RETAIL_REGULAR` with
  `MARGIN_WINDOW_TYPE_UNSPECIFIED`;
- intraday profile: `MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1` with
  `MARGIN_WINDOW_TYPE_INTRADAY`;
- both returned kill-switch flags: `false`;
- exact Default/`DEFAULT` portfolio binding, view and trade permissions, no
  observed position in the selected product, positive available margin, valid
  product/session evidence, and a valid one-contract candidate under the fixed
  caps.

Any different token, profile, setting, duplicate/missing row, stale evidence,
nonzero selected-product position, invalid candidate, or unavailable margin
fails closed without creating or consuming R12.

## Transport And Delegate Binding

The production transport validator must pass before the first eligibility read
and again after claim creation before Preview. It requires:

- installed distribution exactly `coinbase-advanced-py==1.8.4`;
- API base host exactly `api.coinbase.com`;
- timeout exactly 30 seconds and SDK rate-limit-header handling disabled;
- only the `http://` and `https://` session adapters, each with retry total `0`;
- redirect maximum `0`;
- `trust_env=false` and an empty proxy map, so ambient proxy settings cannot
  redirect the request path;
- the prepared certifi CA bundle path and no transport-policy drift.

The production runner creates one memoized canonical Default-profile REST
delegate. The eligibility capability holds that exact object, and the
eligible-to-claim transition passes the same object into the attempt workflow.
The attempt phase cannot hydrate a second SDK client, substitute a delegate,
or construct its Preview facade without a valid durable-claim capability.

Credential hydration inside each cycle is limited to one fixed AWS Secrets
Manager `GetSecretValue` process for secret `coinbase` in `us-east-1`. The
R12-local resolver uses the canonical AWS CLI, CA bundle, and default shared
credentials file in a closed environment with `AWS_MAX_ATTEMPTS=1`, a fixed
regional endpoint, bounded connect/read/process timeouts, bounded output, no
proxy inheritance, and value-blind failure. Its single-use capability is
consumed before process start, so a failed or ambiguous lookup cannot be
retried within that cycle. Before and after that process, the runner verifies
the pinned AWS CLI 2.35.24 executable, complete installation-tree digest and
shape, exact symlink chain, CA-bundle membership, owner and non-writable file
metadata, and exact value-blind `aws --version` output. It also snapshots and
compares the owner-only, single-link shared-credentials file identity around
the process without reading or logging credential content. Any missing,
changed, ambiguous, or unverified binding fails closed after at most the one
consumed credential-hydration process.

No individual Coinbase call is retried. A transport exception is classified
without exception text; the workflow cannot redirect to another endpoint,
profile, product, or client.

## Phase 2: One Durable Attempt

Only a fresh `exact_v3_eligible` completion under the still-held workflow lease
can mint the private transition capability. Immediately before reservation, the
attempt workflow revalidates the complete sanitized eligibility evidence,
candidate, Preview request, hashes, timestamps, transport posture, exact
predecessor binding, paths, product, one-contract count, caps, and V3 pair.

Creating the canonical durable R12 claim begins and consumes the single-use
attempt. The claim stores separate withheld-and-hashed attempt correlation and
idempotency bindings; neither can equal the non-attempt correlation binding.
The claim authorizes only `preview_order`, once. It authorizes no other
Coinbase method.

The R12-only store builds and `fsync`s the complete owner-only claim in a
same-directory staging file, then publishes it with an atomic no-clobber hard
link. Successful link publication is the consumption boundary. Publication is
made directory-durable before the staging name is removed, and that cleanup is
directory-durable before reservation returns (`link -> fsync(directory) ->
unlink(staging) -> fsync(directory)`). Any failure after link publication is
therefore consumed and enters offline recovery; a failure that leaves neither
the canonical path nor published claim evidence remains pre-attempt.

After reservation, the workflow appends an `r12_attempt_claimed` marker to the
eligibility ledger and disables all later eligibility reads. A marker-write
ambiguity does not reopen eligibility: the canonical attempt artifact remains
the authoritative stop signal, R12 is consumed, and the terminal is unknown.

The Preview response path preserves the validated R11 compatibility boundary:
the shallow raw SDK envelope is validated before recursive `_plain()`
normalization, converter-only envelopes are rejected, and the normalized
response is checked against the exact candidate and available margin. A raw
Preview identifier is never persisted or returned. Accepted evidence stores
`preview_id="withheld"` plus only its SHA-256 binding.

## Crash And Unknown-Outcome Recovery

Production startup checks the canonical R12 attempt artifact before the source
release gate and before any credential or client factory can run. Recovery
holds the same nonblocking workflow lease used by eligibility and the
eligible-to-claim transition, so it cannot race a state refresh, claim
transition, Preview path, or terminal write.

Before deciding that the canonical artifact is absent, recovery normalizes
only exact-prefix, owner-only R12 staging files. A same-inode claim staging link
is removed while preserving the canonical consumed claim; safe unpublished
claim staging and safe unpublished terminal staging are removed and the parent
directory is `fsync`ed. Symlinks, foreign ownership, unexpected modes, link
counts, sizes, or identities fail closed without being followed.

- No artifact: remain in eligibility posture, subject to the remaining
  ten-cycle budget, disabled release gate, and all validation/audit gates.
- Complete two-row artifact: validate and return only the fixed sanitized
  terminal projection.
- Claim-only artifact: transition offline to a terminal with
  `claim_only_recovery_unknown_consumed`; do not create identifiers, hydrate a
  client, or call Coinbase.
- Invalid or ambiguous artifact state: fail closed and do not call Coinbase.

Every R12-specific terminal transition is validated against the strict
`AdminFuturesOrderPreviewR12Response` model before persistence. The R12 store
writes and `fsync`s a complete claim-plus-result temporary artifact, seals it
owner-read-only, rechecks the original claim identity, atomically replaces the
claim path, `fsync`s the parent directory, and validates exact readback. There
is no in-place partial terminal append window. A failed or ambiguous transition
remains consumed; any later action is the same offline claim-only recovery
under the lease, never a second claim or Coinbase call.

Any uncertainty once canonical claim material exists, including marker
persistence, Preview-boundary initialization, or Preview return, consumes R12
and cannot be retried. A definitively failed reserve with no claim artifact is
still pre-attempt. Once a claim exists, recovery and diagnosis are offline only.

## Diagnostics And Privacy

Every persisted or returned diagnostic is fixed, sanitized, and value-blind.
The terminal can be `accepted`, `blocked`, or `unknown`; blocker and post-stage
reason codes come from closed allowlists. No raw external exception text is
used as a classifier.

The workflow and response model must reject extra nested fields, raw response
objects, raw portfolio/correlation/idempotency/Preview identifiers, secret
material, private identifiers, and withheld exception text. Portfolio and
correlation values are withheld with hash bindings where required. The runner
returns only a small fixed summary and never emits the full durable artifact.

These privacy rules apply equally to logs, backend readback, generated OpenAPI
and client contracts, frontend readback, tests, audits, and documentation.

## Official Coinbase References

- [Get API Key Permissions](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/data-api/get-api-key-permissions)
- [List Portfolios](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/list-portfolios)
- [Get Product](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-product)
- [Get Best Bid/Ask](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-best-bid-ask)
- [List US Derivatives Positions](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/list-futures-positions)
- [Get US Derivatives Balance Summary](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-futures-balance-summary)
- [Get Intraday Margin Setting](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-intraday-margin-setting)
- [Get Current Margin Window](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-current-margin-window)
- [Preview Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [coinbase-advanced-py v1.8.4](https://github.com/coinbase/coinbase-advanced-py/tree/v1.8.4)

The official endpoint documentation defines the wire endpoints and token
allowlists. It does not define or authorize this project's V3 profile/state
pair, caps, attempt count, or release decision.

## Required Gate Before Any Toggle

The final prepared bytes must pass, at minimum:

```bash
pytest -q \
  tests/unit/test_admin_api_futures_order_preview_r12.py \
  tests/unit/test_admin_api_futures_order_preview_r12_concurrency.py \
  tests/unit/test_admin_api_futures_order_preview_r12_contract.py \
  tests/unit/test_admin_api_futures_order_preview_r12_persistence.py \
  tests/unit/test_run_admin_api_futures_r12_workflow.py \
  tests/unit/test_coinbase_client_wallets.py
python3.13 tools/check_ownership.py
npm --prefix ../coinbase-frontend run test -- \
  tests/unit/FuturesOrderPreviewR12Readback.test.tsx
```

The release review must also prove generated OpenAPI/client consistency,
focused Admin API route/readback coverage, local deployment behavior, no-sweep
accounting, source-disabled no-factory behavior, exact predecessor/path
bindings, claim-only offline recovery, and zero retry/fallback/redirect/mutation
posture. Independent safety and blind contextless auditors must review the same
final bytes and return no unresolved finding.

Only then may a separate audited source change consider setting
`R12_RELEASE_READY` to `True`. Authorization alone does not bypass this hard
gate. Until that change is reviewed and validated, invoking the runner can only
recover an existing local attempt artifact or return
`futures_preview_r12_release_gate_inactive`; it cannot reach a Coinbase client
factory.

## Post-Terminal Offline Closeout

If R12 becomes terminal, the authorized workflow continues only with bounded
offline diagnosis and remediation. That work may update fixed sanitized
classification, tests, backend models, generated contracts, frontend readback,
and documentation, but it may not alter the immutable R1-R12 evidence or make
another Coinbase call. It must not reconstruct a raw response, identifier,
secret, or withheld exception. A future terminal-diagnosis document may be
created only from the validated sanitized terminal after it exists.

Offline closeout does not grant R13, a second Preview, or any exchange mutation.

## Stop Conditions

The prepared workflow stops when any of these conditions applies:

- R12 is terminal and its authorized offline closeout is complete;
- ten eligibility state-refresh cycles are exhausted with R12 unconsumed;
- proceeding would change the product, contract count, exact V3 policy, caps,
  enumerated GET endpoints, or exchange-call limit;
- a required validation or audit remains unresolved.

This preparation grants no R13 attempt, no second R12 call, no Slice 3, Slice
4, or Slice 5 activation, and no other live authority. Do not create an R12
terminal-diagnosis document until R12 is actually terminal.
