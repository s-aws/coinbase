"""Read-only Admin API contract for the operator follow-up operations queue.

All collaborators are synthetic.  The route must not construct a Coinbase
client, run eligibility reconciliation, or mutate local/exchange state.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import uuid

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import follow_up_operations as follow_up_operation_routes
from application.admin_api import command_runtime
from application.admin_api import operator_follow_up_materialization
from application.admin_api import operator_follow_up_materialization_runtime
from application.admin_api import operator_follow_up_operations
from application.admin_api.models import (
    AdminApiActor,
    AdminOrderFollowUpCurrentRequestActivity,
    AdminOrderFollowUpDurableLiveProofActivity,
    AdminOrderFollowUpDurableOperationActivity,
    AdminOrderFollowUpOperationItem,
    AdminOrderFollowUpOperationsQueueResponse,
)
from application.admin_api.operator_follow_up_operations import (
    OperatorFollowUpOperationsError,
    OperatorFollowUpOperationsService,
)
from application.admin_api.mvp_service import AdminMvpService
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiPermission,
    AdminApiRole,
    AdminOrderFollowUpOperationActionability,
    AdminOrderFollowUpOperationState,
    FollowUpAccountingEvidenceOrigin,
    FollowUpExchangeMutationState,
    FollowUpLiveProofEventState,
    FollowUpLiveProofOperationKind,
    FollowUpLiveProofTerminalOutcome,
    FollowUpMaterializationState,
    FollowUpReadAccountingState,
    FollowUpSdkMutationInvocationState,
    FollowUpTransportSubmissionState,
)
from database.order_follow_up_intent import (
    FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION,
    OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID,
    FollowUpIntentStoreUnavailable,
    FollowUpLiveProofOperationRecord,
    FollowUpLiveProofOperationSet,
    FollowUpOperationPageItem,
    FollowUpOperationsPage,
    OperatorFollowUpIntentRepository,
)
from tests.regression.test_admin_api_order_follow_up_intent_repository import (
    _RepositoryHarness,
    _attach_root_intent,
    repository_harness as _repository_harness,
)


repository_harness = _repository_harness


pytestmark = [pytest.mark.regression, pytest.mark.serial]


SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
ROOT_ID = "87aa9a2d-b015-4701-b7e5-63cc26360ad2"
INTENT_ID = "0ec90842-d875-4a7b-9eb1-333c7d618bb1"
CORRELATION_ID = "b80fe761-69e6-462b-9ccb-b40ed93b2ac7"
AUDIT_ID = "1f418e77-9e5e-49f3-861e-a30f942f38fb"


def _passive_current_request_activity(
) -> AdminOrderFollowUpCurrentRequestActivity:
    return AdminOrderFollowUpCurrentRequestActivity(
        sdk_mutation_invocation_state="NOT_INVOKED",
        transport_submission_state="NOT_SUBMITTED",
        exchange_mutation_state="NOT_MUTATED",
        read_accounting_state="EXACT",
        observed_read_count=0,
    )


def _empty_durable_activity() -> AdminOrderFollowUpDurableLiveProofActivity:
    return AdminOrderFollowUpDurableLiveProofActivity()


@pytest.fixture(autouse=True)
def _bootstrap_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")


def _headers(*, roles: str = "trader") -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "operator-follow-up-queue-test",
        "X-Admin-Roles": roles,
    }


def _response() -> AdminOrderFollowUpOperationsQueueResponse:
    item = AdminOrderFollowUpOperationItem(
        follow_up_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=None,
        product_id="BTC-USDC",
        source_status="FILLED",
        derived_follow_up_side="SELL",
        operation_state=(
            AdminOrderFollowUpOperationState.READY_FOR_MATERIALIZATION_AUTHORIZATION
        ),
        state_reason_code="source_full_fill_locally_consistent",
        blocker_codes=[],
        actionability=(
            AdminOrderFollowUpOperationActionability.MATERIALIZATION_REVIEW
        ),
        actionable=True,
        review_navigation_available=True,
        materialization_review_available=True,
        safe_closeout_review_available=False,
        required_permission=AdminApiPermission.ORDER_CREATE,
        actor_authorized=True,
        fresh_authoritative_revalidation_required=True,
        create_allowance_consumption_count=0,
        create_allowance_consumed=False,
        create_call_count=0,
        create_call_consumed=False,
        cancel_allowance_consumption_count=0,
        cancel_allowance_consumed=False,
        cancel_call_count=0,
        cancel_call_consumed=False,
        durable_live_proof_activity=_empty_durable_activity(),
        materialization_attempt_state=None,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        recorded_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
        detail_href=f"/orders/{SOURCE_ID}",
    )
    return AdminOrderFollowUpOperationsQueueResponse(
        filters={
            "product_id": "BTC-USDC",
            "state": (
                AdminOrderFollowUpOperationState.READY_FOR_MATERIALIZATION_AUTHORIZATION
            ),
            "actionability": (
                AdminOrderFollowUpOperationActionability.MATERIALIZATION_REVIEW
            ),
            "limit": 25,
            "offset": 0,
        },
        count=1,
        pagination={
            "limit": 25,
            "offset": 0,
            "returned_count": 1,
            "total_matching_count": 1,
            "next_offset": None,
            "has_more": False,
        },
        items=[item],
        current_request_activity=_passive_current_request_activity(),
    )


@dataclass
class _FakeQueueService:
    error: OperatorFollowUpOperationsError | None = None
    calls: int = 0
    kwargs: dict[str, object] | None = None

    def list_queue(self, **kwargs: object) -> AdminOrderFollowUpOperationsQueueResponse:
        self.calls += 1
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _response()


def _client(service: _FakeQueueService) -> TestClient:
    app = create_app()
    app.dependency_overrides[
        follow_up_operation_routes.get_follow_up_operations_service
    ] = lambda: service
    return TestClient(app)


def test_queue_route_forwards_typed_filters_once_and_returns_only_local_evidence():
    service = _FakeQueueService()
    client = _client(service)

    response = client.get(
        "/api/v1/follow-up-operations",
        params={
            "product_id": "BTC-USDC",
            "state": "ready_for_materialization_authorization",
            "actionability": "materialization_review",
            "limit": 25,
            "offset": 0,
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    assert service.calls == 1
    assert service.kwargs is not None
    actor = service.kwargs.pop("actor")
    assert isinstance(actor, AdminApiActor)
    assert actor.actor_id == "operator-follow-up-queue-test"
    assert service.kwargs == {
        "product_id": "BTC-USDC",
        "state": (
            AdminOrderFollowUpOperationState.READY_FOR_MATERIALIZATION_AUTHORIZATION
        ),
        "actionability": (
            AdminOrderFollowUpOperationActionability.MATERIALIZATION_REVIEW
        ),
        "limit": 25,
        "offset": 0,
    }
    payload = response.json()
    assert payload["filters"] == {
        "product_id": "BTC-USDC",
        "state": "ready_for_materialization_authorization",
        "actionability": "materialization_review",
        "limit": 25,
        "offset": 0,
    }
    assert payload["items"][0]["detail_href"] == f"/orders/{SOURCE_ID}"
    assert payload["read_only"] is True
    assert payload["local_sql_only"] is True
    assert payload["local_classification_only"] is True
    assert payload["local_state_mutated"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_create_call_count"] == 0
    assert payload["live_coinbase_cancel_call_count"] == 0
    assert payload["exchange_state_mutated"] is False
    assert payload["current_request_activity"] == {
        "accounting_scope": "current_request",
        "sdk_mutation_invocation_state": "NOT_INVOKED",
        "transport_submission_state": "NOT_SUBMITTED",
        "exchange_mutation_state": "NOT_MUTATED",
        "read_accounting_state": "EXACT",
        "observed_read_count": 0,
    }
    assert payload["items"][0]["durable_live_proof_activity"] == {
        "eligibility_read": None,
        "create": None,
        "reconciliation_read": None,
        "cancel": None,
    }
    assert payload["items"][0]["create_allowance_consumption_count"] == 0
    assert payload["items"][0]["create_allowance_consumed"] is False
    assert payload["items"][0]["cancel_allowance_consumption_count"] == 0
    assert payload["items"][0]["cancel_allowance_consumed"] is False


def test_queue_route_requires_audit_read_permission():
    service = _FakeQueueService()
    client = _client(service)
    client.app.dependency_overrides[
        follow_up_operation_routes.get_authenticated_actor
    ] = lambda: AdminApiActor(actor_id="permissionless", roles=[])

    response = client.get(
        "/api/v1/follow-up-operations",
        headers=_headers(),
    )

    assert response.status_code == 403
    assert service.calls == 0


def test_queue_route_rejects_unknown_filter_values_before_service_access():
    service = _FakeQueueService()
    response = _client(service).get(
        "/api/v1/follow-up-operations",
        params={"state": "browser_invented_state"},
        headers=_headers(),
    )

    assert response.status_code == 422
    assert service.calls == 0


@pytest.mark.parametrize(
    "query",
    [
        "state=awaiting_source_fill&state=blocked",
        "limit=25&limit=50",
        "browser_only_filter=ready",
    ],
)
def test_queue_route_rejects_duplicate_or_unknown_query_parameters(
    query: str,
):
    service = _FakeQueueService()
    response = _client(service).get(
        f"/api/v1/follow-up-operations?{query}",
        headers=_headers(),
    )

    assert response.status_code == 422
    assert service.calls == 0


def test_queue_route_withholds_repository_exception_text():
    service = _FakeQueueService(
        error=OperatorFollowUpOperationsError(
            code="follow_up_operations_evidence_unavailable",
            http_status_code=503,
        )
    )
    response = _client(service).get(
        "/api/v1/follow-up-operations",
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["message"] == (
        "follow_up_operations_evidence_unavailable"
    )
    assert response.json()["code"] == "backend_unavailable"
    assert "exception" not in response.text.lower()


def test_openapi_exposes_one_read_only_queue_contract():
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/follow-up-operations"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AdminOrderFollowUpOperationsQueueResponse"
    }
    assert "/api/v1/follow-up-operations" in schema["paths"]
    assert "post" not in schema["paths"]["/api/v1/follow-up-operations"]


def test_queue_is_registered_as_local_read_only_inventory_and_capability():
    inventory = next(
        item
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface == "GET /api/v1/follow-up-operations"
    )
    assert inventory.module_id == "spot_operations"
    assert inventory.action_class.value == "read_only"
    assert inventory.permission is AdminApiPermission.AUDIT_READ
    assert "local SQL" in inventory.parity_test
    assert "zero Coinbase" in inventory.parity_test
    assert "zero local" in inventory.parity_test

    capability = next(
        item
        for item in AdminMvpService._capability_items(object())
        if item["route"] == "/api/v1/follow-up-operations"
    )
    assert capability["module_id"] == "spot_operations"
    assert capability["method"] == "GET"
    assert capability["action_class"] == "read_only"
    assert capability["permission"] == "audit:read"
    assert capability["live_enabled"] is False
    assert capability["command_contract"] is False


def test_real_queue_factory_and_handler_never_construct_live_dependencies(
    monkeypatch: pytest.MonkeyPatch,
):
    repository = _EmptyRepository()

    def construction_bomb(*_args: object, **_kwargs: object):
        raise AssertionError("passive queue constructed a live dependency")

    monkeypatch.setattr(
        operator_follow_up_operations,
        "get_default_repository",
        lambda: repository,
    )
    monkeypatch.setattr(
        command_runtime,
        "load_admin_api_rest_client",
        construction_bomb,
    )
    monkeypatch.setattr(
        command_runtime,
        "get_admin_api_spot_market_reference",
        construction_bomb,
    )
    monkeypatch.setattr(
        operator_follow_up_materialization,
        "get_default_operator_follow_up_materialization_service",
        construction_bomb,
    )
    monkeypatch.setattr(
        operator_follow_up_materialization_runtime,
        "build_default_operator_follow_up_materialization_service",
        construction_bomb,
    )

    response = TestClient(create_app()).get(
        "/api/v1/follow-up-operations",
        headers=_headers(roles="viewer"),
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["local_state_mutated"] is False
    assert repository.calls == 1


def test_attempt_classification_is_exhaustive_and_preserves_allowance_accounting():
    expected = {
        "KNOWN_NOT_INVOKED": ("materialization_in_progress", "none", 0, 0),
        "CREATE_INVOCATION_STARTED": (
            "unknown_outcome",
            "safe_closeout_review",
            1,
            0,
        ),
        "CREATE_EXPLICITLY_REJECTED": ("blocked", "none", 1, 0),
        "CREATE_ACCEPTED_NONTERMINAL": (
            "materialized_active",
            "safe_closeout_review",
            1,
            0,
        ),
        "CREATE_ACCEPTED_TERMINAL": ("materialized_terminal", "none", 1, 0),
        "CREATE_UNKNOWN_CONSUMED": (
            "unknown_outcome",
            "safe_closeout_review",
            1,
            0,
        ),
        "CANCEL_INVOCATION_STARTED": ("unknown_outcome", "none", 1, 1),
        "CANCEL_NOT_REQUIRED_TERMINAL": (
            "materialized_terminal",
            "none",
            1,
            0,
        ),
        "CANCEL_EXPLICITLY_REJECTED": (
            "materialized_active",
            "none",
            1,
            1,
        ),
        "CANCEL_ACCEPTED_NONTERMINAL": (
            "materialized_active",
            "none",
            1,
            1,
        ),
        "CANCEL_ACCEPTED_TERMINAL": (
            "materialized_terminal",
            "none",
            1,
            1,
        ),
        "CANCEL_UNKNOWN_CONSUMED": ("unknown_outcome", "none", 1, 1),
    }

    assert set(FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION) == set(
        FollowUpMaterializationState
    )
    assert {
        state.value: (
            classification.operation_state,
            classification.actionability,
            classification.create_allowance_consumption_count,
            classification.cancel_allowance_consumption_count,
        )
        for state, classification in (
            FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION.items()
        )
    } == expected


@dataclass
class _EmptyRepository:
    calls: int = 0

    def list_operations(self, **_kwargs: object) -> FollowUpOperationsPage:
        self.calls += 1
        return FollowUpOperationsPage(items=(), total_matching_count=0)


@dataclass
class _OneItemRepository:
    item: FollowUpOperationPageItem

    def list_operations(self, **_kwargs: object) -> FollowUpOperationsPage:
        return FollowUpOperationsPage(
            items=(self.item,),
            total_matching_count=1,
        )


def _ready_page_item() -> FollowUpOperationPageItem:
    return FollowUpOperationPageItem(
        follow_up_intent_id=INTENT_ID,
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=None,
        product_id="BTC-USDC",
        source_status="FILLED",
        derived_follow_up_side="SELL",
        state="ready_for_materialization_authorization",
        state_reason_code="source_full_fill_locally_consistent",
        actionability="materialization_review",
        materialization_attempt_state=None,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        recorded_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
        live_proof_operations=FollowUpLiveProofOperationSet(
            eligibility_read=None,
            create=None,
            reconciliation_read=None,
            cancel=None,
        ),
    )


def _live_proof_record(
    *,
    operation_kind: FollowUpLiveProofOperationKind,
    event_state: FollowUpLiveProofEventState,
    outcome: FollowUpLiveProofTerminalOutcome | None,
    source_client_order_id: str = SOURCE_ID,
    root_client_order_id: str = ROOT_ID,
    follow_up_intent_id: str = INTENT_ID,
    materialization_id: str | None = None,
    child_client_order_id: str | None = None,
    sdk_state: FollowUpSdkMutationInvocationState = (
        FollowUpSdkMutationInvocationState.NOT_INVOKED
    ),
    transport_state: FollowUpTransportSubmissionState = (
        FollowUpTransportSubmissionState.NOT_SUBMITTED
    ),
    exchange_state: FollowUpExchangeMutationState = (
        FollowUpExchangeMutationState.NOT_MUTATED
    ),
    read_state: FollowUpReadAccountingState = FollowUpReadAccountingState.EXACT,
    observed_read_count: int | None = 0,
    evidence_origin: FollowUpAccountingEvidenceOrigin = (
        FollowUpAccountingEvidenceOrigin.EXPLICIT
    ),
) -> FollowUpLiveProofOperationRecord:
    return FollowUpLiveProofOperationRecord(
        event_id=str(uuid.uuid4()),
        goal_id=OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID,
        operation_kind=operation_kind.value,
        event_state=event_state.value,
        outcome=outcome.value if outcome is not None else None,
        diagnostic_code="follow_up_live_proof_synthetic",
        source_client_order_id=source_client_order_id,
        root_client_order_id=root_client_order_id,
        follow_up_intent_id=follow_up_intent_id,
        materialization_id=materialization_id,
        child_client_order_id=child_client_order_id,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        operation_idempotency_key_sha256="a" * 64,
        sdk_mutation_invocation_state=sdk_state.value,
        transport_submission_state=transport_state.value,
        exchange_mutation_state=exchange_state.value,
        read_accounting_state=read_state.value,
        observed_read_count=observed_read_count,
        accounting_evidence_origin=evidence_origin.value,
        external_call_started=(
            sdk_state is FollowUpSdkMutationInvocationState.INVOKED
        ),
        reported_read_count=observed_read_count or 0,
        individual_retry_count=0,
        authoritative_child_state=None,
        recorded_at="2026-07-19T00:00:00+00:00",
    )


def _attempt_page_item(
    state: FollowUpMaterializationState,
    live_proof_operations: FollowUpLiveProofOperationSet,
) -> FollowUpOperationPageItem:
    classification = FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION[state]
    child_id = "49a850b1-5a2e-4dbb-9125-b1cad4e2dc7d"
    return replace(
        _ready_page_item(),
        child_client_order_id=child_id,
        materialization_id="c17a9e86-7472-42d8-a2cf-eed38b2a7443",
        state=classification.operation_state,
        state_reason_code=classification.state_reason_code,
        actionability=classification.actionability,
        materialization_attempt_state=state.value,
        live_proof_operations=live_proof_operations,
    )


def test_service_projects_partial_explicit_and_conservative_legacy_activity():
    eligibility = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        observed_read_count=6,
    )
    create = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.CREATE,
        event_state=FollowUpLiveProofEventState.INVOCATION_STARTED,
        outcome=None,
        materialization_id="c17a9e86-7472-42d8-a2cf-eed38b2a7443",
        child_client_order_id="49a850b1-5a2e-4dbb-9125-b1cad4e2dc7d",
        sdk_state=FollowUpSdkMutationInvocationState.UNKNOWN,
        transport_state=FollowUpTransportSubmissionState.POSSIBLY_SUBMITTED,
        exchange_state=FollowUpExchangeMutationState.UNKNOWN,
        read_state=FollowUpReadAccountingState.UNKNOWN,
        observed_read_count=None,
        evidence_origin=FollowUpAccountingEvidenceOrigin.LEGACY_CONSERVATIVE,
    )
    item = _attempt_page_item(
        FollowUpMaterializationState.CREATE_INVOCATION_STARTED,
        FollowUpLiveProofOperationSet(
            eligibility_read=eligibility,
            create=create,
            reconciliation_read=None,
            cancel=None,
        ),
    )

    response = OperatorFollowUpOperationsService(
        _OneItemRepository(item)
    ).list_queue(
        actor=AdminApiActor(actor_id="operator-test", roles=[AdminApiRole.TRADER])
    )

    durable = response.items[0].durable_live_proof_activity
    assert durable.eligibility_read is not None
    assert durable.eligibility_read.observed_read_count == 6
    assert durable.eligibility_read.evidence_origin == "live_proof_journal"
    assert durable.create is not None
    assert durable.create.event_state is FollowUpLiveProofEventState.INVOCATION_STARTED
    assert durable.create.sdk_mutation_invocation_state is (
        FollowUpSdkMutationInvocationState.UNKNOWN
    )
    assert durable.create.observed_read_count is None
    assert durable.create.evidence_origin == "conservative_legacy_projection"
    assert response.current_request_activity.observed_read_count == 0


def test_service_projects_pre_sdk_blocked_create_without_safe_closeout_action():
    blocked_create = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.CREATE,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.BLOCKED,
        materialization_id="c17a9e86-7472-42d8-a2cf-eed38b2a7443",
        child_client_order_id="49a850b1-5a2e-4dbb-9125-b1cad4e2dc7d",
        sdk_state=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport_state=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange_state=FollowUpExchangeMutationState.NOT_MUTATED,
        read_state=FollowUpReadAccountingState.EXACT,
        observed_read_count=0,
    )
    item = replace(
        _attempt_page_item(
            FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED,
            FollowUpLiveProofOperationSet(
                eligibility_read=None,
                create=blocked_create,
                reconciliation_read=None,
                cancel=None,
            ),
        ),
        state="blocked",
        state_reason_code="create_blocked_before_sdk_invocation",
        actionability="none",
    )

    response = OperatorFollowUpOperationsService(
        _OneItemRepository(item)
    ).list_queue(
        actor=AdminApiActor(actor_id="operator-test", roles=[AdminApiRole.TRADER])
    )

    projected = response.items[0]
    assert projected.operation_state is AdminOrderFollowUpOperationState.BLOCKED
    assert projected.actionability is AdminOrderFollowUpOperationActionability.NONE
    assert projected.blocker_codes == ["create_blocked_before_sdk_invocation"]
    assert projected.review_navigation_available is False
    assert projected.safe_closeout_review_available is False
    assert projected.create_allowance_consumption_count == 1
    assert projected.durable_live_proof_activity.create is not None
    assert (
        projected.durable_live_proof_activity.create.terminal_outcome
        is FollowUpLiveProofTerminalOutcome.BLOCKED
    )


def test_service_rejects_safe_closeout_projection_for_pre_sdk_blocked_create():
    blocked_create = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.CREATE,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.BLOCKED,
        materialization_id="c17a9e86-7472-42d8-a2cf-eed38b2a7443",
        child_client_order_id="49a850b1-5a2e-4dbb-9125-b1cad4e2dc7d",
        sdk_state=FollowUpSdkMutationInvocationState.NOT_INVOKED,
        transport_state=FollowUpTransportSubmissionState.NOT_SUBMITTED,
        exchange_state=FollowUpExchangeMutationState.NOT_MUTATED,
        read_state=FollowUpReadAccountingState.EXACT,
        observed_read_count=0,
    )
    item = _attempt_page_item(
        FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED,
        FollowUpLiveProofOperationSet(
            eligibility_read=None,
            create=blocked_create,
            reconciliation_read=None,
            cancel=None,
        ),
    )

    with pytest.raises(OperatorFollowUpOperationsError) as exc_info:
        OperatorFollowUpOperationsService(_OneItemRepository(item)).list_queue(
            actor=AdminApiActor(
                actor_id="operator-test",
                roles=[AdminApiRole.TRADER],
            )
        )

    assert exc_info.value.code == "follow_up_operations_evidence_unavailable"


def test_service_projects_missing_unknown_create_proof_as_blocked_unproven():
    item = replace(
        _attempt_page_item(
            FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED,
            FollowUpLiveProofOperationSet(
                eligibility_read=None,
                create=None,
                reconciliation_read=None,
                cancel=None,
            ),
        ),
        state="blocked",
        state_reason_code="create_safe_closeout_evidence_unproven",
        actionability="none",
    )

    response = OperatorFollowUpOperationsService(
        _OneItemRepository(item)
    ).list_queue(
        actor=AdminApiActor(actor_id="operator-test", roles=[AdminApiRole.TRADER])
    )

    projected = response.items[0]
    assert projected.operation_state is AdminOrderFollowUpOperationState.BLOCKED
    assert projected.blocker_codes == ["create_safe_closeout_evidence_unproven"]
    assert projected.review_navigation_available is False
    assert projected.create_allowance_consumption_count == 1
    assert projected.durable_live_proof_activity.create is None


@pytest.mark.parametrize(
    (
        "attempt_state",
        "outcome",
        "exchange_state",
        "observed_read_count",
    ),
    (
        pytest.param(
            FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL,
            FollowUpLiveProofTerminalOutcome.SUCCEEDED,
            FollowUpExchangeMutationState.CONFIRMED_MUTATED,
            1,
            id="accepted",
        ),
        pytest.param(
            FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED,
            FollowUpLiveProofTerminalOutcome.REJECTED,
            FollowUpExchangeMutationState.NOT_MUTATED,
            0,
            id="rejected",
        ),
    ),
)
def test_service_preserves_exact_terminal_create_activity(
    attempt_state: FollowUpMaterializationState,
    outcome: FollowUpLiveProofTerminalOutcome,
    exchange_state: FollowUpExchangeMutationState,
    observed_read_count: int,
):
    create = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.CREATE,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=outcome,
        materialization_id="c17a9e86-7472-42d8-a2cf-eed38b2a7443",
        child_client_order_id="49a850b1-5a2e-4dbb-9125-b1cad4e2dc7d",
        sdk_state=FollowUpSdkMutationInvocationState.INVOKED,
        transport_state=FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
        exchange_state=exchange_state,
        observed_read_count=observed_read_count,
    )
    response = OperatorFollowUpOperationsService(
        _OneItemRepository(
            _attempt_page_item(
                attempt_state,
                FollowUpLiveProofOperationSet(
                    eligibility_read=None,
                    create=create,
                    reconciliation_read=None,
                    cancel=None,
                ),
            )
        )
    ).list_queue(
        actor=AdminApiActor(actor_id="operator-test", roles=[AdminApiRole.TRADER])
    )

    projected = response.items[0].durable_live_proof_activity.create
    assert projected is not None
    assert projected.terminal_outcome is outcome
    assert projected.exchange_mutation_state is exchange_state
    assert projected.observed_read_count == observed_read_count


def test_service_fails_closed_on_malformed_live_proof_identity():
    malformed = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        source_client_order_id=str(uuid.uuid4()),
        observed_read_count=1,
    )
    item = replace(
        _ready_page_item(),
        live_proof_operations=FollowUpLiveProofOperationSet(
            eligibility_read=malformed,
            create=None,
            reconciliation_read=None,
            cancel=None,
        ),
    )

    with pytest.raises(OperatorFollowUpOperationsError) as exc_info:
        OperatorFollowUpOperationsService(
            _OneItemRepository(item)
        ).list_queue(
            actor=AdminApiActor(
                actor_id="operator-test",
                roles=[AdminApiRole.TRADER],
            )
        )

    assert exc_info.value.code == "follow_up_operations_evidence_unavailable"


def test_service_fails_closed_on_malformed_materialization_child_binding():
    create = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.CREATE,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        materialization_id=str(uuid.uuid4()),
        child_client_order_id=str(uuid.uuid4()),
        sdk_state=FollowUpSdkMutationInvocationState.INVOKED,
        transport_state=FollowUpTransportSubmissionState.CONFIRMED_SUBMITTED,
        exchange_state=FollowUpExchangeMutationState.CONFIRMED_MUTATED,
        observed_read_count=1,
    )
    item = _attempt_page_item(
        FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL,
        FollowUpLiveProofOperationSet(
            eligibility_read=None,
            create=create,
            reconciliation_read=None,
            cancel=None,
        ),
    )

    with pytest.raises(OperatorFollowUpOperationsError) as exc_info:
        OperatorFollowUpOperationsService(
            _OneItemRepository(item)
        ).list_queue(
            actor=AdminApiActor(
                actor_id="operator-test",
                roles=[AdminApiRole.TRADER],
            )
        )

    assert exc_info.value.code == "follow_up_operations_evidence_unavailable"


@pytest.mark.parametrize(
    ("role", "actor_authorized", "actionable"),
    [
        (AdminApiRole.VIEWER, False, False),
        (AdminApiRole.AUDITOR, False, False),
        (AdminApiRole.TRADER, True, True),
        (AdminApiRole.ADMIN, True, True),
    ],
)
def test_service_separates_review_navigation_from_actor_authorization(
    role: AdminApiRole,
    actor_authorized: bool,
    actionable: bool,
):
    service = OperatorFollowUpOperationsService(
        _OneItemRepository(_ready_page_item())
    )

    response = service.list_queue(
        actor=AdminApiActor(actor_id="operator-test", roles=[role]),
    )

    item = response.items[0]
    assert item.review_navigation_available is True
    assert item.materialization_review_available is True
    assert item.required_permission is AdminApiPermission.ORDER_CREATE
    assert item.actor_authorized is actor_authorized
    assert item.actionable is actionable


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("limit", True),
        ("limit", 0),
        ("limit", 501),
        ("limit", "25"),
        ("offset", True),
        ("offset", -1),
        ("offset", "0"),
        ("product_id", ""),
    ],
)
def test_service_rejects_invalid_direct_filters_without_repository_access(
    field_name: str,
    value: object,
):
    repository = _EmptyRepository()
    service = OperatorFollowUpOperationsService(repository)
    actor = AdminApiActor(actor_id="operator-test", roles=[AdminApiRole.TRADER])

    with pytest.raises(OperatorFollowUpOperationsError) as exc_info:
        service.list_queue(actor=actor, **{field_name: value})

    assert exc_info.value.code == "follow_up_operations_evidence_unavailable"
    assert repository.calls == 0


@dataclass
class _SingleStatementCursor:
    executions: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    rows: list[dict[str, object]] | None = None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executions.append((query, params))

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows or [
            {"total_matching_count": 0, "follow_up_intent_id": None}
        ]


@dataclass
class _SingleStatementDb:
    cursor: _SingleStatementCursor = field(default_factory=_SingleStatementCursor)

    @contextmanager
    def get_cursor(self):
        yield self.cursor


def test_repository_uses_one_snapshot_statement_and_runs_no_schema_ddl():
    db = _SingleStatementDb()
    repository = OperatorFollowUpIntentRepository(
        db,
        configured_spot_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    page = repository.list_operations(limit=25, offset=0)

    assert page == FollowUpOperationsPage(items=(), total_matching_count=0)
    assert len(db.cursor.executions) == 1
    query = db.cursor.executions[0][0]
    assert "filtered AS" in query
    assert "LEFT JOIN page ON TRUE" in query
    assert "LEFT JOIN LATERAL" in query
    assert "jsonb_agg" in query
    assert "operator_follow_up_live_proof_event" in query
    assert "CREATE TABLE" not in query
    assert "FOR UPDATE" not in query


def _sql_page_row(
    *,
    source_id: str,
    root_id: str,
    intent_id: str,
    eligibility_read: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "total_matching_count": 2,
        "follow_up_intent_id": intent_id,
        "source_client_order_id": source_id,
        "root_client_order_id": root_id,
        "child_client_order_id": None,
        "materialization_id": None,
        "product_id": "BTC-USDC",
        "source_status": "FILLED",
        "derived_follow_up_side": "SELL",
        "operation_state": "ready_for_materialization_authorization",
        "state_reason_code": "source_full_fill_locally_consistent",
        "actionability": "materialization_review",
        "materialization_attempt_state": None,
        "correlation_id": CORRELATION_ID,
        "audit_id": AUDIT_ID,
        "recorded_at": "2026-07-19T00:00:00+00:00",
        "updated_at": "2026-07-19T00:00:00+00:00",
        "eligibility_read_live_proof": eligibility_read,
        "create_live_proof": None,
        "reconciliation_read_live_proof": None,
        "cancel_live_proof": None,
    }


def test_repository_bulk_projects_two_items_and_latest_journal_without_n_plus_one():
    eligibility = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        observed_read_count=4,
    )
    second_source = "21198dd7-512b-425d-8eef-b54b15583478"
    second_root = "6208c209-b971-4bb5-b3da-a33d7ec5106f"
    second_intent = "de494433-881d-4298-bfc4-fd11358a75ea"
    cursor = _SingleStatementCursor(
        rows=[
            _sql_page_row(
                source_id=SOURCE_ID,
                root_id=ROOT_ID,
                intent_id=INTENT_ID,
                eligibility_read=dict(eligibility.__dict__),
            ),
            _sql_page_row(
                source_id=second_source,
                root_id=second_root,
                intent_id=second_intent,
            ),
        ]
    )
    repository = OperatorFollowUpIntentRepository(
        _SingleStatementDb(cursor=cursor),
        configured_spot_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    page = repository.list_operations(
        product_id="BTC-USDC",
        state="ready_for_materialization_authorization",
        actionability="materialization_review",
        limit=2,
        offset=0,
    )

    assert page.total_matching_count == 2
    assert len(page.items) == 2
    assert len(cursor.executions) == 1
    assert page.items[0].live_proof_operations is not None
    projected = page.items[0].live_proof_operations.eligibility_read
    assert projected is not None
    assert projected.observed_read_count == 4
    assert projected.accounting_evidence_origin == "EXPLICIT"
    assert page.items[1].live_proof_operations == FollowUpLiveProofOperationSet(
        eligibility_read=None,
        create=None,
        reconciliation_read=None,
        cancel=None,
    )
    query, params = cursor.executions[0]
    assert query.count("operator_follow_up_live_proof_event") == 1
    assert params[0] == OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID


def test_repository_real_sql_bulk_projects_latest_explicit_journal(
    repository_harness: _RepositoryHarness,
):
    repository = repository_harness.repository()
    source_id = _attach_root_intent(
        repository_harness,
        repository,
        status_after_attach="FILLED",
        with_full_fill=True,
    )
    repository.claim_follow_up_live_proof_operation(
        goal_id=OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID,
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ.value,
        source_client_order_id=source_id,
        correlation_id=CORRELATION_ID,
        audit_id=AUDIT_ID,
        operation_idempotency_key_sha256="a" * 64,
    )
    terminal = repository.record_follow_up_live_proof_terminal(
        goal_id=OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID,
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ.value,
        source_client_order_id=source_id,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED.value,
        diagnostic_code="follow_up_live_proof_eligibility_succeeded",
        sdk_mutation_invocation_state="NOT_INVOKED",
        transport_submission_state="NOT_SUBMITTED",
        exchange_mutation_state="NOT_MUTATED",
        read_accounting_state="EXACT",
        observed_read_count=4,
        individual_retry_count=0,
    )

    page = repository.list_operations(limit=25, offset=0)

    assert len(page.items) == 1
    activity = page.items[0].live_proof_operations
    assert activity is not None
    assert activity.eligibility_read is not None
    assert activity.eligibility_read.event_id == terminal.event_id
    assert activity.eligibility_read.accounting_evidence_origin == "EXPLICIT"
    assert activity.eligibility_read.observed_read_count == 4
    assert activity.create is None
    assert activity.reconciliation_read is None
    assert activity.cancel is None


@pytest.mark.parametrize(
    "accounting_override",
    (
        pytest.param(
            {"transport_submission_state": None},
            id="partial-explicit-tuple",
        ),
        pytest.param(
            {
                "read_accounting_state": "EXACT",
                "observed_read_count": None,
            },
            id="exact-without-count",
        ),
        pytest.param(
            {
                "read_accounting_state": "UNKNOWN",
                "observed_read_count": 1,
            },
            id="unknown-with-count",
        ),
    ),
)
def test_repository_fails_closed_on_partial_or_incoherent_explicit_accounting(
    accounting_override: dict[str, object],
):
    eligibility = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        observed_read_count=4,
    )
    raw = dict(eligibility.__dict__)
    raw.update(accounting_override)
    cursor = _SingleStatementCursor(
        rows=[
            _sql_page_row(
                source_id=SOURCE_ID,
                root_id=ROOT_ID,
                intent_id=INTENT_ID,
                eligibility_read=raw,
            )
        ]
    )
    repository = OperatorFollowUpIntentRepository(
        _SingleStatementDb(cursor=cursor),
        configured_spot_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    with pytest.raises(FollowUpIntentStoreUnavailable) as exc_info:
        repository.list_operations(limit=1, offset=0)

    assert exc_info.value.code == "follow_up_operations_evidence_unavailable"


def test_repository_projects_only_all_null_accounting_as_conservative_legacy():
    eligibility = _live_proof_record(
        operation_kind=FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
        event_state=FollowUpLiveProofEventState.TERMINAL,
        outcome=FollowUpLiveProofTerminalOutcome.SUCCEEDED,
        observed_read_count=2,
    )
    raw = dict(eligibility.__dict__)
    raw.update(
        {
            "sdk_mutation_invocation_state": None,
            "transport_submission_state": None,
            "exchange_mutation_state": None,
            "read_accounting_state": None,
            "observed_read_count": None,
            "reported_read_count": 2,
        }
    )
    cursor = _SingleStatementCursor(
        rows=[
            _sql_page_row(
                source_id=SOURCE_ID,
                root_id=ROOT_ID,
                intent_id=INTENT_ID,
                eligibility_read=raw,
            )
        ]
    )
    repository = OperatorFollowUpIntentRepository(
        _SingleStatementDb(cursor=cursor),
        configured_spot_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    page = repository.list_operations(limit=1, offset=0)

    operation_set = page.items[0].live_proof_operations
    assert operation_set is not None
    projected = operation_set.eligibility_read
    assert projected is not None
    assert projected.accounting_evidence_origin == "LEGACY_CONSERVATIVE"
    assert projected.read_accounting_state == "EXACT"
    assert projected.observed_read_count == 2


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("limit", True),
        ("limit", 0),
        ("limit", 501),
        ("limit", "25"),
        ("offset", True),
        ("offset", -1),
        ("offset", "0"),
        ("product_id", ""),
        ("state", "not_allowlisted"),
        ("actionability", "not_allowlisted"),
    ],
)
def test_repository_rejects_invalid_filters_before_sql(
    field_name: str,
    value: object,
):
    db = _SingleStatementDb()
    repository = OperatorFollowUpIntentRepository(
        db,
        configured_spot_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    with pytest.raises(ValueError):
        repository.list_operations(**{field_name: value})

    assert db.cursor.executions == []


def test_item_model_rejects_unsafe_navigation_identity():
    payload = _response().items[0].model_dump(mode="json")
    payload["source_client_order_id"] = "unsafe/id?query=true"
    payload["detail_href"] = "/orders/unsafe/id?query=true"

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationItem.model_validate(payload)


def test_item_model_rejects_corrupt_state_action_projection():
    payload = _response().items[0].model_dump(mode="json")
    payload["operation_state"] = "blocked"

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationItem.model_validate(payload)


@pytest.mark.parametrize(
    ("source_status", "operation_state", "reason_code", "blockers"),
    [
        (
            "OPEN",
            "ready_for_materialization_authorization",
            "source_full_fill_locally_consistent",
            [],
        ),
        (
            "FILLED",
            "awaiting_source_fill",
            "source_full_fill_not_observed",
            ["source_full_fill_not_observed"],
        ),
        (
            "OPEN",
            "blocked",
            "source_terminal_without_full_fill",
            ["source_terminal_without_full_fill"],
        ),
        (
            "OPEN",
            "blocked",
            "source_status_unknown",
            ["source_status_unknown"],
        ),
        (
            "OPEN",
            "blocked",
            "source_full_fill_inconsistent",
            ["source_full_fill_inconsistent"],
        ),
    ],
)
def test_item_model_rejects_unclaimed_source_status_projection_mismatch(
    source_status: str,
    operation_state: str,
    reason_code: str,
    blockers: list[str],
):
    payload = _response().items[0].model_dump(mode="json")
    payload.update(
        {
            "source_status": source_status,
            "operation_state": operation_state,
            "state_reason_code": reason_code,
            "blocker_codes": blockers,
            "actionability": (
                "materialization_review"
                if operation_state == "ready_for_materialization_authorization"
                else "none"
            ),
            "actionable": operation_state == "ready_for_materialization_authorization",
            "review_navigation_available": (
                operation_state == "ready_for_materialization_authorization"
            ),
            "materialization_review_available": (
                operation_state == "ready_for_materialization_authorization"
            ),
            "safe_closeout_review_available": False,
            "required_permission": (
                "order:create"
                if operation_state == "ready_for_materialization_authorization"
                else None
            ),
            "actor_authorized": (
                operation_state == "ready_for_materialization_authorization"
            ),
            "fresh_authoritative_revalidation_required": (
                operation_state == "ready_for_materialization_authorization"
            ),
        }
    )

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationItem.model_validate(payload)


def test_queue_model_rejects_duplicate_page_identity():
    payload = _response().model_dump(mode="json")
    payload["items"] = [payload["items"][0], payload["items"][0]]
    payload["count"] = 2
    payload["pagination"]["returned_count"] = 2
    payload["pagination"]["total_matching_count"] = 2

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationsQueueResponse.model_validate(payload)


def test_queue_model_rejects_more_items_than_requested_limit():
    payload = _response().model_dump(mode="json")
    second = dict(payload["items"][0])
    second_source_id = "21198dd7-512b-425d-8eef-b54b15583478"
    second["follow_up_intent_id"] = "de494433-881d-4298-bfc4-fd11358a75ea"
    second["source_client_order_id"] = second_source_id
    second["root_client_order_id"] = second_source_id
    second["detail_href"] = f"/orders/{second_source_id}"
    payload["items"].append(second)
    payload["count"] = 2
    payload["filters"]["limit"] = 1
    payload["pagination"].update(
        {
            "limit": 1,
            "returned_count": 2,
            "total_matching_count": 2,
        }
    )

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationsQueueResponse.model_validate(payload)


def test_queue_model_rejects_nonzero_or_unknown_current_request_activity():
    payload = _response().model_dump(mode="json")
    payload["current_request_activity"]["observed_read_count"] = 1

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationsQueueResponse.model_validate(payload)

    payload = _response().model_dump(mode="json")
    payload["current_request_activity"].update(
        {
            "read_accounting_state": "UNKNOWN",
            "observed_read_count": None,
        }
    )
    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationsQueueResponse.model_validate(payload)


def test_queue_item_rejects_allowance_compatibility_alias_drift():
    payload = _response().items[0].model_dump(mode="json")
    payload["create_allowance_consumption_count"] = 1
    payload["create_allowance_consumed"] = True

    with pytest.raises(ValueError):
        AdminOrderFollowUpOperationItem.model_validate(payload)


def test_queue_contract_round_trip_is_strict_and_activity_is_value_blind():
    payload = _response().model_dump(mode="json")

    assert AdminOrderFollowUpOperationsQueueResponse.model_validate(
        payload
    ).model_dump(mode="json") == payload
    assert "diagnostic_code" not in str(payload["current_request_activity"])
    assert "correlation_id" not in str(
        payload["items"][0]["durable_live_proof_activity"]
    )
