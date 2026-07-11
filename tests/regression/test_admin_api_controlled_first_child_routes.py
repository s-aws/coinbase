"""Route-level contract coverage for the controlled first Admin child."""

from __future__ import annotations

import gc
import shutil
import uuid

import pytest

from application.admin_api.command_service import AdminApiCommandDependencies
from application.admin_api.models import (
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    AdminApiRole,
)
from tests.regression import test_admin_api_contract as contract


# Importing the full FastAPI contract graph is intentionally serial-only.
pytestmark = [pytest.mark.regression, pytest.mark.serial]


@pytest.fixture(autouse=True)
def _close_imported_contract_clients():
    yield
    while contract._ACTIVE_TEST_CLIENTS:
        client = contract._ACTIVE_TEST_CLIENTS.pop()
        try:
            client.app.dependency_overrides.clear()
        finally:
            client.close()
    gc.collect()
    while contract._ACTIVE_TEST_STORE_DIRS:
        shutil.rmtree(
            contract._ACTIVE_TEST_STORE_DIRS.pop(),
            ignore_errors=True,
        )


def _admit_controlled_stealth(**kwargs) -> AdminLiveAdmissionDecisionEvidence:
    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.PASSED,
        allowed=True,
        route=kwargs["route"],
        method=kwargs["method"],
        module_id=kwargs["module_id"],
        identity_key=kwargs["identity_key"],
        identity_value=kwargs["identity_value"],
        action_class=kwargs["action_class"],
        required_permission=kwargs["required_permission"],
        service_method=kwargs["service_method"],
        actor_id=kwargs["actor_id"],
        idempotency_key=kwargs["idempotency_key"],
        operator_intent=kwargs["operator_intent"],
        payload_hash=kwargs["payload_hash"],
        approval_snapshot_present=True,
        approval_snapshot_id="approval-controlled-child-route",
        admission_audit_present=True,
        admission_audit_id="audit-controlled-child-route",
        cap_guard_present=True,
        cap_guard_decision_id="cap-controlled-child-route",
        reconciliation_plan_present=True,
        reconciliation_plan_id="recon-controlled-child-route",
        live_execution_service_present=True,
        live_execution_service_status=(
            AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
        ),
        live_execution_service_missing_reason=None,
        browser_authority="backend_admin_api",
        blockers=[],
        detail="Exact controlled first-child route test evidence.",
    )


def _ids() -> tuple[str, str]:
    root_id = "11111111-1111-4111-8111-111111111111"
    child_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coinbase://filled-follow-up/{root_id}/{root_id}",
        )
    )
    return root_id, child_id


class _RecordingControlledService:
    def __init__(self) -> None:
        self.dependencies = AdminApiCommandDependencies()
        self.reveal_commands = []
        self.cancel_commands = []

    def reveal_stealth_order_by_stealth_order_id(self, command):
        self.reveal_commands.append(command)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="reveal_stealth_order_by_stealth_order_id",
            message="Controlled reveal reached the canonical fake service.",
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
        )

    def cancel_stealth_order_by_stealth_order_id(self, command):
        self.cancel_commands.append(command)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_stealth_order_by_stealth_order_id",
            message="Controlled cancel reached the canonical fake service.",
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
        )


def test_controlled_first_child_reveal_route_binds_proofs_rbac_and_idempotency(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes
    from api.v1.routes import stealth as stealth_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        _admit_controlled_stealth,
    )
    monkeypatch.setattr(
        stealth_routes,
        "_manual_order_admin_cap_guard_context",
        lambda **_kwargs: ("cap-controlled-child-route", "2.00"),
    )
    root_id, child_id = _ids()
    intent = "controlled_test_profile_first_child_reveal"
    headers = contract._headers(
        idempotency_key="idem-controlled-first-child-reveal-route",
        operator_intent=intent,
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "approved deterministic first child",
        "manual_live_acknowledgement": True,
        "expected_root_client_order_id": root_id,
        "controlled_limit_price": "102400.00",
        "controlled_batch_id": "controlled-ten-pair-route-test",
        "controlled_batch_slot": 1,
    }

    denied = client.post(
        f"/api/v1/stealth/orders/{child_id}/reveal",
        headers=contract._headers(
            idempotency_key="idem-controlled-reveal-viewer-denied",
            operator_intent=intent,
            roles=AdminApiRole.VIEWER.value,
        ),
        json=body,
    )
    assert denied.status_code == 403
    assert service.reveal_commands == []

    audit_count = len(client.admin_api_test_audit_store.read_recent())
    accepted = client.post(
        f"/api/v1/stealth/orders/{child_id}/reveal",
        headers=headers,
        json=body,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert len(service.reveal_commands) == 1
    command = service.reveal_commands[0]
    assert command.allow_live_execution is True
    assert command.request.expected_root_client_order_id == root_id
    assert command.request.controlled_batch_id == body["controlled_batch_id"]
    assert command.request.controlled_batch_slot == 1
    assert str(command.request.controlled_limit_price) == "102400.00"
    assert command.admin_approval_snapshot_id == "approval-controlled-child-route"
    assert command.admission_audit_id == "audit-controlled-child-route"
    assert command.admin_cap_guard_decision_id == "cap-controlled-child-route"
    assert command.admin_reconciliation_plan_id == "recon-controlled-child-route"
    assert str(command.admin_max_submitted_notional_usdc) == "2.00"
    assert len(client.admin_api_test_audit_store.read_recent()) == audit_count + 1

    replay = client.post(
        f"/api/v1/stealth/orders/{child_id}/reveal",
        headers=headers,
        json=body,
    )
    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert len(service.reveal_commands) == 1

    conflict = client.post(
        f"/api/v1/stealth/orders/{child_id}/reveal",
        headers=headers,
        json={**body, "controlled_batch_slot": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == AdminApiCommandStatus.CONFLICT.value
    assert len(service.reveal_commands) == 1


def test_controlled_first_child_cancel_route_binds_proofs_and_replays_once(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        _admit_controlled_stealth,
    )
    root_id, child_id = _ids()
    headers = contract._headers(
        idempotency_key="idem-controlled-first-child-cancel-route",
        operator_intent="controlled_test_profile_first_child_cancel",
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "cancel exact child before next root",
        "manual_live_acknowledgement": True,
        "expected_root_client_order_id": root_id,
        "controlled_batch_id": "controlled-ten-pair-route-test",
        "controlled_batch_slot": 1,
    }

    audit_count = len(client.admin_api_test_audit_store.read_recent())
    accepted = client.post(
        f"/api/v1/stealth/orders/{child_id}/cancel",
        headers=headers,
        json=body,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert len(service.cancel_commands) == 1
    command = service.cancel_commands[0]
    assert command.allow_live_execution is True
    assert command.request.expected_root_client_order_id == root_id
    assert command.request.controlled_batch_id == body["controlled_batch_id"]
    assert command.request.controlled_batch_slot == 1
    assert command.admin_approval_snapshot_id == "approval-controlled-child-route"
    assert command.admission_audit_id == "audit-controlled-child-route"
    assert command.admin_cap_guard_decision_id == "cap-controlled-child-route"
    assert command.admin_reconciliation_plan_id == "recon-controlled-child-route"
    assert len(client.admin_api_test_audit_store.read_recent()) == audit_count + 1

    replay = client.post(
        f"/api/v1/stealth/orders/{child_id}/cancel",
        headers=headers,
        json=body,
    )
    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert len(service.cancel_commands) == 1
