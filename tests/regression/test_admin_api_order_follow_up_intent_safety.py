"""Safety contracts for the operator follow-up-intent boundary.

These tests deliberately exercise only local, synthetic state.  They make no
Coinbase calls and do not depend on any operator database content.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import orders as order_routes
from application.admin_api.models import AdminOrderFollowUpIntentAttachRequest
from application.admin_api.operator_follow_up_intent import (
    ATTACH_SINGLE_FOLLOW_UP_INTENT,
    OperatorFollowUpIntentError,
    OperatorFollowUpIntentRequestContext,
    OperatorFollowUpIntentService,
)
from database.order_follow_up_intent import (
    FollowUpIntentEligibility,
    FollowUpIntentReadback,
    FollowUpIntentStoreConflict,
    OperatorFollowUpIntentRepository,
)


pytestmark = pytest.mark.regression


VALID_SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
INVALID_SOURCE_ID = "not-a-client-order-uuid"


def _headers(*, include_command: bool) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator-test-001",
        "X-Admin-Roles": "trader",
    }
    if include_command:
        headers.update(
            {
                "Idempotency-Key": "follow-up-safety-idempotency-key",
                "X-Correlation-Id": "follow-up-safety-correlation-id",
                "X-Operator-Intent": ATTACH_SINGLE_FOLLOW_UP_INTENT,
            }
        )
    return headers


def _missing_eligibility(source_client_order_id: str) -> FollowUpIntentEligibility:
    return FollowUpIntentEligibility(
        source_client_order_id=source_client_order_id,
        root_client_order_id=source_client_order_id,
        source_found=False,
        eligible=False,
        eligibility_status="blocked",
        blockers=("source_order_not_found",),
        source_status="UNKNOWN",
        source_ownership_provenance="UNKNOWN",
        product_id="UNKNOWN",
        product_type="UNKNOWN",
        source_is_child=False,
        source_authoritative_zero_fill=False,
        source_follow_up_child_absent=False,
        automatic_semantic_claim_absent=False,
        portfolio_scope_sha256="0" * 64,
        slot_used=0,
    )


class _MissingSourceRepository:
    def read(self, source_client_order_id: str) -> FollowUpIntentReadback:
        return FollowUpIntentReadback(
            eligibility=_missing_eligibility(source_client_order_id),
            record=None,
        )

    def attach(self, _command):
        raise FollowUpIntentStoreConflict("source_order_not_found")


class _NoopAuditStore:
    def append(self, event):
        return event.audit_id


@pytest.fixture
def missing_source_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    service = OperatorFollowUpIntentService(
        repository=_MissingSourceRepository(),
        audit_store=_NoopAuditStore(),
    )
    app = create_app()
    app.dependency_overrides[order_routes.get_order_follow_up_intent_service] = (
        lambda: service
    )
    return TestClient(app)


@pytest.mark.parametrize("method", ["get", "post"])
def test_follow_up_intent_path_rejects_non_uuid_client_order_id(
    missing_source_client: TestClient,
    method: str,
):
    """Malformed identities are validation errors, not repository lookups."""

    kwargs: dict[str, object] = {
        "headers": _headers(include_command=method == "post"),
    }
    if method == "post":
        kwargs["json"] = {
            "acknowledge_future_materialization_requires_fresh_authorization": True
        }

    response = getattr(missing_source_client, method)(
        f"/api/v1/orders/{INVALID_SOURCE_ID}/follow-up-intent",
        **kwargs,
    )

    assert response.status_code == 422


def test_follow_up_intent_get_returns_not_found_for_unknown_valid_uuid(
    missing_source_client: TestClient,
):
    response = missing_source_client.get(
        f"/api/v1/orders/{VALID_SOURCE_ID}/follow-up-intent",
        headers=_headers(include_command=False),
    )

    assert response.status_code == 404
    assert response.json()["message"] == "source_order_not_found"


def test_follow_up_intent_attach_returns_not_found_for_unknown_valid_uuid(
    missing_source_client: TestClient,
):
    """POST and GET expose the same absence semantics for a valid identity."""

    response = missing_source_client.post(
        f"/api/v1/orders/{VALID_SOURCE_ID}/follow-up-intent",
        headers=_headers(include_command=True),
        json={
            "acknowledge_future_materialization_requires_fresh_authorization": True
        },
    )

    assert response.status_code == 404
    assert response.json()["message"] == "source_order_not_found"


def test_service_translates_missing_attach_source_to_not_found(
    monkeypatch: pytest.MonkeyPatch,
):
    """Pin the service mapping independently of the HTTP error renderer."""

    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    service = OperatorFollowUpIntentService(
        repository=_MissingSourceRepository(),
        audit_store=_NoopAuditStore(),
    )

    with pytest.raises(OperatorFollowUpIntentError) as exc_info:
        service.attach(
            source_client_order_id=VALID_SOURCE_ID,
            request=AdminOrderFollowUpIntentAttachRequest(
                acknowledge_future_materialization_requires_fresh_authorization=True
            ),
            context=OperatorFollowUpIntentRequestContext(
                actor_id="operator-test-001",
                roles=("trader",),
                idempotency_key="follow-up-safety-idempotency-key",
                correlation_id="follow-up-safety-correlation-id",
                operator_intent=ATTACH_SINGLE_FOLLOW_UP_INTENT,
            ),
        )

    assert exc_info.value.code == "source_order_not_found"
    assert exc_info.value.http_status_code == 404


@dataclass
class _RecordingCursor:
    statements: list[str] = field(default_factory=list)

    def execute(self, query, _params=None) -> None:
        self.statements.append(" ".join(str(query).split()))

    def fetchone(self):
        # No intent row and no source order row.  That is enough to complete a
        # repository read without needing any synthetic private order data.
        return None


@dataclass
class _RecordingDatabase:
    cursor: _RecordingCursor = field(default_factory=_RecordingCursor)

    @contextmanager
    def get_cursor(self):
        yield self.cursor


def test_follow_up_intent_read_path_never_runs_schema_ddl():
    """A read endpoint must not create tables or indexes as a side effect."""

    database = _RecordingDatabase()
    repository = OperatorFollowUpIntentRepository(
        database,
        configured_spot_portfolio_id="11111111-2222-4333-8444-555555555555",
        schema="follow_up_read_safety_test",
    )

    result = repository.read(VALID_SOURCE_ID)

    assert result.eligibility.source_found is False
    ddl = [
        statement
        for statement in database.cursor.statements
        if statement.upper().startswith(("CREATE ", "ALTER ", "DROP "))
    ]
    assert ddl == []


def test_repository_rejects_non_uuid_source_before_database_access():
    database = _RecordingDatabase()
    repository = OperatorFollowUpIntentRepository(
        database,
        configured_spot_portfolio_id="11111111-2222-4333-8444-555555555555",
        schema="follow_up_read_safety_test",
    )

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.read(INVALID_SOURCE_ID)

    assert exc_info.value.code == "source_client_order_id_invalid"
    assert database.cursor.statements == []
