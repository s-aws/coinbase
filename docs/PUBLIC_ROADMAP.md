# Public Roadmap

This roadmap contains public, non-sensitive work that can be discussed without
private model routing, private release planning, or internal research notes.

## Current Direction

- Keep goal id `legacy_fill_follow_up_operator_slice` as the current delivery
  authority: Admin order -> fill/readback evidence -> follow-up decision ->
  operator-visible parent/child chain.
- Keep the public repo runnable and reviewable without private orchestration.
- Maintain strict module ownership boundaries for smaller-agent work.
- Preserve the existing regression suite as the public release gate.
- Continue moving toward v3-style compact, consistent modules without a rewrite.

## Near-Term Public Work

- Maintain the guarded no-live fill/follow-up operator slice and address only
  demonstrated operator-visible or immediate safety blockers. Automatic/live
  fill-event parity requires explicit fill-testing approval.
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
