"""Route-level contract coverage for the controlled first Admin child."""

from __future__ import annotations

import gc
import shutil
import uuid

import pytest

from application.admin_api.command_service import AdminApiCommandDependencies
from application.admin_api.idempotency import make_payload_hash
from application.admin_api.models import (
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
    AdminOrderFillFollowUpChildCancelReadinessResponse,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
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


def _controlled_stealth_admission(
    *,
    allowed: bool,
    **kwargs,
) -> AdminLiveAdmissionDecisionEvidence:
    return AdminLiveAdmissionDecisionEvidence(
        status=(AdminApiGateStatus.PASSED if allowed else AdminApiGateStatus.BLOCKED),
        allowed=allowed,
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
        approval_snapshot_present=allowed,
        approval_snapshot_id=(
            "approval-controlled-child-route" if allowed else None
        ),
        admission_audit_present=allowed,
        admission_audit_id="audit-controlled-child-route" if allowed else None,
        cap_guard_present=allowed,
        cap_guard_decision_id="cap-controlled-child-route" if allowed else None,
        reconciliation_plan_present=allowed,
        reconciliation_plan_id="recon-controlled-child-route" if allowed else None,
        live_execution_service_present=True,
        live_execution_service_status=(
            AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
        ),
        live_execution_service_missing_reason=None,
        browser_authority="backend_admin_api" if allowed else "rejected",
        blockers=(
            []
            if allowed
            else [
                AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING,
                AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
                AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
                AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
            ]
        ),
        detail=(
            "Exact controlled first-child route test evidence."
            if allowed
            else "Controlled first-child proofs have not been installed."
        ),
    )


def _admit_controlled_stealth(**kwargs) -> AdminLiveAdmissionDecisionEvidence:
    return _controlled_stealth_admission(allowed=True, **kwargs)


class _ControlledAdmissionResolver:
    def __init__(self) -> None:
        self.required_proofs_installed = False

    def install_required_proofs(self) -> None:
        self.required_proofs_installed = True

    def __call__(self, **kwargs) -> AdminLiveAdmissionDecisionEvidence:
        return _controlled_stealth_admission(
            allowed=self.required_proofs_installed,
            **kwargs,
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
        self.root_cancel_commands = []
        self.reveal_manager_sdk_calls = 0
        self.cancel_manager_exchange_calls = 0
        self.root_cancel_unready_once = False
        self.root_cancel_unknown_once = False

    def reveal_stealth_order_by_stealth_order_id(self, command):
        self.reveal_commands.append(command)
        if command.allow_live_execution:
            self.reveal_manager_sdk_calls += 1
        return AdminApiCommandResponse(
            status=(
                AdminApiCommandStatus.ACCEPTED
                if command.allow_live_execution
                else AdminApiCommandStatus.NOT_IMPLEMENTED
            ),
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="reveal_stealth_order_by_stealth_order_id",
            message="Controlled reveal reached the canonical fake service.",
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            failure_stage=None if command.allow_live_execution else "approval",
        )

    def cancel_stealth_order_by_stealth_order_id(self, command):
        self.cancel_commands.append(command)
        if command.allow_live_execution:
            self.cancel_manager_exchange_calls += 1
        return AdminApiCommandResponse(
            status=(
                AdminApiCommandStatus.ACCEPTED
                if command.allow_live_execution
                else AdminApiCommandStatus.NOT_IMPLEMENTED
            ),
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_stealth_order_by_stealth_order_id",
            message="Controlled cancel reached the canonical fake service.",
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            failure_stage=None if command.allow_live_execution else "approval",
        )

    def cancel_order_fill_follow_up_child_by_root_client_order_id(self, command):
        self.root_cancel_commands.append(command)
        if self.root_cancel_unknown_once:
            self.root_cancel_unknown_once = False
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.REJECTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method=(
                    "cancel_order_fill_follow_up_child_by_root_client_order_id"
                ),
                message="Cancel boundary crossed; reconcile same key.",
                client_order_id=command.root_client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                failure_stage="cancellation_unknown",
                data={
                    "semantic_claim": {
                        "outcome": "unknown",
                        "reconciliation_required": True,
                    }
                },
            )
        if self.root_cancel_unready_once:
            self.root_cancel_unready_once = False
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.REJECTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method=(
                    "cancel_order_fill_follow_up_child_by_root_client_order_id"
                ),
                message="Transient root-scoped readiness blocker.",
                client_order_id=command.root_client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=False,
                live_coinbase_orders_ran=False,
                failure_stage="root_child_cancel_readiness",
            )
        return AdminApiCommandResponse(
            status=(
                AdminApiCommandStatus.ACCEPTED
                if command.admission_decision.allowed
                else AdminApiCommandStatus.NOT_IMPLEMENTED
            ),
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method=(
                "cancel_order_fill_follow_up_child_by_root_client_order_id"
            ),
            message="Root-scoped cancel reached the canonical fake service.",
            client_order_id=command.root_client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            failure_stage=(
                None if command.admission_decision.allowed else "approval"
            ),
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
    legacy_payload_hash = make_payload_hash(
        {
            "endpoint": f"POST /api/v1/stealth/orders/{child_id}/reveal",
            "actor_id": "operator-001",
            "roles": ["trader"],
            "operator_intent": intent,
            "body": body,
            "path_params": {"stealth_order_id": child_id},
        }
    )
    assert command.request.controlled_prior_preparation_sha256 is None
    assert command.admission_decision.payload_hash == legacy_payload_hash
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

    recovery_hash = "a" * 64
    recovery_body = {
        **body,
        "controlled_prior_preparation_sha256": recovery_hash,
    }
    recovery = client.post(
        f"/api/v1/stealth/orders/{child_id}/reveal",
        headers={
            **headers,
            "Idempotency-Key": "idem-controlled-first-child-recovery-route",
        },
        json=recovery_body,
    )
    assert recovery.status_code == 200
    assert len(service.reveal_commands) == 2
    recovery_command = service.reveal_commands[1]
    expected_recovery_payload_hash = make_payload_hash(
        {
            "endpoint": f"POST /api/v1/stealth/orders/{child_id}/reveal",
            "actor_id": "operator-001",
            "roles": ["trader"],
            "operator_intent": intent,
            "body": recovery_body,
            "path_params": {"stealth_order_id": child_id},
        }
    )
    assert recovery_command.request.controlled_prior_preparation_sha256 == (
        recovery_hash
    )
    assert recovery_command.admission_decision.payload_hash == (
        expected_recovery_payload_hash
    )
    assert expected_recovery_payload_hash != legacy_payload_hash


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


def test_root_scoped_child_cancel_route_is_source_disabled_before_dependencies(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    root_id, _child_id = _ids()
    intent = "controlled_v15_test_profile_first_child_cancel"
    headers = contract._headers(
        idempotency_key="idem-v15-root-child-cancel-route",
        operator_intent=intent,
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "cancel selected root deterministic first child",
        "manual_live_acknowledgement": True,
        "controlled_plan_sha256": "a" * 64,
    }
    route = f"/api/v1/orders/{root_id}/fill-follow-up/child-cancel"

    unauthenticated_headers = dict(headers)
    unauthenticated_headers.pop("Authorization")
    unauthenticated = client.post(
        route,
        headers=unauthenticated_headers,
        json=body,
    )
    assert unauthenticated.status_code == 401

    denied = client.post(
        route,
        headers=contract._headers(
            idempotency_key="idem-v15-root-child-cancel-viewer",
            operator_intent=intent,
            roles=AdminApiRole.VIEWER.value,
        ),
        json=body,
    )
    assert denied.status_code == 403
    assert service.root_cancel_commands == []

    stores = (
        client.admin_api_test_idempotency_store,
        client.admin_api_test_audit_store,
        client.admin_api_test_approval_store,
        client.admin_api_test_cap_guard_store,
        client.admin_api_test_reconciliation_store,
    )
    before = {
        store.path: store.path.read_bytes() if store.path.exists() else None
        for store in stores
    }

    def _unexpected_dependency():
        raise AssertionError("source-disabled child cancel resolved a live dependency")

    for dependency in (
        order_routes.get_command_service,
        order_routes.get_idempotency_store,
        order_routes.get_audit_store,
        order_routes.get_approval_store,
        order_routes.get_cap_guard_store,
        order_routes.get_reconciliation_store,
        order_routes.get_live_execution_service,
    ):
        client.app.dependency_overrides[dependency] = _unexpected_dependency

    response = client.post(route, headers=headers, json=body)
    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["client_order_id"] == root_id
    assert payload["correlation_id"] == "corr-001"
    assert payload["idempotency_key"] == "idem-v15-root-child-cancel-route"
    assert payload["live_exchange_submitted"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["failure_stage"] == "source_disabled_not_implemented"
    assert payload["data"] == {
        "source_disabled": True,
        "browser_authority": "display_only",
        "bff_authority": "source_disabled_not_forwarded",
        "local_state_mutated": False,
        "exchange_mutation_attempted": False,
    }
    assert service.root_cancel_commands == []
    assert {
        path: path.read_bytes() if path.exists() else None for path in before
    } == before


def test_root_scoped_child_cancel_readiness_never_promotes_historical_evidence(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes

    class _HistoricallyReadyService:
        @staticmethod
        def build_order_fill_follow_up_child_cancel_readiness(**kwargs):
            return AdminOrderFillFollowUpChildCancelReadinessResponse(
                root_client_order_id=kwargs["root_client_order_id"],
                found=True,
                ready=True,
                readiness_status="ready",
                backend_decision="allowed",
                blockers=[],
                browser_authority="display_and_submit_root_only",
                detail=(
                    "Historical service helper considered the sealed child "
                    "ready for exchange revalidation."
                ),
            )

    client = contract._client(monkeypatch)
    client.app.dependency_overrides[order_routes.get_command_service] = (
        _HistoricallyReadyService
    )
    root_id, _child_id = _ids()

    response = client.get(
        f"/api/v1/orders/{root_id}/fill-follow-up/child-cancel/readiness",
        headers=contract._headers(roles=AdminApiRole.AUDITOR.value),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["ready"] is False
    assert payload["readiness_status"] == "source_disabled"
    assert payload["backend_decision"] == "blocked"
    assert payload["blockers"] == ["source_disabled_not_implemented"]
    assert payload["browser_authority"] == "display_only"
    assert "historical local evidence" in payload["detail"].lower()
    assert "source-disabled" in payload["detail"].lower()


def test_installed_route_allowlist_cannot_be_bypassed_by_child_cancel_override(
    monkeypatch,
) -> None:
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    def _unexpected_admission(**_kwargs):
        raise AssertionError("source-disabled child cancel evaluated admission")

    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        _unexpected_admission,
    )
    root_id, _child_id = _ids()
    response = client.post(
        f"/api/v1/orders/{root_id}/fill-follow-up/child-cancel",
        headers=contract._headers(
            idempotency_key="idem-installed-route-child-cancel-blocked",
            operator_intent="controlled_v15_test_profile_first_child_cancel",
            roles=AdminApiRole.TRADER.value,
        ),
        json={
            "reason": "unsupported in installed operator runtime",
            "manual_live_acknowledgement": True,
            "controlled_plan_sha256": "a" * 64,
        },
    )

    assert response.status_code == 501
    assert response.json()["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert response.json()["failure_stage"] == "source_disabled_not_implemented"
    assert service.root_cancel_commands == []


def test_root_scoped_child_cancel_same_key_remains_fixed_source_disabled(
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
    root_id, _child_id = _ids()
    headers = contract._headers(
        idempotency_key="idem-v15-root-child-transient-unready",
        operator_intent="controlled_v15_test_profile_first_child_cancel",
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "cancel selected root deterministic first child",
        "manual_live_acknowledgement": True,
        "controlled_plan_sha256": "a" * 64,
    }
    route = f"/api/v1/orders/{root_id}/fill-follow-up/child-cancel"

    first = client.post(route, headers=headers, json=body)
    second = client.post(route, headers=headers, json=body)

    for response in (first, second):
        assert response.status_code == 501
        assert response.headers.get("X-Idempotency-Replayed") is None
        assert response.json()["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
        assert response.json()["live_exchange_submitted"] is False
        assert response.json()["failure_stage"] == "source_disabled_not_implemented"
    assert service.root_cancel_commands == []


def test_root_scoped_child_cancel_never_enters_unknown_reconciliation(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    service.root_cancel_unknown_once = True
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        _admit_controlled_stealth,
    )
    root_id, _child_id = _ids()
    headers = contract._headers(
        idempotency_key="idem-v15-root-child-unknown-reconcile",
        operator_intent="controlled_v15_test_profile_first_child_cancel",
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "cancel_active_deterministic_first_child",
        "manual_live_acknowledgement": True,
        "controlled_plan_sha256": "a" * 64,
    }
    route = f"/api/v1/orders/{root_id}/fill-follow-up/child-cancel"

    first = client.post(route, headers=headers, json=body)
    second = client.post(route, headers=headers, json=body)

    assert first.status_code == 501
    assert second.status_code == 501
    assert first.json()["live_exchange_submitted"] is False
    assert second.json()["live_exchange_submitted"] is False
    assert first.json()["live_coinbase_orders_ran"] is False
    assert second.json()["live_coinbase_orders_ran"] is False
    assert service.root_cancel_unknown_once is True
    assert service.root_cancel_commands == []


def test_controlled_first_child_reveal_same_key_retries_once_after_proofs_install(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes
    from api.v1.routes import stealth as stealth_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    admission = _ControlledAdmissionResolver()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        admission,
    )
    monkeypatch.setattr(
        stealth_routes,
        "_manual_order_admin_cap_guard_context",
        lambda **_kwargs: ("cap-controlled-child-route", "2.00"),
    )
    root_id, child_id = _ids()
    headers = contract._headers(
        idempotency_key="idem-controlled-reveal-retry-after-proofs",
        operator_intent="controlled_test_profile_first_child_reveal",
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "approved deterministic first child",
        "manual_live_acknowledgement": True,
        "expected_root_client_order_id": root_id,
        "controlled_limit_price": "102400.00",
        "controlled_batch_id": "controlled-ten-pair-route-retry-test",
        "controlled_batch_slot": 1,
    }
    route = f"/api/v1/stealth/orders/{child_id}/reveal"

    blocked = client.post(route, headers=headers, json=body)

    assert blocked.status_code == 501
    assert blocked.json()["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert blocked.json()["admission_decision"]["allowed"] is False
    assert len(service.reveal_commands) == 1
    assert service.reveal_commands[0].allow_live_execution is False
    assert service.reveal_manager_sdk_calls == 0

    admission.install_required_proofs()
    accepted = client.post(route, headers=headers, json=body)

    assert accepted.status_code == 200
    assert accepted.headers.get("X-Idempotency-Replayed") is None
    assert accepted.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert accepted.json()["admission_decision"]["allowed"] is True
    assert len(service.reveal_commands) == 2
    assert service.reveal_commands[1].allow_live_execution is True
    assert service.reveal_manager_sdk_calls == 1

    replay = client.post(route, headers=headers, json=body)

    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert replay.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert len(service.reveal_commands) == 2
    assert service.reveal_manager_sdk_calls == 1


def test_controlled_first_child_cancel_same_key_retries_once_after_proofs_install(
    monkeypatch,
):
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    admission = _ControlledAdmissionResolver()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        admission,
    )
    root_id, child_id = _ids()
    headers = contract._headers(
        idempotency_key="idem-controlled-cancel-retry-after-proofs",
        operator_intent="controlled_test_profile_first_child_cancel",
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": "cancel exact child before next root",
        "manual_live_acknowledgement": True,
        "expected_root_client_order_id": root_id,
        "controlled_batch_id": "controlled-ten-pair-route-retry-test",
        "controlled_batch_slot": 1,
    }
    route = f"/api/v1/stealth/orders/{child_id}/cancel"

    blocked = client.post(route, headers=headers, json=body)

    assert blocked.status_code == 501
    assert blocked.json()["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert blocked.json()["admission_decision"]["allowed"] is False
    assert len(service.cancel_commands) == 1
    assert service.cancel_commands[0].allow_live_execution is False
    assert service.cancel_manager_exchange_calls == 0

    admission.install_required_proofs()
    accepted = client.post(route, headers=headers, json=body)

    assert accepted.status_code == 200
    assert accepted.headers.get("X-Idempotency-Replayed") is None
    assert accepted.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert accepted.json()["admission_decision"]["allowed"] is True
    assert len(service.cancel_commands) == 2
    assert service.cancel_commands[1].allow_live_execution is True
    assert service.cancel_manager_exchange_calls == 1

    replay = client.post(route, headers=headers, json=body)

    assert replay.status_code == 200
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert replay.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert len(service.cancel_commands) == 2
    assert service.cancel_manager_exchange_calls == 1


@pytest.mark.parametrize(
    ("route_suffix", "operator_intent", "commands_attr", "live_calls_attr"),
    [
        (
            "reveal",
            "generic_stealth_reveal",
            "reveal_commands",
            "reveal_manager_sdk_calls",
        ),
        (
            "cancel",
            "generic_stealth_cancel",
            "cancel_commands",
            "cancel_manager_exchange_calls",
        ),
    ],
)
def test_generic_stealth_intent_cannot_retry_controlled_cached_501(
    monkeypatch,
    route_suffix,
    operator_intent,
    commands_attr,
    live_calls_attr,
):
    from api.v1.routes import orders as order_routes

    client = contract._client(monkeypatch)
    service = _RecordingControlledService()
    admission = _ControlledAdmissionResolver()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: service
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        admission,
    )
    root_id, child_id = _ids()
    headers = contract._headers(
        idempotency_key=f"idem-generic-stealth-{route_suffix}-no-retry",
        operator_intent=operator_intent,
        roles=AdminApiRole.TRADER.value,
    )
    body = {
        "reason": f"generic stealth {route_suffix}",
        "manual_live_acknowledgement": True,
        "expected_root_client_order_id": root_id,
        "controlled_batch_id": "controlled-ten-pair-route-no-broadening-test",
        "controlled_batch_slot": 1,
    }
    if route_suffix == "reveal":
        body["controlled_limit_price"] = "102400.00"
    route = f"/api/v1/stealth/orders/{child_id}/{route_suffix}"

    blocked = client.post(route, headers=headers, json=body)
    assert blocked.status_code == 501
    assert len(getattr(service, commands_attr)) == 1
    assert getattr(service, live_calls_attr) == 0

    admission.install_required_proofs()
    replay = client.post(route, headers=headers, json=body)

    assert replay.status_code == 501
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert replay.json()["admission_decision"]["allowed"] is False
    assert len(getattr(service, commands_attr)) == 1
    assert getattr(service, live_calls_attr) == 0
