# Public Roadmap

This roadmap contains public, non-sensitive work that can be discussed without
private model routing, private release planning, or internal research notes.

## Current Direction

- Preserve goal id `futures_preview_acceptance_recovery_r12` as completed
  terminal history with status `complete_terminal_unknown_consumed`. Its
  source release gate is false, its single-use claim is consumed, and no
  further Coinbase call, R13 attempt, or Slice 3/4/5 activation is authorized.
- Preserve `selected_order_execution_closeout_slice` as completed historical
  selected-root fill-ledger/audit, terminal-child, and read-only recovery
  evidence rather than current work authority.
- Keep the public repo runnable and reviewable without private orchestration.
- Maintain strict module ownership boundaries for smaller-agent work.
- Preserve the existing regression suite as the public release gate.
- Continue moving toward v3-style compact, consistent modules without a rewrite.

## Near-Term Public Work

- `operator_attach_single_follow_up_intent` is now the first completed mutation
  in the routed operator Orders workspace. It records one backend-authorized,
  durably audited, idempotent and race-safe future follow-up intent for an
  eligible system-owned source order identified by `source_client_order_id`.
  The backend owns exact OPEN and zero-fill eligibility, duplicate prevention,
  atomic claim, flat-root lineage, Test-portfolio scope, catalog-backed Spot
  policy, and later live gates. The browser forwards only explicit operator
  acknowledgement through generated contracts and displays backend evidence.
  Attachment is a zero-notional local-state mutation: it creates no child,
  invokes no engine handler, runs no reconciliation, and makes no Coinbase
  call. Future materialization remains separate roadmap work requiring fresh
  authorization.
- Maintain the completed selected-order execution closeout and address only
  demonstrated operator-visible or immediate safety blockers. Automatic/live
  fill-event parity uses the same explicit order limits and backend gate chain
  as every live order; expected fill status creates no separate permission
  class.
- Enforce ownership boundaries with `.agents/ownership.yaml` and
  `tools/check_ownership.py`.
- Keep dashboard message contracts synchronized with implemented behavior.
- Keep stealth exchange-truth invariants documented and covered by regression
  tests.
- Bring spot trading to a readiness baseline before adding spot-specific
  strategy features. See [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md).
- Reduce root-level historical/debug clutter by archiving or moving it behind
  explicit owners.

M57 phase continuation and M58 fan-out, scheduler, runtime-control, retry,
wallet-ledger, and ladder/grid work are parked unless explicitly reprioritized
or proven to directly block the current slice.

## Non-Public Work

Private repo only:

- model selection and routing
- private agent prompts
- private release scripts and release-only tests
- private future roadmap and research notes
- agent run logs and eval output
