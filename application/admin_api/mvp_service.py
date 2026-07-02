"""Backend-owned Admin MVP command and read service.

The service keeps the local Admin API small: it exposes the read shapes the
current frontend needs, records proof-chain evidence, and performs live Coinbase
submission only when explicit backend gates are satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import os
from typing import Any, Callable, Mapping
import uuid


ADMIN_API_VERSION = "0.1.0-prod-mvp"
MANUAL_ORDER_ROUTE = "/api/v1/orders"
CANCEL_ORDER_ROUTE = "/api/v1/orders/{client_order_id}/cancel"
ACCOUNT_MANAGEMENT_ROUTE = "/api/v1/admin/account-management"
ACCOUNT_MANAGEMENT_MODULE_ID = "account_management"
MANUAL_ORDER_MODULE_ID = "spot_operations"
MANUAL_ORDER_ACTION_CLASS = "live_exchange_place"
MANUAL_ORDER_PERMISSION = "order:create"
MANUAL_ORDER_SERVICE_METHOD = "place_manual_order"
LIVE_SERVICE_DECISION_ROUTE = "/api/v1/admin/live-execution/service-decisions"
LIVE_SERVICE_DECISION_PERMISSION = "config:update"
LIVE_SERVICE_DECISION_SERVICE_METHOD = "record_live_service_decision"
LIVE_ADAPTER_DECISION_ROUTE = "/api/v1/admin/live-execution/adapter-decisions"
LIVE_ADAPTER_DECISION_PERMISSION = "config:update"
LIVE_ADAPTER_DECISION_SERVICE_METHOD = "record_live_adapter_decision"
DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
DEFAULT_MAX_EXECUTED_NOTIONAL_USDC = Decimal("1.00")
DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC = Decimal("0")
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


class AdminMvpCommandStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_IMPLEMENTED = "not_implemented"


class AdminMvpGateStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class AdminMvpLiveServiceStatus(str, Enum):
    APPROVAL_REQUIRED = "approval_required"
    LIVE_DISABLED = "live_disabled"


@dataclass(frozen=True)
class AdminMvpRequestContext:
    """Auditable request context supplied by the BFF or dashboard adapter."""

    idempotency_key: str
    correlation_id: str
    operator_intent: str
    actor_id: str
    roles: tuple[str, ...] = ("operator",)


@dataclass(frozen=True)
class AdminMvpApiResult:
    """HTTP-like result returned by the service and local server."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AdminMvpStore:
    """Process-local MVP evidence store for local deployment."""

    command_identity_by_idempotency_key: dict[str, str] = field(default_factory=dict)
    service_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    admission_audits: dict[str, dict[str, Any]] = field(default_factory=dict)
    cap_guard_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    reconciliation_plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_adapter_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    submitted_notional_usdc: Decimal = Decimal("0")
    executed_notional_usdc: Decimal = Decimal("0")
    live_coinbase_orders_ran: bool = False


@dataclass(frozen=True)
class AdminMvpDependencies:
    """Runtime dependencies for the Admin MVP service."""

    rest_client: Any = None
    rest_client_available: bool = False
    live_coinbase_execution_enabled: bool = False
    runtime_controller_factory: Callable[[], Any] = field(
        default_factory=lambda: _default_runtime_controller_factory
    )
    uuid_factory: Callable[[], str] = field(default_factory=lambda: lambda: str(uuid.uuid4()))
    now_factory: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )


def live_coinbase_execution_enabled_from_env() -> bool:
    """Return True when local backend live execution is explicitly enabled."""

    for name in (
        "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
        "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED",
    ):
        value = os.environ.get(name, "")
        if value.strip().lower() in TRUTHY_ENV_VALUES:
            return True
    return False


def _default_runtime_controller_factory() -> Any:
    from core.runtime_controller import get_runtime_controller

    return get_runtime_controller()


class AdminMvpService:
    """Small backend Admin API service for the local MVP."""

    def __init__(
        self,
        dependencies: AdminMvpDependencies | None = None,
        store: AdminMvpStore | None = None,
    ) -> None:
        self.dependencies = dependencies or AdminMvpDependencies(
            live_coinbase_execution_enabled=live_coinbase_execution_enabled_from_env(),
        )
        self.store = store or AdminMvpStore()

    def get_read_response(
        self,
        path: str,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Return a local read response for one Admin API path."""

        normalized_path = _normalize_path(path)
        if normalized_path == "/api/v1/admin/bootstrap":
            return self._ok(self._admin_bootstrap(context), context)
        if normalized_path == "/api/v1/admin/health":
            return self._ok(self._admin_health(), context)
        if normalized_path == "/api/v1/admin/session":
            return self._ok(self._admin_session(context), context)
        if normalized_path == "/api/v1/admin/oidc-readiness":
            return self._ok(self._oidc_readiness(), context)
        if normalized_path == "/api/v1/admin/capabilities":
            return self._ok(self._capability_registry(), context)
        if normalized_path == "/api/v1/admin/csrf":
            return self._ok(self._csrf_contract(), context)
        if normalized_path == ACCOUNT_MANAGEMENT_ROUTE:
            return self._ok(self._account_management(context), context)
        if normalized_path == "/api/v1/admin/live-enablement":
            return self._ok(self._live_enablement(), context)
        if normalized_path == "/api/v1/admin/enterprise-readiness":
            return self._ok(self._enterprise_readiness(), context)
        if normalized_path == "/api/v1/admin/release-gate":
            return self._ok(self._simple_gate("admin_release_gate"), context)
        if normalized_path == "/api/v1/admin/recovery-gate":
            return self._ok(self._simple_gate("admin_recovery_gate"), context)
        if normalized_path == "/api/v1/admin/fill-ledger-health":
            return self._ok(self._simple_gate("admin_fill_ledger_health"), context)
        if normalized_path == "/api/v1/admin/frontend-fixtures":
            return self._ok(self._frontend_fixtures(), context)
        if normalized_path == "/api/v1/admin/approvals":
            return self._ok(self._approval_list(), context)
        if normalized_path.startswith("/api/v1/admin/approvals/requests/"):
            return self._ok(
                self._approval_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/admission-audits":
            return self._ok(self._admission_audit_list(), context)
        if normalized_path.startswith("/api/v1/admin/admission-audits/"):
            return self._ok(
                self._admission_audit_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/cap-guard/decisions":
            return self._ok(self._cap_guard_list(), context)
        if normalized_path.startswith("/api/v1/admin/cap-guard/decisions/"):
            return self._ok(
                self._cap_guard_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/reconciliation/plans":
            return self._ok(self._reconciliation_list(), context)
        if normalized_path.startswith("/api/v1/admin/reconciliation/plans/"):
            return self._ok(
                self._reconciliation_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/live-execution/admission-preview":
            return self.preview_admission(query, context)
        if normalized_path == "/api/v1/admin/live-execution/service-decisions":
            return self._ok(self._live_service_decision_list(), context)
        if normalized_path.startswith("/api/v1/admin/live-execution/service-decisions/"):
            return self._ok(
                self._live_service_decision_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/live-execution/adapter-decisions":
            return self._ok(self._live_adapter_decision_list(), context)
        if normalized_path.startswith("/api/v1/admin/live-execution/adapter-decisions/"):
            return self._ok(
                self._live_adapter_decision_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/guard-risk-policy":
            return self._ok(self._guard_risk_policy(query), context)
        if normalized_path == "/api/v1/admin/audit-workbench":
            return self._ok(self._audit_workbench(query), context)
        if normalized_path == "/api/v1/orders":
            return self._ok(self._order_list(query), context)
        if normalized_path.startswith("/api/v1/orders/"):
            return self._ok(self._order_detail(_last_path_part(normalized_path)), context)
        if normalized_path == "/api/v1/spot/command-suite":
            return self._ok(self._spot_command_suite(), context)
        if normalized_path.startswith("/api/v1/spot/"):
            return self._ok(self._spot_placeholder(normalized_path, query), context)
        if normalized_path.startswith("/api/v1/stealth/"):
            return self._ok(self._stealth_placeholder(normalized_path, query), context)
        if normalized_path.startswith("/api/v1/movement-repricing/"):
            return self._ok(
                self._movement_repricing_placeholder(normalized_path, query),
                context,
            )
        if normalized_path.startswith("/api/v1/futures/"):
            return self._ok(self._futures_placeholder(normalized_path, query), context)
        return self._error(404, f"Admin MVP route not found: {normalized_path}", context)

    def record_live_service_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend live-service posture evidence."""

        decision_id = str(body.get("decision_id") or self.dependencies.uuid_factory())
        record = self._live_service_decision_record(decision_id, body, context)
        self.store.service_decisions[decision_id] = record
        return self._ok(
            {
                "type": "admin_live_service_decision",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
                "service_method": LIVE_SERVICE_DECISION_SERVICE_METHOD,
                "message": "Live-service decision recorded.",
                "decision": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _live_service_decision_record(
        self,
        decision_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        requested_status = str(
            body.get("requested_service_status")
            or AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
        )
        return {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": LIVE_SERVICE_DECISION_ROUTE,
            "method": "POST",
            "module_id": "admin_system_health",
            "action_class": "local_state_mutation",
            "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
            "service_method": LIVE_SERVICE_DECISION_SERVICE_METHOD,
            "status": str(body.get("status") or AdminMvpGateStatus.PASSED.value),
            "requested_service_status": requested_status,
            "live_execution_service_status": requested_status,
            "service_enabled": bool(body.get("service_enabled", True)),
            "source": "admin_api_live_service_decision_log",
            "deployment_ref": str(body.get("deployment_ref") or "coinbase-local"),
            "runtime_configuration_ref": str(
                body.get("runtime_configuration_ref") or "coinbase-local-runtime"
            ),
            "decision_reason": str(
                body.get("decision_reason")
                or "Local MVP backend live-service decision recorded."
            ),
            "live_coinbase_execution_approved": bool(
                body.get("live_coinbase_execution_approved", False)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    DEFAULT_MAX_EXECUTED_NOTIONAL_USDC,
                )
            ),
            "enablement_precondition_required": True,
            "enablement_precondition_resolved": False,
            "enablement_precondition_authority": "backend_only",
            "required_enablement_artifacts": [
                "deployment_ref",
                "runtime_configuration_ref",
                "live_coinbase_execution_approved",
            ],
            "recorded_enablement_artifacts": [
                "deployment_ref",
                "runtime_configuration_ref",
            ],
            "missing_enablement_artifacts": [
                "manual_backend_live_execution_review",
            ],
            "resolver_eligible": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "detail": "Backend-owned disabled live-service decision evidence.",
        }

    def record_live_adapter_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend live-adapter construction posture evidence."""

        decision_id = str(body.get("decision_id") or self.dependencies.uuid_factory())
        record = self._live_adapter_decision_record(decision_id, body, context)
        self.store.live_adapter_decisions[decision_id] = record
        return self._ok(
            {
                "type": "admin_live_adapter_decision",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
                "service_method": LIVE_ADAPTER_DECISION_SERVICE_METHOD,
                "message": "Live-adapter decision recorded.",
                "decision": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _live_adapter_decision_record(
        self,
        decision_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        requested_status = str(
            body.get("requested_adapter_status")
            or AdminMvpLiveServiceStatus.LIVE_DISABLED.value
        )
        return {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": LIVE_ADAPTER_DECISION_ROUTE,
            "method": "POST",
            "module_id": "admin_system_health",
            "action_class": "local_state_mutation",
            "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
            "service_method": LIVE_ADAPTER_DECISION_SERVICE_METHOD,
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            "requested_adapter_status": requested_status,
            "live_execution_adapter_status": requested_status,
            "target_route": str(body.get("target_route") or MANUAL_ORDER_ROUTE),
            "target_method": str(body.get("target_method") or "POST"),
            "target_module_id": str(body.get("target_module_id") or MANUAL_ORDER_MODULE_ID),
            "target_service_method": str(
                body.get("target_service_method") or MANUAL_ORDER_SERVICE_METHOD
            ),
            "adapter_reference": str(
                body.get("adapter_reference")
                or f"AdminApiCommandService.{MANUAL_ORDER_SERVICE_METHOD}"
            ),
            "adapter_constructed": bool(body.get("adapter_constructed", False)),
            "adapter_enabled": bool(body.get("adapter_enabled", False)),
            "source": "admin_api_live_adapter_decision_log",
            "construction_review_ref": str(
                body.get("construction_review_ref")
                or "adapter-construction-review-disabled"
            ),
            "decision_reason": str(
                body.get("decision_reason")
                or "Local MVP backend live-adapter decision recorded."
            ),
            "live_coinbase_execution_approved": bool(
                body.get("live_coinbase_execution_approved", False)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(body.get("max_submitted_notional_usdc"), Decimal("0"))
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(body.get("max_executed_notional_usdc"), Decimal("0"))
            ),
            "construction_precondition_required": True,
            "construction_precondition_resolved": False,
            "construction_precondition_authority": "backend_route_binding_only_no_execution",
            "required_construction_artifacts": [
                "route_bound_live_execution_adapter",
                "shared_command_service_adapter",
            ],
            "recorded_construction_artifacts": ["route_bound_live_execution_adapter"],
            "missing_construction_artifacts": ["shared_command_service_adapter"],
            "route_mapping_satisfies_construction": False,
            "adapter_configuration_satisfies_construction": False,
            "resolver_eligible": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "detail": "Backend-owned disabled live-adapter decision evidence.",
        }

    def submit_manual_order(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Submit a manual order through backend admission and execution gates."""

        client_order_id = self._client_order_id(context.idempotency_key)
        payload_hash = _payload_hash(body)
        notional = _manual_order_notional(body)
        admission = self._admission_decision(
            context=context,
            identity_value=client_order_id,
            payload_hash=payload_hash,
        )
        if not admission["allowed"]:
            return self._manual_order_blocked_response(
                status_code=501,
                command_status=AdminMvpCommandStatus.NOT_IMPLEMENTED,
                message="Manual order requires approval, audit, cap, and reconciliation evidence before Coinbase execution.",
                failure_stage="approval_required",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        pre_coinbase_failure = self._pre_coinbase_failure(body, notional, admission)
        if pre_coinbase_failure:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=pre_coinbase_failure["message"],
                failure_stage=pre_coinbase_failure["failure_stage"],
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        return self._execute_manual_order(
            body=body,
            context=context,
            client_order_id=client_order_id,
            notional=notional,
            admission=admission,
        )

    def cancel_order_by_client_order_id(
        self,
        client_order_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Return a fail-closed cancel response until cancel proof gates exist."""

        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.NOT_IMPLEMENTED.value,
            "action_class": "live_exchange_cancel",
            "required_permission": "order:cancel",
            "service_method": "cancel_order_by_client_order_id",
            "message": "Cancel remains backend-owned and disabled until cancel proof gates are implemented.",
            "client_order_id": client_order_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "failure_stage": "durable_audit_required",
            "live_exchange_submitted": False,
            **self._runtime_evidence(),
            **self._live_outputs(False, Decimal("0")),
        }
        return self._result(501, response, context)

    def create_approval_request(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record an approval request bound to one command identity."""

        approval_request_id = str(
            body.get("approval_request_id") or f"approval-request-{self.dependencies.uuid_factory()}"
        )
        record = {
            "approval_request_id": approval_request_id,
            "approval_id": None,
            "status": "requested",
            "lifecycle_status": "requested",
            "requested_by_actor_id": context.actor_id,
            "requested_at": self._now_iso(),
            "decided_at": None,
            "revoked_at": None,
            "expires_at": None,
            "expired": False,
            **_command_evidence_from_body(body),
            "decision_actor_id": None,
            "revoked_by_actor_id": None,
            "cap_guard_decision_ref": body.get("cap_guard_decision_ref"),
            "reconciliation_plan_ref": body.get("reconciliation_plan_ref"),
            "request_reason": body.get("request_reason"),
            "decision_reason": None,
            "revoke_reason": None,
            "snapshot_linked": False,
            "live_execution_authority": False,
            "live_exchange_submitted": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": "Backend-owned approval request awaiting decision.",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.approval_requests[approval_request_id] = record
        return self._ok(
            {
                "type": "admin_approval_lifecycle",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": "approval:request",
                "service_method": "create_approval_request",
                "message": "Approval request recorded.",
                "approval": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def decide_approval_request(
        self,
        approval_request_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record an approval decision for a requested command."""

        request = self.store.approval_requests.get(approval_request_id)
        if request is None:
            return self._error(404, "Approval request not found.", context)
        decision = str(body.get("decision") or "").strip().lower()
        if decision != "approved":
            return self._error(400, "Only approved decisions are supported in the MVP.", context)
        approval_id = str(body.get("approval_id") or f"approval-{self.dependencies.uuid_factory()}")
        record = {
            **request,
            "approval_id": approval_id,
            "approval_request_id": approval_request_id,
            "status": "approved",
            "lifecycle_status": "approved",
            "decision": "approved",
            "decision_reason": body.get("decision_reason"),
            "decision_actor_id": context.actor_id,
            "decided_at": self._now_iso(),
            "expires_at": body.get("expires_at"),
            "cap_guard_decision_ref": body.get("cap_guard_decision_ref"),
            "reconciliation_plan_ref": body.get("reconciliation_plan_ref"),
            "snapshot_linked": True,
            "decision_correlation_id": context.correlation_id,
            "decision_idempotency_key": context.idempotency_key,
            "detail": "Backend-owned approval snapshot recorded.",
        }
        self.store.approval_requests[approval_request_id] = record
        self.store.approval_snapshots[approval_id] = record
        return self._ok(
            {
                "type": "admin_approval_lifecycle",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": "approval:manage",
                "service_method": "decide_approval_request",
                "message": "Approval decision recorded.",
                "approval": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_admission_audit(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record durable admission audit evidence for a command."""

        audit_id = str(
            body.get("admission_audit_id") or f"admission-audit-{self.dependencies.uuid_factory()}"
        )
        record = {
            "admission_audit_id": audit_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "actor_id": body.get("actor_id") or context.actor_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.admission_audits[audit_id] = record
        return self._ok(
            {
                "type": "admin_admission_audit_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "admission_audit": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_cap_guard_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record cap and guard evidence for a command."""

        decision_id = str(body.get("decision_id") or f"cap-guard-{self.dependencies.uuid_factory()}")
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "admission_audit_id": body.get("admission_audit_id"),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    DEFAULT_MAX_EXECUTED_NOTIONAL_USDC,
                )
            ),
            "wallet_check_required": bool(body.get("wallet_check_required", True)),
            "wallet_check_status": str(
                body.get("wallet_check_status") or AdminMvpGateStatus.BLOCKED.value
            ),
            "wallet_available_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("wallet_available_notional_usdc"),
                    DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC,
                )
            ),
            "wallet_check_source": str(body.get("wallet_check_source") or "missing"),
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.cap_guard_decisions[decision_id] = record
        return self._ok(
            {
                "type": "admin_cap_guard_decision_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "decision": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_reconciliation_plan(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record post-submit reconciliation plan evidence for a command."""

        plan_id = str(body.get("plan_id") or f"reconciliation-{self.dependencies.uuid_factory()}")
        record = {
            "plan_id": plan_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "admission_audit_id": body.get("admission_audit_id"),
            "cap_guard_decision_id": body.get("cap_guard_decision_id"),
            "exchange_submission_required": bool(
                body.get("exchange_submission_required", True)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    DEFAULT_MAX_EXECUTED_NOTIONAL_USDC,
                )
            ),
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.reconciliation_plans[plan_id] = record
        return self._ok(
            {
                "type": "admin_reconciliation_plan_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "plan": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def preview_admission(
        self,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Preview admission state from persisted backend proof evidence."""

        identity_value = _query_text(query, "identity_value")
        payload_hash = _query_text(query, "payload_hash")
        command_idempotency_key = _query_text(query, "command_idempotency_key")
        preview_context = AdminMvpRequestContext(
            idempotency_key=command_idempotency_key,
            correlation_id=context.correlation_id,
            operator_intent=_query_text(query, "operator_intent"),
            actor_id=_query_text(query, "actor_id"),
            roles=context.roles,
        )
        admission = self._admission_decision(
            context=preview_context,
            identity_value=identity_value,
            payload_hash=payload_hash,
        )
        return self._ok(
            {
                "type": "admin_live_admission_preview",
                "admission_decision": admission,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _execute_manual_order(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        client_order_id: str,
        notional: Decimal,
        admission: dict[str, Any],
    ) -> AdminMvpApiResult:
        if not self.dependencies.live_coinbase_execution_enabled:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message="Live Coinbase execution is not enabled for this local backend process.",
                failure_stage="action_condition_guard",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )
        order_configuration = _manual_order_configuration(body)
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_admission(controller)
            with _track_runtime_place(controller):
                result = self.dependencies.rest_client.create_order(
                    client_order_id=client_order_id,
                    product_id=str(body.get("product_id") or ""),
                    side=str(body.get("side") or ""),
                    order_configuration=order_configuration,
                )
        except Exception as exc:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=f"Coinbase order submission failed: {exc}",
                failure_stage="coinbase_rest",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        result_data = _object_to_dict(result)
        order_id = str(result_data.get("order_id") or "")
        self.store.submitted_notional_usdc += notional
        self.store.live_coinbase_orders_ran = True
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "message": "Manual order submitted to Coinbase by backend Admin API.",
            "client_order_id": client_order_id,
            "coinbase_order_id": order_id or None,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "admission_decision": admission,
            "live_exchange_submitted": True,
            "submission_event_recorded": False,
            **self._runtime_evidence(),
            **self._live_outputs(True, notional),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _manual_order_blocked_response(
        self,
        *,
        status_code: int,
        command_status: AdminMvpCommandStatus,
        message: str,
        failure_stage: str,
        client_order_id: str,
        notional: Decimal,
        admission: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        body = {
            "type": "admin_api_command_result",
            "status": command_status.value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "message": message,
            "client_order_id": client_order_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "admission_decision": dict(admission),
            "live_exchange_submitted": False,
            "failure_stage": failure_stage,
            **self._runtime_evidence(),
            **self._live_outputs(False, notional),
        }
        return self._result(status_code, body, context)

    def _pre_coinbase_failure(
        self,
        body: Mapping[str, Any],
        notional: Decimal,
        admission: Mapping[str, Any],
    ) -> dict[str, str] | None:
        if not _manual_live_acknowledged(body):
            return {
                "failure_stage": "manual_live_acknowledgement",
                "message": "Manual live acknowledgement is required.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "failure_stage": "product_capability",
                "message": "Coinbase REST client is not available to the backend.",
            }
        admitted_cap = self._admitted_cap_guard(admission)
        max_submitted = _decimal_value(
            admitted_cap.get("max_submitted_notional_usdc") if admitted_cap else None,
            DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
        )
        if notional > max_submitted:
            return {
                "failure_stage": "direct_spot_cap_required",
                "message": "Manual order notional exceeds backend cap evidence.",
            }
        wallet_failure = _wallet_inventory_failure(admitted_cap, notional)
        if wallet_failure is not None:
            return wallet_failure
        if not self._latest_service_decision_allows_live():
            return {
                "failure_stage": "durable_audit_required",
                "message": "Backend live-service decision has not approved live execution.",
            }
        return None

    def _admitted_cap_guard(self, admission: Mapping[str, Any]) -> dict[str, Any] | None:
        decision_id = str(admission.get("cap_guard_decision_id") or "")
        if not decision_id:
            return None
        return self.store.cap_guard_decisions.get(decision_id)

    def _admission_decision(
        self,
        *,
        context: AdminMvpRequestContext,
        identity_value: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        approval = self._matching_approval(identity_value, context.idempotency_key, payload_hash)
        admission_audit = self._matching_admission_audit(
            identity_value,
            context.idempotency_key,
            payload_hash,
        )
        cap_guard = self._matching_cap_guard(identity_value, context.idempotency_key, payload_hash)
        reconciliation = self._matching_reconciliation(
            identity_value,
            context.idempotency_key,
            payload_hash,
        )
        service_status = self._live_service_status()
        service_present = bool(self.store.service_decisions)
        blockers = []
        if approval is None:
            blockers.append("approval_snapshot_missing")
        if admission_audit is None:
            blockers.append("admission_audit_missing")
        if cap_guard is None:
            blockers.append("cap_guard_missing")
        if reconciliation is None:
            blockers.append("reconciliation_plan_missing")
        if service_status != AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value:
            blockers.append("live_execution_service_missing")
        allowed = not blockers
        return {
            "status": (
                AdminMvpGateStatus.PASSED.value
                if allowed
                else AdminMvpGateStatus.BLOCKED.value
            ),
            "allowed": allowed,
            "route": MANUAL_ORDER_ROUTE,
            "method": "POST",
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "identity_value": identity_value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "actor_id": context.actor_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "payload_hash": payload_hash,
            "approval_snapshot_required": True,
            "approval_snapshot_present": approval is not None,
            "approval_snapshot_id": approval.get("approval_id") if approval else None,
            "admission_audit_required": True,
            "admission_audit_present": admission_audit is not None,
            "admission_audit_id": (
                admission_audit.get("admission_audit_id") if admission_audit else None
            ),
            "cap_guard_required": True,
            "cap_guard_present": cap_guard is not None,
            "cap_guard_decision_id": cap_guard.get("decision_id") if cap_guard else None,
            "reconciliation_required": True,
            "reconciliation_plan_present": reconciliation is not None,
            "reconciliation_plan_id": reconciliation.get("plan_id") if reconciliation else None,
            "live_execution_service_required": True,
            "live_execution_service_present": service_present,
            "live_execution_service_status": service_status,
            "live_execution_service_source": "application/admin_api/mvp_service.py",
            "browser_authority": "backend_admin_api" if allowed else "rejected",
            "live_exchange_submitted": False,
            "blockers": blockers,
            "evidence": _evidence_refs(approval, admission_audit, cap_guard, reconciliation),
            "detail": (
                "Backend proof chain admits the manual order."
                if allowed
                else "Backend proof chain is incomplete for manual order admission."
            ),
        }

    def _matching_approval(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.approval_snapshots.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            status_field="decision",
            required_status="approved",
        )

    def _matching_admission_audit(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.admission_audits.values(),
            identity_value,
            idempotency_key,
            payload_hash,
        )

    def _matching_cap_guard(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.cap_guard_decisions.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            required_allowed=True,
        )

    def _matching_reconciliation(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.reconciliation_plans.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            required_allowed=True,
        )

    def _client_order_id(self, idempotency_key: str) -> str:
        existing = self.store.command_identity_by_idempotency_key.get(idempotency_key)
        if existing:
            return existing
        client_order_id = self.dependencies.uuid_factory()
        self.store.command_identity_by_idempotency_key[idempotency_key] = client_order_id
        return client_order_id

    def _runtime_evidence(self) -> dict[str, Any]:
        rest_ready = self.dependencies.rest_client_available and self.dependencies.rest_client is not None
        return {
            "live_command_runtime_enabled": True,
            "live_command_rest_client_available": rest_ready,
            "live_command_runtime_ready": rest_ready,
            "live_command_runtime_missing_reason": None if rest_ready else "rest_client_unavailable",
            "live_command_runtime_source": "application/admin_api/mvp_service.py",
        }

    def _live_service_status(self) -> str:
        latest = _latest_record(self.store.service_decisions)
        if latest and latest.get("service_enabled"):
            return str(
                latest.get("requested_service_status")
                or AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
            )
        return AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value

    def _latest_service_decision_allows_live(self) -> bool:
        latest = _latest_record(self.store.service_decisions)
        return bool(latest and latest.get("live_coinbase_execution_approved"))

    def _now_iso(self) -> str:
        return self.dependencies.now_factory().astimezone(timezone.utc).isoformat()

    def _ok(
        self,
        body: dict[str, Any],
        context: AdminMvpRequestContext,
        *,
        live_execution_enabled: bool = False,
    ) -> AdminMvpApiResult:
        return self._result(200, body, context, live_execution_enabled=live_execution_enabled)

    def _error(
        self,
        status_code: int,
        message: str,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        return self._result(
            status_code,
            {
                "type": "admin_mvp_error",
                "code": "request_error",
                "message": message,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _result(
        self,
        status_code: int,
        body: dict[str, Any],
        context: AdminMvpRequestContext,
        *,
        live_execution_enabled: bool = False,
    ) -> AdminMvpApiResult:
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-Id": context.correlation_id,
            "X-Request-Id": context.correlation_id,
            "X-Admin-Api-Version": ADMIN_API_VERSION,
            "X-Live-Execution-Enabled": "true" if live_execution_enabled else "false",
        }
        return AdminMvpApiResult(status_code=status_code, body=body, headers=headers)

    def _live_outputs(self, live_ran: bool, notional: Decimal) -> dict[str, Any]:
        return {
            "live_coinbase_execution": "submitted" if live_ran else "not_run",
            "notional_usdc": _decimal_text(notional),
            "live_coinbase_orders_ran": live_ran,
        }

    def _admin_bootstrap(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        return {
            "type": "admin_bootstrap",
            "status": "ready",
            "actor": {"actor_id": context.actor_id, "roles": list(context.roles)},
            "capabilities_route": "/api/v1/admin/capabilities",
            "session_route": "/api/v1/admin/session",
            "live_coinbase_orders_ran": False,
        }

    def _admin_health(self) -> dict[str, Any]:
        return {
            "type": "admin_health",
            "status": "ok",
            "service": "coinbase-admin-prod-mvp",
            "version": ADMIN_API_VERSION,
            "deployment_target": "coinbase-local",
            "read_only": True,
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            **self._live_outputs(False, Decimal("0")),
        }

    def _admin_session(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        return {
            "type": "admin_session",
            "status": "authenticated",
            "session_status": "authenticated",
            "actor": {"actor_id": context.actor_id, "roles": list(context.roles)},
            "actor_id": context.actor_id,
            "roles": list(context.roles),
            "auth_mode": "bootstrap_bearer",
            "bearer_token_visible_to_browser": False,
            "live_coinbase_orders_ran": False,
        }

    def _oidc_readiness(self) -> dict[str, Any]:
        return {
            "type": "admin_oidc_jwt_readiness",
            "active_auth_mode": "bootstrap_bearer",
            "mode": "oidc_jwt",
            "status": "blocked",
            "verifier_implemented": False,
            "missing_env_vars": [],
            "live_coinbase_orders_ran": False,
        }

    def _capability_registry(self) -> dict[str, Any]:
        return {
            "type": "admin_capabilities",
            "capabilities": self._capability_items(),
            "live_coinbase_orders_ran": False,
        }

    def _csrf_contract(self) -> dict[str, Any]:
        return {
            "type": "admin_csrf_contract",
            "csrf_required": False,
            "csrf_header_name": "X-CSRF-Token",
            "token_issued_by_backend": False,
            "token_visible_to_browser": False,
            "live_coinbase_orders_ran": False,
        }

    def _account_management(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        return {
            "type": "admin_account_management",
            "status": "warning",
            "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
            "environment": self._account_management_environment(),
            "operator": {
                "actor_id": context.actor_id,
                "roles": list(context.roles),
                "required_permission": "analytics:read",
                "auth_mode": "bootstrap_bearer",
            },
            "account_scope": {
                "scope_type": "local_admin_portfolio",
                "scope_id": "local-admin-account-scope",
                "source": "backend_admin_mvp",
                "freshness_status": "local_default_not_connected",
            },
            "portfolio_scope": {
                "portfolio_id": "local-admin-portfolio",
                "portfolio_name": "Local Admin Portfolio",
                "source": "backend_admin_mvp",
                "freshness_status": "local_default_not_connected",
            },
            "wallet_inventory": self._account_management_wallet_inventory(),
            "permissions": self._account_management_permissions(context),
            "command_readiness_prerequisites": self._account_management_prerequisites(),
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "audit_surface": ACCOUNT_MANAGEMENT_ROUTE,
            },
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "coinbase_read_enabled": False,
            "live_coinbase_read_ran": False,
            **self._live_outputs(False, Decimal("0")),
            "notional_usdc": "0",
        }

    def _account_management_environment(self) -> dict[str, Any]:
        return {
            "environment": "local",
            "deployment_target": "coinbase-local",
            "backend_repository": "s-aws/coinbase",
            "admin_api_version": ADMIN_API_VERSION,
        }

    def _account_management_wallet_inventory(self) -> dict[str, Any]:
        return {
            "currency": "USDC",
            "available_notional_usdc": "0",
            "hold_notional_usdc": "0",
            "total_notional_usdc": "0",
            "source": "backend_admin_mvp_default",
            "freshness_status": "local_default_not_connected",
            "status": "blocked",
            "error": "No Coinbase account read has been enabled for this local MVP route.",
        }

    def _account_management_permissions(
        self,
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        return {
            "actor_id": context.actor_id,
            "roles": list(context.roles),
            "required_permission": "analytics:read",
            "permission_status": "visible",
            "mutation_permissions_granted": [],
        }

    def _account_management_prerequisites(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "backend_admin_api_contract",
                "status": "visible",
                "detail": "Account management is exposed only through this backend Admin API read route.",
            },
            {
                "name": "rbac",
                "status": "visible",
                "detail": "Read access uses Admin API session and role evidence.",
            },
            {
                "name": "wallet_inventory_evidence",
                "status": "blocked",
                "detail": "Live Coinbase account and wallet reads are disabled until a backend proof path exists.",
            },
            {
                "name": "approval_admission_cap_reconciliation",
                "status": "blocked",
                "detail": "No account, transfer, or trading mutation can proceed from this read route.",
            },
        ]

    def _live_enablement(self) -> dict[str, Any]:
        manual_path = self._live_path(
            route=MANUAL_ORDER_ROUTE,
            method="POST",
            live_enabled=True,
            live_eligible=True,
        )
        cancel_path = self._live_path(
            route=CANCEL_ORDER_ROUTE,
            method="POST",
            live_enabled=False,
            live_eligible=False,
        )
        return {
            "type": "admin_live_enablement",
            "status": self._live_service_status(),
            "default_live_coinbase_execution": "not_run",
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            "quote_currency": "USDC",
            "max_submitted_notional_usdc": _decimal_text(self._max_submitted_notional()),
            "max_executed_notional_usdc": _decimal_text(DEFAULT_MAX_EXECUTED_NOTIONAL_USDC),
            "live_enabled_path_count": 1,
            "live_eligible_path_count": 1,
            "live_command_runtime_enabled": True,
            **self._runtime_evidence(),
            "live_command_runtime_ready_path_count": 1,
            "paths": [manual_path, cancel_path],
            "checks": [
                {
                    "name": "backend_admin_service_gate",
                    "status": self._live_service_status(),
                    "detail": "Manual order requires backend proof-chain admission before Coinbase execution.",
                }
            ],
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _enterprise_readiness(self) -> dict[str, Any]:
        modules = [
            _module_registry(
                "admin_system_health",
                "Admin / System Health",
                "platform_ready",
                ["/api/v1/admin/health", "/api/v1/admin/session"],
            ),
            _module_registry(
                ACCOUNT_MANAGEMENT_MODULE_ID,
                "Account Management",
                "mvp_read_ready",
                [ACCOUNT_MANAGEMENT_ROUTE],
            ),
            _module_registry(
                "spot_operations",
                "Spot Operations",
                "mvp_controlled_live_ready",
                ["/api/v1/orders", "/api/v1/spot/command-suite"],
            ),
        ]
        return {
            "type": "admin_enterprise_readiness",
            "candidate": "prod_admin_mvp",
            "status": "warning",
            "module_count": len(modules),
            "supported_module_count": len(modules),
            "unsupported_module_count": 0,
            "command_gap_count": 0,
            "functionality_inventory": [],
            "mutation_taxonomy": [],
            "modules": modules,
            "security_checks": [],
            "release_checks": [],
            "live_coinbase_orders_ran": False,
        }

    def _simple_gate(self, gate_type: str) -> dict[str, Any]:
        return {
            "type": gate_type,
            "status": "passed",
            "checks": [],
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _frontend_fixtures(self) -> dict[str, Any]:
        return {
            "type": "admin_frontend_fixtures",
            "fixtures": {},
            "live_coinbase_orders_ran": False,
        }

    def _approval_list(self) -> dict[str, Any]:
        approvals = list(self.store.approval_requests.values())
        pending_count = sum(1 for approval in approvals if approval.get("status") == "requested")
        approved_count = sum(1 for approval in approvals if approval.get("status") == "approved")
        rejected_count = sum(1 for approval in approvals if approval.get("status") == "rejected")
        revoked_count = sum(1 for approval in approvals if approval.get("status") == "revoked")
        expired_count = sum(1 for approval in approvals if approval.get("expired"))
        return {
            "type": "admin_approval_lifecycle_list",
            "approvals": approvals,
            "returned_count": len(approvals),
            "total_count": len(approvals),
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "revoked_count": revoked_count,
            "expired_count": expired_count,
            "count": len(approvals),
            "pagination": _pagination(len(approvals), len(approvals), 0),
            "live_coinbase_orders_ran": False,
        }

    def _approval_detail(self, approval_request_id: str) -> dict[str, Any]:
        approval = self.store.approval_requests.get(approval_request_id)
        return {
            "type": "admin_approval_lifecycle",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if approval is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": "approval:read",
            "service_method": "get_approval_request",
            "message": (
                "Approval detail loaded."
                if approval is not None
                else "Approval request was not found."
            ),
            "approval": approval,
            "found": approval is not None,
            "correlation_id": approval.get("correlation_id") if approval else None,
            "idempotency_key": approval.get("idempotency_key") if approval else None,
            "audit_id": (
                f"audit-{approval.get('idempotency_key')}"
                if approval and approval.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _admission_audit_list(self) -> dict[str, Any]:
        records = list(self.store.admission_audits.values())
        return {
            "type": "admin_admission_audit_list",
            "admission_audits": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _admission_audit_detail(self, audit_id: str) -> dict[str, Any]:
        audit = self.store.admission_audits.get(audit_id)
        return {
            "type": "admin_admission_audit_detail",
            "admission_audit": audit,
            "found": audit is not None,
            "live_coinbase_orders_ran": False,
        }

    def _cap_guard_list(self) -> dict[str, Any]:
        records = list(self.store.cap_guard_decisions.values())
        return {
            "type": "admin_cap_guard_decision_list",
            "decisions": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _cap_guard_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.cap_guard_decisions.get(decision_id)
        return {
            "type": "admin_cap_guard_decision_detail",
            "decision": decision,
            "found": decision is not None,
            "live_coinbase_orders_ran": False,
        }

    def _reconciliation_list(self) -> dict[str, Any]:
        records = list(self.store.reconciliation_plans.values())
        return {
            "type": "admin_reconciliation_plan_list",
            "plans": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _reconciliation_detail(self, plan_id: str) -> dict[str, Any]:
        plan = self.store.reconciliation_plans.get(plan_id)
        return {
            "type": "admin_reconciliation_plan_detail",
            "plan": plan,
            "found": plan is not None,
            "live_coinbase_orders_ran": False,
        }

    def _live_service_decision_list(self) -> dict[str, Any]:
        records = list(self.store.service_decisions.values())
        passed_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.PASSED.value
        )
        blocked_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.BLOCKED.value
        )
        return {
            "type": "admin_live_service_decision_list",
            "decisions": records,
            "returned_count": len(records),
            "total_count": len(records),
            "passed_count": passed_count,
            "blocked_count": blocked_count,
            "warning_count": 0,
            "resolver_eligible_count": sum(
                1 for record in records if record.get("resolver_eligible")
            ),
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _live_service_decision_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.service_decisions.get(decision_id)
        return {
            "type": "admin_live_service_decision",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if decision is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
            "service_method": "get_live_service_decision",
            "message": (
                "Live-service decision detail loaded."
                if decision is not None
                else "Live-service decision was not found."
            ),
            "decision": decision,
            "found": decision is not None,
            "correlation_id": decision.get("correlation_id") if decision else None,
            "idempotency_key": decision.get("idempotency_key") if decision else None,
            "audit_id": (
                f"audit-{decision.get('idempotency_key')}"
                if decision and decision.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _live_adapter_decision_list(self) -> dict[str, Any]:
        records = list(self.store.live_adapter_decisions.values())
        passed_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.PASSED.value
        )
        blocked_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.BLOCKED.value
        )
        return {
            "type": "admin_live_adapter_decision_list",
            "decisions": records,
            "returned_count": len(records),
            "total_count": len(records),
            "passed_count": passed_count,
            "blocked_count": blocked_count,
            "warning_count": 0,
            "resolver_eligible_count": sum(
                1 for record in records if record.get("resolver_eligible")
            ),
            "constructed_count": sum(
                1 for record in records if record.get("adapter_constructed")
            ),
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _live_adapter_decision_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.live_adapter_decisions.get(decision_id)
        return {
            "type": "admin_live_adapter_decision",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if decision is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
            "service_method": "get_live_adapter_decision",
            "message": (
                "Live-adapter decision detail loaded."
                if decision is not None
                else "Live-adapter decision was not found."
            ),
            "decision": decision,
            "found": decision is not None,
            "correlation_id": decision.get("correlation_id") if decision else None,
            "idempotency_key": decision.get("idempotency_key") if decision else None,
            "audit_id": (
                f"audit-{decision.get('idempotency_key')}"
                if decision and decision.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _order_list(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _query_int(query, "limit", 10)
        offset = _query_int(query, "offset", 0)
        return {
            "type": "admin_order_list",
            "count": 0,
            "items": [],
            "pagination": _pagination(limit, 0, offset),
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _order_detail(self, client_order_id: str) -> dict[str, Any]:
        return {
            "type": "admin_order_detail",
            "client_order_id": client_order_id,
            "found": False,
            "order": None,
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _spot_command_suite(self) -> dict[str, Any]:
        commands = [_manual_order_command(), _cancel_order_command()]
        return {
            "type": "spot_command_suite",
            "status": "approval_required",
            "command_count": len(commands),
            "blocked_command_count": 2,
            "live_enabled_command_count": 1,
            "executable_command_count": 0,
            "coverage_gap_count": 0,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "spot_rules_platform_default": False,
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            "commands": commands,
            "coverage_gaps": [],
            "live_coinbase_orders_ran": False,
        }

    def _spot_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/spot/readiness":
            return {
                "type": "spot_readiness",
                "status": "warning",
                "products": [],
                "planned_budget": {},
                "wallet_snapshot": {},
                "action_guard_summary": [],
                "read_only": True,
                "live_coinbase_orders_ran": False,
            }
        if path == "/api/v1/spot/sweep/status":
            return _operator_status("spot_sweep_status")
        if path == "/api/v1/spot/sweep/pnl":
            return {"type": "spot_sweep_pnl", "pnl_report": {}, "live_coinbase_orders_ran": False}
        if path == "/api/v1/spot/pnl/checkpoints":
            return {
                "type": "spot_pnl_checkpoint_list",
                "checkpoints": [],
                "count": 0,
                "live_coinbase_orders_ran": False,
            }
        if path.startswith("/api/v1/spot/pnl/checkpoints/"):
            return {
                "type": "spot_pnl_checkpoint_detail",
                "checkpoint_id": _last_path_part(path),
                "found": False,
                "checkpoint": None,
                "live_coinbase_orders_ran": False,
            }
        if path in {"/api/v1/spot/cost-basis/status", "/api/v1/spot/campaign/status"}:
            return _operator_status(_last_path_part(path))
        if "/direct-orders/" in path:
            return {
                "type": "spot_direct_order_audit",
                "status": "missing",
                "client_order_id": path.split("/direct-orders/", 1)[1].split("/", 1)[0],
                "audit": {},
                "message": "No local direct-order audit record exists.",
                "live_coinbase_orders_ran": False,
            }
        return {
            "type": "spot_placeholder",
            "status": "blocked",
            "route": path,
            "read_only": True,
            "items": [],
            "live_coinbase_orders_ran": False,
        }

    def _stealth_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/stealth/orders":
            limit = _query_int(query, "limit", 10)
            offset = _query_int(query, "offset", 0)
            return {
                "type": "admin_stealth_order_list",
                "count": 0,
                "items": [],
                "pagination": _pagination(limit, 0, offset),
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        if path == "/api/v1/stealth/command-suite":
            return _empty_command_suite("admin_stealth_command_suite")
        if path.count("/") >= 4:
            return {
                "type": "admin_stealth_detail",
                "stealth_order_id": path.split("/stealth/orders/", 1)[-1].split("/", 1)[0],
                "found": False,
                "order": None,
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        return _empty_read(path)

    def _movement_repricing_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/movement-repricing/evidence":
            limit = _query_int(query, "limit", 10)
            offset = _query_int(query, "offset", 0)
            return {
                "type": "movement_repricing_evidence_list",
                "count": 0,
                "items": [],
                "pagination": _pagination(limit, 0, offset),
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        return {
            "type": "movement_repricing_detail",
            "scope": "client_order_id" if "/orders/" in path else "stealth_order_id",
            "client_order_id": _last_path_part(path) if "/orders/" in path else None,
            "stealth_order_id": _last_path_part(path) if "/stealth/" in path else None,
            "found": False,
            "items": [],
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "live_coinbase_orders_ran": False,
        }

    def _futures_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/futures/command-suite":
            return _empty_command_suite("admin_futures_command_suite")
        if path == "/api/v1/futures/account":
            return {
                "type": "admin_futures_account",
                "configured_product_scope": [],
                "observed_position_scope": [],
                "position_count": 0,
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        if path == "/api/v1/futures/positions":
            limit = _query_int(query, "limit", 10)
            offset = _query_int(query, "offset", 0)
            return {
                "type": "admin_futures_position_list",
                "count": 0,
                "items": [],
                "pagination": _pagination(limit, 0, offset),
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        if path == "/api/v1/futures/risk-proofs":
            return {
                "type": "admin_futures_risk_proof_list",
                "count": 0,
                "items": [],
                "proof_records_created": False,
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_coinbase_orders_ran": False,
            }
        if "/risk-proofs/" in path:
            return {
                "type": "admin_futures_risk_proof_detail",
                "futures_risk_proof_id": _last_path_part(path),
                "found": False,
                "record": None,
                "proof_record_created": False,
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_coinbase_orders_ran": False,
            }
        return {
            "type": "admin_futures_position_detail",
            "position_key": _last_path_part(path),
            "found": False,
            "position": None,
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "live_coinbase_orders_ran": False,
        }

    def _guard_risk_policy(self, query: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "admin_guard_risk_policy",
            "filters": dict(query),
            "action_condition_policy": {},
            "live_execution_gate": {},
            "product_capability_policy": {},
            "profitability_policy": {},
            "configured_limit_rules": [],
            "product_capability_decisions": [],
            "authority_sources": [],
            "rejection_categories": [],
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    def _audit_workbench(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _query_int(query, "limit", 10)
        offset = _query_int(query, "offset", 0)
        return {
            "type": "admin_audit_workbench",
            "items": [],
            "count": 0,
            "pagination": _pagination(limit, 0, offset),
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _capability_items(self) -> list[dict[str, Any]]:
        read_routes = [
            "/api/v1/admin/bootstrap",
            "/api/v1/admin/health",
            "/api/v1/admin/session",
            "/api/v1/admin/oidc-readiness",
            "/api/v1/admin/capabilities",
            "/api/v1/admin/csrf",
            ACCOUNT_MANAGEMENT_ROUTE,
            "/api/v1/admin/live-enablement",
            "/api/v1/admin/enterprise-readiness",
            "/api/v1/admin/release-gate",
            "/api/v1/admin/recovery-gate",
            "/api/v1/admin/fill-ledger-health",
            "/api/v1/admin/frontend-fixtures",
            "/api/v1/orders",
            "/api/v1/spot/command-suite",
        ]
        capabilities = [
            _read_capability(
                route,
                ACCOUNT_MANAGEMENT_MODULE_ID
                if route == ACCOUNT_MANAGEMENT_ROUTE
                else "admin_system_health",
            )
            for route in read_routes
        ]
        capabilities.extend([
            _command_capability(
                route=MANUAL_ORDER_ROUTE,
                action_class=MANUAL_ORDER_ACTION_CLASS,
                required_permission=MANUAL_ORDER_PERMISSION,
                shared_method=MANUAL_ORDER_SERVICE_METHOD,
                live_enabled=True,
            ),
            _command_capability(
                route=CANCEL_ORDER_ROUTE,
                action_class="live_exchange_cancel",
                required_permission="order:cancel",
                shared_method="cancel_order_by_client_order_id",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/approvals/requests",
                action_class="local_state_mutation",
                required_permission="approval:request",
                shared_method="create_approval_request",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                action_class="local_state_mutation",
                required_permission="approval:manage",
                shared_method="decide_approval_request",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/admission-audits",
                action_class="local_state_mutation",
                required_permission="admission_audit:record",
                shared_method="record_admission_audit",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/cap-guard/decisions",
                action_class="local_state_mutation",
                required_permission="cap_guard:record",
                shared_method="record_cap_guard_decision",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/reconciliation/plans",
                action_class="local_state_mutation",
                required_permission="reconciliation:record",
                shared_method="record_reconciliation_plan",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/live-execution/service-decisions",
                action_class="local_state_mutation",
                required_permission="config:update",
                shared_method="record_live_service_decision",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/live-execution/adapter-decisions",
                action_class="local_state_mutation",
                required_permission="config:update",
                shared_method="record_live_adapter_decision",
                live_enabled=False,
            ),
        ])
        return capabilities

    def _live_path(
        self,
        *,
        route: str,
        method: str,
        live_enabled: bool,
        live_eligible: bool,
    ) -> dict[str, Any]:
        runtime = self._runtime_evidence()
        return {
            "route": route,
            "method": method,
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "action_class": (
                MANUAL_ORDER_ACTION_CLASS if route == MANUAL_ORDER_ROUTE else "live_exchange_cancel"
            ),
            "required_permission": (
                MANUAL_ORDER_PERMISSION if route == MANUAL_ORDER_ROUTE else "order:cancel"
            ),
            "service_method": (
                MANUAL_ORDER_SERVICE_METHOD
                if route == MANUAL_ORDER_ROUTE
                else "cancel_order_by_client_order_id"
            ),
            "live_enabled": live_enabled,
            "live_eligible": live_eligible,
            "live_command_runtime_ready": runtime["live_command_runtime_ready"],
            "live_command_runtime_missing_reason": runtime[
                "live_command_runtime_missing_reason"
            ],
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": "Backend controlled-live route evidence.",
        }

    def _max_submitted_notional(self) -> Decimal:
        latest = _latest_record(self.store.service_decisions)
        if not latest:
            return DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC
        return _decimal_value(
            latest.get("max_submitted_notional_usdc"),
            DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
        )


def _payload_hash(body: Mapping[str, Any]) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manual_order_notional(body: Mapping[str, Any]) -> Decimal:
    quote_size = _decimal_value(body.get("quote_size"), Decimal("0"))
    if quote_size > 0:
        return quote_size
    base_size = _decimal_value(body.get("base_size"), Decimal("0"))
    limit_price = _decimal_value(body.get("limit_price"), Decimal("0"))
    return base_size * limit_price


def _wallet_inventory_failure(
    cap_guard: Mapping[str, Any] | None,
    notional: Decimal,
) -> dict[str, str] | None:
    if cap_guard is None:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Backend wallet/inventory evidence is required before Coinbase execution.",
        }
    if bool(cap_guard.get("wallet_check_required", True)) is False:
        return None
    wallet_status = str(
        cap_guard.get("wallet_check_status") or AdminMvpGateStatus.BLOCKED.value
    )
    if wallet_status != AdminMvpGateStatus.PASSED.value:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Backend wallet/inventory check has not passed.",
        }
    wallet_available = _decimal_value(
        cap_guard.get("wallet_available_notional_usdc"),
        DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC,
    )
    if notional > wallet_available:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Manual order notional exceeds backend wallet/inventory evidence.",
        }
    return None


def _manual_order_configuration(body: Mapping[str, Any]) -> dict[str, Any]:
    order_type = str(body.get("order_type") or "MARKET").upper()
    if order_type == "LIMIT":
        inner = {
            "base_size": str(body.get("base_size") or ""),
            "limit_price": str(body.get("limit_price") or ""),
            "post_only": bool(body.get("post_only", False)),
        }
        return {"limit_limit_gtc": {key: value for key, value in inner.items() if value != ""}}
    inner: dict[str, str] = {}
    if body.get("base_size"):
        inner["base_size"] = str(body["base_size"])
    if body.get("quote_size"):
        inner["quote_size"] = str(body["quote_size"])
    return {"market_market_ioc": inner}


def _manual_live_acknowledged(body: Mapping[str, Any]) -> bool:
    value = body.get("manual_live_acknowledgement", body.get("manual_live_acknowledged"))
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_ENV_VALUES
    return bool(value)


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _check_runtime_admission(controller: Any) -> None:
    from core.runtime_controller import INFLIGHT_REST_PLACE

    check_admission = getattr(controller, "check_admission", None)
    if callable(check_admission):
        check_admission(INFLIGHT_REST_PLACE)


def _track_runtime_place(controller: Any):
    from contextlib import nullcontext
    from core.runtime_controller import INFLIGHT_REST_PLACE

    tracker = getattr(controller, "track_inflight", None)
    if callable(tracker):
        return tracker(INFLIGHT_REST_PLACE)
    return nullcontext()


def _find_matching_record(
    records: Any,
    identity_value: str,
    idempotency_key: str,
    payload_hash: str,
    *,
    status_field: str | None = None,
    required_status: str | None = None,
    required_allowed: bool | None = None,
) -> dict[str, Any] | None:
    for record in records:
        if record.get("identity_value") != identity_value:
            continue
        if record.get("command_idempotency_key") != idempotency_key:
            continue
        if record.get("payload_hash") != payload_hash:
            continue
        if status_field and str(record.get(status_field)) != required_status:
            continue
        if required_allowed is not None and bool(record.get("allowed")) is not required_allowed:
            continue
        return record
    return None


def _command_evidence_from_body(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route": str(body.get("route") or ""),
        "method": str(body.get("method") or ""),
        "module_id": str(body.get("module_id") or ""),
        "identity_key": str(body.get("identity_key") or ""),
        "identity_value": str(body.get("identity_value") or ""),
        "action_class": str(body.get("action_class") or ""),
        "required_permission": str(body.get("required_permission") or ""),
        "service_method": str(body.get("service_method") or MANUAL_ORDER_SERVICE_METHOD),
        "operator_intent": str(body.get("operator_intent") or ""),
        "command_idempotency_key": str(body.get("command_idempotency_key") or ""),
        "payload_hash": str(body.get("payload_hash") or ""),
    }


def _evidence_refs(*records: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for record in records:
        if not record:
            continue
        for key in ("approval_id", "admission_audit_id", "decision_id", "plan_id"):
            value = record.get(key)
            if value:
                refs.append(str(value))
                break
    return refs


def _decimal_value(value: Any, default: Decimal) -> Decimal:
    try:
        if value in (None, ""):
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _decimal_text(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"))
    return format(normalized, "f")


def _latest_record(records: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return next(reversed(records.values()))


def _query_text(query: Mapping[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def _query_int(query: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(_query_text(query, key) or default)
    except ValueError:
        return default


def _pagination(limit: int, count: int, offset: int) -> dict[str, Any]:
    return {
        "limit": limit,
        "offset": offset,
        "returned_count": count,
        "total_matching_count": count,
        "next_offset": None,
        "has_more": False,
    }


def _normalize_path(path: str) -> str:
    return "/" + path.strip().split("?", 1)[0].strip("/")


def _last_path_part(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _read_capability(route: str, module_id: str) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "route": route,
        "method": "GET",
        "availability": "available",
        "live_enabled": False,
        "frontend_safe": True,
        "action_class": "read_only",
        "permission": "analytics:read",
        "required_permission": "analytics:read",
        "shared_method": "read_mvp_contract",
        "idempotency": "not_required",
        "approval": "not_required",
        "caps": "not_required",
        "audit": "read_only",
        "command_contract": False,
        "compatibility_mode": "prod_mvp",
        "parity_test": "tests/regression/test_admin_mvp_api.py",
        "detail": "Read-only backend Admin MVP evidence.",
    }


def _command_capability(
    *,
    route: str,
    action_class: str,
    required_permission: str,
    shared_method: str,
    live_enabled: bool,
) -> dict[str, Any]:
    return {
        "module_id": MANUAL_ORDER_MODULE_ID if route.startswith("/api/v1/orders") else "admin_system_health",
        "route": route,
        "method": "POST",
        "availability": "available",
        "live_enabled": live_enabled,
        "frontend_safe": True,
        "action_class": action_class,
        "permission": required_permission,
        "required_permission": required_permission,
        "shared_method": shared_method,
        "idempotency": "required",
        "approval": "required",
        "caps": "required",
        "audit": "required",
        "command_contract": True,
        "compatibility_mode": "backend_admin_api_only",
        "parity_test": "tests/regression/test_admin_mvp_api.py",
        "detail": "Mutating route is backend-owned and auditable.",
    }


def _manual_order_command() -> dict[str, Any]:
    return {
        "mutation_family": "spot_manual_order",
        "route": MANUAL_ORDER_ROUTE,
        "method": "POST",
        "identity_key": "client_order_id",
        "shared_method": MANUAL_ORDER_SERVICE_METHOD,
        "status": "blocked",
        "live_execution_status": AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value,
        "live_enabled": True,
        "live_eligible": True,
        "executable": False,
        "live_adapter_configured": True,
        "missing_gate_chain": [
            "approval_snapshot",
            "admission_audit",
            "cap_guard",
            "reconciliation_plan",
        ],
        "proof_routes": [
            _proof_route("approval", "/api/v1/admin/approvals/requests", "approval_request_id"),
            _proof_route("admission_audit", "/api/v1/admin/admission-audits", "admission_audit_id"),
            _proof_route("cap_guard", "/api/v1/admin/cap-guard/decisions", "decision_id"),
            _proof_route("reconciliation", "/api/v1/admin/reconciliation/plans", "plan_id"),
        ],
        "readiness_preconditions": [],
        "readiness_precondition_count": 0,
        "blocking_readiness_precondition_count": 0,
        "passed_readiness_precondition_count": 0,
    }


def _cancel_order_command() -> dict[str, Any]:
    return {
        "mutation_family": "spot_order_cancel",
        "route": CANCEL_ORDER_ROUTE,
        "method": "POST",
        "identity_key": "client_order_id",
        "shared_method": "cancel_order_by_client_order_id",
        "status": "blocked",
        "live_execution_status": AdminMvpLiveServiceStatus.LIVE_DISABLED.value,
        "live_enabled": False,
        "live_eligible": False,
        "executable": False,
        "live_adapter_configured": False,
        "missing_gate_chain": ["cancel_proof_chain"],
        "proof_routes": [],
        "readiness_preconditions": [],
        "readiness_precondition_count": 0,
        "blocking_readiness_precondition_count": 0,
        "passed_readiness_precondition_count": 0,
    }


def _proof_route(gate: str, route: str, identity_key: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "route": route,
        "method": "POST",
        "identity_key": identity_key,
        "command_identity_key": "client_order_id",
        "shared_method": gate,
        "status": "available",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": "Backend proof-chain evidence route.",
    }


def _module_registry(
    module_id: str,
    module: str,
    support_status: str,
    evidence_routes: list[str],
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "module": module,
        "support_status": support_status,
        "read_routes": [f"GET {route}" for route in evidence_routes],
        "command_routes": [],
        "live_routes": [f"POST {MANUAL_ORDER_ROUTE}"] if module_id == "spot_operations" else [],
        "unsupported_actions": [],
        "command_gaps": [],
        "identity_keys": ["client_order_id"] if module_id == "spot_operations" else ["correlation_id"],
        "constraints": [],
        "evidence_routes": evidence_routes,
        "verification": ["tests/regression/test_admin_mvp_api.py"],
        "action_posture": {
            "module_id": module_id,
            "status": support_status,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _empty_command_suite(response_type: str) -> dict[str, Any]:
    return {
        "type": response_type,
        "status": "blocked",
        "command_count": 0,
        "blocked_command_count": 0,
        "executable_command_count": 0,
        "live_enabled_command_count": 0,
        "command_route_count": 0,
        "commands": [],
        "coverage_gaps": [],
        "read_only": True,
        "command_routes_mode": "backend_admin_api",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_coinbase_orders_ran": False,
    }


def _operator_status(response_type: str) -> dict[str, Any]:
    return {
        "type": response_type,
        "status": "warning",
        "operator_status": {
            "status": "warning",
            "latest_run_status": "not_configured",
        },
        "read_only": True,
        "live_coinbase_orders_ran": False,
    }


def _empty_read(path: str) -> dict[str, Any]:
    return {
        "type": "admin_mvp_empty_read",
        "route": path,
        "status": "blocked",
        "read_only": True,
        "live_coinbase_orders_ran": False,
    }


_SERVICE_SINGLETON: AdminMvpService | None = None


def get_admin_mvp_service() -> AdminMvpService:
    """Return the process-local Admin MVP service singleton."""

    global _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is None:
        _SERVICE_SINGLETON = AdminMvpService(
            AdminMvpDependencies(
                rest_client=_load_rest_client(),
                rest_client_available=_rest_client_available(),
                live_coinbase_execution_enabled=live_coinbase_execution_enabled_from_env(),
            )
        )
    return _SERVICE_SINGLETON


def _load_rest_client() -> Any:
    try:
        from configuration import REST_CLIENT

        return REST_CLIENT
    except Exception:
        return None


def _rest_client_available() -> bool:
    return _load_rest_client() is not None
