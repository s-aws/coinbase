# Futures Slice 2R11 Preparation

Goal id: `futures_preview_acceptance_recovery_r11`

Final action: `stop_and_await_operator_direction`

Status: `complete_terminal_blocked_before_preview`

Alignment token: `r11_terminal_pre_preview_v3_operator_policy_rejection`

## Current Posture

Slice 2R11 is consumed, terminal `blocked`, immutable, and cannot be retried.
It stopped at `remaining_margin_validation` before candidate construction or
Coinbase Preview. All six bounded reads ran exactly once; Preview, retry,
fallback, redirect, submission, Create, Cancel, Close, Reduce, and every other
exchange-mutation counter remained `0`.

The structured boundary is
`margin_window_type_documented_but_operator_rejected`: failing row `1`,
recognized profile `retail_intraday_margin_1`, field `margin_window_type`, and
value type `string`. This is an exact V3 operator-defined profile/state-policy
rejection, not a Preview response or a reason to broaden schema or acceptance.
The immutable R11 file/evidence SHA-256 pair is
`effb4bd037b853e06da14a0327d71eb8104e2b7edb2f56970b4c47ef855b6061` /
`548bbb02709c70dc320219bc15520b40ed948309ad09ec0f8af8f812d63bedea`.
The runner is permanently tombstoned. See
`docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md`.

Unless a section explicitly states the terminal result, the remaining
readiness, activation, and validation language is retained as historical
preparation evidence only and grants no current authority.

## Fixed Authority Boundary

The successor retains all of these exact constraints:

- policy: exact V3;
- product: `AVP-20DEC30-CDE`;
- contract count: one;
- strict caps: `<100 / <150 / <300 USDC`;
- Coinbase Preview attempts: one was authorized, zero ran, and the claim is
  consumed with no remaining authority;
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

The bootstrap also binds the complete confirmed non-stdlib execution closure,
not only the four Preview-path files. The canonical
`r11-runtime-dependency-binding-v1` manifest contains exactly these 17
distributions and versions:

- `coinbase-advanced-py==1.8.4`, `requests==2.34.2`, `urllib3==2.7.0`,
  `PyJWT==2.13.0`, `cryptography==49.0.0`, and `cffi==2.1.0`;
- `certifi==2026.6.17`, `charset-normalizer==3.4.9`, `idna==3.18`,
  `backoff==2.2.1`, `websockets==13.1`, and `PySocks==1.7.1`;
- `pydantic==2.13.4`, `pydantic_core==2.46.4`,
  `annotated-types==0.7.0`, `typing-inspection==0.4.2`, and
  `typing_extensions==4.16.0`.

Its exact binding SHA-256 is
`2119cad7e5d47201a637511c61944ff01be7b5708cb642be8da8634edb8f1541`.
Before any project import, every distribution's exact site, metadata name,
version, `RECORD` hash, recorded-file size, and recorded-file digest must
validate, with no symlink, duplicate provider, cross-site shadow, or
unrecorded executable source or extension. A persistent import-origin guard
then admits site-package modules only when their origins are in that verified
`RECORD` file set. It remains installed for lazy imports, and loaded origins
are content-and-identity revalidated immediately when located and swept again
after the fixed SDK and project imports. Imported test mode retains the guard
through those project imports, then removes it because that mode has no live
factory authority. An unexpected
non-stdlib import therefore fails closed instead of expanding the manifest at
runtime.

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

## Credential Lookup Boundary

The Secrets Manager subprocess is also hash-bound before live activation. It
uses the absolute, versioned executable
`/home/developer/.local/aws-cli/v2/2.35.24/dist/aws`, never the mutable
`aws` name or a `current`/`PATH` lookup. The executable SHA-256 is
`cf06831bd626c1132effdff0c403cc115ae15fe83aaf455f43e504c148d344e5`.
The complete versioned AWS CLI tree is bound to 8,649 entries, 254,415,287
regular-file bytes, and SHA-256
`ec5b4574cc2fd9ee0f91afe7cef682a52ded5ac98faeae9bbc23b0b6f04ff7c1`.
The command also pins that tree's
`dist/awscli/botocore/cacert.pem`, the `coinbase` secret id, the
`us-east-1` region, the regional HTTPS Secrets Manager endpoint, JSON output,
no pager, one AWS attempt, and bounded connect/read/process timeouts.

Its child environment is constructed from scratch with only this allowlist:

- `AWS_CLI_AUTO_PROMPT=off`, `AWS_CLI_HISTORY_FILE=/dev/null`,
  `AWS_CONFIG_FILE=/dev/null`, `AWS_EC2_METADATA_DISABLED=true`, and
  `AWS_PAGER=`;
- `AWS_DEFAULT_REGION=us-east-1`, `AWS_REGION=us-east-1`,
  `AWS_PROFILE=default`, `AWS_MAX_ATTEMPTS=1`, and
  `AWS_RETRY_MODE=standard`;
- `AWS_SHARED_CREDENTIALS_FILE=/home/developer/.aws/credentials`,
  `HOME=/nonexistent`, `LC_ALL=C`, and `PATH` equal to the versioned AWS CLI
  `dist` directory.

No ambient `PATH`, `AWS_*`, proxy, endpoint, TLS, config, or credential
override is inherited. Preflight may validate the executable bundle and
credential-provider file metadata without reading credential content, but it
cannot perform a secret lookup. The deferred client first validates the exact
exclusive persisted R11 claim; only then may its sole client factory mint a
single-use claim-bound lookup capability. The lookup consumes that capability,
revalidates the claim, the full AWS CLI binding, and the credential file's
stat-only identity immediately before the subprocess, then revalidates the
bundle and credential identity again before returning any payload. Direct or
imported-mode lookup without CLI activation and that persisted-claim capability
fails before a subprocess. Any scope, bundle, subprocess, timeout,
exit-status, or bounded-output failure is reduced to the fixed value-blind
`futures Preview R11 credential preparation failed` diagnostic. It never
includes AWS stdout, stderr, exception text, credentials, or secret payloads.
That post-claim failure consumes R11 and cannot authorize a second lookup or
Coinbase attempt.

This credential hardening changes no trading authority: R11 still permits at
most one Coinbase Preview call and zero Coinbase retries, fallbacks,
redirects, Create, Cancel, Close, Reduce, or other exchange mutations.

## Historical Readiness And Audit Gate

The following gate governed preparation before the terminal claim. It is
retained as audit history and grants no current runner authority:

- focused backend response, claim, privacy, runner, model, and OpenAPI tests
  pass with synthetic sanitized fixtures;
- focused frontend contract and readback tests pass without action controls;
- local deployment validation passes;
- backend and frontend tracked worktrees are clean, on `main`, and exactly
  synchronized with `origin/main`; the backend permits no untracked file, while
  the frontend permits only the four pre-existing root PNGs bound by exact
  filename and SHA-256 (all other untracked files fail the gate). A second
  backend closure check also rejects ignored importable source, legacy
  bytecode, symlinks, or ABI extensions in tracked Python namespaces;
- the prepared backend and frontend revisions are bound as their exact raw,
  lowercase 40-hex Git object IDs; the normalized runner, authorization,
  audit-receipt, and component integrity evidence remains exact lowercase
  64-hex SHA-256. The exact SDK pin and bounded activation expiry are also
  fixed;
- one independent safety audit and one independent blind-contextless audit
  return distinct passing receipts;
- the activation commit changes only the runner relative to the prepared
  revision, and a stdlib-only bootstrap parses a structurally inert `if False`
  audit-binding suite before execution can reach it; the suite must contain
  exactly the ten named literal assignments with no extra statement, call,
  duplicate, executable expression, or alternate wrapper;
- direct preflight and confirmation require isolated, site-disabled,
  bytecode-disabled Python with an impossible adjacent-cache prefix
  (`python3.13 -I -S -B -X pycache_prefix=/dev/null/r11`).
  Before the runner adds the repository to `sys.path` or imports any project
  module, the bootstrap verifies clean synchronized `main` revisions, zero
  backend untracked files, the exact hash-bound frontend PNG allowlist, the
  documented Python 3.13 interpreter, the exact `coinbase-advanced-py` 1.8.4
  metadata, the exact 17-distribution runtime binding, every complete
  distribution `RECORD`, every recorded file hash and size, the absence of
  unrecorded dependency executable files, and the existing Preview-path source
  hashes. The verified dependency sites are ordered explicitly, a persistent
  origin guard is installed before project imports, and all loaded site-package
  origins are rechecked against the verified trees after imports;
- imported mode performs the same source, repository, dependency, and origin
  checks but has no CLI bootstrap receipt. It cannot confirm R11, construct the
  fixed production store, or hydrate the canonical client. Synthetic path,
  client, clock, and producer injection exists only in tests over the underlying
  non-live producer;
- the production R11 path is absent before reservation and the exact R10
  predecessor validates immediately before the attempt.

Preflight is offline. It must not load credentials, instantiate a live client,
call Coinbase, or create the production artifact. Audit activation does not
itself consume R11; the exclusive claim reservation does.

The historical canonical commands were:

```bash
python3.13 -I -S -B -X pycache_prefix=/dev/null/r11 tools/run_admin_api_futures_no_live_preview_r11.py --preflight
python3.13 -I -S -B -X pycache_prefix=/dev/null/r11 tools/run_admin_api_futures_no_live_preview_r11.py --confirm-one-r11-preview
```

Neither command may be invoked now. R11 is consumed and the runner is
permanently tombstoned.

## Terminal Handling

The authorized call count is global for R11, not per process, command, failure
category, or remediation cycle. There is no retry after a transport-unknown,
validator-blocked, persistence-blocked, or otherwise uncertain result.

The first independent pre-activation audit found that the R11 producer's fixed
value-blind early blocker and fixed terminal-predecessor-validation suffix were
stricter than the existing read-model grammar. Red tests now prove both exact
R11 forms remain value-blind and can be validated for Admin API readback; the
model accepts only those exact R11 constants while retaining the older
tokenized grammar for predecessor attempts.

The later blind audit rejected the first isolated bootstrap because dependency
path precedence, four-file-only SDK binding, ignored executable shadows, and
redirectable imported helpers left alternate pre-import or per-path behavior.
The complete `RECORD`/origin closure, impossible bytecode cache, ignored-shadow
gate, imported source validation, and fixed production-only constructors are
the corresponding fail-closed remediation. No rejected audit receipt is
eligible for activation binding.

The first fresh post-validation blind-contextless audit also rejected the
prepared frontend because confirmed-live Futures place, close/reduce, and
cancel controls were co-resident with R11 readback and ignored the runtime
live-action flag. That rejected receipt is likewise ineligible. The bounded
remediation keeps `BackendRuntime.liveActionsEnabled` fixed false, omits all
three confirmed-live controls, rejects confirmed-live intent before client
invocation, preserves only `dry_run=true` drafts and read-only fill evidence,
and expands the audited component manifest to cover the complete Admin-shell,
runtime, canonical client/BFF, unit, e2e, and documentation boundary. Fresh
validation and two new passing receipts remain mandatory.

The first activation after that frontend remediation failed its isolated
preflight at the literal bootstrap before claim reservation, credential
hydration, dependency imports, or network access. R11 remained absent and
unconsumed. The parser had incorrectly grouped the raw 40-hex preparation and
frontend Git object IDs with 64-hex SHA-256 evidence, while the later
activation-commit check compared those fields directly with `git rev-parse`.
The bounded offline correction restores an inactive gate, validates the two
Git object IDs with an exact lowercase 40-hex grammar, validates only the
integrity fields with the exact lowercase 64-hex SHA-256 grammar, and adds
mixed-width positive and wrong-width negative tests. The failed activation's
receipts, component binding, normalized hash, and expiry are stale and cannot
be reused; a new preparation revision and two fresh passing audits are
required before a new runner-only activation child may exist.

The bounded offline diagnosis and remediation are complete. The closeout binds
the immutable terminal hashes above, permanently tombstones the runner, and
classifies the result as the fixed pre-Preview V3 operator-policy boundary.
No raw response, secret, private identifier, restricted Preview identifier, or
exception text was added to readback.

This goal grants no R12 attempt and no Slice 3, Slice 4, or Slice 5 activation.
Those terminal conditions are satisfied. Further work requires explicit
operator direction and may not infer authority to change the product, contract
count, V3 policy, caps, or one-call limit.

## Historical Validation Scope

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
