# Documentation Index

Ordered entry point for the Coinbase Advanced Trading Engine documentation.

## Project Entry

- [Current MVP Goal](../genai_data/AGENT_MVP_REBUILD_GOAL.md) - goal id
  `futures_preview_acceptance_recovery_r8_r10_and_conditional_terminal_roundtrip_slice_3`;
  R8 terminal blocked with opaque zero-call readback, R9 terminal blocked after
  one returned Preview reached response validation, R10 terminal blocked at
  sanitized economics validation, recovery exhausted, and Slice 3 not run
- [Futures Slice 2R7 Preparation and Closeout](FUTURES_SLICE_2R7_PREPARATION.md) -
  immutable R6 ancestry, corrected response-schema binding, one-use transport
  posture, readiness gates, and terminal record
- [Futures Slice 2R7 Terminal Diagnosis](FUTURES_SLICE_2R7_TERMINAL_DIAGNOSIS.md) -
  derived sanitized failure boundary, hash semantics, terminal machine state,
  and no-retry/no-successor authority
- [Futures Slice 2R8 Terminal Diagnosis](FUTURES_SLICE_2R8_TERMINAL_DIAGNOSIS.md) -
  opaque fixed-artifact binding, zero-call forensic classification, test-path
  remediation, and conditional R9 successor posture
- [Futures Slice 2R9 Terminal Diagnosis](FUTURES_SLICE_2R9_TERMINAL_DIAGNOSIS.md) -
  exact immutable file/evidence hashes, one-Preview response-validation
  boundary, zero-mutation proof, and historical R10 preparation posture
- [Futures Slice 2R10 Terminal Diagnosis](FUTURES_SLICE_2R10_TERMINAL_DIAGNOSIS.md) -
  exact immutable terminal binding, sanitized economics-validation boundary,
  zero-mutation accounting, permanent runner disablement, and no-successor state
- [Root README](../README.md)
- [Expanded AI Context](../genai_data/README.md)
- [Architecture](../genai_data/ARCHITECTURE.md)
- [Order ID Handling](../genai_data/ORDER_ID_HANDLING.md)

## Main Workflows

- [Action Condition Guards](../README.action-condition-guards.md)
- [Spot Trading](../README.spot-trading.md)
- [Spot Portfolio Sweep](../README.spot-portfolio-sweep.md)
- [Spot Campaigns](../README.spot-campaign.md)
- [Spot Recovery Proof Records](../README.spot-recovery-proofs.md)
- [Spot Recovery Snapshot Records](../README.spot-recovery-snapshots.md)
- [Stealth Command Suite Readiness](../README.stealth-command-suite.md)
- [Stealth Active-Placement Exchange-Truth Evidence](../README.stealth-exchange-truth-proofs.md)
- [Stealth Mutation-Claim Snapshot Proofs](../README.stealth-mutation-claim-proofs.md)
- [Stealth Manager-Invocation Policy](../README.stealth-manager-invocation-policy.md)
- [Stealth Coinbase Exchange Policy](../README.stealth-coinbase-exchange-policy.md)
- [Stealth State-Mutation Policy](../README.stealth-state-mutation-policy.md)
- [Stealth Post-Write Reconciliation Execution Policy](../README.stealth-post-write-reconciliation-execution-policy.md)
- [Stealth Recovery Proofs](../README.stealth-recovery-proofs.md)
- [Stealth Reveal-Trigger Proofs](../README.stealth-reveal-trigger-proofs.md)
- [Stealth Reconciliation Proofs](../README.stealth-reconciliation-proofs.md)
- [Stealth Cancel/Replace Proofs](../README.stealth-cancel-replace-proofs.md)
- [Stealth Order Reads](STEALTH_ORDER_READS.md)
- [Spot Campaign Public Runbook](SPOT_CAMPAIGN_PUBLIC_RUNBOOK.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Live Order Surfaces](LIVE_ORDER_SURFACES.md)
- [Admin API](../README.admin-api.md)
- [Admission Audit Records](../README.admission-audits.md)
- [Cap/Guard Decision Records](../README.cap-guard-decisions.md)
- [Reconciliation Plan Records](../README.reconciliation-plans.md)
- [Movement And Repricing](../README.movement-repricing.md)
- [Futures/Perpetuals Admin Reads](../README.futures-perpetuals.md)
- [Guard/Risk Policy Admin Reads](../README.guard-risk-policy.md)
- [Audit Workbench Admin Reads](../README.audit-workbench.md)
- [Admin Platform Architecture](ADMIN_PLATFORM_ARCHITECTURE.md)
- [Admin Module Capability Matrix](ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Maintainer Handoff](MAINTAINER_HANDOFF.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [USDC Pair Snapshot Limit Automation MVP](plans/USDC_PAIR_SNAPSHOT_LIMIT_AUTOMATION_MVP.md)
- [Frontend Association](FRONTEND_ASSOCIATION.md)
- [Admin API E2E Plan](plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Command Workflows](COMMAND_WORKFLOWS.md)
- [Operator Read Models](OPERATOR_READ_MODELS.md)
- [Admin API Contextless Review Log](plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md)
- [Autonomous Work Queue](plans/AUTONOMOUS_WORK_QUEUE.md) - historical planning
  and artifact evidence only
- [Spot Phases 185-196 Report](plans/SPOT_PHASE_185_196_REPORT.md)
- [API Reference](../genai_data/API_REFERENCE.md)
- [Configuration](../genai_data/CONFIGURATION.md)
- [Data Models](../genai_data/DATA_MODELS.md)

## Tooling And Policy

- [Agents Overview](agents/README.md)
- [Public Invariants](agents/INVARIANTS.md)
- [Ownership](agents/OWNERSHIP.md)
- [Admin API Contract Agent](agents/AGENT_ADMIN_API_CONTRACT.md)
- [Public Release Readiness](PUBLIC_RELEASE_READINESS.md)
- [External Testing Runbook](EXTERNAL_TESTING_RUNBOOK.md)
- [Regression Process](REGRESSION_PROCESS.md)
- [Testing Strategy](../genai_data/TESTING_STRATEGY.md)
- [Spot Readiness Test Gate](SPOT_READINESS_TEST_GATE.md)
- [Spot Contextless Agent Testing](SPOT_CONTEXTLESS_AGENT_TESTING.md)
- Contextless checklist harness:
  `python3.13 tools/run_spot_contextless_agent_checklist.py --summary-only`
- Direct spot order audit:
  `python3.13 tools/run_spot_direct_order_audit.py --client-order-id <client_order_id>`
- Dashboard direct spot order audit:
  `request_spot_direct_order_audit` with `params.client_order_id`
- Spot campaign operator reports:
  `python3.13 tools/run_spot_campaign.py --ledger-cleanup-plan --summary-only`
  and `python3.13 tools/run_spot_campaign.py --pnl-delta-report --summary-only`
- Local app-only Admin API runner:
  `python3.13 tools/run_admin_api.py --dev-token local-admin-token`
- Canonical engine embedding:
  `main.py` with `COINBASE_ADMIN_API_EMBEDDED_ENABLED=true`; activation is not
  a separate fill-testing permission, and every order remains subject to the
  current goal's explicit order limits and complete backend gate chain.
- Process-parallel regression closeout:
  `python3.13 tools/run_parallel_regression.py --workers 4`
- Stale test-process check before closeout and after interrupted tests:
  `python3.13 tools/check_stale_test_processes.py --include-sibling-frontend`
- Runtime artifact check after regression memory spikes:
  `python3.13 tools/check_runtime_artifacts.py`
- Admin API OIDC readiness smoke:
  `python3.13 tools/run_admin_oidc_readiness_smoke.py --summary-only`
- Admin API route inventory export:
  `python -m tools.export_admin_api_route_inventory`
- Autonomous work queue check:
  `python3.13 tools/run_autonomous_work_queue_check.py --summary-only`

## Examples

- [Action Condition Guard Examples](examples/action-condition-guards.md)
- [Spot Trading Examples](examples/spot-trading.md)
- [Spot Feature Intake Examples](examples/spot-feature-intake.md)
- [Spot Portfolio Sweep Examples](examples/spot-portfolio-sweep.md)
- [Spot Campaign Examples](examples/spot-campaign.md)
- [Spot Recovery Proof Examples](examples/spot-recovery-proofs.md)
- [Spot Recovery Snapshot Examples](examples/spot-recovery-snapshots.md)
- [Stealth Command Suite Examples](examples/stealth-command-suite.md)
- [Stealth Active-Placement Exchange-Truth Examples](examples/stealth-exchange-truth-proofs.md)
- [Stealth Mutation-Claim Snapshot Proof Examples](examples/stealth-mutation-claim-proofs.md)
- [Stealth Manager-Invocation Policy Examples](examples/stealth-manager-invocation-policy.md)
- [Stealth Coinbase Exchange Policy Examples](examples/stealth-coinbase-exchange-policy.md)
- [Stealth State-Mutation Policy Examples](examples/stealth-state-mutation-policy.md)
- [Stealth Post-Write Reconciliation Execution Policy Examples](examples/stealth-post-write-reconciliation-execution-policy.md)
- [Stealth Recovery Proof Examples](examples/stealth-recovery-proofs.md)
- [Stealth Reveal-Trigger Proof Examples](examples/stealth-reveal-trigger-proofs.md)
- [Stealth Reconciliation Proof Examples](examples/stealth-reconciliation-proofs.md)
- [Stealth Cancel/Replace Proof Examples](examples/stealth-cancel-replace-proofs.md)
- [Spot Campaign Retry Fixture](examples/spot-campaign-retry-plan-fixture.json)
- [Admin API Examples](examples/admin-api.md)
- [Admission Audit Examples](examples/admission-audits.md)
- [Cap/Guard Decision Examples](examples/cap-guard-decisions.md)
- [Reconciliation Plan Examples](examples/reconciliation-plans.md)
- [Movement And Repricing Examples](examples/movement-repricing.md)
- [Futures/Perpetuals Examples](examples/futures-perpetuals.md)
- [Guard/Risk Policy Examples](examples/guard-risk-policy.md)
- [Audit Workbench Examples](examples/audit-workbench.md)

## State, Modes, And Roadmaps

- [Public Roadmap](PUBLIC_ROADMAP.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Historical Agent State Snapshot](../genai_data/agent_state.md)
- [Debugging Strategy](../genai_data/DEBUGGING_STRATEGY.md)
