"""Route contracts for explicit operator follow-up materialization.

All dependencies are synthetic.  These tests never construct a Coinbase client
and make no exchange or network call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as admin_api_app, create_app
from api.v1.routes import orders as order_routes
from application.admin_api.models import (
    AdminOrderFollowUpMaterializationCancelResponse,
    AdminOrderFollowUpMaterializationCommandResponse,
    AdminOrderFollowUpMaterializationReadResponse,
)
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.live_execution import (
    AdminApiLiveExecutionServiceState,
    CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
)
from application.admin_api.operator_follow_up_materialization import (
    AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
    OperatorFollowUpMaterializationError,
    SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]


SOURCE_ID = "d24c9fc3-29c2-4e76-87d7-3d27cb94530f"
ROOT_ID = "87aa9a2d-b015-4701-b7e5-63cc26360ad2"
CHILD_ID = "72a77ad1-386a-5aad-a4fb-feb575b87a5c"
INTENT_ID = "0ec90842-d875-4a7b-9eb1-333c7d618bb1"
ATTEMPT_ID = "4f7d2e1f-96b4-43af-9901-f217879a4ac5"
AUDIT_ID = "1f418e77-9e5e-49f3-861e-a30f942f38fb"
CORRELATION_ID = "b80fe761-69e6-462b-9ccb-b40ed93b2ac7"
IDEMPOTENCY_KEY = "98296253-d0b8-44ca-8701-8c17ca99d397"


def _headers(
    *,
    operator_intent: str | None = None,
    roles: str = "trader",
    actor_id: str = "operator-materialization-test",
    correlation_id: str = CORRELATION_ID,
) -> dict[str, str]:
    values = {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": actor_id,
        "X-Admin-Roles": roles,
    }
    if operator_intent is not None:
        values.update(
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Correlation-Id": correlation_id,
                "X-Operator-Intent": operator_intent,
            }
        )
    return values


def _eligibility(*, ready: bool = True) -> dict[str, object]:
    return {
        "source_client_order_id": SOURCE_ID,
        "root_client_order_id": ROOT_ID,
        "attached_intent_present": True,
        "source_status": "FILLED",
        "source_full_fill_proven": True,
        "source_terminal_revalidated": True,
        "test_portfolio_revalidated": True,
        "product_policy_revalidated": True,
        "wallet_revalidated": ready,
        "cap_revalidated": ready,
        "reconciliation_revalidated": ready,
        "child_absent": True,
        "attempt_unconsumed": True,
        "ready": ready,
        "backend_decision": "ready" if ready else "blocked",
        "blockers": [] if ready else ["wallet_evidence_unavailable"],
    }


def _candidate() -> dict[str, object]:
    return {
        "child_client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "base_size": "0.00001",
        "limit_price": "100000.00",
        "submitted_notional_usdc": "1.00",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
        "effective_notional_cap_usdc": "1.00",
        "post_only": False,
        "backend_derived": True,
    }


def _allowance(*, create_consumed: bool, cancel_consumed: bool = False) -> dict[str, object]:
    return {
        "create_call_limit": 1,
        "create_call_count": 1 if create_consumed else 0,
        "create_call_consumed": create_consumed,
        "create_retry_allowed": False,
        "cancel_call_limit": 1,
        "cancel_call_count": 1 if cancel_consumed else 0,
        "cancel_call_consumed": cancel_consumed,
        "cancel_retry_allowed": False,
        "fallback_allowed": False,
    }


def _attempt(*, state: str = "CREATE_ACCEPTED_NONTERMINAL") -> dict[str, object]:
    return {
        "materialization_id": ATTEMPT_ID,
        "follow_up_intent_id": INTENT_ID,
        "source_client_order_id": SOURCE_ID,
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "state": state,
        "terminal": state in {
            "CREATE_EXPLICITLY_REJECTED",
            "CREATE_ACCEPTED_TERMINAL",
            "CREATE_UNKNOWN_CONSUMED",
            "CANCEL_ACCEPTED_TERMINAL",
            "CANCEL_UNKNOWN_CONSUMED",
            "CHILD_ALREADY_TERMINAL_NO_CANCEL",
        },
        "unknown_outcome": state in {
            "CREATE_UNKNOWN_CONSUMED",
            "CANCEL_UNKNOWN_CONSUMED",
        },
        "exchange_order_id_present": state == "CREATE_ACCEPTED_NONTERMINAL",
        "exchange_order_id_authority": "withheld_backend_evidence",
        "correlation_id": CORRELATION_ID,
        "audit_id": AUDIT_ID,
        "recorded_at": "2026-07-18T12:00:00+00:00",
        "updated_at": "2026-07-18T12:00:01+00:00",
    }


def _read_response(
    *,
    follow_up_intent_id: str | None = INTENT_ID,
) -> AdminOrderFollowUpMaterializationReadResponse:
    return AdminOrderFollowUpMaterializationReadResponse(
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        follow_up_intent_id=follow_up_intent_id,
        environment="local-controlled-live",
        portfolio_scope="approved_test_portfolio",
        required_materialization_operator_intent=(
            AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        ),
        required_safe_closeout_operator_intent=(
            SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT
        ),
        eligibility={
            **_eligibility(),
            "source_terminal_revalidated": False,
            "test_portfolio_revalidated": False,
            "product_policy_revalidated": False,
            "wallet_revalidated": False,
            "cap_revalidated": False,
            "reconciliation_revalidated": False,
            "ready": False,
            "backend_decision": "blocked",
            "blockers": ["fresh_live_authorization_required"],
        },
        authorization_request_forwardability={
            "request_forwardable": True,
            "backend_decision": "forward_fresh_acknowledgement_only",
            "blockers": [],
            "acknowledgement_only": True,
            "live_eligibility": False,
            "exchange_call_authority": False,
            "browser_authority": (
                "display_and_forward_fresh_acknowledgement_only"
            ),
        },
        candidate=_candidate(),
        attempt=None,
        call_allowance=_allowance(create_consumed=False),
        safe_closeout_eligibility={
            "request_eligible": False,
            "backend_decision": "blocked",
            "blockers": ["materialization_not_started"],
            "authoritative_child_read_required": True,
            "cancel_only_if_authoritatively_active": True,
        },
    )


def _command_response() -> AdminOrderFollowUpMaterializationCommandResponse:
    return AdminOrderFollowUpMaterializationCommandResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="materialize_order_follow_up_intent",
        message="Materialization reached a fixed accepted terminal classification.",
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        environment="local-controlled-live",
        portfolio_scope="approved_test_portfolio",
        operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
        correlation_id=CORRELATION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        audit_id=AUDIT_ID,
        replayed=False,
        eligibility=_eligibility(),
        candidate=_candidate(),
        attempt=_attempt(),
        call_allowance=_allowance(create_consumed=True),
        current_request_activity={
            "sdk_mutation_invocation_state": "INVOKED",
            "transport_submission_state": "CONFIRMED_SUBMITTED",
            "exchange_mutation_state": "CONFIRMED_MUTATED",
            "read_accounting_state": "EXACT",
            "observed_read_count": 2,
        },
        durable_live_proof_activity={},
        live_coinbase_read_ran=True,
        live_coinbase_create_call_count=1,
        live_coinbase_cancel_call_count=0,
        live_exchange_submitted=True,
        exchange_state_mutated=True,
    )


def _cancel_response() -> AdminOrderFollowUpMaterializationCancelResponse:
    return AdminOrderFollowUpMaterializationCancelResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="safe_closeout_materialized_follow_up_intent",
        message="Exact materialized child reached safe closeout.",
        source_client_order_id=SOURCE_ID,
        root_client_order_id=ROOT_ID,
        child_client_order_id=CHILD_ID,
        environment="local-controlled-live",
        portfolio_scope="approved_test_portfolio",
        operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
        correlation_id=CORRELATION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        audit_id=AUDIT_ID,
        replayed=False,
        attempt=_attempt(state="CANCEL_ACCEPTED_TERMINAL"),
        call_allowance=_allowance(create_consumed=True, cancel_consumed=True),
        current_request_activity={
            "sdk_mutation_invocation_state": "INVOKED",
            "transport_submission_state": "CONFIRMED_SUBMITTED",
            "exchange_mutation_state": "CONFIRMED_MUTATED",
            "read_accounting_state": "EXACT",
            "observed_read_count": 4,
        },
        durable_live_proof_activity={},
        live_coinbase_read_ran=True,
        live_coinbase_create_call_count=0,
        live_coinbase_cancel_call_count=1,
        live_exchange_cancel_submitted=True,
        exchange_state_mutated=True,
    )


def _admitted_live_execution_state(
    *,
    supported_routes: frozenset[tuple[str, str]] = (
        OPERATOR_MVP_SUPPORTED_LIVE_ROUTES
    ),
) -> AdminApiLiveExecutionServiceState:
    return AdminApiLiveExecutionServiceState(
        required=True,
        present=True,
        status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        source=CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
        missing_reason=None,
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        supported_routes=supported_routes,
    )


@dataclass
class _FakeLiveExecutionService:
    state: AdminApiLiveExecutionServiceState = field(
        default_factory=_admitted_live_execution_state
    )
    admission_calls: int = 0

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        self.admission_calls += 1
        return self.state


@dataclass
class _FakeMaterializationService:
    materialize_calls: int = 0
    cancel_calls: int = 0
    read_calls: int = 0
    last_request: object | None = None
    last_context: object | None = None
    audit_store: FileAdminApiAuditStore | None = None
    materialize_error: object | None = None
    cancel_error: object | None = None
    materialize_audit_binding_conflict: bool = False
    cancel_audit_binding_conflict: bool = False
    materialize_contexts: list[object] = field(default_factory=list)
    cancel_contexts: list[object] = field(default_factory=list)
    materialize_operation_audit_id: str | None = None
    cancel_operation_audit_id: str | None = None
    live_execution_service: _FakeLiveExecutionService = field(
        default_factory=_FakeLiveExecutionService
    )

    def read(self, *, source_client_order_id: str):
        assert source_client_order_id == SOURCE_ID
        self.read_calls += 1
        return _read_response()

    def materialize(self, *, source_client_order_id: str, request: object, context: object):
        assert source_client_order_id == SOURCE_ID
        self.materialize_calls += 1
        self.last_request = request
        self.last_context = context
        self.materialize_contexts.append(context)
        if self.materialize_error is not None:
            raise self.materialize_error
        if (
            self.materialize_operation_audit_id is not None
            and self.materialize_operation_audit_id != context.audit_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_audit_binding_conflict",
                409,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if self.materialize_operation_audit_id is None:
            self.materialize_operation_audit_id = context.audit_id
        response = _command_response()
        response_audit_id = (
            AUDIT_ID
            if self.materialize_audit_binding_conflict
            else self.materialize_operation_audit_id
        )
        return response.model_copy(
            update={
                "audit_id": response_audit_id,
                "attempt": response.attempt.model_copy(
                    update={"audit_id": response_audit_id}
                ),
            }
        )

    def safe_closeout(self, *, source_client_order_id: str, request: object, context: object):
        assert source_client_order_id == SOURCE_ID
        self.cancel_calls += 1
        self.last_request = request
        self.last_context = context
        self.cancel_contexts.append(context)
        if self.cancel_error is not None:
            raise self.cancel_error
        if (
            self.cancel_operation_audit_id is not None
            and self.cancel_operation_audit_id != context.audit_id
        ):
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_audit_binding_conflict",
                409,
                failure_stage="pre_exchange_evaluation",
                live_coinbase_read_ran=False,
                live_coinbase_orders_ran=False,
                live_exchange_submitted=False,
            )
        if self.cancel_operation_audit_id is None:
            self.cancel_operation_audit_id = context.audit_id
        response = _cancel_response()
        response_audit_id = (
            AUDIT_ID
            if self.cancel_audit_binding_conflict
            else self.cancel_operation_audit_id
        )
        return response.model_copy(
            update={
                "audit_id": response_audit_id,
                "attempt": response.attempt.model_copy(
                    update={"audit_id": response_audit_id}
                ),
            }
        )


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> tuple[TestClient, _FakeMaterializationService]:
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "1")
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_ENVIRONMENT",
        "test-controlled-live",
    )
    audit_store = FileAdminApiAuditStore(tmp_path / "materialization-audit.jsonl")
    service = _FakeMaterializationService(audit_store=audit_store)
    app = create_app()
    app.dependency_overrides[
        order_routes.get_order_follow_up_materialization_service
    ] = lambda: service
    app.dependency_overrides[order_routes.get_live_execution_service] = (
        lambda: service.live_execution_service
    )
    app.dependency_overrides[order_routes.get_audit_store] = lambda: audit_store
    return TestClient(app), service


def test_passive_materialization_get_is_local_readback_only(client):
    http, service = client

    response = http.get(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert service.read_calls == 1
    assert service.materialize_calls == 0
    assert service.cancel_calls == 0
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_coinbase_create_call_count"] == 0
    assert payload["live_coinbase_cancel_call_count"] == 0
    assert payload["candidate"]["backend_derived"] is True
    assert payload["safe_closeout_eligibility"]["backend_decision"] == "blocked"
    assert payload["authorization_request_forwardability"] == {
        "request_forwardable": True,
        "backend_decision": "forward_fresh_acknowledgement_only",
        "blockers": [],
        "acknowledgement_only": True,
        "live_eligibility": False,
        "exchange_call_authority": False,
        "browser_authority": (
            "display_and_forward_fresh_acknowledgement_only"
        ),
    }


def test_passive_readback_represents_no_attached_intent_without_fake_identity():
    readback = _read_response(follow_up_intent_id=None)

    assert readback.follow_up_intent_id is None


def test_passive_readback_exposes_sanitized_audit_and_dual_row_projection():
    payload = _read_response().model_dump(mode="json")
    payload["audit_events"] = [
        {
            "event_id": "7ca7c68d-3f60-4215-a483-bf359fef7704",
            "state": "CREATE_ACCEPTED_NONTERMINAL",
            "diagnostic_code": "follow_up_materialization_create_accepted",
            "operation_audit_id": AUDIT_ID,
            "environment": "local-controlled-live",
            "operator_intent": AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            "correlation_id": CORRELATION_ID,
            "exchange_order_id_present": True,
            "recorded_at": "2026-07-18T12:00:01+00:00",
        }
    ]
    payload["local_projection"] = {
        "local_state_event_id": "21b1b69c-17dc-46e0-83f4-c5bf86acc1dd",
        "materialization_id": ATTEMPT_ID,
        "child_client_order_id": CHILD_ID,
        "transition_kind": "CREATE_ACCEPTED_ACTIVE",
        "authoritative_order_status": "PENDING",
        "exchange_order_id_present": True,
        "operation_audit_id": AUDIT_ID,
        "recorded_at": "2026-07-18T12:00:02+00:00",
        "order_parent_and_stealth_match": True,
    }

    readback = AdminOrderFollowUpMaterializationReadResponse(**payload)
    serialized = readback.model_dump(mode="json")

    assert len(serialized["audit_events"]) == 1
    assert serialized["local_projection"]["order_parent_and_stealth_match"] is True
    assert "actor_id" not in serialized["audit_events"][0]
    assert "roles" not in serialized["audit_events"][0]
    assert "exchange_order_id" not in serialized["audit_events"][0]


def test_materialize_post_forwards_only_fixed_acknowledgements_and_context(client):
    http, service = client
    body = {
        "authorize_materialization_of_attached_intent": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
        "acknowledge_child_terms_are_backend_derived": True,
    }

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT),
        json=body,
    )

    assert response.status_code == 200
    assert service.materialize_calls == 1
    assert service.last_request.model_dump(mode="json") == body
    assert service.last_context.operator_intent == AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
    assert service.last_context.environment == "test-controlled-live"
    assert service.last_context.audit_id
    payload = response.json()
    assert payload["required_permission"] == "order:create"
    assert payload["service_method"] == "materialize_order_follow_up_intent"
    assert payload["live_coinbase_create_call_count"] == 1
    assert payload["call_allowance"]["create_retry_allowed"] is False
    assert payload["audit_id"] != service.last_context.audit_id
    assert payload["correlation_id"] == CORRELATION_ID
    assert payload["attempt"]["audit_id"] == service.last_context.audit_id

    assert service.audit_store is not None
    events = service.audit_store.read_recent(limit=10)
    assert len(events) == 1
    receipt = events[0]
    assert payload["audit_id"] == receipt.audit_id
    assert receipt.audit_id != service.last_context.audit_id
    assert receipt.actor_id == "operator-materialization-test"
    assert receipt.action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
    assert receipt.permission == AdminApiPermission.ORDER_CREATE
    assert receipt.client_order_id == SOURCE_ID
    assert receipt.request_id == CORRELATION_ID
    assert receipt.idempotency_key == IDEMPOTENCY_KEY
    assert receipt.operator_intent == AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
    assert receipt.status == "received"
    assert receipt.failure_stage == "authorization_received_for_evaluation"
    assert receipt.message == (
        "follow_up_materialization_authorization_received_for_evaluation"
    )
    assert receipt.live_exchange_submitted is False
    assert receipt.live_coinbase_orders_ran is False
    assert receipt.live_coinbase_read_ran is False
    assert receipt.coinbase_order_id is None


@pytest.mark.parametrize(
    ("path_suffix", "operator_intent", "body"),
    [
        (
            "materialization",
            AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            {
                "authorize_materialization_of_attached_intent": True,
                "acknowledge_unknown_outcome_consumes_create_allowance": True,
                "acknowledge_child_terms_are_backend_derived": True,
            },
        ),
        (
            "materialization/safe-closeout",
            SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            {
                "authorize_single_cancel_for_safe_closeout": True,
                "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "blocked_state",
    [
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=False,
                status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
                source="not_configured",
                missing_reason="live_service_enablement_decision_missing",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="decision-absent",
        ),
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
                source="disabled_backend_service",
                missing_reason="live_execution_disabled",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="runtime-disabled",
        ),
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                source="admin_api_live_service_decision_log",
                missing_reason=(
                    "live_service_enablement_decision_not_resolver_eligible"
                ),
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="decision-stale",
        ),
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                source="admin_api_live_service_decision_log",
                missing_reason=(
                    "live_service_enablement_decision_not_resolver_eligible"
                ),
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="decision-wrong-installed-binding",
        ),
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                source="admin_api_live_service_decision_log",
                missing_reason=(
                    "live_service_enablement_decision_not_resolver_eligible"
                ),
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="decision-recorded-before-current-lease",
        ),
        pytest.param(
            _admitted_live_execution_state(supported_routes=frozenset()),
            id="exact-route-not-installed",
        ),
        pytest.param(
            AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                source=CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
                missing_reason=None,
                max_submitted_notional_usdc="2.00",
                max_executed_notional_usdc="0.50",
                supported_routes=OPERATOR_MVP_SUPPORTED_LIVE_ROUTES,
            ),
            id="decision-cap-binding-does-not-match-installed-policy",
        ),
    ],
)
def test_follow_up_mutations_require_current_exact_route_live_service_admission(
    client,
    path_suffix: str,
    operator_intent: str,
    body: dict[str, bool],
    blocked_state: AdminApiLiveExecutionServiceState,
):
    http, service = client
    service.live_execution_service.state = blocked_state

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{path_suffix}",
        headers=_headers(operator_intent=operator_intent),
        json=body,
    )

    assert response.status_code == 503
    assert response.json()["message"] == (
        "follow_up_materialization_live_service_admission_blocked"
    )
    assert response.json()["live_coinbase_orders_ran"] is False
    assert service.materialize_calls == 0
    assert service.cancel_calls == 0
    assert service.live_execution_service.admission_calls == 1


@pytest.mark.parametrize(
    ("path_suffix", "operator_intent", "body", "context_attr"),
    [
        (
            "materialization",
            AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            {
                "authorize_materialization_of_attached_intent": True,
                "acknowledge_unknown_outcome_consumes_create_allowance": True,
                "acknowledge_child_terms_are_backend_derived": True,
            },
            "materialize_contexts",
        ),
        (
            "materialization/safe-closeout",
            SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            {
                "authorize_single_cancel_for_safe_closeout": True,
                "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
            },
            "cancel_contexts",
        ),
    ],
)
def test_operation_audit_binding_survives_replay_with_new_request_correlation(
    client,
    path_suffix: str,
    operator_intent: str,
    body: dict[str, bool],
    context_attr: str,
):
    http, service = client
    replay_correlation_id = "aa62d277-c4d8-4c7d-9f7b-c04b868a78b9"

    first = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{path_suffix}",
        headers=_headers(operator_intent=operator_intent),
        json=body,
    )
    replay = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{path_suffix}",
        headers=_headers(
            operator_intent=operator_intent,
            correlation_id=replay_correlation_id,
        ),
        json=body,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    contexts = getattr(service, context_attr)
    assert len(contexts) == 2
    assert contexts[0].correlation_id == CORRELATION_ID
    assert contexts[1].correlation_id == replay_correlation_id
    assert contexts[0].audit_id == contexts[1].audit_id
    assert first.json()["audit_id"] != replay.json()["audit_id"]
    assert first.json()["correlation_id"] == CORRELATION_ID
    assert replay.json()["correlation_id"] == replay_correlation_id
    assert first.json()["attempt"]["audit_id"] == contexts[0].audit_id
    assert replay.json()["attempt"]["audit_id"] == contexts[0].audit_id

    assert service.audit_store is not None
    receipts = service.audit_store.read_recent(limit=10)
    assert len(receipts) == 2
    assert {event.request_id for event in receipts} == {
        CORRELATION_ID,
        replay_correlation_id,
    }
    assert len({event.audit_id for event in receipts}) == 2
    assert all(event.audit_id != contexts[0].audit_id for event in receipts)
    assert {first.json()["audit_id"], replay.json()["audit_id"]} == {
        event.audit_id for event in receipts
    }


@pytest.mark.parametrize(
    ("changed_actor_id", "changed_roles"),
    [
        ("different-materialization-operator", "trader"),
        ("operator-materialization-test", "admin"),
    ],
)
def test_operation_audit_binding_changes_with_actor_or_roles_and_fails_closed(
    client,
    changed_actor_id: str,
    changed_roles: str,
):
    http, service = client
    body = {
        "authorize_materialization_of_attached_intent": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
        "acknowledge_child_terms_are_backend_derived": True,
    }

    first = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        ),
        json=body,
    )
    changed_context = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            actor_id=changed_actor_id,
            roles=changed_roles,
        ),
        json=body,
    )

    assert first.status_code == 200
    assert changed_context.status_code == 409
    assert changed_context.json()["message"] == (
        "follow_up_materialization_audit_binding_conflict"
    )
    assert len(service.materialize_contexts) == 2
    assert (
        service.materialize_contexts[0].audit_id
        != service.materialize_contexts[1].audit_id
    )


def test_operation_audit_binding_changes_with_environment_and_fails_closed(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    http, service = client
    body = {
        "authorize_materialization_of_attached_intent": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
        "acknowledge_child_terms_are_backend_derived": True,
    }
    first = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        ),
        json=body,
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_ENVIRONMENT",
        "different-controlled-live-environment",
    )

    changed_context = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            correlation_id="c73b168d-f731-41b4-928d-722ae68b0f1d",
        ),
        json=body,
    )

    assert first.status_code == 200
    assert changed_context.status_code == 409
    assert changed_context.json()["message"] == (
        "follow_up_materialization_audit_binding_conflict"
    )
    assert len(service.materialize_contexts) == 2
    assert (
        service.materialize_contexts[0].audit_id
        != service.materialize_contexts[1].audit_id
    )


@pytest.mark.parametrize(
    "extra_field",
    [
        "product_id",
        "side",
        "base_size",
        "limit_price",
        "child_client_order_id",
        "exchange_order_id",
        "environment",
        "portfolio_scope",
        "submitted_notional_usdc",
        "max_submitted_notional_usdc",
    ],
)
def test_materialize_post_rejects_browser_trading_fields_before_service(client, extra_field):
    http, service = client
    body = {
        "authorize_materialization_of_attached_intent": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
        "acknowledge_child_terms_are_backend_derived": True,
        extra_field: "browser-value",
    }

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT),
        json=body,
    )

    assert response.status_code == 422
    assert service.materialize_calls == 0


def test_attachment_operator_intent_cannot_authorize_materialization(client):
    http, service = client

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(operator_intent="attach_single_follow_up_intent"),
        json={
            "authorize_materialization_of_attached_intent": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert response.status_code == 422
    assert service.materialize_calls == 0


def test_safe_closeout_post_resolves_child_backend_side(client):
    http, service = client
    body = {
        "authorize_single_cancel_for_safe_closeout": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization/safe-closeout",
        headers=_headers(operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT),
        json=body,
    )

    assert response.status_code == 200
    assert service.cancel_calls == 1
    assert service.last_request.model_dump(mode="json") == body
    assert service.last_context.environment == "test-controlled-live"
    payload = response.json()
    assert payload["required_permission"] == "order:cancel"
    assert payload["child_client_order_id"] == CHILD_ID
    assert payload["live_coinbase_cancel_call_count"] == 1
    assert payload["call_allowance"]["cancel_retry_allowed"] is False
    assert payload["audit_id"] != service.last_context.audit_id
    assert payload["correlation_id"] == CORRELATION_ID
    assert payload["attempt"]["audit_id"] == service.last_context.audit_id
    assert service.audit_store is not None
    assert payload["audit_id"] == service.audit_store.read_recent(limit=1)[0].audit_id


@pytest.mark.parametrize(
    ("operation", "operator_intent", "body"),
    [
        (
            "materialize",
            AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            {
                "authorize_materialization_of_attached_intent": True,
                "acknowledge_unknown_outcome_consumes_create_allowance": True,
                "acknowledge_child_terms_are_backend_derived": True,
            },
        ),
        (
            "safe_closeout",
            SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            {
                "authorize_single_cancel_for_safe_closeout": True,
                "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
            },
        ),
    ],
)
def test_post_service_audit_binding_conflict_never_claims_zero_live_activity(
    client,
    operation: str,
    operator_intent: str,
    body: dict[str, bool],
):
    http, service = client
    if operation == "materialize":
        service.materialize_audit_binding_conflict = True
        suffix = "materialization"
    else:
        service.cancel_audit_binding_conflict = True
        suffix = "materialization/safe-closeout"

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{suffix}",
        headers=_headers(operator_intent=operator_intent),
        json=body,
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["message"] == "follow_up_materialization_audit_binding_conflict"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["current_request_activity"] == {
        "accounting_scope": "current_request",
        "sdk_mutation_invocation_state": "UNKNOWN",
        "transport_submission_state": "POSSIBLY_SUBMITTED",
        "exchange_mutation_state": "UNKNOWN",
        "read_accounting_state": "UNKNOWN",
        "observed_read_count": None,
    }
    assert payload["audit_id"] != service.last_context.audit_id
    assert service.audit_store is not None
    assert payload["audit_id"] == service.audit_store.read_recent(limit=1)[0].audit_id
    assert service.materialize_calls == (1 if operation == "materialize" else 0)
    assert service.cancel_calls == (1 if operation == "safe_closeout" else 0)


@pytest.mark.parametrize(
    (
        "operation",
        "diagnostic",
        "expected_status",
        "action_class",
        "permission",
        "failure_stage",
        "live_read_ran",
    ),
    [
        (
            "materialize",
            "follow_up_live_proof_operation_unavailable",
            409,
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            AdminApiPermission.ORDER_CREATE,
            "eligibility_claim_before_read",
            False,
        ),
        (
            "materialize",
            "follow_up_materialization_eligibility_blocked",
            409,
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            AdminApiPermission.ORDER_CREATE,
            "eligibility_after_live_read",
            True,
        ),
        (
            "safe_closeout",
            "follow_up_materialization_child_not_cancelable",
            409,
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            AdminApiPermission.ORDER_CANCEL,
            "pre_exchange_evaluation",
            False,
        ),
    ],
)
def test_preclaim_rejection_appends_sanitized_outcome_and_returns_typed_audit_id(
    client,
    operation: str,
    diagnostic: str,
    expected_status: int,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
    failure_stage: str,
    live_read_ran: bool,
):
    from application.admin_api.operator_follow_up_materialization import (
        OperatorFollowUpMaterializationError,
    )

    http, service = client
    error = OperatorFollowUpMaterializationError(
        diagnostic,
        expected_status,
        failure_stage=failure_stage,
        live_coinbase_read_ran=live_read_ran,
        live_coinbase_orders_ran=False,
        live_exchange_submitted=False,
    )
    if operation == "materialize":
        service.materialize_error = error
        suffix = "materialization"
        intent = AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        body = {
            "authorize_materialization_of_attached_intent": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        }
    else:
        service.cancel_error = error
        suffix = "materialization/safe-closeout"
        intent = SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT
        body = {
            "authorize_single_cancel_for_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
        }

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{suffix}",
        headers=_headers(operator_intent=intent),
        json=body,
    )

    assert response.status_code == expected_status
    payload = response.json()
    assert payload == {
        "code": "idempotency_conflict",
        "message": diagnostic,
        "severity": "warning",
        "guard_name": None,
        "field_path": None,
        "correlation_id": CORRELATION_ID,
        "audit_id": payload["audit_id"],
        "live_coinbase_orders_ran": False,
        "current_request_activity": {
            "accounting_scope": "current_request",
            "sdk_mutation_invocation_state": "NOT_INVOKED",
            "transport_submission_state": "NOT_SUBMITTED",
            "exchange_mutation_state": "NOT_MUTATED",
            "read_accounting_state": (
                "UNKNOWN" if live_read_ran else "EXACT"
            ),
            "observed_read_count": None if live_read_ran else 0,
        },
    }
    assert payload["audit_id"]
    assert payload["audit_id"] != service.last_context.audit_id

    assert service.audit_store is not None
    events = list(reversed(service.audit_store.read_recent(limit=10)))
    assert len(events) == 2
    receipt, outcome = events
    assert receipt.status == "received"
    assert outcome.audit_id == payload["audit_id"]
    assert outcome.audit_id != receipt.audit_id
    assert outcome.status == AdminApiCommandStatus.CONFLICT
    assert outcome.message == diagnostic
    assert outcome.failure_stage == failure_stage
    assert outcome.actor_id == "operator-materialization-test"
    assert outcome.action_class == action_class
    assert outcome.permission == permission
    assert outcome.client_order_id == SOURCE_ID
    assert outcome.operator_intent == intent
    assert outcome.request_id == CORRELATION_ID
    assert outcome.live_exchange_submitted is False
    assert outcome.live_coinbase_orders_ran is False
    assert outcome.live_coinbase_read_ran is live_read_ran
    assert outcome.coinbase_order_id is None


def test_audit_receipt_failure_fails_closed_before_materialization_service(client):
    class _FailingAuditStore:
        def find_unique_by_audit_id(self, audit_id: str):
            del audit_id
            return None

        def append_unique(self, event):
            del event
            raise OSError("withheld audit failure")

    http, service = client
    app = http.app
    app.dependency_overrides[order_routes.get_audit_store] = _FailingAuditStore

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        ),
        json={
            "authorize_materialization_of_attached_intent": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["message"] == "follow_up_materialization_audit_unavailable"
    assert response.json()["audit_id"] is None
    assert response.json()["live_coinbase_orders_ran"] is False
    assert response.json()["current_request_activity"][
        "sdk_mutation_invocation_state"
    ] == "NOT_INVOKED"
    assert response.json()["current_request_activity"]["observed_read_count"] == 0
    assert service.materialize_calls == 0
    assert service.cancel_calls == 0


def test_unknown_exchange_boundary_preserves_unknown_without_fabricated_calls(client):
    from application.admin_api.operator_follow_up_materialization import (
        OperatorFollowUpMaterializationError,
    )

    http, service = client
    service.materialize_error = OperatorFollowUpMaterializationError(
        "follow_up_materialization_result_persistence_unavailable",
        503,
    )

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization",
        headers=_headers(
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT
        ),
        json={
            "authorize_materialization_of_attached_intent": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["live_coinbase_orders_ran"] is False
    assert response.json()["current_request_activity"] == {
        "accounting_scope": "current_request",
        "sdk_mutation_invocation_state": "UNKNOWN",
        "transport_submission_state": "POSSIBLY_SUBMITTED",
        "exchange_mutation_state": "UNKNOWN",
        "read_accounting_state": "UNKNOWN",
        "observed_read_count": None,
    }
    assert service.audit_store is not None
    outcome = service.audit_store.read_recent(limit=1)[0]
    assert outcome.failure_stage == "exchange_boundary_outcome_unknown"
    assert outcome.live_coinbase_read_ran is False
    assert outcome.live_coinbase_orders_ran is False
    assert outcome.live_exchange_submitted is False
    assert outcome.current_request_activity is not None
    assert (
        outcome.current_request_activity.sdk_mutation_invocation_state
        == "UNKNOWN"
    )


def test_specialized_post_sdk_error_keeps_submission_possible_not_confirmed() -> None:
    from application.admin_api.operator_follow_up_materialization import (
        OperatorFollowUpMaterializationError,
    )

    stage, live_read, sdk_invoked, submitted, activity = (
        order_routes._follow_up_materialization_execution_evidence(
            OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable",
                503,
                failure_stage="create_result_persistence",
                live_coinbase_read_ran=True,
                live_coinbase_orders_ran=True,
                live_exchange_submitted=True,
            )
        )
    )

    assert stage == "create_result_persistence"
    assert live_read is True
    assert sdk_invoked is True
    assert submitted is False
    assert activity.sdk_mutation_invocation_state == "INVOKED"
    assert activity.transport_submission_state == "POSSIBLY_SUBMITTED"
    assert activity.exchange_mutation_state == "UNKNOWN"
    assert activity.read_accounting_state == "UNKNOWN"
    assert activity.observed_read_count is None


@pytest.mark.parametrize(
    "extra_field",
    [
        "child_client_order_id",
        "exchange_order_id",
        "product_id",
        "environment",
        "portfolio_scope",
    ],
)
def test_safe_closeout_rejects_browser_identity_or_scope_fields(
    client,
    extra_field: str,
):
    http, service = client

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/materialization/safe-closeout",
        headers=_headers(
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT
        ),
        json={
            "authorize_single_cancel_for_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
            extra_field: "browser-value",
        },
    )

    assert response.status_code == 422
    assert service.cancel_calls == 0


@pytest.mark.parametrize(
    ("path_suffix", "operator_intent", "roles"),
    [
        ("materialization", AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT, "auditor"),
        (
            "materialization/safe-closeout",
            SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            "auditor",
        ),
    ],
)
def test_materialization_mutations_enforce_backend_rbac(
    client, path_suffix: str, operator_intent: str, roles: str
):
    http, service = client
    body = (
        {
            "authorize_materialization_of_attached_intent": True,
            "acknowledge_unknown_outcome_consumes_create_allowance": True,
            "acknowledge_child_terms_are_backend_derived": True,
        }
        if path_suffix == "materialization"
        else {
            "authorize_single_cancel_for_safe_closeout": True,
            "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
        }
    )

    response = http.post(
        f"/api/v1/orders/{SOURCE_ID}/follow-up-intent/{path_suffix}",
        headers=_headers(operator_intent=operator_intent, roles=roles),
        json=body,
    )

    assert response.status_code == 403
    assert service.materialize_calls == 0
    assert service.cancel_calls == 0


@pytest.mark.parametrize(
    ("path", "expected_schema"),
    [
        (
            "/api/v1/orders/{source_client_order_id}/follow-up-intent/materialization",
            "AdminOrderFollowUpMaterializationCommandResponse",
        ),
        (
            "/api/v1/orders/{source_client_order_id}/follow-up-intent/materialization/safe-closeout",
            "AdminOrderFollowUpMaterializationCancelResponse",
        ),
    ],
)
def test_materialization_openapi_uses_typed_durable_400_and_409_bodies(
    path: str,
    expected_schema: str,
) -> None:
    openapi_schema = admin_api_app.openapi()
    operation = openapi_schema["paths"][path]["post"]

    for status_code in ("400", "409"):
        schema = operation["responses"][status_code]["content"][
            "application/json"
        ]["schema"]
        assert schema["anyOf"] == [
            {"$ref": f"#/components/schemas/{expected_schema}"},
            {
                "$ref": (
                    "#/components/schemas/"
                    "AdminOrderFollowUpMaterializationErrorResponse"
                )
            },
        ]
    error_schema = openapi_schema["components"]["schemas"][
        "AdminOrderFollowUpMaterializationErrorResponse"
    ]
    assert "current_request_activity" in error_schema["required"]
