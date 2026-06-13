# Admin API Examples

These examples describe the current enterprise Admin API contract. Mutating
HTTP endpoints are authenticated, permission-checked, idempotent, and audited,
then return `not_implemented`; they do not call Coinbase. Read-only spot
operator endpoints are available behind the same fail-closed auth dependency.

The Admin API is the backend contract layer for the enterprise admin platform.
Spot is the first complete product module. Do not use spot wallet, USDC,
cost-basis, or no-shorting rules as generic admin behavior for
futures/perpetuals, stealth orders, repricing, or risk policy modules.

## Bootstrap And Session

Start the local backend target for frontend development:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The runner binds `http://127.0.0.1:8787` by default and keeps mutating HTTP
routes live-disabled.

For frontend integration, set CORS to the exact local frontend origin:

```powershell
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
```

The CORS contract is origin-allowlisted and permits `X-CSRF-Token` for
cookie/session or BFF bridge deployments. Current bearer-token bootstrap still
fails closed unless `COINBASE_ADMIN_API_BEARER_TOKEN` is configured on the
backend. When `COINBASE_ADMIN_API_CSRF_REQUIRED=true`, mutating `/api/v1/`
requests must include `X-CSRF-Token` matching
`COINBASE_ADMIN_API_CSRF_TOKEN`; read-only `GET` routes do not require it.

Use bootstrap and session reads to render environment, backend association,
live-action posture, and backend RBAC evidence. These routes do not require
idempotency headers and do not run Coinbase orders.
The local bootstrap verifier mode is `bootstrap_bearer`. Production-shaped
OIDC deployments use `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt`; that mode
verifies RS256 JWTs against configured issuer, audience, and JWKS settings
and derives actor/role evidence from claims.

OIDC/JWT readiness uses these backend environment names:

```powershell
$env:COINBASE_ADMIN_API_AUTH_MODE = "oidc_jwt"
$env:COINBASE_ADMIN_API_OIDC_ISSUER = "https://issuer.example.test"
$env:COINBASE_ADMIN_API_OIDC_AUDIENCE = "coinbase-admin-api"
$env:COINBASE_ADMIN_API_OIDC_JWKS_URL = "https://issuer.example.test/.well-known/jwks.json"
```

Missing values fail closed with `401`. Expected claim mapping is `sub` for
subject, `email` for email, `roles` for roles, `iss` for issuer, and `aud`
for audience. In OIDC mode the backend ignores browser-supplied
`X-Admin-Actor` and `X-Admin-Roles`; those values are derived from verified
JWT claims.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as available to the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

Expected evidence:

- `ADMIN_OIDC_READINESS_SMOKE_SUMMARY` status `passed`
- missing OIDC config blocks
- configured temporary JWKS readiness reports `ready`
- `oidc_jwt` session claims define actor and roles
- live Coinbase execution not run; notional `$0`

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8787/api/v1/admin/bootstrap `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

```http
GET /api/v1/admin/bootstrap
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected posture fields:

```json
{
  "type": "admin_bootstrap",
  "backend_repository": "s-aws/coinbase",
  "mutating_routes_live_disabled": true,
  "live_execution_enabled": false,
  "live_coinbase_orders_ran": false
}
```

```http
GET /api/v1/admin/session
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
```

The session response includes `actor`, `roles`, `permissions`, and
`bearer_token_visible_to_browser=false`.

```http
GET /api/v1/admin/csrf
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns the CSRF header name, whether CSRF is required, and the
token source/rotation policy. It never returns the token value.

```http
GET /api/v1/admin/oidc-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns backend OIDC verifier evidence for release checks:
active auth mode, required and missing OIDC settings, claim mapping, JWKS
reachability, and no-live notional posture.

```http
GET /api/v1/admin/capabilities
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Command capability rows are derived from `ADMIN_API_ROUTE_INVENTORY` and
include `action_class`, `permission`, `shared_method`, `idempotency`,
`approval`, `caps`, `audit`, `command_contract`, and `parity_test`. They are
metadata for frontend validation and diagnostics only; they do not enable live
Coinbase execution. `frontend_safe=true` means the row is safe for Admin
frontend/BFF contract exposure under backend authority, not that the command
is safe or approved for live trading.

The checked-in export
`openapi/coinbase-admin-api-route-inventory.json` is generated from the same
inventory and is the artifact consumed by frontend route-coverage checks.
Each route inventory artifact row includes `module_id`; frontend checks use it
to prove route ownership, not to authorize browser-side trading behavior.

```http
GET /api/v1/admin/live-enablement
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected M8-M54 live-enablement posture:

```json
{
  "type": "admin_live_enablement",
  "status": "live_disabled",
  "approved_phase_range": "1721-1740",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "quote_currency": "USDC",
  "product_scope": "cheapest Coinbase USDC spot product available to US customers",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "retain_inventory": true,
  "reconciliation_required": true,
  "live_enabled_path_count": 0,
  "live_eligible_path_count": 0,
  "preflight_check_count": 40,
  "blocking_preflight_check_count": 20,
  "passed_preflight_check_count": 20,
  "approval_snapshot_required_count": 5,
  "approval_snapshot_present_count": 0,
  "approval_snapshot_missing_count": 5,
  "approval_snapshot_required_field_count": 75,
  "approval_snapshot_missing_field_count": 75,
  "approval_store_required_count": 5,
  "approval_store_configured_count": 5,
  "approval_store_missing_count": 0,
  "approval_store_requirement_count": 60,
  "approval_store_missing_requirement_count": 0,
  "admission_audit_required_count": 5,
  "admission_audit_configured_count": 0,
  "admission_audit_missing_count": 5,
  "admission_audit_fact_count": 50,
  "admission_audit_missing_fact_count": 45,
  "cap_guard_required_count": 5,
  "cap_guard_configured_count": 0,
  "cap_guard_missing_count": 5,
  "cap_guard_requirement_count": 70,
  "cap_guard_missing_requirement_count": 70,
  "live_execution_adapter_required_count": 5,
  "live_execution_adapter_configured_count": 1,
  "live_execution_adapter_missing_count": 4,
  "readiness_precondition_count": 45,
  "blocking_readiness_precondition_count": 29,
  "passed_readiness_precondition_count": 16,
  "paths": [
    {
      "path_id": "post.api.v1.orders",
      "route": "/api/v1/orders",
      "method": "POST",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "module_owner": "strategy",
      "identity_key": "client_order_id",
      "action_class": "live_exchange_place",
      "required_permission": "order:create",
      "shared_method": "place_manual_order",
      "live_enabled": false,
      "live_eligible": false,
      "status": "approval_required",
      "governance_status": "blocked",
      "approval_required": true,
      "cap_required": true,
      "guard_required": true,
      "audit_required": true,
      "idempotency_key_required": true,
      "operator_intent_required": true,
      "payload_hash_required": true,
      "request_id_required": true,
      "audit_id_required": true,
      "reconciliation_required": true,
      "preflight_checks": [
        {
          "name": "auth_rbac",
          "category": "authorization",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "FastAPI route requires authenticated Admin API actor and backend RBAC.",
          "detail": "Live-shaped HTTP routes already fail closed without auth and permission evidence."
        },
        {
          "name": "idempotency_operator_intent",
          "category": "idempotency",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Idempotency-Key, X-Operator-Intent, payload hash, and request id are captured before command service delegation.",
          "detail": "Current dry command contracts preserve replay/conflict evidence without placing Coinbase orders."
        },
        {
          "name": "durable_audit",
          "category": "audit",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Command audit events are written before live-disabled responses are returned.",
          "detail": "Audit id and correlation id are available as operator evidence for dry-submit review."
        },
        {
          "name": "browser_authority",
          "category": "browser_authority",
          "status": "passed",
          "required": true,
          "blocking": false,
          "owner": "admin_api_contract",
          "evidence": "Frontend authority is display_only and command workflows require backend capability evidence.",
          "detail": "The browser may show preflight evidence but must not approve, place, cancel, or reconcile live orders."
        },
        {
          "name": "approval_snapshot",
          "category": "approval",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "admin_api_contract",
          "evidence": "No explicit M8 live approval snapshot is attached to this route.",
          "detail": "The route remains live-disabled until approval evidence is durable and route-specific."
        },
        {
          "name": "cap_guard_policy",
          "category": "cap_guard",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "Live cap and action-condition guard decisions are not yet wired as route-specific admission evidence.",
          "detail": "Guard, cap, wallet, position, and domain risk semantics must remain backend-owned before live enablement."
        },
        {
          "name": "live_execution_service",
          "category": "live_execution_service",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "place_manual_order is exposed only through the current live-disabled Admin API contract.",
          "detail": "No HTTP command route is admitted to live Coinbase execution in the enterprise Admin API path."
        },
        {
          "name": "post_live_reconciliation",
          "category": "reconciliation",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "owner": "strategy",
          "evidence": "Post-live reconciliation evidence is not wired for this route.",
          "detail": "A live path cannot be enabled until the exact route reports post-submit reconciliation evidence under cap."
        }
      ],
      "blocking_preflight_check_count": 4,
      "passed_preflight_check_count": 4,
      "readiness_precondition_count": 9,
      "blocking_readiness_precondition_count": 5,
      "passed_readiness_precondition_count": 4,
      "readiness_preconditions": [
        {
          "precondition": "approval_snapshot",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "not_configured",
          "expected_source": "approval_snapshot",
          "blocker": "approval_snapshot_missing",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "detail": "POST /api/v1/orders remains live-disabled until a durable route-specific approval snapshot is present."
        },
        {
          "precondition": "execution_intent_envelope",
          "status": "passed",
          "required": true,
          "configured": true,
          "blocking": false,
          "backend_owned": true,
          "route_bound": true,
          "source": "command_admission",
          "expected_source": "AdminApiCommandService.place_manual_order",
          "blocker": null,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "detail": "POST /api/v1/orders command admissions expose backend-owned execution intent evidence, but the intent remains non-executable while live execution is disabled."
        }
      ],
      "approval_snapshot": {
        "status": "blocked",
        "required": true,
        "present": false,
        "durable": false,
        "route_specific": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "not_configured",
        "required_field_count": 15,
        "missing_required_field_count": 15,
        "required_fields": [
          {
            "field": "route",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "/api/v1/orders",
            "detail": "Approval must bind to the exact Admin API route."
          },
          {
            "field": "method",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "POST",
            "detail": "Approval must bind to the exact HTTP method."
          },
          {
            "field": "module_id",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "spot_operations",
            "detail": "Approval must bind to the backend-owned enterprise module id."
          },
          {
            "field": "identity_key",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "client_order_id",
            "detail": "Approval must bind to the module-specific command identity key."
          },
          {
            "field": "identity_value",
            "status": "blocked",
            "required": true,
            "expected_source": "command_identity",
            "expected_value": null,
            "detail": "Approval must bind to the exact route or request identity value."
          },
          {
            "field": "action_class",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "live_exchange_place",
            "detail": "Approval must bind to the live action class being requested."
          },
          {
            "field": "required_permission",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "order:create",
            "detail": "Approval must name the backend permission required for the route."
          },
          {
            "field": "requested_by_actor_id",
            "status": "blocked",
            "required": true,
            "expected_source": "authenticated_actor",
            "expected_value": null,
            "detail": "Approval must bind to the backend-authenticated requesting actor."
          },
          {
            "field": "operator_intent",
            "status": "blocked",
            "required": true,
            "expected_source": "command_headers",
            "expected_value": null,
            "detail": "Approval must bind to durable operator intent, not browser-only acknowledgement."
          },
          {
            "field": "idempotency_key",
            "status": "blocked",
            "required": true,
            "expected_source": "command_headers",
            "expected_value": null,
            "detail": "Approval must bind to the idempotency key for the submitted command."
          },
          {
            "field": "payload_hash",
            "status": "blocked",
            "required": true,
            "expected_source": "command_service",
            "expected_value": null,
            "detail": "Approval must bind to the command payload hash so payload drift is not approved."
          },
          {
            "field": "approved_by_actor_id",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Approval must identify the backend-authenticated approver."
          },
          {
            "field": "expires_at",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Approval must expire and must not be treated as an evergreen browser switch."
          },
          {
            "field": "cap_guard_decision_ref",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Approval must bind to backend cap and guard decision evidence."
          },
          {
            "field": "reconciliation_plan_ref",
            "status": "blocked",
            "required": true,
            "expected_source": "reconciliation_policy",
            "expected_value": null,
            "detail": "Approval must bind to post-live reconciliation evidence for the route."
          }
        ],
        "evidence": [
          "No durable route-specific approval snapshot is present.",
          "Approval must be backend-owned, route-specific, expiring, and payload-bound.",
          "Browser acknowledgement is not sufficient live execution approval."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until a durable route-specific approval snapshot is present."
      },
      "approval_store_contract": {
        "status": "passed",
        "required": true,
        "configured": true,
        "durable": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "admin_api_approval_store",
        "requirement_count": 12,
        "missing_requirement_count": 0,
        "requirements": [
          {
            "requirement": "backend_owned",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval storage is owned by the backend approval store."
          },
          {
            "requirement": "route_bound",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": "/api/v1/orders",
            "detail": "Approval records bind approval to the exact route."
          },
          {
            "requirement": "payload_hash_bound",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval records bind to the submitted command payload hash."
          },
          {
            "requirement": "append_only_audit",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_approval_store",
            "expected_value": null,
            "detail": "Approval records are stored as append-only JSONL evidence."
          },
          {
            "requirement": "browser_authority_rejected",
            "status": "passed",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Approval storage must reject browser-only acknowledgement as live authority."
          }
        ],
        "evidence": [
          "Durable backend approval store contract is implemented.",
          "Approval records are backend-owned, route-bound, expiring, payload-bound, and append-only.",
          "No approval mutation endpoint or browser approval authority is exposed by this evidence."
        ],
        "detail": "POST /api/v1/orders has a durable approval store contract, but remains live-disabled until a route-specific approval snapshot, cap/guard decision, full admission audit trail, and reconciliation plan are linked."
      },
      "admission_audit_trail": {
        "status": "blocked",
        "required": true,
        "configured": false,
        "append_only": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "admin_api_audit_log_partial",
        "fact_count": 10,
        "missing_fact_count": 9,
        "facts": [
          {
            "fact": "route_admission_requested",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "POST /api/v1/orders",
            "detail": "Audit trail must record the exact route admission request."
          },
          {
            "fact": "approval_store_decision_linked",
            "status": "blocked",
            "required": true,
            "expected_source": "approval_store",
            "expected_value": null,
            "detail": "Audit trail must link the backend approval-store decision, approving actor, and requesting actor."
          },
          {
            "fact": "command_admission_decision_recorded",
            "status": "passed",
            "required": true,
            "expected_source": "admin_api_audit_log",
            "expected_value": "spot_operations",
            "detail": "Append-only Admin API audit records now store the backend admission decision before Coinbase submission."
          },
          {
            "fact": "exchange_submission_linked",
            "status": "blocked",
            "required": true,
            "expected_source": "coinbase_adapter",
            "expected_value": null,
            "detail": "Audit trail must link the exchange submission result when live execution is admitted."
          },
          {
            "fact": "browser_authority_rejection_recorded",
            "status": "blocked",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Audit trail must record that browser acknowledgement is not live authority."
          }
        ],
        "evidence": [
          "Command admission decisions are recorded in the append-only Admin API audit log.",
          "Full live admission remains blocked until approval, cap/guard, exchange submission, and reconciliation facts are linked.",
          "Browser evidence remains display-only and cannot write or satisfy admission audit facts."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until the backend can write and verify the full append-only live-admission audit trail."
      },
      "cap_guard_contract": {
        "status": "blocked",
        "required": true,
        "configured": false,
        "route_specific": true,
        "backend_owned": true,
        "browser_authority": "display_only",
        "source": "not_configured",
        "requirement_count": 14,
        "missing_requirement_count": 14,
        "requirements": [
          {
            "requirement": "backend_owned",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Cap and guard decisions must be owned and enforced by the backend."
          },
          {
            "requirement": "route_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "route_inventory",
            "expected_value": "/api/v1/orders",
            "detail": "Cap and guard decisions must bind to the exact Admin API route."
          },
          {
            "requirement": "notional_cap_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": "3.10",
            "detail": "Cap and guard decisions must enforce approved submitted/executed notional caps."
          },
          {
            "requirement": "domain_guard_bound",
            "status": "blocked",
            "required": true,
            "expected_source": "guard_risk_policy",
            "expected_value": null,
            "detail": "Spot order guard must bind notional caps, product capability, wallet budget, no-shorting SELL inventory authority, cost-basis policy, and manual live acknowledgement to the submitted payload."
          },
          {
            "requirement": "browser_authority_rejected",
            "status": "blocked",
            "required": true,
            "expected_source": "frontend_boundary",
            "expected_value": "display_only",
            "detail": "Cap and guard decisions must reject browser-computed authority."
          }
        ],
        "evidence": [
          "No route-specific backend cap/guard decision contract is configured for this route.",
          "Cap/guard decisions must be backend-owned, route-bound, payload-bound, approval-linked, and admission-audit-linked.",
          "Browser-side wallet, margin, profitability, or cap calculations cannot satisfy live admission guards."
        ],
        "detail": "POST /api/v1/orders remains live-disabled until a route-specific backend cap/guard decision contract is implemented and configured."
      },
      "live_execution_adapter": {
        "required": true,
        "configured": true,
        "backend_owned": true,
        "route_bound": true,
        "status": "approval_required",
        "source": "m53_backend_pilot_dry_run",
        "missing_reason": "pilot_dry_run_only",
        "module_id": "spot_operations",
        "route": "/api/v1/orders",
        "method": "POST",
        "service_method": "place_manual_order",
        "adapter_reference": "AdminApiCommandService.place_manual_order",
        "action_class": "live_exchange_place",
        "executable": false,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": [
          "create_order",
          "cancel_order",
          "execute",
          "submit",
          "coinbase_client"
        ],
        "evidence": [
          "Live-shaped route is mapped to the shared backend command service.",
          "The M53 pilot adapter is route-bound dry-run evidence only and remains non-executable.",
          "Browser and BFF layers cannot create a route-local execution adapter."
        ],
        "detail": "POST /api/v1/orders is mapped to AdminApiCommandService.place_manual_order through the M53 dry-run pilot adapter, but the Admin API live execution service remains disabled and non-executable."
      },
      "browser_authority": "display_only",
      "capability_source": "GET /api/v1/admin/capabilities",
      "readiness_source": "GET /api/v1/admin/enterprise-readiness",
      "reconciliation_blockers": [
        "post-live reconciliation evidence is not wired for this route",
        "explicit M8 live approval snapshot is not present for this route",
        "backend cap, guard, idempotency, operator-intent, and audit evidence must be enforced before live enablement",
        "spot wallet, inventory, no-shorting, and cost-basis authority must remain backend-owned"
      ],
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "product_scope": "cheapest Coinbase USDC spot product available to US customers",
      "max_submitted_notional_usdc": "3.10",
      "max_executed_notional_usdc": "1.00",
      "evidence": [
        "M4 guard/risk evidence required",
        "M6 command contract proof required",
        "M8 explicit live approval required",
        "idempotency, operator intent, payload hash, request id, and audit id required",
        "post-live reconciliation required"
      ],
      "notes": "Current Admin API command contract is live-disabled; this read route is governance evidence only and does not grant browser command authority."
    }
  ],
  "checks": [
    {
      "name": "live_execution_default",
      "status": "passed",
      "detail": "Default live Coinbase execution is not_run with submitted/executed notional $0."
    },
    {
      "name": "reconciliation_gate",
      "status": "blocked",
      "detail": "No path is live-enabled until post-live reconciliation evidence is wired for that path."
    }
  ],
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is evidence only. It lists command paths that could later be
considered for controlled live enablement, but every current path remains
`live_enabled=false` until explicit live approval, cap, guard, audit, and
reconciliation gates pass. M27 governance fields make that fail-closed posture
auditable per route; they do not approve live execution. M29 preflight fields
make passed and blocking prerequisites visible per route; they are not a
browser approval workflow, live switch, command route, Coinbase call, or
reconciliation substitute. M30 approval snapshot fields make the missing
durable, route-specific, backend-owned, expiring, payload-bound approval
record explicit; they are not approval storage or browser approval. M36
approval-store foundation fields make configured durable backend
approval-store infrastructure explicit; they are not approval mutation,
browser approval, command authority, Coinbase execution, or reconciliation proof.
M37 approval snapshot resolver infrastructure is backend-only and can derive
immutable evidence from exact unexpired store records; it is not proof that
command admission may proceed. M38 command admission wiring can report whether
that resolver found a snapshot, but a found snapshot only changes evidence and
does not remove live-disabled, admission-audit, cap/guard, reconciliation, or
browser-authority blockers. M39 command admission audit wiring can report
whether exact append-only admission audit proof was found, but a found audit
proof only changes evidence and does not remove live-disabled, cap/guard,
reconciliation, or browser-authority blockers. M32
admission-audit trail fields make the missing append-only backend admission
audit facts explicit; they are not audit storage, approval storage, browser
approval, command authority, Coinbase execution, or reconciliation proof.
M33 cap/guard contract fields make the missing route-specific backend cap and
guard decision bindings explicit; they are not guard execution, browser wallet
or profitability authority, browser approval, command authority, Coinbase
execution, or reconciliation proof.
M44 live execution adapter contract fields make the route-to-shared-command
service boundary explicit; they are not route-local execution, browser
approval, BFF execution authority, Coinbase calls, or order/exchange-state
mutation.
M45 live execution intent fields make the command-to-live-execution intent
explicit under command admission decisions; they are not an executable
adapter, browser approval, BFF execution authority, Coinbase call, or
order/exchange-state mutation.
M46 live readiness precondition fields normalize the route's existing
approval-store, approval-snapshot, admission-audit, cap/guard,
reconciliation, adapter, intent, browser/BFF, and disabled live-service
evidence into a checklist. They are derived from `GET
/api/v1/admin/live-enablement`; they are not a new endpoint, command
admission call, browser approval workflow, BFF execution authority, live
switch, Coinbase call, or route-local executor.

M34 command admission decision fields appear on live-disabled HTTP command
responses. They bind the command route, module, identity key, actor,
idempotency key, operator intent, and payload hash to the current blockers.
They are not browser approval, command authority, guard execution,
reconciliation authority, or live Coinbase execution.

Example command admission intent fragment:

```json
{
  "admission_decision": {
    "live_execution_intent": {
      "required": true,
      "prepared": false,
      "executable": false,
      "status": "live_disabled",
      "source": "disabled_backend_service",
      "missing_reason": "live_execution_disabled",
      "route": "/api/v1/orders",
      "method": "POST",
      "identity_key": "client_order_id",
      "service_method": "place_manual_order",
      "adapter_reference": "AdminApiCommandService.place_manual_order",
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "live_exchange_submitted": false,
      "blockers": [
        "live_execution_disabled",
        "browser_authority_rejected"
      ]
    }
  }
}
```

M35 persists command admission decisions to the existing append-only Admin API
audit log. M36 adds backend-owned append-only approval-store infrastructure,
so approval-store contract evidence may pass while route-specific approval
snapshots remain absent and live execution remains disabled. M37 adds
backend-only snapshot resolver infrastructure over exact unexpired approval
records. M38 wires live-disabled command admission evidence to that resolver
without adding live admission. M39 wires live-disabled command admission
evidence to backend-owned audit proof without adding audit mutation. M40 wires
live-disabled command admission evidence to backend-owned cap/guard proof
without adding guard mutation, browser guard authority, live admission, or
Coinbase execution. M41 wires live-disabled command admission evidence to
backend-owned reconciliation plan proof without adding reconciliation
execution, browser reconciliation authority, live admission, order-state
mutation, or Coinbase execution. M42 makes the disabled backend live
execution service boundary explicit without adding a live switch, browser
approval, BFF execution authority, or Coinbase execution. M43 introduces a
backend-owned disabled service descriptor without adding create, cancel,
submit, execute, browser, BFF, or Coinbase authority methods. M44 adds
live-enablement adapter evidence without making route-to-service mapping
executable. M45 adds command admission execution-intent evidence without
making command-to-service intent executable. M46 adds normalized
live-readiness checklist evidence without making any prerequisite executable
or admissive. M47 adds a backend-owned functionality inventory and gap ledger
without adding mutation or live authority. None of these
milestones adds an approval endpoint, browser approval, or Coinbase execution
path.

```http
GET /api/v1/admin/enterprise-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected M9/M21/M23/M24/M25/M26/M27/M28/M29/M30/M31/M32/M33/M34/M35/M36/M37/M38/M39/M40/M41/M42/M43/M44/M45/M46/M47/M48/M49/M50/M51/M52/M53/M54 enterprise readiness posture:

```json
{
  "type": "admin_enterprise_readiness",
  "candidate": "enterprise_admin_m9",
  "approved_phase_range": "1721-1740",
  "status": "warning",
  "supported_module_count": 7,
  "unsupported_module_count": 1,
  "command_gap_count": 17,
  "module_registry_count": 8,
  "module_action_posture_count": 8,
  "functionality_inventory_count": 18,
  "backend_supported_workflow_count": 17,
  "admin_exposed_workflow_count": 15,
  "command_workflow_count": 10,
  "live_designated_workflow_count": 5,
  "recovery_workflow_count": 1,
  "automation_workflow_count": 1,
  "repair_workflow_count": 1,
  "mutation_taxonomy_count": 16,
  "route_bound_mutation_taxonomy_count": 14,
  "live_disabled_mutation_count": 6,
  "backend_contract_required_mutation_count": 2,
  "compatibility_mutation_count": 3,
  "functionality_inventory": [
    {
      "workflow_id": "spot.order_command_drafts",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "workflow_type": "command_draft",
      "exposure_status": "admin_draft_live_disabled",
      "support_status": "command_draft_live_disabled",
      "backend_supported": true,
      "admin_api_exposed": true,
      "frontend_exposed": true,
      "command_capable": true,
      "live_designated": true,
      "live_enabled": false,
      "identity_keys": ["client_order_id", "campaign_id", "sweep_config_id"],
      "command_routes": [
        "POST /api/v1/orders",
        "POST /api/v1/orders/{client_order_id}/cancel",
        "POST /api/v1/spot/campaign/executions",
        "POST /api/v1/spot/sweep/automation-runs"
      ],
      "required_next_contract": "Approval, cap/guard, audit, reconciliation, and live adapter admission must all pass before execution.",
      "blockers": [
        "live_execution_disabled",
        "approval_snapshot_missing",
        "cap_guard_missing",
        "reconciliation_plan_missing"
      ],
      "frontend_boundary": "Keep buttons dry-submit/live-disabled unless backend capability and live-enablement evidence explicitly admit execution.",
      "spot_rule_boundary": "Spot commands must preserve no-shorting and inventory authority.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "workflow_id": "futures.commands_not_modeled",
      "module_id": "futures_perpetuals",
      "module": "Futures / Perpetuals",
      "workflow_type": "command_draft",
      "exposure_status": "backend_contract_required",
      "support_status": "not_modeled",
      "backend_supported": false,
      "admin_api_exposed": false,
      "frontend_exposed": false,
      "command_capable": true,
      "live_designated": false,
      "live_enabled": false,
      "required_next_contract": "Backend command contracts over position side, margin, leverage, liquidation, reduce-only, close-only, funding, cap, approval, audit, and reconciliation evidence.",
      "blockers": ["backend futures command contract missing"],
      "frontend_boundary": "Do not add futures command drafts from spot order/cancel patterns.",
      "spot_rule_boundary": "Spot rules are forbidden in futures command authority.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    }
  ],
  "mutation_taxonomy": [
    {
      "mutation_id": "spot.order_cancel",
      "mutation_family": "spot_order_cancel",
      "workflow_id": "spot.order_command_drafts",
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "exposure_status": "admin_draft_live_disabled",
      "support_status": "command_draft_live_disabled",
      "command_surfaces": [
        "POST /api/v1/orders/{client_order_id}/cancel"
      ],
      "action_classes": ["live_exchange_cancel"],
      "required_permissions": ["order:cancel"],
      "identity_keys": ["client_order_id", "campaign_id", "sweep_config_id"],
      "payload_binding_fields": [
        "endpoint",
        "actor",
        "operator_intent",
        "body",
        "path_params"
      ],
      "idempotency_required": true,
      "operator_intent_required": true,
      "rbac_required": true,
      "approval_required": true,
      "cap_guard_required": true,
      "admission_audit_required": true,
      "reconciliation_required": true,
      "live_adapter_required": true,
      "owning_backend_service": "application/admin_api/command_service.py",
      "shared_command_service_method": "cancel_order_by_client_order_id",
      "browser_authority": "display_only",
      "bff_execution_authority": "forward_only_no_execution",
      "route_local_execution_allowed": false,
      "blockers": [
        "live_execution_disabled",
        "approval_snapshot_missing",
        "cancel reconciliation proof missing"
      ],
      "frontend_boundary": "Do not accept exchange order_id as the internal cancel identity; frontend cancel evidence must stay client_order_id-scoped.",
      "live_coinbase_execution": "not_run",
      "notional_usdc": "0"
    },
    {
      "mutation_id": "futures.commands_contract_required",
      "mutation_family": "futures_contract_required",
      "workflow_id": "futures.commands_not_modeled",
      "module_id": "futures_perpetuals",
      "exposure_status": "backend_contract_required",
      "support_status": "not_modeled",
      "command_surfaces": [],
      "identity_keys": ["position_key", "product_id", "portfolio_id"],
      "required_next_contract": "Futures/perpetual command contracts over position side, margin, collateral, liquidation, reduce-only, close-only, funding, order, cancel, and reconciliation semantics.",
      "blockers": ["backend futures command contract missing"],
      "frontend_boundary": "Do not create futures command drafts by copying spot order, wallet, no-shorting, or cost-basis behavior.",
      "spot_rule_boundary": "Spot rules are forbidden in futures/perpetual command authority."
    }
  ],
  "modules": [
    {
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "primary_owner": "strategy",
      "support_status": "command_draft_live_disabled",
      "unsupported_actions": [
        "spot short selling",
        "browser-side wallet or cost-basis authority",
        "frontend live order placement without backend M8 approval"
      ],
      "command_gaps": [
        {
          "action": "spot short selling",
          "status": "unsupported",
          "reason": "Spot accounts cannot sell assets the account does not hold.",
          "required_backend_contract": "No backend contract should enable spot short selling; spot sell authority remains inventory-backed.",
          "frontend_boundary": "Do not model a spot short draft or bypass backend wallet and inventory authority.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "business/spot_portfolio_sweep.py",
        "business/spot_inventory_authority.py",
        "application/admin_api/command_service.py",
        "api/v1/routes/spot.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getSpotReadiness",
        "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
        "src/features/spot-ops/spotBackendAdapters.ts"
      ],
      "documentation_refs": [
        "README.spot-trading.md",
        "README.spot-portfolio-sweep.md",
        "README.spot-campaign.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot rules apply here only: no short selling, USDC spot scope, inventory authority, cost basis, and average-cost evidence must not be copied into non-spot modules.",
      "action_posture": {
        "module_id": "spot_operations",
        "support_status": "command_draft_live_disabled",
        "read_route_count": 11,
        "command_route_count": 5,
        "live_route_count": 4,
        "evidence_route_count": 9,
        "unsupported_action_count": 3,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "16 route inventory rows are bound to module_id=spot_operations; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "futures_perpetuals",
      "module": "Futures / Perpetuals",
      "primary_owner": "admin_api_contract",
      "support_status": "read_only_ready",
      "unsupported_actions": [
        "frontend futures placement",
        "frontend futures cancel/close/reduce",
        "spot inventory rules in futures workflows"
      ],
      "command_gaps": [
        {
          "action": "frontend futures placement",
          "status": "not_modeled",
          "reason": "Futures/perpetual placement needs backend-owned margin, leverage, liquidation, reduce-only, collateral, and approval contracts before UI drafting.",
          "required_backend_contract": "POST futures/perpetual placement contract with margin, leverage, liquidation, reduce-only, cap, approval, audit, and reconciliation evidence.",
          "frontend_boundary": "Do not add a futures/perpetual placement draft, dry-submit, or BFF route until the backend contract and capability row exist.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["position_key"],
      "backend_contract_refs": [
        "application/admin_api/read_service.py::build_futures_account",
        "application/admin_api/read_service.py::build_futures_positions",
        "api/v1/routes/futures.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getFuturesAccount",
        "src/shared/api/contracts/backendRuntime.ts::loadFuturesPerpetualsReadSnapshot",
        "src/features/admin-shell/AdminShell.tsx"
      ],
      "documentation_refs": [
        "README.futures-perpetuals.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot inventory, USDC, no-shorting, cost-basis, and average-cost rules are forbidden as futures/perpetual authority. Futures require position, margin, leverage, collateral, liquidation, and reduce-only backend contracts.",
      "action_posture": {
        "module_id": "futures_perpetuals",
        "support_status": "read_only_ready",
        "read_route_count": 3,
        "command_route_count": 0,
        "live_route_count": 0,
        "evidence_route_count": 3,
        "unsupported_action_count": 3,
        "command_gap_count": 3,
        "route_module_id_status": "passed",
        "route_module_id_detail": "3 route inventory rows are bound to module_id=futures_perpetuals; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "legacy_dashboard_websocket",
      "module": "Legacy Dashboard WebSocket",
      "primary_owner": "dashboard_contract",
      "support_status": "unsupported",
      "unsupported_actions": [
        "enterprise frontend direct WebSocket command execution",
        "new admin module implementation through dashboard.py"
      ],
      "command_gaps": [
        {
          "action": "enterprise frontend direct WebSocket command execution",
          "status": "unsupported",
          "reason": "The legacy dashboard WebSocket is compatibility-only and is not the enterprise admin command plane.",
          "required_backend_contract": "Backend-owned Admin API route through auth, RBAC, idempotency, approval, caps, audit, and the shared command service.",
          "frontend_boundary": "Do not call dashboard.py or legacy dashboard WebSocket handlers from enterprise frontend product UI.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "dashboard_server.py",
        "docs/LIVE_ORDER_SURFACES.md",
        "application/admin_api/command_service.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/adminBffProxy.ts",
        "src/shared/api/contracts/mutationContracts.ts",
        "src/features/command-workflows"
      ],
      "documentation_refs": [
        "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Legacy dashboard behavior is compatibility-only. Spot rules exposed there are not reusable enterprise frontend authority and must be reintroduced only through Admin API contracts.",
      "action_posture": {
        "module_id": "legacy_dashboard_websocket",
        "support_status": "unsupported",
        "read_route_count": 0,
        "command_route_count": 3,
        "live_route_count": 3,
        "evidence_route_count": 0,
        "unsupported_action_count": 2,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "3 route inventory rows are bound to module_id=legacy_dashboard_websocket; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    }
  ],
  "security_checks": [
    {
      "name": "browser_authority_boundary",
      "status": "passed",
      "detail": "Enterprise admin frontend/Admin HTTP authority is backend_contract_only; this path does not approve, place, cancel, or reconcile Coinbase orders. Legacy browser live surfaces are compatibility-only and documented in docs/LIVE_ORDER_SURFACES.md."
    }
  ],
  "release_checks": [
    {
      "name": "frontend_release_gate",
      "status": "warning",
      "detail": "Run npm run release:gate after frontend/API changes before release."
    }
  ],
  "frontend_authority": "backend_contract_only",
  "live_posture": "live_disabled",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is module and release-candidate evidence only. Warning release
checks mean the external gate still has to be run; they are not browser-side
approval or live execution authority.

## Cancel By Client Order ID

Current live-disabled command shape:

```http
POST /api/v1/orders/{client_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1082
X-Correlation-Id: corr-20260610-001
X-Operator-Intent: operator_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
Content-Type: application/json

{"reason":"operator_requested_cancel"}
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future live execution must call the project Coinbase wrapper
`cancel_order(client_order_id)` after rate/cap policy is complete. The wrapper
must parse Coinbase cancel payloads and accept only explicit `success: true`
evidence as a successful exchange cancellation.

## Stealth Cancel By Stealth Order ID

Current live-disabled command shape:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: operator_stealth_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence with `stealth_order_id`
- return `501` with `status: "not_implemented"`
- never call Coinbase
- never mark a revealed placement hidden/cancelled or mutate stealth lifecycle
  state

This command draft is keyed by `stealth_order_id`. Active placement client ids
and exchange order ids are evidence only. Future live execution must reconcile
the live placement through the existing stealth lifecycle exchange-handling
path before local state can change.

## Order Reads

Order reads are local/backend evidence routes. They are keyed by
`client_order_id`; exchange-native ids are exposed only as `exchange_order_id`
evidence.
If durable row-level audit metadata exists, read items may also include
optional `correlation_id` and `audit_id` fields for operator audit navigation.
Those ids are not order identity and must not be used for cancellation.

```http
GET /api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The response model does not contain an `order_id` identity field. If exchange
evidence is known, it appears as `exchange_order_id` with
`exchange_order_id_evidence_only=true`. List responses include pagination
metadata: `limit`, `offset`, `returned_count`, `total_matching_count`,
`next_offset`, and `has_more`.

Frontend read-model interactions over these rows are display-only. Local
filtering, sorting, selected detail panels, responsive table scrolling, and
audit anchors must use backend-shaped row data already loaded through the
Admin API. They must not create a second fetch path, use exchange
`order_id` as identity, or infer wallet/guard/execution authority in the
browser.

## Stealth Order Reads

Stealth reads are local/backend lifecycle evidence routes. They are keyed by
`stealth_order_id`. Active placement client ids and exchange order ids are
evidence fields only. The current enterprise Admin API exposes only the
live-disabled stealth cancel draft above; stealth create, reveal, hide, move,
and reprice command routes are not modeled.

```http
GET /api/v1/stealth/orders?product_id=BTC-USDC&stealth_status=REVEALED&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/stealth/orders/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Response rows include lifecycle and policy evidence such as `status`,
`revealed_orders`, `active_placement_client_order_id`,
`active_exchange_order_id`, `cancel_reentry_state`, and
`anchor_repricing_state`. These fields are display evidence for the admin
platform. They must not be used by a frontend to mutate stealth lifecycle
state or cancel a live placement.

## Movement And Repricing

Movement/repricing reads expose existing durable and runtime-safe evidence.
The read routes do not move parent orders, premark moves, trigger repricing,
cancel Coinbase orders, or replace revealed stealth placements.

```http
GET /api/v1/movement-repricing/evidence?product_id=BTC-USDC&evidence_type=stealth_repricing_state&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/stealth/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Response items may include parent move history from `order_moves`, stealth
move audit rows from `stealth_order_moves`, repricing state from
`stealth_orders.anchor_repricing_state_json`, replacement-slot evidence, and
runtime mutation claim evidence when the existing manager state is observable.
Exchange-native ids are exposed as exchange evidence only.

Movement repricing has one live-disabled command draft:

```http
POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: idem-movement-reprice-001
X-Correlation-Id: corr-movement-reprice-001
X-Operator-Intent: movement_reprice_review
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json

{"reason":"operator_requested_reprice"}
```

The request identity is the path `stealth_order_id`. Do not send
`client_order_id` or `order_id` in the body. The current response is HTTP
`501` with `status="not_implemented"`, durable audit/idempotency evidence,
`live_exchange_submitted=false`, and `data.stealth_manager_invoked=false`.
It does not clear repricing cooldowns, invoke the live dashboard repricer,
cancel placements, or call Coinbase.

## Futures/Perpetuals Reads

Futures/perpetual reads expose backend-owned account, risk, and position
evidence. They are not command routes. They do not place, close, reduce,
cancel, or liquidate positions.

```http
GET /api/v1/futures/account
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions/{position_key}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Account responses separate configured product metadata from observed runtime
position coverage:

- `configured_product_scope`
- `observed_position_scope`

Position rows are keyed by `position_key`. Do not replace that key with spot
wallet identity, `client_order_id`, or Coinbase `order_id`. Close/reduce sides
are backend-derived from observed position side and are not exchange-observed
reduce-only or close-only order flags. Funding-rate evidence is currently
`not_modeled`.

## Guard/Risk Policy Reads

Guard/risk policy reads expose backend-owned policy posture. They are not
command routes and they do not approve live execution, run wallet checks,
calculate profitability in the browser, or contact Coinbase.

```http
GET /api/v1/admin/guard-risk-policy?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

The response includes `action_condition_policy`, `configured_limit_rules`,
`live_execution_gate`, `product_capability_policy`,
`product_capability_decisions`, `profitability_policy`, `authority_sources`,
and `rejection_categories`.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="live_disabled"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

Do not use this route as a browser preflight approval endpoint. Actual command
acceptance/rejection remains in the backend command service path.

## Audit Workbench Reads

Audit workbench reads expose backend-owned cross-module evidence. They are not
command routes and they do not mutate audit history, replay commands, call
Coinbase, or approve live execution.

```http
GET /api/v1/admin/audit-workbench?module=orders&client_order_id=client-order-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

The response includes `module_summary`, `events`, `filters`, `pagination`,
and no-live posture fields. Order events are keyed by `client_order_id`.
Stealth events use `stealth_order_id`. Futures/perpetual events use
`position_key`. Exchange-native ids appear only as exchange evidence.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="evidence_only"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

## Live Placement Approval

Current live-disabled command shape:

```json
{
  "product_id": "BTC-USDC",
  "side": "BUY",
  "order_type": "LIMIT",
  "quote_size": "1.00",
  "limit_price": "65000.00",
  "manual_live_acknowledgement": true
}
```

Required headers for that placement include:

```http
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: manual_one_off
X-Admin-Actor: trader-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:create`
- derive a stable backend-owned `client_order_id` before command admission
  when the request omitted one
- evaluate durable idempotency
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future backend behavior:

- validate product capability and size
- run action-condition guards
- enforce live caps
- create or verify an approval snapshot
- reuse the already-derived backend-owned `client_order_id`
- persist idempotency and audit state
- submit to Coinbase only after all gates pass

## Campaign Execution Command

Campaign execution is now a backend-owned command route, but live execution is
still disabled.

```http
POST /api/v1/spot/campaign/executions
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1084
X-Correlation-Id: corr-20260610-003
X-Operator-Intent: campaign_execute
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json
X-CSRF-Token: <configured-csrf-token-when-required>
```

```json
{
  "campaign_id": "usdc-sweep-001",
  "side": "BUY",
  "quote_notional_per_product": "1.00",
  "product_ids": ["BTC-USDC", "ETH-USDC"],
  "dry_run": false,
  "manual_live_acknowledgement": true
}
```

Current response behavior:

- authorize `campaign:execute`
- evaluate idempotency
- write command audit evidence
- return `501` with `service_method: "execute_spot_campaign"`
- include approval/cap guard evidence
- never call Coinbase

## Spot Sweep Automation Command

Spot sweep automation now has a backend-owned command route, but live
execution, scheduler execution, and Coinbase submission are still disabled.

```http
POST /api/v1/spot/sweep/automation-runs
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1085
X-Correlation-Id: corr-20260613-001
X-Operator-Intent: sweep_automation_run
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json
X-CSRF-Token: <configured-csrf-token-when-required>
```

```json
{
  "sweep_config_id": "spot-sweep-usdc-hourly",
  "side": "BUY",
  "quote_notional_per_product": "1.00",
  "repeat_every_hours": "6",
  "max_runs": 2,
  "max_products": 3,
  "max_total_notional_per_run": "3.00",
  "max_notional_per_order": "1.00",
  "max_planned_orders": 3,
  "run_if_due": true,
  "dry_run": false,
  "manual_live_acknowledgement": true
}
```

Current response behavior:

- authorize `spot_sweep:execute`
- evaluate idempotency
- write command audit and route-bound admission evidence
- return `501` with `service_method: "run_spot_sweep_automation"`
- include approval/cap/reconciliation/live-disabled guard evidence
- report `live_exchange_submitted=false` and `sweep_runner_invoked=false`
- never run sweep CLI tools and never call Coinbase

## Idempotent Retry

If the same `Idempotency-Key` and same command payload are sent again for the
same endpoint, path identity, actor/roles, and operator intent, the API should
return the original command result without minting a second `client_order_id`
or submitting a second Coinbase order.
For manual order create requests that omit `client_order_id`, the route derives
one from endpoint, actor, idempotency key, and payload hash before admission.
That derived id is response/audit evidence and the value future approval
snapshots must bind to; the browser must not invent it.

If the same `Idempotency-Key` is reused with a different payload, path
identity, actor/roles, or `X-Operator-Intent`, the API should return conflict.

## Read-Only Spot Operator Routes

Read-only routes always require `Authorization`. In `bootstrap_bearer` mode
they also require `X-Admin-Actor` and `X-Admin-Roles`. In `oidc_jwt` mode the
backend derives actor and roles from verified JWT claims and ignores those
bootstrap headers. Read routes do not require `Idempotency-Key`. Missing or
invalid auth returns `401`; insufficient role evidence returns `403`.

```http
GET /api/v1/spot/readiness?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Current read-only routes:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/guard-risk-policy`
- `GET /api/v1/admin/audit-workbench`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/admin/approvals`
- `GET /api/v1/admin/approvals/requests/{approval_request_id}`
- `GET /api/v1/admin/admission-audits`
- `GET /api/v1/admin/admission-audits/{admission_audit_id}`
- `GET /api/v1/admin/cap-guard/decisions`
- `GET /api/v1/admin/cap-guard/decisions/{decision_id}`
- `GET /api/v1/admin/reconciliation/plans`
- `GET /api/v1/admin/reconciliation/plans/{plan_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/pnl/checkpoints`
- `GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`
- `GET /api/v1/spot/command-suite`

Spot P/L checkpoint records are local-state evidence for operator review. They
must be sourced from `/api/v1/spot/sweep/pnl`; they do not approve sells,
prove profitability, execute reconciliation, create tax lots, or submit
Coinbase orders.

```http
POST /api/v1/spot/pnl/checkpoints
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Idempotency-Key: spot-pnl-checkpoint-2026-06-13
X-Correlation-Id: spot-pnl-checkpoint-request-2026-06-13
X-Operator-Intent: daily_spot_pnl_review
Content-Type: application/json
```

```json
{
  "checkpoint_id": "spot-pnl-checkpoint-2026-06-13",
  "scope": "portfolio",
  "product_ids": ["BTC-USDC", "ETH-USDC"],
  "source_report_route": "/api/v1/spot/sweep/pnl",
  "review_status": "passed",
  "pnl_snapshot": {
    "portfolio_mark_to_market_usdc": "128.40",
    "since_last_purchase_usdc": "3.21"
  },
  "average_cost_snapshot": {
    "source": "coinbase_average_cost"
  },
  "operator_notes": "Daily operator checkpoint from sweep P/L report."
}
```

Accepted responses include the persisted `checkpoint_id`, status, source
route, payload hash, and explicit no-authority flags:
`profitability_authority=false`, `sell_authority=false`,
`checkpoint_is_tax_accounting=false`, `live_exchange_submitted=false`, and
`live_coinbase_orders_ran=false`.
When the request includes `average_cost_snapshot`, responses also include
`average_cost_reviewed=true`, `average_cost_review_source`, and an
`average_cost_review_detail` warning that the review evidence is not sell,
profit, tax, browser guard, or Coinbase execution authority. List responses
include `average_cost_review_count`.

```http
GET /api/v1/spot/pnl/checkpoints?checkpoint_status=passed&limit=25
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

`GET /api/v1/spot/command-suite` is M54 read-only backend evidence for the
current spot command families. It covers manual spot order placement, order
cancel by `client_order_id`, and campaign execution readiness. It does not
execute commands, approve live execution, evaluate wallet inventory in the
browser, or make spot-only rules reusable by futures/perpetuals or stealth
modules. Each command row includes backend-owned `proof_routes` for approval,
admission audit, cap/guard, and reconciliation records. These routes are
local-state evidence requirements only; they do not execute the command.
Each command row also includes backend-owned `readiness_preconditions` copied
from live-enablement evidence so operators can see which gates are configured,
blocking, or passed without treating the browser as a gate evaluator.
The response also includes `coverage_gaps` for remaining M54 spot families
that are not command-complete. Gap rows are read-only planning evidence, not
mutation routes or browser authority. Each gap row may include typed
`current_read_evidence` rows for existing read-only evidence routes derived
from backend route inventory.

```http
GET /api/v1/spot/command-suite
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```json
{
  "type": "spot_command_suite",
  "module_id": "spot_operations",
  "status": "blocked",
  "approved_phase_range": "1721-1740",
  "command_count": 4,
  "blocked_command_count": 4,
  "live_enabled_command_count": 0,
  "executable_command_count": 0,
  "coverage_gap_count": 4,
  "spot_rules_platform_default": false,
  "browser_authority": "display_only",
  "bff_authority": "forward_only_no_execution",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "commands": [
    {
      "mutation_family": "spot_manual_order",
      "route": "/api/v1/orders",
      "method": "POST",
      "identity_key": "client_order_id",
      "shared_method": "place_manual_order",
      "status": "blocked",
      "live_execution_status": "approval_required",
      "live_adapter_configured": true,
      "live_enabled": false,
      "executable": false,
      "proof_routes": [
        {
          "gate": "approval",
          "route": "/api/v1/admin/approvals/requests",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "approval:request",
          "shared_method": "create_approval_request",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Create a backend-owned approval request bound to the exact route, method, actor, idempotency key, payload hash, and command identity."
        },
        {
          "gate": "approval",
          "route": "/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "approval:manage",
          "shared_method": "decide_approval_request",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "approval_request_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admin-api.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Record the backend approval decision. Browser approval remains insufficient and does not execute the command."
        },
        {
          "gate": "audit",
          "route": "/api/v1/admin/admission-audits",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "admission_audit:record",
          "shared_method": "record_admission_audit",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.admission-audits.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admission-audits.md"
          ],
          "detail": "Append exact admission audit evidence for the route-bound command. The writer cannot mark live admission allowed."
        },
        {
          "gate": "cap_guard",
          "route": "/api/v1/admin/cap-guard/decisions",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "cap_guard:record",
          "shared_method": "record_cap_guard_decision",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.cap-guard-decisions.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/cap-guard-decisions.md"
          ],
          "detail": "Record backend cap/guard evidence. The browser and BFF must not evaluate wallet, inventory, profitability, margin, or account limits."
        },
        {
          "gate": "reconciliation",
          "route": "/api/v1/admin/reconciliation/plans",
          "method": "POST",
          "action_class": "local_state_mutation",
          "required_permission": "reconciliation:record",
          "shared_method": "record_reconciliation_plan",
          "status": "blocked",
          "required": true,
          "blocking": true,
          "identity_key": "client_order_id",
          "command_identity_key": "client_order_id",
          "backend_owned": true,
          "route_bound": true,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "documentation_refs": [
            "README.reconciliation-plans.md",
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/reconciliation-plans.md"
          ],
          "detail": "Record backend reconciliation proof requirements. This does not execute reconciliation or mutate order/exchange state."
        }
      ],
      "readiness_preconditions": [
        {
          "precondition": "approval_snapshot",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "not_configured",
          "expected_source": "approval_snapshot",
          "blocker": "approval_snapshot_missing",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "No browser-side approval snapshot may satisfy live admission."
          ],
          "detail": "Approval snapshot evidence is required before live admission."
        },
        {
          "precondition": "browser_bff_boundary",
          "status": "passed",
          "required": true,
          "configured": true,
          "blocking": false,
          "backend_owned": true,
          "route_bound": true,
          "source": "frontend_boundary",
          "expected_source": "backend_contract",
          "blocker": null,
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "Browser and BFF authority is bounded to display/forward-only evidence."
          ],
          "detail": "Browser and BFF authority cannot satisfy live admission."
        },
        {
          "precondition": "live_execution_service",
          "status": "blocked",
          "required": true,
          "configured": false,
          "blocking": true,
          "backend_owned": true,
          "route_bound": true,
          "source": "disabled_backend_service",
          "expected_source": "admin_api_live_execution_service",
          "blocker": "live_execution_disabled",
          "browser_authority": "display_only",
          "bff_authority": "forward_only_no_execution",
          "evidence": [
            "No Coinbase client method is exposed."
          ],
          "detail": "The backend live execution service is disabled."
        }
      ]
    },
    {
      "mutation_family": "spot_order_cancel",
      "route": "/api/v1/orders/{client_order_id}/cancel",
      "method": "POST",
      "identity_key": "client_order_id",
      "shared_method": "cancel_order_by_client_order_id",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    },
    {
      "mutation_family": "spot_campaign_execution",
      "route": "/api/v1/spot/campaign/executions",
      "method": "POST",
      "identity_key": "campaign_id",
      "shared_method": "execute_spot_campaign",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    },
    {
      "mutation_family": "spot_sweep_automation",
      "route": "/api/v1/spot/sweep/automation-runs",
      "method": "POST",
      "identity_key": "sweep_config_id",
      "shared_method": "run_spot_sweep_automation",
      "required_permission": "spot_sweep:execute",
      "status": "blocked",
      "live_execution_status": "live_disabled",
      "live_adapter_configured": false,
      "live_enabled": false,
      "executable": false
    }
  ],
  "coverage_gaps": [
    {
      "family": "spot_sweep_automation",
      "status": "blocked",
      "exposure_status": "admin_draft_live_disabled",
      "command_route": "/api/v1/spot/sweep/automation-runs",
      "current_read_evidence_routes": [
        "GET /api/v1/spot/sweep/status",
        "GET /api/v1/spot/campaign/status",
        "GET /api/v1/spot/command-suite"
      ],
      "current_read_evidence": [
        {
          "route": "/api/v1/spot/sweep/status",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_sweep_status",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-portfolio-sweep.md",
            "docs/COMMAND_WORKFLOWS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/campaign/status",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_campaign_status",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "README.spot-campaign.md",
            "docs/COMMAND_WORKFLOWS.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        },
        {
          "route": "/api/v1/spot/command-suite",
          "method": "GET",
          "action_class": "read_only",
          "required_permission": "analytics:read",
          "shared_method": "build_spot_command_suite",
          "backend_owned": true,
          "browser_authority": "display_only",
          "bff_authority": "read_only_forward",
          "documentation_refs": [
            "docs/COMMAND_WORKFLOWS.md",
            "docs/examples/admin-api.md"
          ],
          "detail": "Existing read-only Admin API evidence route for a spot command-suite coverage gap; it does not create a command route, execute reconciliation, or call Coinbase."
        }
      ],
      "required_backend_contract": "Durable enterprise sweep scheduling, pause/resume, run-limit, retry, execution-record, recovery, and reconciliation contract.",
      "required_gate_chain": [
        "route_inventory_contract",
        "approval_snapshot",
        "admission_audit",
        "cap_guard_decision",
        "reconciliation_plan",
        "live_execution_service"
      ],
      "missing_contracts": [
        "enterprise_sweep_scheduler_contract",
        "sweep_run_limit_contract",
        "sweep_pause_resume_contract",
        "sweep_retry_recovery_contract",
        "sweep_reconciliation_execution_contract"
      ],
      "backend_owned": true,
      "browser_authority": "display_only",
      "bff_authority": "forward_only_no_execution",
      "spot_rule_boundary": "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, and average-cost rules apply only to spot command authority.",
      "documentation_refs": [
        "README.spot-portfolio-sweep.md",
        "README.spot-campaign.md",
        "docs/COMMAND_WORKFLOWS.md"
      ],
      "detail": "Sweep and campaign evidence is readable, but enterprise admin sweep automation is not command-complete until durable scheduler, run-limit, recovery, and reconciliation contracts exist."
    }
  ]
}
```

## Approval Lifecycle

Approval lifecycle routes write backend-owned local approval evidence only.
They do not submit orders, cancel orders, run guard checks, execute
reconciliation, or call Coinbase.

Create a route-bound approval request:

```http
POST /api/v1/admin/approvals/requests
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Idempotency-Key: approval-request-001
X-Correlation-Id: corr-approval-001
X-Operator-Intent: request_manual_order_approval
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_reason": "bounded canary approval"
}
```

Approve the request. Only an actor with `approval:manage` can decide or revoke
approval lifecycle records:

```http
POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: approval-decision-001
X-Correlation-Id: corr-approval-002
X-Operator-Intent: approve_manual_order_snapshot
Content-Type: application/json

{
  "decision": "approved",
  "decision_reason": "bounded canary approval",
  "expires_at": "2026-06-12T19:00:00+00:00",
  "cap_guard_decision_ref": "cap-guard-001",
  "reconciliation_plan_ref": "reconciliation-001"
}
```

Revoke an approved snapshot:

```http
POST /api/v1/admin/approvals/{approval_id}/revoke
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: approval-revoke-001
X-Correlation-Id: corr-approval-003
X-Operator-Intent: revoke_manual_order_snapshot
Content-Type: application/json

{
  "revoke_reason": "operator cancelled the approval"
}
```

## Admission Audit Records

Admission audit routes persist backend-owned command admission proof only.
They do not submit orders, call Coinbase, run cap/guard checks, execute
reconciliation, or let the browser/BFF write audit authority.

List recorded admission audits:

```http
GET /api/v1/admin/admission-audits?admission_status=blocked&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one admission audit:

```http
GET /api/v1/admin/admission-audits/audit-admission-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one backend admission audit proof:

```http
POST /api/v1/admin/admission-audits
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: admission-audit-record-001
X-Correlation-Id: corr-admission-audit-001
X-Operator-Intent: record_manual_order_admission_audit
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "operator-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_snapshot_approved_by_actor_id": "approver-001",
  "approval_snapshot_requested_by_actor_id": "operator-001",
  "approval_snapshot_expires_at": "2026-06-12T19:00:00+00:00",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "allowed": false,
  "status": "blocked",
  "reason": "backend admission audit proof recorded before cap/guard and reconciliation proofs"
}
```

The writer rejects records that claim `allowed=true` or `status=passed`.
The returned `admission_audit_id` can be linked by cap/guard and
reconciliation records, but it does not authorize live execution.

## Cap/Guard Decision Records

Cap/guard decision routes persist backend-owned admission evidence only. They
do not submit orders, call Coinbase, or let the browser/BFF evaluate wallet,
margin, profitability, inventory, account-limit, or spot-specific guard rules.

List recorded decisions:

```http
GET /api/v1/admin/cap-guard/decisions?decision_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one decision:

```http
GET /api/v1/admin/cap-guard/decisions/cap-guard-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Record one backend cap/guard decision:

```http
POST /api/v1/admin/cap-guard/decisions
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: cap-guard-record-001
X-Correlation-Id: corr-cap-guard-001
X-Operator-Intent: record_manual_order_cap_guard
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "admin-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_cap_guard_decision_ref": "cap-guard-001",
  "admission_audit_id": "audit-admission-001",
  "allowed": true,
  "status": "passed",
  "cap_policy_ref": "submitted_notional_cap:3.10",
  "guard_policy_ref": "action_condition_guard:manual_order",
  "product_scope": "BTC-USDC",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend cap and guard inputs accepted the route-bound envelope"
}
```

Only `allowed=true` with `status=passed` is resolver-eligible. Any mismatch,
blocked status, warning status, route mismatch, permission mismatch, or
duplicate decision id fails closed as evidence only.

Revoked and expired snapshots fail closed in the existing approval resolver.
An approved snapshot still does not make a command executable while cap/guard,
admission audit, reconciliation, disabled live service, and remaining execution
gates remain blocked.

## Reconciliation Plan Records

Reconciliation plan routes persist backend-owned post-submit reconciliation
plan evidence only. They do not submit orders, call Coinbase, execute
reconciliation, mutate order state, mutate exchange state, or let the
browser/BFF create reconciliation proof.

List recorded plans:

```http
GET /api/v1/admin/reconciliation/plans?plan_status=passed&limit=10
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Read one plan:

```http
GET /api/v1/admin/reconciliation/plans/reconciliation-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Record one backend reconciliation plan:

```http
POST /api/v1/admin/reconciliation/plans
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: admin-001
X-Admin-Roles: admin
Idempotency-Key: reconciliation-plan-record-001
X-Correlation-Id: corr-reconciliation-plan-001
X-Operator-Intent: record_manual_order_reconciliation_plan
Content-Type: application/json

{
  "route": "/api/v1/orders",
  "method": "POST",
  "module_id": "spot_operations",
  "identity_key": "client_order_id",
  "identity_value": "client-approved-001",
  "action_class": "live_exchange_place",
  "required_permission": "order:create",
  "service_method": "place_manual_order",
  "actor_id": "admin-001",
  "operator_intent": "manual_one_off",
  "command_idempotency_key": "manual-order-idem-001",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "approval_snapshot_id": "approval-snapshot-001",
  "approval_reconciliation_plan_ref": "reconciliation-001",
  "admission_audit_id": "audit-admission-001",
  "cap_guard_decision_id": "cap-guard-001",
  "allowed": true,
  "status": "passed",
  "reconciliation_policy_ref": "post_submit_reconciliation:manual_order",
  "product_scope": "BTC-USDC",
  "exchange_submission_required": true,
  "post_submit_reconciliation_required": true,
  "retained_inventory_required": true,
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "reason": "backend reconciliation plan accepted the route-bound envelope"
}
```

Only `allowed=true` with `status=passed` is resolver-eligible. Any mismatch,
blocked status, warning status, read-only route target, local-state route
target, permission mismatch, or duplicate plan id fails closed as evidence
only.

## Structured Errors

Auth, RBAC, and validation errors return JSON bodies shaped for frontend
display:

```json
{
  "code": "auth_required",
  "message": "Invalid Admin API bearer token",
  "severity": "warning",
  "correlation_id": "corr-20260610-004",
  "live_coinbase_orders_ran": false
}
```

Every response includes `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, and `X-Live-Execution-Enabled`.

## Frontend Smoke Commands

From `C:\coinbase-frontend`, use the canonical release-hardening gate to
validate the route inventory, artifact evidence, runtime evidence, autonomous
queue posture, tests, and dry smokes without contacting Coinbase:

```powershell
npm run release:gate
```

Against a local Admin API, configure `ADMIN_API_BASE_URL`,
`ADMIN_API_BEARER_TOKEN`, `ADMIN_API_ACTOR_ID`, and `ADMIN_API_ROLES`. If
backend CSRF is required, also configure `ADMIN_API_CSRF_TOKEN`, then run:

```powershell
npm run smoke:read
npm run smoke:command
```

Direct frontend smoke scripts still accept `ADMIN_API_ACTOR` as a legacy
fallback, but `ADMIN_API_ACTOR_ID` is the canonical actor variable shared with
BFF mode.

The command smoke expects `501` live-disabled responses and reports live
Coinbase execution as not run with notional `$0`.

The frontend release artifact bundle includes:

- `artifacts/release-readiness.json`
- `artifacts/deployment-package-manifest.json`
- `artifacts/observability-drill.json`
- `artifacts/synthetic-probes.json`
- `artifacts/public-release-checklist.json`
- `artifacts/runtime-evidence.json`

Those artifacts are no-live deployment evidence. They are not approval for
live Coinbase execution and not backend approval to place or cancel Coinbase
orders.
The autonomous queue remains part of the no-live release gate, and these
artifacts are not approval for live Coinbase execution.

For same-origin BFF smoke, start the frontend with `NEXT_PUBLIC_ADMIN_API_MODE=bff`
and server-only `ADMIN_API_*` variables, then run:

```powershell
$env:FRONTEND_BASE_URL = "http://127.0.0.1:3000"
npm run smoke:bff
```

BFF smoke reads through `/api/admin/api/v1/...` and posts to BFF command
routes expecting backend `501` live-disabled responses. It must report live
Coinbase execution as not run with notional `$0`.

The BFF copies only documented response-evidence headers back to browser code:
`Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Missing BFF server authority should be handled as
`admin_bff_proxy_error`, not as a trading approval or Coinbase execution
failure.

The frontend deployment package manifest and observability drill are no-live
evidence artifacts. `server_env_static` BFF authority is local/staging evidence
only; production readiness is conditional on frontend `backend_oidc_jwt` BFF
mode and backend `oidc_jwt` verifier configuration.
