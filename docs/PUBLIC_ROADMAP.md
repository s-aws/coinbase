# Public Roadmap

This roadmap contains public, non-sensitive work that can be discussed without
private model routing, private release planning, or internal research notes.

## Current Direction

- Keep goal id `futures_preview_acceptance_recovery_r12` as current authority
  through its exact terminal closeout. Its prepared release-disabled validation
  and audit work after an ineligible pre-claim cycle 1 remains ahead of every
  successor; this roadmap grants no extra eligibility read, claim, Preview, or
  exchange mutation.
- Preserve `selected_order_execution_closeout_slice` as completed historical
  selected-root fill-ledger/audit, terminal-child, and read-only recovery
  evidence rather than current work authority.
- Keep the public repo runnable and reviewable without private orchestration.
- Maintain strict module ownership boundaries for smaller-agent work.
- Preserve the existing regression suite as the public release gate.
- Continue moving toward v3-style compact, consistent modules without a rewrite.

## Near-Term Public Work

- After terminal closeout of the current R12 workflow, deliver
  `operator_attach_single_follow_up_intent` as the next MVP: one
  backend-authorized, durably audited, idempotent and race-safe future
  follow-up intent for an eligible system-owned source order identified by
  `source_client_order_id`. Until R12 closes this is planning-only; it grants no
  implementation, local mutation, child creation, Coinbase call, or live
  authority. The backend owns positive status and zero-fill eligibility,
  duplicate prevention, atomic claim, flat-root lineage, product policy, and
  later live gates. The browser only forwards explicit operator input through
  generated contracts and displays backend evidence.
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
