from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import orders as order_routes
from application.admin_api.models import (
    AdminOrderFollowUpIntentAttachResponse,
    AdminOrderFollowUpIntentAuditBinding,
    AdminOrderFollowUpIntentEligibilityEvidence,
    AdminOrderFollowUpIntentItem,
    AdminOrderFollowUpIntentReadResponse,
)
from core.enums import AdminApiActionClass, AdminApiCommandStatus, AdminApiPermission


SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
ROOT_ID = "87aa9a2d-b015-4701-b7e5-63cc26360ad2"
INTENT_ID = "0ec90842-d875-4a7b-9eb1-333c7d618bb1"
CLAIM_ID = "6cf63093-4463-4855-bd7d-ab3ca1b6bbbe"
AUDIT_ID = "1f418e77-9e5e-49f3-861e-a30f942f38fb"
CORRELATION_ID = "corr-attach-follow-up-001"
IDEMPOTENCY_KEY = "idem-attach-follow-up-001"
OPERATOR_INTENT = "attach_single_follow_up_intent"


def _headers(*, roles: str = "trader", include_command: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator-test-001",
        "X-Admin-Roles": roles,
    }
    if include_command:
        headers.update(
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Correlation-Id": CORRELATION_ID,
                "X-Operator-Intent": OPERATOR_INTENT,
            }
        )
    return headers


def _eligibility(*, eligible: bool, slot_used: int) -> AdminOrderFollowUpIntentEligibilityEvidence:
    return AdminOrderFollowUpIntentEligibilityEvidence(
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        source_found=True,
        eligible=eligible,
        eligibility_status="eligible" if eligible else "attached",
        blockers=[] if eligible else ["follow_up_intent_already_attached"],
        source_status="OPEN",
        source_ownership_provenance="ADMIN_FILL_FOLLOW_UP",
        product_id="BTC-USDC",
        product_type="SPOT",
        module_id="spot_operations",
        source_is_child=True,
        source_authoritative_zero_fill=True,
        source_follow_up_child_absent=True,
        automatic_semantic_claim_absent=True,
        portfolio_scope_sha256="a" * 64,
        slot_limit=1,
        slot_used=slot_used,
        attachment_notional_usdc="0",
        submitted_notional_usdc="0",
        future_materialization_requires_fresh_authorization=True,
    )


def _intent() -> AdminOrderFollowUpIntentItem:
    return AdminOrderFollowUpIntentItem(
        follow_up_intent_id=INTENT_ID,
        claim_id=CLAIM_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        trigger="FILLED",
        intent_kind="single_on_full_fill",
        semantic_intent="EXIT",
        derived_follow_up_side="SELL",
        state="ATTACHED",
        intent_sha256="b" * 64,
        audit_id=AUDIT_ID,
        correlation_id=CORRELATION_ID,
        recorded_at="2026-07-18T12:00:00+00:00",
        future_materialization_requires_fresh_authorization=True,
    )


def _read_response(*, attached: bool) -> AdminOrderFollowUpIntentReadResponse:
    return AdminOrderFollowUpIntentReadResponse(
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        eligibility=_eligibility(eligible=not attached, slot_used=1 if attached else 0),
        follow_up_intent=_intent() if attached else None,
        read_only=True,
        local_state_mutated=False,
        live_coinbase_read_ran=False,
        live_coinbase_orders_ran=False,
        order_engine_follow_up_handler_called=False,
        follow_up_child_created=False,
        reconciliation_ran=False,
        exchange_state_mutated=False,
    )


def _attach_response(
    *,
    status: AdminApiCommandStatus = AdminApiCommandStatus.ACCEPTED,
    replayed: bool = False,
) -> AdminOrderFollowUpIntentAttachResponse:
    return AdminOrderFollowUpIntentAttachResponse(
        status=status,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="attach_order_follow_up_intent",
        message="Single follow-up intent attached.",
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        audit_id=AUDIT_ID,
        replayed=replayed,
        eligibility=_eligibility(eligible=False, slot_used=1),
        follow_up_intent=_intent(),
        audit_binding=AdminOrderFollowUpIntentAuditBinding(
            actor_id="operator-test-001",
            environment="local",
            portfolio_scope_sha256="a" * 64,
            source_client_order_id=SOURCE_ID,
            root_client_order_id=ROOT_ID,
            intent_sha256="b" * 64,
            claim_id=CLAIM_ID,
            terminal_result="ATTACHED",
        ),
        local_state_mutated=not replayed,
        live_coinbase_read_ran=False,
        live_coinbase_orders_ran=False,
        order_engine_follow_up_handler_called=False,
        follow_up_child_created=False,
        reconciliation_ran=False,
        exchange_state_mutated=False,
    )


@dataclass
class _FakeIntentService:
    attached: bool = False
    attach_calls: int = 0
    last_request: object | None = None
    last_context: object | None = None

    def read(self, *, source_client_order_id: str) -> AdminOrderFollowUpIntentReadResponse:
        assert source_client_order_id == SOURCE_ID
        return _read_response(attached=self.attached)

    def attach(
        self,
        *,
        source_client_order_id: str,
        request: object,
        context: object,
    ) -> AdminOrderFollowUpIntentAttachResponse:
        assert source_client_order_id == SOURCE_ID
        self.attach_calls += 1
        self.last_request = request
        self.last_context = context
        if self.attached:
            return _attach_response(
                status=AdminApiCommandStatus.REPLAYED,
                replayed=True,
            )
        self.attached = True
        return _attach_response()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakeIntentService]:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    service = _FakeIntentService()
    app = create_app()
    app.dependency_overrides[order_routes.get_order_follow_up_intent_service] = (
        lambda: service
    )
    return TestClient(app), service


@pytest.mark.regression
def test_follow_up_intent_routes_fail_closed_when_feature_is_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "0")
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    service = _FakeIntentService()
    app = create_app()
    app.dependency_overrides[order_routes.get_order_follow_up_intent_service] = (
        lambda: service
    )
    http = TestClient(app)

    read_response = http.get(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(include_command=False),
    )
    attach_response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(),
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True
        },
    )

    assert read_response.status_code == 503
    assert read_response.json()["code"] == "backend_unavailable"
    assert read_response.json()["message"] == "operator_follow_up_intent_disabled"
    assert attach_response.status_code == 503
    assert attach_response.json()["code"] == "backend_unavailable"
    assert attach_response.json()["message"] == "operator_follow_up_intent_disabled"
    assert service.attach_calls == 0


@pytest.mark.regression
def test_follow_up_intent_get_is_authoritative_no_live_readback(client):
    http, _service = client

    response = http.get(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(include_command=False),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_client_order_id"] == SOURCE_ID
    assert payload["root_client_order_id"] == ROOT_ID
    assert payload["eligibility"]["eligible"] is True
    assert payload["eligibility"]["slot_limit"] == 1
    assert payload["eligibility"]["attachment_notional_usdc"] == "0"
    assert payload["read_only"] is True
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["follow_up_child_created"] is False
    assert payload["exchange_state_mutated"] is False


@pytest.mark.regression
def test_follow_up_intent_post_forwards_only_acknowledgement_and_backend_context(client):
    http, service = client

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(),
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["required_permission"] == "order:create"
    assert payload["service_method"] == "attach_order_follow_up_intent"
    assert payload["source_client_order_id"] == SOURCE_ID
    assert payload["root_client_order_id"] == ROOT_ID
    assert payload["follow_up_intent"]["follow_up_intent_id"] == INTENT_ID
    assert payload["follow_up_intent"]["claim_id"] == CLAIM_ID
    assert payload["eligibility"]["slot_limit"] == 1
    assert payload["eligibility"]["slot_used"] == 1
    assert payload["eligibility"]["submitted_notional_usdc"] == "0"
    assert payload["follow_up_child_created"] is False
    assert payload["order_engine_follow_up_handler_called"] is False
    assert payload["reconciliation_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["exchange_state_mutated"] is False
    assert service.attach_calls == 1
    assert service.last_request.model_dump() == {
        "acknowledge_future_materialization_requires_fresh_authorization": True
    }
    assert service.last_context.idempotency_key == IDEMPOTENCY_KEY
    assert service.last_context.correlation_id == CORRELATION_ID
    assert service.last_context.operator_intent == OPERATOR_INTENT
    assert service.last_context.actor_id == "operator-test-001"


@pytest.mark.regression
@pytest.mark.parametrize("roles", ["viewer", "operator", "auditor"])
def test_follow_up_intent_post_requires_order_create_permission(client, roles: str):
    http, service = client

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(roles=roles),
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert service.attach_calls == 0


@pytest.mark.regression
@pytest.mark.parametrize(
    ("missing_header", "replacement"),
    [
        ("Idempotency-Key", None),
        ("X-Correlation-Id", None),
        ("X-Operator-Intent", None),
        ("X-Operator-Intent", "place_order"),
    ],
)
def test_follow_up_intent_post_requires_exact_command_headers(
    client,
    missing_header: str,
    replacement: str | None,
):
    http, service = client
    headers = _headers()
    if replacement is None:
        headers.pop(missing_header)
    else:
        headers[missing_header] = replacement

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=headers,
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True
        },
    )

    assert response.status_code in {400, 422}
    assert service.attach_calls == 0


@pytest.mark.regression
def test_follow_up_intent_same_key_replays_and_get_reads_one_durable_slot(client):
    http, service = client
    body = {
        "acknowledge_future_materialization_requires_fresh_authorization": True
    }

    first = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(),
        json=body,
    )
    replay = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(),
        json=body,
    )
    readback = http.get(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(include_command=False),
    )

    assert first.json()["status"] == "accepted"
    assert replay.json()["status"] == "replayed"
    assert replay.json()["replayed"] is True
    assert replay.json()["local_state_mutated"] is False
    assert readback.json()["eligibility"]["slot_used"] == 1
    assert readback.json()["follow_up_intent"]["follow_up_intent_id"] == INTENT_ID
    assert service.attach_calls == 2


@pytest.mark.regression
def test_follow_up_intent_body_forbids_browser_trading_fields(client):
    http, service = client

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent",
        headers=_headers(),
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "price": "1",
            "size": "1",
            "client_order_id": "browser-minted-child",
        },
    )

    assert response.status_code == 422
    assert service.attach_calls == 0
