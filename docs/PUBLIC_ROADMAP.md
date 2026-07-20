# Public Roadmap

This roadmap contains public, non-sensitive work that can be discussed without
private model routing, private release planning, or internal research notes.

## Current Direction

- Goal `operator_core_workspaces_origin_prod_alignment_v1` has Status:
  `in_progress`. Current action is
  `implement_validate_audit_and_deploy_core_operator_workspaces`; default action
  is `continue_bounded_implementation_and_offline_remediation`. It aligns the
  persistent authenticated Portfolio, Spot Operations, Orders-detail, and
  System Operations workspaces to backend-owned Admin API contracts while
  keeping Diagnostics separate. No goal-scoped Coinbase call has run yet.
- Historical predecessor goal
  `operator_follow_up_operations_queue_and_single_live_proof` completed with
  status `complete_zero_candidates`. The routed,
  passive local-SQL Follow-up Operations queue now has backend-owned
  pagination, filtering, classification, actionable readback, navigation, and
  a one-statement/no-N+1 projection of four durable proof-operation slots.
  Exact-zero current-request activity is separate from durable activity and
  Create/Cancel allowance consumption. Replay preserves durable evidence while
  reporting zero new activity; only all-null legacy accounting may project
  conservatively, and partial explicit accounting fails closed. Specialized
  follow-up errors expose sanitized typed activity without raw responses,
  private identifiers, or exception text. Focused/full validation, deployment
  validation, and independent safety plus blind-contextless audits passed. The
  exact post-gate local `materialization_review` candidate count is `0`; the
  passive queue made zero Coinbase reads/Create/Cancel calls. The goal-scoped
  proof claim was not created and was not required, and eligibility,
  reconciliation, Create, and Cancel did not run. All live allowances remain
  unconsumed, but the goal authority is closed and grants no continuing proof
  call. Keep the Controlled-live operator stack available under its separate
  durable controls.
- Historical predecessor goal
  `operator_authorize_and_materialize_follow_up_intent` has Status:
  `complete`. Its backend-owned materialization and exact-child safe-closeout
  contracts, operator readback, generated integration, focused/full validation,
  and independent safety plus blind-contextless audits passed. The live proof
  found no eligible filled attached intent, so no candidate, durable attempt or
  claim, materialized child, Coinbase eligibility/reconciliation read, Create,
  Cancel, submitted/executed notional, or unknown live outcome exists. The
  live-proof allowances remain unconsumed. Synthetic tests are not live proof.
  Evidence is backend focused `164 passed`, canonical full `1102 passed, 6
  skipped` parallel plus `457 passed, 150 skipped` serial, frontend focused
  `179 passed`, and independent safety plus blind-contextless audit `PASS`.
  Its terminal action was `await_operator_direction_for_next_mvp`.
  Bounded Controlled-live observation for candidate counting: the audited
  installed operator review stack reported runtime mode `controlled_live`, frontend
  `0.0.0.0:3000`, backend
  `127.0.0.1:8787`, and approved Test portfolio configuration without exposing
  its identifier. This observation made zero Coinbase calls and does not claim
  final post-closeout deployment health. Release, startup, and status made zero
  Coinbase calls and consumed no live-proof allowance.
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
  call.
- `operator_authorize_and_materialize_follow_up_intent` is the first delivered
  live-capable Orders-detail successor mutation. It adds a separately
  acknowledged, one-use backend materialization
  attempt only after a fresh authoritative full-fill, lineage, approved Test
  portfolio, Spot-product, market, wallet, and cap decision. The backend derives
  the child identity and entire order tuple, persists the exact child in a
  non-revealable local state before crossing the durable boundary, and permits
  no more than one canonical Create. A separate exact-child safe-closeout may
  use no more than one canonical Cancel after exact pre-Cancel evidence. Create
  response identity plus exact post-Create readback and exact post-Cancel
  readback bind the complete child tuple and terminal truth. Unknown outcomes
  consume their applicable allowance; crash recovery journals unknown before
  read-only reconciliation, and neither action retries, follows a redirect,
  falls back to another identity, or accepts browser trading terms. The
  passive Orders-detail read remains local-only and separately reports only
  whether a fresh acknowledgement request may be forwarded.
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
