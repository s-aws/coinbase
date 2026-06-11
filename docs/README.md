# Documentation Index

Ordered entry point for the Coinbase Advanced Trading Engine documentation.

## Project Entry

- [Root README](../README.md)
- [Expanded AI Context](../genai_data/README.md)
- [Architecture](../genai_data/ARCHITECTURE.md)
- [Order ID Handling](../genai_data/ORDER_ID_HANDLING.md)

## Main Workflows

- [Action Condition Guards](../README.action-condition-guards.md)
- [Spot Trading](../README.spot-trading.md)
- [Spot Portfolio Sweep](../README.spot-portfolio-sweep.md)
- [Spot Campaigns](../README.spot-campaign.md)
- [Spot Campaign Public Runbook](SPOT_CAMPAIGN_PUBLIC_RUNBOOK.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Live Order Surfaces](LIVE_ORDER_SURFACES.md)
- [Admin API](../README.admin-api.md)
- [Movement And Repricing](../README.movement-repricing.md)
- [Futures/Perpetuals Admin Reads](../README.futures-perpetuals.md)
- [Guard/Risk Policy Admin Reads](../README.guard-risk-policy.md)
- [Audit Workbench Admin Reads](../README.audit-workbench.md)
- [Admin Platform Architecture](ADMIN_PLATFORM_ARCHITECTURE.md)
- [Admin Module Capability Matrix](ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Frontend Association](FRONTEND_ASSOCIATION.md)
- [Admin API E2E Plan](plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin API Contextless Review Log](plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md)
- [Autonomous Work Queue](plans/AUTONOMOUS_WORK_QUEUE.md)
- [Spot Phases 185-196 Report](plans/SPOT_PHASE_185_196_REPORT.md)
- [Netflix AI Engineer Workbench](../README.netflix-ai-engineer-site.md)
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
- [Testing Strategy](../genai_data/TESTING_STRATEGY.md)
- [Spot Readiness Test Gate](SPOT_READINESS_TEST_GATE.md)
- [Spot Contextless Agent Testing](SPOT_CONTEXTLESS_AGENT_TESTING.md)
- Contextless checklist harness:
  `python tools\run_spot_contextless_agent_checklist.py --summary-only`
- Direct spot order audit:
  `python tools\run_spot_direct_order_audit.py --client-order-id <client_order_id>`
- Dashboard direct spot order audit:
  `request_spot_direct_order_audit` with `params.client_order_id`
- Spot campaign operator reports:
  `python tools\run_spot_campaign.py --ledger-cleanup-plan --summary-only`
  and `python tools\run_spot_campaign.py --pnl-delta-report --summary-only`
- Local Admin API runner:
  `python tools\run_admin_api.py --dev-token local-admin-token`
- Admin API OIDC readiness smoke:
  `python tools\run_admin_oidc_readiness_smoke.py --summary-only`
- Autonomous work queue check:
  `python tools\run_autonomous_work_queue_check.py --summary-only`

## Examples

- [Action Condition Guard Examples](examples/action-condition-guards.md)
- [Spot Trading Examples](examples/spot-trading.md)
- [Spot Feature Intake Examples](examples/spot-feature-intake.md)
- [Spot Portfolio Sweep Examples](examples/spot-portfolio-sweep.md)
- [Spot Campaign Examples](examples/spot-campaign.md)
- [Spot Campaign Retry Fixture](examples/spot-campaign-retry-plan-fixture.json)
- [Admin API Examples](examples/admin-api.md)
- [Movement And Repricing Examples](examples/movement-repricing.md)
- [Futures/Perpetuals Examples](examples/futures-perpetuals.md)
- [Guard/Risk Policy Examples](examples/guard-risk-policy.md)
- [Audit Workbench Examples](examples/audit-workbench.md)
- [Netflix AI Engineer Workbench Examples](examples/netflix-ai-engineer-site.md)

## State, Modes, And Roadmaps

- [Public Roadmap](PUBLIC_ROADMAP.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Spot Readiness Roadmap](SPOT_READINESS_ROADMAP.md)
- [Agent State](../genai_data/agent_state.md)
- [Debugging Strategy](../genai_data/DEBUGGING_STRATEGY.md)
