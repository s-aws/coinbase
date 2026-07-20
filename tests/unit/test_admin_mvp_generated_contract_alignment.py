"""Focused generated-contract alignment for legacy AdminMvpService reads."""

from application.admin_api.auth import ROLE_PERMISSIONS
from application.admin_api.models import AdminSessionResponse
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
    AdminMvpStore,
)
from core.enums import (
    AdminApiPermission,
    AdminApiRole,
    AdminApiSessionStatus,
)


def _context(*, roles: tuple[str, ...] = ("operator",)) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key="contract-alignment-key",
        correlation_id="contract-alignment-correlation",
        operator_intent="read generated contract evidence",
        actor_id="operator-contract-test",
        roles=roles,
    )


def _service() -> AdminMvpService:
    return AdminMvpService(
        dependencies=AdminMvpDependencies(),
        store=AdminMvpStore(),
    )


def test_admin_mvp_session_exactly_satisfies_generated_session_contract() -> None:
    payload = _service().get_read_response(
        "/api/v1/admin/session",
        {},
        _context(),
    ).body

    session = AdminSessionResponse.model_validate(payload)

    assert session.status == AdminApiSessionStatus.SIGNED_IN
    assert session.permissions == sorted(
        ROLE_PERMISSIONS[AdminApiRole.OPERATOR],
        key=lambda permission: permission.value,
    )
    assert payload == session.model_dump(mode="json")


def test_admin_mvp_spot_manual_command_exposes_backend_contract_authority() -> None:
    payload = _service().get_read_response(
        "/api/v1/spot/command-suite",
        {},
        _context(),
    ).body
    manual_command = next(
        command
        for command in payload["commands"]
        if command["route"] == "/api/v1/orders"
    )

    assert manual_command["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert manual_command["backend_owned"] is True
    assert manual_command["route_bound"] is True
