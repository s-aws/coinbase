"""Live execution service posture for Admin API command admission.

This module intentionally exposes service-state evidence only. It does not
place, cancel, move, reconcile, or submit Coinbase orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from core.enums import (
    AdminApiActionClass,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)


DISABLED_LIVE_EXECUTION_SERVICE_SOURCE = "disabled_backend_service"
DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE = (
    "disabled_stealth_command_live_adapter"
)
POST_WRITE_RECONCILIATION_ROUTE = "/api/v1/admin/reconciliation/plans"
POST_WRITE_RECONCILIATION_METHOD = "POST"
POST_WRITE_RECONCILIATION_SOURCE = "post_write_reconciliation_contract"
EXECUTION_BOUNDARY_AUTHORITY = "backend_contract_only_no_execution"
LIVE_EXECUTION_DISABLED_REASON = "live_execution_disabled"
DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS = (
    "create_order",
    "cancel_order",
    "execute",
    "submit",
    "coinbase_client",
)
M53_PILOT_LIVE_ADAPTER_ROUTE = "/api/v1/orders"
M53_PILOT_LIVE_ADAPTER_METHOD = "POST"
M53_PILOT_LIVE_ADAPTER_MODULE_ID = "spot_operations"
M53_PILOT_LIVE_ADAPTER_SERVICE_METHOD = "place_manual_order"
M53_PILOT_LIVE_ADAPTER_SOURCE = "m53_backend_pilot_dry_run"
M53_PILOT_LIVE_ADAPTER_MISSING_REASON = "pilot_dry_run_only"


@dataclass(frozen=True, slots=True)
class AdminApiLiveExecutionServiceState:
    """Backend-owned live execution service posture."""

    required: bool = True
    present: bool = False
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "not_configured"
    missing_reason: str | None = LIVE_EXECUTION_DISABLED_REASON


class AdminApiLiveExecutionService(Protocol):
    """Protocol for service-state providers used by admission evidence."""

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        """Return backend-owned live execution service posture."""
        ...


class DisabledAdminApiLiveExecutionService:
    """Disabled service boundary for future live Admin API execution.

    The current implementation is evidence-only. Keeping this object separate
    from command routes makes the final execution boundary visible without
    adding an executable path.
    """

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        return AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
            source=DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
            missing_reason=LIVE_EXECUTION_DISABLED_REASON,
        )


def get_disabled_live_execution_service() -> DisabledAdminApiLiveExecutionService:
    """Return the default backend-owned disabled live execution service."""

    return DisabledAdminApiLiveExecutionService()


def build_live_execution_service_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
    live_execution_service: AdminApiLiveExecutionService | None = None,
) -> dict[str, Any]:
    """Return read-only route-to-live-service boundary evidence.

    This is a projection of the backend-owned live execution service state,
    not a live service implementation or adapter factory.
    """

    service = live_execution_service or get_disabled_live_execution_service()
    state = service.admission_state()
    return {
        "required": state.required,
        "present": state.present,
        "enabled": False,
        "backend_owned": True,
        "route_bound": True,
        "final_boundary": True,
        "status": state.status,
        "source": state.source,
        "missing_reason": state.missing_reason,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "service_reference": "DisabledAdminApiLiveExecutionService.admission_state",
        "action_class": action_class,
        "executable": False,
        "live_exchange_submission_allowed": False,
        "live_exchange_submitted": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "Live execution service state is owned by backend admission.",
            "The current service state is disabled and non-executable.",
            "Browser and BFF layers may display this boundary but cannot enable it.",
        ],
        "detail": (
            f"{method} {route} requires the backend live execution service for "
            f"{service_method}; the service remains disabled with "
            f"{state.missing_reason or LIVE_EXECUTION_DISABLED_REASON}."
        ),
    }


def build_disabled_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
) -> dict[str, Any]:
    """Return read-only route-to-service adapter evidence.

    The adapter contract names the shared backend command method that would
    remain the execution boundary in a future live phase. It does not add an
    executable method to the disabled service descriptor.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "configured": False,
        "backend_owned": True,
        "route_bound": True,
        "status": AdminApiLiveExecutionStatus.LIVE_DISABLED,
        "source": DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
        "missing_reason": LIVE_EXECUTION_DISABLED_REASON,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "action_class": action_class,
        "executable": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "Live-shaped route is mapped to the shared backend command service.",
            "The disabled live execution service descriptor has no executable adapter.",
            "Browser and BFF layers cannot create a route-local execution adapter.",
        ],
        "detail": (
            f"{method} {route} is mapped to {adapter_reference}, but the "
            "Admin API live execution service remains disabled and "
            "non-executable."
        ),
    }


def build_m53_pilot_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
) -> dict[str, Any]:
    """Return the M53 route-bound pilot adapter evidence.

    This contract deliberately stops short of executable live submission. It
    proves the selected route is mapped to the shared command service and can
    be dry-run admitted, while the live execution service remains the final
    backend-only boundary before any Coinbase call is possible.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "configured": True,
        "backend_owned": True,
        "route_bound": True,
        "status": AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        "source": M53_PILOT_LIVE_ADAPTER_SOURCE,
        "missing_reason": M53_PILOT_LIVE_ADAPTER_MISSING_REASON,
        "module_id": module_id,
        "route": route,
        "method": method,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "action_class": action_class,
        "executable": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "forbidden_methods": list(DISABLED_LIVE_EXECUTION_FORBIDDEN_METHODS),
        "evidence": [
            "M53 pilot maps one route to the shared backend command service.",
            "Pilot adapter admission is dry-run only and exposes no submit method.",
            "Live execution service admission remains required before Coinbase submission.",
            "Browser and BFF layers cannot make the pilot adapter executable.",
        ],
        "detail": (
            f"{method} {route} is configured as the M53 dry-run pilot for "
            f"{adapter_reference}; it remains non-executable until backend "
            "live execution service admission, route-bound approvals, caps, "
            "admission audit, reconciliation proof, and live caps all pass."
        ),
    }


def build_live_execution_adapter_contract(
    *,
    method: str,
    route: str,
    module_id: str,
    service_method: str,
    action_class: AdminApiActionClass,
) -> dict[str, Any]:
    """Return route-specific live adapter evidence for Admin API readiness."""

    if (
        method == M53_PILOT_LIVE_ADAPTER_METHOD
        and route == M53_PILOT_LIVE_ADAPTER_ROUTE
        and module_id == M53_PILOT_LIVE_ADAPTER_MODULE_ID
        and service_method == M53_PILOT_LIVE_ADAPTER_SERVICE_METHOD
    ):
        return build_m53_pilot_live_execution_adapter_contract(
            method=method,
            route=route,
            module_id=module_id,
            service_method=service_method,
            action_class=action_class,
        )
    return build_disabled_live_execution_adapter_contract(
        method=method,
        route=route,
        module_id=module_id,
        service_method=service_method,
        action_class=action_class,
    )


def build_disabled_live_execution_intent(
    *,
    method: str,
    route: str,
    module_id: str,
    identity_key: str,
    identity_value: str | None,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission | str,
    service_method: str,
    actor_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
    blockers: Sequence[AdminApiLiveAdmissionBlocker],
    live_execution_state: AdminApiLiveExecutionServiceState,
) -> dict[str, Any]:
    """Return the disabled command-to-execution intent evidence.

    This envelope describes the backend-owned execution intent that must be
    admitted before a future live adapter may submit anything. It is evidence
    only; it does not expose create, cancel, submit, or execute behavior.
    """

    adapter_reference = f"AdminApiCommandService.{service_method}"
    return {
        "required": True,
        "prepared": False,
        "backend_owned": True,
        "route_bound": True,
        "payload_bound": True,
        "idempotency_bound": True,
        "executable": False,
        "status": live_execution_state.status,
        "source": live_execution_state.source,
        "missing_reason": live_execution_state.missing_reason,
        "module_id": module_id,
        "route": route,
        "method": method,
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": action_class,
        "required_permission": required_permission,
        "service_method": service_method,
        "adapter_reference": adapter_reference,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "operator_intent": operator_intent,
        "payload_hash": payload_hash,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_exchange_submitted": False,
        "blockers": list(blockers),
        "evidence": [
            "Execution intent is owned by backend command admission.",
            "Payload hash, idempotency key, actor, and operator intent are bound.",
            "Live execution service remains disabled before adapter invocation.",
        ],
        "detail": (
            f"{method} {route} produced a disabled execution intent for "
            f"{adapter_reference}; no live adapter may execute while "
            f"{live_execution_state.missing_reason or LIVE_EXECUTION_DISABLED_REASON} "
            "is present."
        ),
    }
