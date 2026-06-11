# Admin API Contextless Review Log

This log records blind reviews for the Admin API/backend association work.

## Backend Sync Review - Phases 241-270

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- identify the backend-owned OpenAPI source
- explain manual spot order create, cancel, campaign execution, order reads,
  and direct spot audit through Admin API
- confirm live Coinbase execution posture
- confirm `client_order_id` versus exchange id usage
- identify required gates
- report code/docs gaps that would mislead a contextless agent or human

Findings:

- Backend OpenAPI source and frontend generated-client flow were discoverable.
- Manual create, cancel, campaign execution, order list/detail, and direct
  order audit routes were discoverable.
- Live HTTP Coinbase execution was clearly disabled through the app headers,
  approval gate, command service, and regression tests.
- `client_order_id` identity rules were clear. Exchange ids were exposed only
  as evidence fields.
- Required backend and frontend quality gates were discoverable.
- The frontend command UI is still intentionally disabled; this is expected.
- Frontend command mock tests used stale service method names.
- Backend Admin API agent context still described implemented files as
  future/planned.
- Frontend command workflow docs used wording that could imply current HTTP
  commands already run guard/cap checks instead of short-circuiting at the
  live-disabled gate.

Resolution:

- Updated frontend mock command responses to use `place_manual_order` and
  `cancel_order_by_client_order_id`.
- Updated `docs/agents/AGENT_ADMIN_API_CONTRACT.md` to describe current
  implemented modules, routes, and tests.
- Updated frontend command workflow docs to say guard/cap evidence is required
  before live enablement and current HTTP commands short-circuit at the
  live-disabled gate.

Status:

- Findings resolved. No live Coinbase execution was run.

## Runtime Hardening Review - Phases 371-390

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- explain how the enterprise frontend creates or dry-submits a spot order
  without inventing frontend trading behavior
- identify the backend OpenAPI source and frontend generated contract
- identify BFF server-only authority and CSRF handling
- identify manual create/cancel wrappers and `client_order_id` identity
- identify backend route/service/gate flow
- identify dry-submit, audit, idempotency, and correlation evidence rendering
- identify order pagination and direct-order audit identity rules
- list proof commands and surface misleading docs/code

Findings:

- Review passed. The frontend still has no live trading path; command buttons
  remain disabled and dry-submit/live-disabled evidence is backend-owned.
- The reviewer found the contract path:
  backend OpenAPI -> generated frontend schema -> `BackendApiClient` wrappers.
- BFF mode was clear: browser selects `/api/admin`, while server-only
  `ADMIN_API_*` variables supply backend authority and optional CSRF.
- Manual create/cancel flow was clear:
  `CommandWorkflowShell` -> `commandDrySubmit.ts` -> `BackendApiClient` ->
  backend `api/v1/routes/orders.py` -> `AdminApiCommandService`.
- Cancel, order reads, pagination, and direct-order audit remain keyed by
  `client_order_id`; exchange ids are evidence only.
- Dry-submit evidence renders HTTP status, command status, idempotency key,
  `client_order_id`, audit id, correlation id, and live Coinbase execution
  false.
- Risk identified: legacy dashboard WebSocket docs are accurate but can
  mislead a contextless frontend agent if read without the frontend/Admin API
  boundary docs.
- Risk identified: cancel route inventory wording understated the current HTTP
  live-disabled approval gate.

Resolution:

- Added explicit warnings to legacy spot/dashboard docs that enterprise
  frontend product flows must use the HTTP Admin API/BFF contract, not the
  dashboard WebSocket.
- Updated route inventory wording for HTTP cancel to match the current
  fail-closed approval gate.

Status:

- Findings resolved. No live Coinbase execution was run. Notional `$0`.
