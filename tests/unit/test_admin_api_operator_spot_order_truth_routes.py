from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from api.v1.routes import orders as order_routes
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandResponse,
    AdminLiveAdmissionDecisionEvidence,
    CancelOrderRequest,
)
from application.admin_api.operator_spot_order_truth_service import (
    SpotOrderTruthGoalRecord,
)
from application.admin_api.operator_spot_order_truth_service_runtime import (
    SpotOrderTruthExecutionPosture,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    AdminApiRole,
)


CLIENT_ORDER_ID = "11111111-1111-4111-8111-111111111111"
REQUEST_CORRELATION_ID = "22222222-2222-4222-8222-222222222222"


def _record(**updates) -> SpotOrderTruthGoalRecord:
    record = SpotOrderTruthGoalRecord(
        goal_id="operator_spot_order_truth_and_exact_cancel_reconcile_v1",
        revision=2,
        cycles_used=0,
        active_cycle_number=None,
        last_action=None,
        last_target_client_order_id=None,
        last_outcome="NOT_RUN",
        diagnostic_code="operator_spot_order_truth_not_refreshed",
        category_attempts={
            "api_key_permissions": 0,
            "portfolio_catalog": 0,
            "spot_order_catalog": 0,
        },
        page_count=0,
        order_count=0,
        portfolio_id_sha256=None,
        evidence_sha256=None,
        cancel_outcome="NOT_RUN",
        cancel_exchange_invoked=None,
        cancel_target_client_order_id=None,
        cancel_exchange_order_id_sha256=None,
        correlation_id=None,
        audit_id=None,
        refreshed_at=None,
        updated_at="2026-07-26T00:00:00Z",
    )
    return replace(record, **updates)


def _order() -> dict:
    return {
        "client_order_id": CLIENT_ORDER_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "OPEN",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "size": "0.0001",
        "limit_price": "100000",
        "filled_size": "0",
        "created_at": "2026-07-26T00:00:00Z",
        "updated_at": "2026-07-26T00:00:01Z",
        "observed_at": "2026-07-26T00:00:02Z",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "exchange_order_id_sha256": "c" * 64,
        "authoritatively_nonterminal": True,
        "cancel_eligible": True,
    }


class _Service:
    def __init__(self) -> None:
        self.record = _record()
        self.historical = _record(
            revision=3,
            cycles_used=1,
            last_action="REFRESH_CATALOG",
            last_outcome="SUCCEEDED",
            diagnostic_code="operator_spot_order_truth_catalog_refreshed",
            category_attempts={
                "api_key_permissions": 1,
                "portfolio_catalog": 1,
                "spot_order_catalog": 1,
            },
            page_count=1,
            order_count=1,
            correlation_id=REQUEST_CORRELATION_ID,
            audit_id="33333333-3333-4333-8333-333333333333",
        )
        self.calls: list[tuple] = []

    def read_goal(self):
        return self.record

    def list_orders(self, **kwargs):
        return {
            "filters": {
                "product_id": kwargs["product_id"],
                "order_status": kwargs["order_status"],
            },
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [_order()],
        }

    def get_order(self, client_order_id):
        return _order() if client_order_id == CLIENT_ORDER_ID else None

    def read_cycle_result(self, *, correlation_id, actor_id):
        if (
            correlation_id == REQUEST_CORRELATION_ID
            and actor_id == "operator-1"
        ):
            return True, True, self.historical
        return False, False, None

    def refresh_catalog(self, *, context):
        self.calls.append(("REFRESH_CATALOG", context))
        self.record = replace(
            self.historical,
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
        )
        return self.record

    def reconcile_exact(self, *, context, client_order_id):
        self.calls.append(("RECONCILE_EXACT", context, client_order_id))
        self.record = replace(
            self.historical,
            last_action="RECONCILE_EXACT",
            last_target_client_order_id=client_order_id,
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
        )
        return self.record

def _client(monkeypatch, *, roles=None):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED",
        "1",
    )
    service = _Service()
    app = FastAPI()
    app.include_router(order_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=roles or [AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    app.dependency_overrides[
        order_routes.get_operator_spot_order_truth_service
    ] = lambda: service
    app.dependency_overrides[
        order_routes.get_operator_spot_order_truth_read_repository
    ] = lambda: service
    monkeypatch.setattr(
        order_routes,
        "get_operator_spot_order_truth_execution_posture",
        lambda: SpotOrderTruthExecutionPosture(
            ready=True,
            diagnostic_code=(
                "operator_spot_order_truth_execution_posture_ready"
            ),
        ),
    )
    return TestClient(app), service


def _refresh_body(revision: int = 2) -> dict:
    return {
        "expected_revision": revision,
        "authorize_one_no_retry_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_one": True,
        "acknowledge_unknown_read_fails_closed": True,
    }


def test_spot_truth_list_detail_and_result_are_call_free(monkeypatch):
    client, _service = _client(monkeypatch)

    listed = client.get(
        "/api/v1/spot/order-operations",
        params={
            "product_id": "BTC-USDC",
            "order_status": "OPEN",
            "limit": 25,
            "offset": 0,
        },
    )
    detail = client.get(
        f"/api/v1/spot/order-operations/{CLIENT_ORDER_ID}"
    )
    predecessor_detail = client.get(
        "/api/v1/spot/order-operations/legacy-admin-root-order"
    )
    result = client.get(
        "/api/v1/spot/order-operations/mutation-results/"
        f"{REQUEST_CORRELATION_ID}"
    )

    assert listed.status_code == 200
    assert listed.json()["page_load_coinbase_calls"] == 0
    assert listed.json()["items"][0]["client_order_id"] == CLIENT_ORDER_ID
    assert listed.json()["items"][0].get("order_id") is None
    assert listed.json()["authority"]["portfolio_profile_alias"] == "Test"
    assert detail.status_code == 200
    assert detail.json()["found"] is True
    assert detail.json()["page_load_coinbase_calls"] == 0
    assert "RECONCILE_EXACT" in detail.json()["authority"]["allowed_actions"]
    assert predecessor_detail.status_code == 200
    assert predecessor_detail.json()["client_order_id"] == (
        "legacy-admin-root-order"
    )
    assert predecessor_detail.json()["found"] is False
    assert predecessor_detail.json()["order"] is None
    assert predecessor_detail.json()["authority"]["allowed_actions"] == []
    assert predecessor_detail.json()["page_load_coinbase_calls"] == 0
    assert result.status_code == 200
    assert result.json()["found"] is True
    assert result.json()["terminal"] is True
    assert result.json()["result"]["allowed_actions"] == []


def test_spot_refresh_and_reconcile_forward_explicit_one_cycle_authority(
    monkeypatch,
):
    client, service = _client(monkeypatch)
    refresh = client.post(
        "/api/v1/spot/order-operations/refresh",
        headers={
            "Idempotency-Key": "refresh-1",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "refresh_spot_order_catalog",
        },
        json=_refresh_body(),
    )
    assert refresh.status_code == 200
    assert service.calls[0][0] == "REFRESH_CATALOG"
    assert (
        service.calls[0][1]
        .acknowledge_cycle_is_goal_global_and_limited_to_one
        is True
    )

    client, service = _client(monkeypatch)
    reconcile = client.post(
        f"/api/v1/spot/order-operations/{CLIENT_ORDER_ID}/reconciliation",
        headers={
            "Idempotency-Key": "reconcile-1",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "reconcile_exact_spot_order",
        },
        json=_refresh_body(),
    )
    assert reconcile.status_code == 200
    assert service.calls[0][0] == "RECONCILE_EXACT"
    assert service.calls[0][2] == CLIENT_ORDER_ID


def test_spot_truth_viewer_can_read_but_cannot_mutate(monkeypatch):
    client, service = _client(monkeypatch, roles=[AdminApiRole.VIEWER])

    listed = client.get("/api/v1/spot/order-operations")
    refresh = client.post(
        "/api/v1/spot/order-operations/refresh",
        headers={
            "Idempotency-Key": "viewer-refresh",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "refresh_spot_order_catalog",
        },
        json=_refresh_body(),
    )

    assert listed.status_code == 200
    assert listed.json()["authority"]["allowed_actions"] == []
    assert refresh.status_code == 403
    assert service.calls == []


def test_spot_truth_feature_flag_fails_closed(monkeypatch):
    client, service = _client(monkeypatch)
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED",
        "0",
    )
    assert client.get("/api/v1/spot/order-operations").status_code == 503

    assert service.calls == []


def test_goal12_has_no_dedicated_live_cancel_route(monkeypatch):
    client, _service = _client(monkeypatch)
    response = client.post(
        f"/api/v1/spot/order-operations/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "cancel-1",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "cancel_exact_spot_order",
        },
        json={},
    )

    assert response.status_code == 404
    assert any(
        route.path == "/orders/{client_order_id}/cancel"
        for route in order_routes.router.routes
    )


def test_existing_cancel_request_requires_strict_goal12_cycle_binding():
    binding = {
        "goal_id": (
            "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
        ),
        "expected_revision": 3,
        "expected_evidence_sha256": "a" * 64,
        "expected_portfolio_id_sha256": "b" * 64,
        "acknowledge_unknown_cancel_consumes_allowance": True,
    }
    request = CancelOrderRequest(
        reason="exact Goal 12 cancel",
        manual_live_acknowledgement=True,
        goal12_spot_order_truth=binding,
    )

    assert request.goal12_spot_order_truth is not None
    assert request.goal12_spot_order_truth.expected_revision == 3
    with pytest.raises(
        ValidationError,
        match="goal12_recovery_cancel_binding_conflict",
    ):
        CancelOrderRequest(
            goal12_spot_order_truth=binding,
            recovery_case_id=CLIENT_ORDER_ID,
            recovery_case_revision=1,
            recovery_plan_sha256="c" * 64,
        )


def test_existing_cancel_route_rejects_goal12_binding_when_feature_disabled(
    monkeypatch,
):
    client, _service = _client(monkeypatch)
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED",
        "0",
    )
    client.app.dependency_overrides[
        order_routes.get_command_service
    ] = object
    for dependency in (
        order_routes.get_idempotency_store,
        order_routes.get_audit_store,
        order_routes.get_approval_store,
        order_routes.get_cap_guard_store,
        order_routes.get_reconciliation_store,
        order_routes.get_live_execution_service,
    ):
        client.app.dependency_overrides[dependency] = object
    client.app.dependency_overrides[
        order_routes.get_operator_spot_recovery_cancel_repository
    ] = lambda: (lambda: None)
    client.app.dependency_overrides[
        order_routes.get_operator_spot_order_truth_cancel_repository_factory
    ] = lambda: (
        lambda: pytest.fail("disabled Goal 12 must not construct its ledger")
    )
    monkeypatch.setattr(
        order_routes,
        "_execute_idempotent_command",
        lambda **_kwargs: pytest.fail(
            "disabled Goal 12 must not enter command admission"
        ),
    )

    response = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "disabled-goal12-cancel",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "cancel_exact_goal12_spot_order",
        },
        json={
            "reason": "disabled Goal 12 binding",
            "manual_live_acknowledgement": True,
            "goal12_spot_order_truth": {
                "goal_id": (
                    "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
                ),
                "expected_revision": 3,
                "expected_evidence_sha256": "a" * 64,
                "expected_portfolio_id_sha256": "b" * 64,
                "acknowledge_unknown_cancel_consumes_allowance": True,
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "operator_spot_order_truth_disabled"


def test_disabled_goal12_routes_do_not_construct_repository_or_service(
    monkeypatch,
):
    import database.operator_spot_order_truth as repository_module

    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED",
        raising=False,
    )
    monkeypatch.setattr(
        repository_module,
        "get_default_operator_spot_order_truth_repository",
        lambda: pytest.fail(
            "disabled Goal 12 must not construct its repository"
        ),
    )
    monkeypatch.setattr(
        order_routes,
        "get_default_operator_spot_order_truth_service",
        lambda: pytest.fail(
            "disabled Goal 12 must not construct its service"
        ),
    )
    app = FastAPI()
    app.include_router(order_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="operator-1",
        roles=[AdminApiRole.ADMIN, AdminApiRole.TRADER],
    )
    client = TestClient(app)

    list_response = client.get("/api/v1/spot/order-operations")
    refresh_response = client.post(
        "/api/v1/spot/order-operations/refresh",
        headers={
            "Idempotency-Key": "disabled-refresh",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "refresh_spot_order_truth",
        },
        json={
            "expected_revision": 0,
            "authorize_one_no_retry_cycle": True,
            "acknowledge_cycle_is_goal_global_and_limited_to_one": True,
            "acknowledge_unknown_read_fails_closed": True,
        },
    )

    assert list_response.status_code == 503
    assert list_response.json()["detail"] == (
        "operator_spot_order_truth_disabled"
    )
    assert refresh_response.status_code == 503
    assert refresh_response.json()["detail"] == (
        "operator_spot_order_truth_disabled"
    )


def test_existing_cancel_route_owns_goal12_claim_and_exact_sdk_boundary(
    monkeypatch,
):
    client, _service = _client(monkeypatch)
    portfolio_id = "44444444-4444-4444-8444-444444444444"
    portfolio_hash = hashlib.sha256(
        portfolio_id.encode("utf-8")
    ).hexdigest()
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        portfolio_id,
    )
    exchange_order_id = "exchange-order-goal12"
    exchange_hash = hashlib.sha256(
        exchange_order_id.encode("utf-8")
    ).hexdigest()
    calls: list[tuple] = []

    class Goal12Repository:
        def __init__(self):
            self.terminal = None

        def get_order(self, client_order_id):
            assert client_order_id == CLIENT_ORDER_ID
            return {
                **_order(),
                "exchange_order_id_sha256": exchange_hash,
            }

        def claim_cancel(self, **kwargs):
            calls.append(("claim", kwargs))
            assert kwargs["expected_evidence_sha256"] == "a" * 64
            assert (
                kwargs["expected_portfolio_id_sha256"]
                == portfolio_hash
            )
            assert len(kwargs["payload_sha256"]) == 64
            if kwargs["context"].idempotency_key == "goal12-pending":
                raise ValueError(
                    "operator_spot_order_truth_cancel_request_pending"
                )
            if self.terminal is not None:
                return self.terminal, "goal12-claim-1", True
            return (
                _record(
                    revision=3,
                    cycles_used=1,
                    last_outcome="SUCCEEDED",
                    evidence_sha256="a" * 64,
                    portfolio_id_sha256=portfolio_hash,
                    cancel_outcome="CLAIMED",
                ),
                "goal12-claim-1",
                False,
            )

        def mark_cancel_exchange_invoked(self, *, claim_id):
            calls.append(("sdk_boundary", claim_id))

        def release_cancel_before_exchange(self, *, claim_id):
            raise AssertionError(
                f"admitted exact boundary unexpectedly released {claim_id}"
            )

        def restore_cancel_before_sdk(self, *, claim_id):
            calls.append(("restore_pre_sdk", claim_id))
            return _record(
                revision=4,
                cycles_used=1,
                last_outcome="SUCCEEDED",
                evidence_sha256="a" * 64,
                portfolio_id_sha256=portfolio_hash,
                cancel_outcome="NOT_RUN",
                cancel_exchange_invoked=None,
                correlation_id=(
                    "77777777-7777-4777-8777-777777777777"
                ),
                audit_id="33333333-3333-4333-8333-333333333333",
            )

        def finish_cancel(self, *, claim_id, execution):
            calls.append(("finish", claim_id, execution.outcome))
            self.terminal = _record(
                revision=4,
                cycles_used=1,
                last_outcome="SUCCEEDED",
                evidence_sha256="a" * 64,
                portfolio_id_sha256=portfolio_hash,
                cancel_outcome=execution.outcome,
                cancel_exchange_invoked=True,
                cancel_target_client_order_id=CLIENT_ORDER_ID,
                cancel_exchange_order_id_sha256=exchange_hash,
                correlation_id=REQUEST_CORRELATION_ID,
                audit_id="33333333-3333-4333-8333-333333333333",
            )
            return self.terminal

    class CommandService:
        def cancel_order_by_client_order_id(
            self,
            command,
            *,
            before_cancel_sdk_call=None,
            expected_goal12_exchange_order_id_sha256=None,
            expected_goal12_portfolio_id_sha256=None,
        ):
            if command.request.goal12_spot_order_truth is None:
                calls.append(("generic_command", command.client_order_id))
                return AdminApiCommandResponse(
                    status=AdminApiCommandStatus.ACCEPTED,
                    action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                    required_permission=AdminApiPermission.ORDER_CANCEL,
                    service_method="cancel_order_by_client_order_id",
                    message="sanitized predecessor cancel",
                    client_order_id=command.client_order_id,
                    correlation_id=command.envelope.correlation_id,
                    idempotency_key=command.envelope.idempotency_key,
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                )
            calls.append(("command", command.allow_live_execution))
            assert command.request.goal12_spot_order_truth is not None
            assert (
                expected_goal12_exchange_order_id_sha256
                == exchange_hash
            )
            assert (
                expected_goal12_portfolio_id_sha256
                == portfolio_hash
            )
            before_cancel_sdk_call()
            if command.request.reason == "synthetic final authority failure":
                return AdminApiCommandResponse(
                    status=AdminApiCommandStatus.REJECTED,
                    action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                    required_permission=AdminApiPermission.ORDER_CANCEL,
                    service_method="cancel_order_by_client_order_id",
                    message="fixed pre-SDK authority rejection",
                    client_order_id=command.client_order_id,
                    correlation_id=command.envelope.correlation_id,
                    idempotency_key=command.envelope.idempotency_key,
                    live_exchange_submitted=False,
                    live_coinbase_orders_ran=False,
                    failure_stage="cancellation_pre_sdk_authority",
                )
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="sanitized",
                client_order_id=command.client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                data={
                    "portfolio_scope": {
                        "expected_portfolio_id": portfolio_id,
                        "observed_portfolio_id": portfolio_id,
                        "portfolio_id": portfolio_id,
                    },
                    "cancellation_readback": {
                        "canonical_cancel_explicitly_rejected": False,
                        "terminal_status_proven": True,
                        "authoritative_status": "CANCELLED",
                        "authoritative_readback": {
                            "exchange_order_id": exchange_order_id,
                        },
                        "canonical_cancel_evidence": {
                            "outcome": "succeeded",
                            "exchange_order_id": exchange_order_id,
                        },
                    }
                },
            )

    repository = Goal12Repository()
    client.app.dependency_overrides[
        order_routes.get_operator_spot_order_truth_cancel_repository_factory
    ] = lambda: (lambda: repository)
    client.app.dependency_overrides[
        order_routes.get_command_service
    ] = CommandService
    for dependency in (
        order_routes.get_idempotency_store,
        order_routes.get_audit_store,
        order_routes.get_approval_store,
        order_routes.get_cap_guard_store,
        order_routes.get_reconciliation_store,
        order_routes.get_live_execution_service,
    ):
        client.app.dependency_overrides[dependency] = object
    client.app.dependency_overrides[
        order_routes.get_operator_spot_recovery_cancel_repository
    ] = lambda: (lambda: None)

    def execute_admitted(**kwargs):
        return kwargs["command_runner_with_admission"](
            SimpleNamespace(
                allowed=True,
                admission_audit_id=(
                    "33333333-3333-4333-8333-333333333333"
                ),
            )
        )

    monkeypatch.setattr(
        order_routes,
        "_execute_idempotent_command",
        execute_admitted,
    )

    unbound = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "unbound-goal12-cancel",
            "X-Correlation-Id": (
                "55555555-5555-4555-8555-555555555555"
            ),
            "X-Operator-Intent": "cancel_exact_selected_spot_order",
        },
        json={
            "reason": "unbound generic cancel must fail closed",
            "manual_live_acknowledgement": True,
        },
    )

    assert unbound.status_code == 200
    assert unbound.json()["status"] == "rejected"
    assert unbound.json()["failure_stage"] == "goal12_binding_required"
    assert calls == []

    pending = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "goal12-pending",
            "X-Correlation-Id": (
                "88888888-8888-4888-8888-888888888888"
            ),
            "X-Operator-Intent": "cancel_exact_goal12_spot_order",
        },
        json={
            "reason": "read existing pending claim",
            "manual_live_acknowledgement": True,
            "goal12_spot_order_truth": {
                "goal_id": (
                    "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
                ),
                "expected_revision": 3,
                "expected_evidence_sha256": "a" * 64,
                "expected_portfolio_id_sha256": portfolio_hash,
                "acknowledge_unknown_cancel_consumes_allowance": True,
            },
        },
    )

    assert pending.status_code == 200
    assert pending.json()["status"] == "rejected"
    assert pending.json()["failure_stage"] == "goal12_claim_pending"
    assert pending.json()["live_coinbase_orders_ran"] is False
    assert [call[0] for call in calls] == ["claim"]
    calls.clear()

    pre_sdk = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "goal12-pre-sdk-authority",
            "X-Correlation-Id": (
                "77777777-7777-4777-8777-777777777777"
            ),
            "X-Operator-Intent": "cancel_exact_goal12_spot_order",
        },
        json={
            "reason": "synthetic final authority failure",
            "manual_live_acknowledgement": True,
            "goal12_spot_order_truth": {
                "goal_id": (
                    "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
                ),
                "expected_revision": 3,
                "expected_evidence_sha256": "a" * 64,
                "expected_portfolio_id_sha256": portfolio_hash,
                "acknowledge_unknown_cancel_consumes_allowance": True,
            },
        },
    )

    assert pre_sdk.status_code == 200
    assert pre_sdk.json()["status"] == "rejected"
    assert pre_sdk.json()["failure_stage"] == (
        "cancellation_pre_sdk_authority"
    )
    assert pre_sdk.json()["live_coinbase_orders_ran"] is False
    assert pre_sdk.json()["data"]["goal12_spot_order_truth"][
        "cancel_outcome"
    ] == "NOT_RUN"
    assert [call[0] for call in calls] == [
        "claim",
        "command",
        "sdk_boundary",
        "restore_pre_sdk",
    ]
    calls.clear()

    response = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "goal12-cancel-idempotency",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "cancel_exact_goal12_spot_order",
        },
        json={
            "reason": "operator selected exact Goal 12 order",
            "manual_live_acknowledgement": True,
            "goal12_spot_order_truth": {
                "goal_id": (
                    "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
                ),
                "expected_revision": 3,
                "expected_evidence_sha256": "a" * 64,
                "expected_portfolio_id_sha256": portfolio_hash,
                "acknowledge_unknown_cancel_consumes_allowance": True,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["goal12_spot_order_truth"] == {
        "goal_id": (
            "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
        ),
        "revision": 4,
        "cycles_used": 1,
        "cancel_outcome": "ACCEPTED",
        "cancel_exchange_invoked": True,
        "cancel_exchange_order_id_sha256": exchange_hash,
        "correlation_id": REQUEST_CORRELATION_ID,
        "audit_id": "33333333-3333-4333-8333-333333333333",
        "replayed": False,
    }
    assert exchange_order_id not in response.text
    assert portfolio_id not in response.text
    assert (
        body["data"]["portfolio_scope"]["portfolio_id_sha256"]
        == portfolio_hash
    )
    assert (
        body["data"]["cancellation_readback"][
            "authoritative_readback"
        ]["exchange_order_id_sha256"]
        == exchange_hash
    )
    assert (
        body["data"]["cancellation_readback"][
            "canonical_cancel_evidence"
        ]["exchange_order_id_sha256"]
        == exchange_hash
    )
    assert [call[0] for call in calls] == [
        "claim",
        "command",
        "sdk_boundary",
        "finish",
    ]

    replay = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers={
            "Idempotency-Key": "goal12-cancel-idempotency",
            "X-Correlation-Id": REQUEST_CORRELATION_ID,
            "X-Operator-Intent": "cancel_exact_goal12_spot_order",
        },
        json={
            "reason": "operator selected exact Goal 12 order",
            "manual_live_acknowledgement": True,
            "goal12_spot_order_truth": {
                "goal_id": (
                    "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
                ),
                "expected_revision": 3,
                "expected_evidence_sha256": "a" * 64,
                "expected_portfolio_id_sha256": portfolio_hash,
                "acknowledge_unknown_cancel_consumes_allowance": True,
            },
        },
    )

    assert replay.status_code == 200
    assert replay.json()["data"]["goal12_spot_order_truth"]["replayed"] is True
    assert replay.json()["audit_id"] is None
    assert replay.json()["data"]["goal12_spot_order_truth"]["audit_id"] == (
        "33333333-3333-4333-8333-333333333333"
    )
    assert replay.json()["live_coinbase_orders_ran"] is False
    assert exchange_order_id not in replay.text
    assert [call[0] for call in calls] == [
        "claim",
        "command",
        "sdk_boundary",
        "finish",
        "claim",
    ]

    predecessor = client.post(
        "/api/v1/orders/legacy-admin-root-order/cancel",
        headers={
            "Idempotency-Key": "predecessor-cancel-idempotency",
            "X-Correlation-Id": (
                "66666666-6666-4666-8666-666666666666"
            ),
            "X-Operator-Intent": "cancel_exact_selected_spot_order",
        },
        json={
            "reason": "predecessor generic cancel remains available",
            "manual_live_acknowledgement": True,
        },
    )

    assert predecessor.status_code == 200
    assert predecessor.json()["status"] == "accepted"
    assert calls[-1] == (
        "generic_command",
        "legacy-admin-root-order",
    )


def test_postgresql_cancel_replay_gets_unique_route_audit_once(
    monkeypatch,
    tmp_path,
):
    client, _service = _client(monkeypatch)
    portfolio_id = "44444444-4444-4444-8444-444444444444"
    portfolio_hash = hashlib.sha256(
        portfolio_id.encode("utf-8")
    ).hexdigest()
    exchange_hash = hashlib.sha256(b"exchange-order-goal12").hexdigest()
    stored_admission_audit = "stored-goal12-admission-audit"
    route_audit_store = FileAdminApiAuditStore(
        tmp_path / "goal12-audit.jsonl"
    )
    idempotency_store = FileIdempotencyStore(
        tmp_path / "goal12-idempotency.jsonl"
    )
    route_audit_store.append(
        AdminApiAuditEvent(
            audit_id=stored_admission_audit,
            actor_id="operator-1",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            permission=AdminApiPermission.ORDER_CANCEL,
            endpoint="POST /api/v1/orders/{client_order_id}/cancel",
            request_id="original-admission-request",
            operator_intent="cancel_exact_goal12_spot_order",
            idempotency_key="goal12-pg-replay",
            client_order_id=CLIENT_ORDER_ID,
            status=AdminApiCommandStatus.ACCEPTED,
            message="stored admission evidence",
        )
    )

    class ReplayRepository:
        def get_order(self, client_order_id):
            assert client_order_id == CLIENT_ORDER_ID
            return {
                **_order(),
                "exchange_order_id_sha256": exchange_hash,
            }

        def claim_cancel(self, **_kwargs):
            return (
                _record(
                    revision=4,
                    cycles_used=1,
                    last_outcome="SUCCEEDED",
                    evidence_sha256="a" * 64,
                    portfolio_id_sha256=portfolio_hash,
                    cancel_outcome="ACCEPTED",
                    cancel_exchange_invoked=True,
                    cancel_target_client_order_id=CLIENT_ORDER_ID,
                    cancel_exchange_order_id_sha256=exchange_hash,
                    correlation_id=REQUEST_CORRELATION_ID,
                    audit_id=stored_admission_audit,
                ),
                "stored-goal12-claim",
                True,
            )

    def admitted(**kwargs):
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
            admission_audit_present=True,
            admission_audit_id=stored_admission_audit,
            cap_guard_present=True,
            reconciliation_plan_present=True,
            live_execution_service_present=True,
            live_execution_service_status=(
                AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
            ),
            live_execution_service_missing_reason=None,
            browser_authority="backend_admin_api",
            blockers=[],
            detail="synthetic exact Goal 12 admission",
        )

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        portfolio_id,
    )
    monkeypatch.setattr(
        order_routes,
        "evaluate_command_live_admission",
        admitted,
    )
    client.app.dependency_overrides[
        order_routes.get_operator_spot_order_truth_cancel_repository_factory
    ] = lambda: (lambda: ReplayRepository())
    client.app.dependency_overrides[
        order_routes.get_idempotency_store
    ] = lambda: idempotency_store
    client.app.dependency_overrides[
        order_routes.get_audit_store
    ] = lambda: route_audit_store
    for dependency in (
        order_routes.get_approval_store,
        order_routes.get_cap_guard_store,
        order_routes.get_reconciliation_store,
        order_routes.get_live_execution_service,
    ):
        client.app.dependency_overrides[dependency] = object
    class UncalledCommandService:
        def cancel_order_by_client_order_id(self, *_args, **_kwargs):
            pytest.fail("PostgreSQL replay must not call the service")

    client.app.dependency_overrides[
        order_routes.get_command_service
    ] = UncalledCommandService
    client.app.dependency_overrides[
        order_routes.get_operator_spot_recovery_cancel_repository
    ] = lambda: (lambda: None)

    headers = {
        "Idempotency-Key": "goal12-pg-replay",
        "X-Correlation-Id": REQUEST_CORRELATION_ID,
        "X-Operator-Intent": "cancel_exact_goal12_spot_order",
    }
    payload = {
        "reason": "replay exact durable Goal 12 result",
        "manual_live_acknowledgement": True,
        "goal12_spot_order_truth": {
            "goal_id": (
                "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
            ),
            "expected_revision": 3,
            "expected_evidence_sha256": "a" * 64,
            "expected_portfolio_id_sha256": portfolio_hash,
            "acknowledge_unknown_cancel_consumes_allowance": True,
        },
    }
    first = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers=headers,
        json=payload,
    )
    second = client.post(
        f"/api/v1/orders/{CLIENT_ORDER_ID}/cancel",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200
    assert first.json()["data"]["goal12_spot_order_truth"]["replayed"] is True
    assert first.json()["data"]["goal12_spot_order_truth"]["audit_id"] == (
        stored_admission_audit
    )
    assert first.json()["audit_id"] != stored_admission_audit
    assert second.status_code == 200
    assert second.headers["X-Idempotency-Replayed"] == "true"
    assert second.json()["audit_id"] == first.json()["audit_id"]
    events = route_audit_store.read_recent(limit=10)
    assert len(events) == 2
    assert {event.audit_id for event in events} == {
        stored_admission_audit,
        first.json()["audit_id"],
    }
