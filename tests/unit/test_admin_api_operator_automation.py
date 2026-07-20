"""Typed, local-only operator automation control-plane service tests."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
from typing import Any, Mapping

import pytest
from pydantic import ValidationError

from application.admin_api.automation_models import (
    AutomationControlAction,
    AutomationControlEventItem,
    AutomationControlPlaneItem,
    AutomationControlRequest,
    AutomationDefinitionCreateRequest,
    AutomationDefinitionEventItem,
    AutomationDefinitionItem,
    AutomationDefinitionLifecycleAction,
    AutomationDefinitionLifecycleRequest,
    AutomationDefinitionSchedule,
    AutomationDefinitionScheduleRequest,
    AutomationDomain,
    AutomationEligibilityRefreshActivity,
    AutomationEligibilityCycleMutationResponse,
    AutomationEligibilityRefreshRequest,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationOneShotRunRequest,
    AutomationSingleChildAuthorizationRequest,
    AutomationSingleChildEligibilityReadback,
    AutomationSingleChildPlanReadback,
    AutomationSpotSingleChildOrderSpec,
    AutomationPagination,
    AutomationRunEventItem,
    AutomationRunEventListResponse,
    AutomationRunItem,
    AutomationRunState,
    AutomationScheduleMode,
)
from application.admin_api.operator_automation import (
    AutomationEligibilityRepositoryMutation,
    AutomationRepositoryConflict,
    AutomationRepositoryMutation,
    AutomationRepositoryPage,
    OperatorAutomationError,
    OperatorAutomationService,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"


def _definition(
    *,
    job_kind: str = AutomationJobKind.SPOT_SWEEP.value,
    domain: str = AutomationDomain.SPOT.value,
    state: str = "DRAFT",
    product_ids: list[str] | None = None,
) -> dict[str, Any]:
    resolved_products = product_ids
    if resolved_products is None:
        resolved_products = (
            [] if job_kind == AutomationJobKind.FOLLOW_UP.value else ["BTC-USDC"]
        )
    return {
        "definition_id": DEFINITION_ID,
        "revision": 1,
        "display_name": "Bounded Spot sweep review",
        "domain": domain,
        "job_kind": job_kind,
        "product_ids": resolved_products,
        "lifecycle_state": state,
        "schedule": {
            "mode": AutomationScheduleMode.MANUAL_ONLY.value,
            "interval_minutes": None,
            "next_review_at": None,
            "due": False,
        },
        "adapter_status": "UNAVAILABLE",
        "live_execution_available": False,
        "allowed_actions": ["ENABLE", "DISABLE", "SET_SCHEDULE", "RUN_ONCE"],
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _run() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "definition_id": DEFINITION_ID,
        "domain": AutomationDomain.SPOT.value,
        "job_kind": AutomationJobKind.SPOT_SWEEP.value,
        "trigger": "ONE_SHOT",
        "state": AutomationRunState.BLOCKED.value,
        "diagnostic_code": "automation_domain_adapter_unavailable",
        "adapter_status": "UNAVAILABLE",
        "live_attempt_consumed": False,
        "coinbase_api_call_count": 0,
        "create_call_count": 0,
        "cancel_call_count": 0,
        "client_order_id": None,
        "audit_id": AUDIT_ID,
        "correlation_id": "automation-correlation-1",
        "claimed_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _single_child_run(
    *,
    state: AutomationRunState,
    diagnostic_code: str,
    coinbase_api_call_count: int | None,
    create_call_count: int | None,
    cancel_call_count: int | None,
    call_count_exact: bool,
    child_terminal: bool | None,
) -> dict[str, Any]:
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
    ]
    return {
        **_run(),
        "job_kind": AutomationJobKind.SPOT_CAMPAIGN.value,
        "state": state.value,
        "diagnostic_code": diagnostic_code,
        "adapter_status": state.value,
        "live_attempt_consumed": True,
        "coinbase_api_call_count": coinbase_api_call_count,
        "create_call_count": create_call_count,
        "cancel_call_count": cancel_call_count,
        "call_count_exact": call_count_exact,
        "client_order_id": "4dc878e7-f27b-42b5-adf3-4965b2b916d9",
        "child_terminal": child_terminal,
        "single_child_plan": {
            "plan_sha256": "e" * 64,
            "portfolio_scope": "Test",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.00001",
            "limit_price": "50000.00",
            "submitted_notional_usdc": "0.50",
            "possible_execution_notional_usdc": "0.50",
        },
        "eligibility": {
            "cycle_number": 1,
            "required_categories": categories,
            "completed_categories": categories,
            "eligible": True,
            "blocker_code": None,
            "coinbase_api_call_count": 7,
            "call_count_exact": True,
        },
        "allowed_actions": [],
    }


def _source_gated_single_child_run(
    *,
    cycle_number: int | None = None,
    completed_categories: list[str] | None = None,
    coinbase_api_call_count: int | None = 0,
    call_count_exact: bool = True,
) -> dict[str, Any]:
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
    ]
    return {
        **_run(),
        "job_kind": AutomationJobKind.SPOT_CAMPAIGN.value,
        "state": AutomationRunState.BLOCKED.value,
        "diagnostic_code": "automation_active_order_catalog_read_not_authorized",
        "adapter_status": "BLOCKED",
        "live_execution_available": False,
        "coinbase_api_call_count": coinbase_api_call_count,
        "call_count_exact": call_count_exact,
        "single_child_plan": {
            "plan_sha256": "b" * 64,
            "portfolio_scope": "CONFIGURED_UNVERIFIED",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.00001",
            "limit_price": "50000.00",
            "submitted_notional_usdc": "0.50",
            "possible_execution_notional_usdc": "0.50",
        },
        "eligibility": {
            "cycle_number": cycle_number,
            "required_categories": categories,
            "completed_categories": completed_categories or [],
            "eligible": False,
            "blocker_code": "automation_active_order_catalog_read_not_authorized",
            "coinbase_api_call_count": coinbase_api_call_count,
            "call_count_exact": call_count_exact,
        },
        "allowed_actions": ["REFRESH_ELIGIBILITY"],
    }


def _control() -> dict[str, Any]:
    return {
        "posture": "ACTIVE",
        "local_admission_enabled": True,
        "recurring_worker_started": False,
        "live_scheduler_enabled": False,
        "coinbase_api_call_count": 0,
        "exchange_mutation_count": 0,
        "allowed_actions": ["PAUSE", "DRAIN", "SHUTDOWN"],
        "updated_at": NOW.isoformat(),
    }


@dataclass
class _FakeRepository:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error: Exception | None = None
    replayed: bool = False

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error

    def get_control_posture(self) -> Mapping[str, Any]:
        self._record("get_control_posture")
        return _control()

    def list_definitions(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_definitions", **kwargs)
        return AutomationRepositoryPage(items=(_definition(),), total_count=1)

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None:
        self._record("get_definition", definition_id=definition_id)
        return _definition() if definition_id == DEFINITION_ID else None

    def create_definition(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("create_definition", **kwargs)
        return AutomationRepositoryMutation(
            entity=_definition(),
            audit_id=AUDIT_ID,
            correlation_id="automation-correlation-1",
            replayed=self.replayed,
        )

    def transition_definition(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("transition_definition", **kwargs)
        action = kwargs["action"]
        state = {
            AutomationDefinitionLifecycleAction.ENABLE: "ENABLED",
            AutomationDefinitionLifecycleAction.DISABLE: "DISABLED",
            AutomationDefinitionLifecycleAction.PAUSE: "PAUSED",
            AutomationDefinitionLifecycleAction.RESUME: "ENABLED",
            AutomationDefinitionLifecycleAction.DRAIN: "DRAINING",
        }[action]
        return AutomationRepositoryMutation(
            entity=_definition(state=state),
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def set_schedule(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("set_schedule", **kwargs)
        entity = _definition()
        entity["schedule"] = {
            "mode": "INTERVAL_REVIEW_ONLY",
            "interval_minutes": 60,
            "next_review_at": "2026-07-20T13:00:00+00:00",
            "due": False,
        }
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def clear_schedule(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("clear_schedule", **kwargs)
        return AutomationRepositoryMutation(
            entity=_definition(),
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def transition_control_posture(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("transition_control_posture", **kwargs)
        entity = _control()
        entity["posture"] = kwargs["action"].value
        entity["local_admission_enabled"] = kwargs["action"] is AutomationControlAction.RESUME
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def claim_one_shot_run(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("claim_one_shot_run", **kwargs)
        return AutomationRepositoryMutation(
            entity=_run(),
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def authorize_single_child(self, **kwargs: Any) -> AutomationRepositoryMutation:
        self._record("authorize_single_child", **kwargs)
        return AutomationRepositoryMutation(
            entity=_run(),
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
        )

    def refresh_spot_eligibility(
        self,
        **kwargs: Any,
    ) -> AutomationEligibilityRepositoryMutation:
        self._record("refresh_spot_eligibility", **kwargs)
        return AutomationEligibilityRepositoryMutation(
            entity=_source_gated_single_child_run(
                cycle_number=1,
                completed_categories=[
                    "api_key_permissions",
                    "portfolio_catalog",
                ],
                coinbase_api_call_count=3,
            ),
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
            replayed=self.replayed,
            coinbase_api_call_count=3,
            call_count_exact=True,
        )

    def list_runs(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_runs", **kwargs)
        return AutomationRepositoryPage(items=(_run(),), total_count=1)

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        self._record("get_run", run_id=run_id)
        return _run() if run_id == RUN_ID else None

    def list_run_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_run_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "218d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "run_id": RUN_ID,
                    "sequence": 1,
                    "from_state": None,
                    "state": "CLAIMED",
                    "diagnostic_code": "one_shot_run_claimed",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
                {
                    "event_id": "228d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "run_id": RUN_ID,
                    "sequence": 2,
                    "from_state": "CLAIMED",
                    "state": "BLOCKED",
                    "diagnostic_code": "automation_domain_adapter_unavailable",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=2,
        )

    def list_definition_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_definition_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "318d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "definition_id": DEFINITION_ID,
                    "from_state": None,
                    "to_state": "DRAFT",
                    "diagnostic_code": "automation_definition_created",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=1,
        )

    def list_control_events(self, **kwargs: Any) -> AutomationRepositoryPage:
        self._record("list_control_events", **kwargs)
        return AutomationRepositoryPage(
            items=(
                {
                    "event_id": "418d5f34-a054-410b-9c92-ddd09dcd6b03",
                    "from_state": "ACTIVE",
                    "to_state": "PAUSED",
                    "diagnostic_code": "automation_control_pause",
                    "audit_id": AUDIT_ID,
                    "correlation_id": "automation-route-correlation",
                    "recorded_at": NOW.isoformat(),
                },
            ),
            total_count=1,
        )


def _context() -> AutomationMutationContext:
    return AutomationMutationContext(
        actor_id="operator-automation-test",
        roles=("trader",),
        idempotency_key="automation-idempotency-1",
        correlation_id="automation-correlation-1",
        operator_intent="create_automation_definition",
    )


def test_create_request_is_strict_and_never_accepts_a_futures_domain_or_payload():
    request = AutomationDefinitionCreateRequest(
        display_name="Spot sweep",
        job_kind=AutomationJobKind.SPOT_SWEEP,
        product_ids=["BTC-USDC"],
    )
    assert request.job_kind is AutomationJobKind.SPOT_SWEEP

    with pytest.raises(ValidationError):
        AutomationDefinitionCreateRequest.model_validate(
            {
                "display_name": "Futures sweep",
                "job_kind": "FUTURES_SWEEP",
            }
        )
    with pytest.raises(ValidationError):
        AutomationDefinitionCreateRequest.model_validate(
            {
                "display_name": "Spot sweep",
                "job_kind": "SPOT_SWEEP",
                "product_ids": ["BTC-USDC"],
                "executor_payload": {"product_id": "AVP-20DEC30-CDE"},
            }
        )


def test_single_child_definition_spec_is_typed_btc_usdc_campaign_only():
    spec = AutomationSpotSingleChildOrderSpec(
        side="BUY",
        base_size="0.00001",
        limit_price="50000.00",
    )
    request = AutomationDefinitionCreateRequest(
        display_name="One bounded BTC child",
        job_kind=AutomationJobKind.SPOT_CAMPAIGN,
        product_ids=["BTC-USDC"],
        single_child_order=spec,
    )

    assert request.single_child_order == spec
    assert request.single_child_order.order_type == "LIMIT"
    assert request.single_child_order.time_in_force == "GOOD_UNTIL_CANCELLED"
    assert request.single_child_order.post_only is False

    for job_kind in (
        AutomationJobKind.SPOT_SWEEP,
        AutomationJobKind.SPOT_LADDER,
        AutomationJobKind.FOLLOW_UP,
    ):
        with pytest.raises(
            ValidationError,
            match="automation_single_child_job_kind_blocked",
        ):
            AutomationDefinitionCreateRequest(
                display_name="Unsupported single child",
                job_kind=job_kind,
                product_ids=(
                    []
                    if job_kind is AutomationJobKind.FOLLOW_UP
                    else ["BTC-USDC"]
                ),
                single_child_order=spec,
            )

    with pytest.raises(ValidationError):
        AutomationSpotSingleChildOrderSpec.model_validate(
            {
                "side": "BUY",
                "base_size": "0.00001",
                "limit_price": "50000.00",
                "order_type": "MARKET",
            }
        )


def test_exact_run_authorization_accepts_only_acknowledgements_and_plan_hash():
    body = AutomationSingleChildAuthorizationRequest(
        confirm_single_child_create=True,
        confirm_exact_child_safe_closeout_cancel=True,
        confirm_unknown_consumes_allowance=True,
        expected_plan_sha256="a" * 64,
        reason="Authorize this exact prepared child once",
    )
    assert body.confirm_single_child_create is True
    assert body.confirm_exact_child_safe_closeout_cancel is True
    assert body.confirm_unknown_consumes_allowance is True

    with pytest.raises(ValidationError):
        AutomationSingleChildAuthorizationRequest.model_validate(
            {
                key: value
                for key, value in body.model_dump(mode="json").items()
                if key != "confirm_exact_child_safe_closeout_cancel"
            }
        )

    with pytest.raises(ValidationError):
        AutomationSingleChildAuthorizationRequest.model_validate(
            {
                **body.model_dump(mode="json"),
                "product_id": "BTC-USDC",
                "client_order_id": RUN_ID,
                "limit_price": "50000.00",
            }
        )


def test_spot_eligibility_refresh_request_requires_both_consumption_acknowledgements():
    body = AutomationEligibilityRefreshRequest(
        confirm_approved_eligibility_reads=True,
        confirm_unknown_consumes_cycle=True,
        expected_plan_sha256="a" * 64,
        reason="Refresh this exact source-gated run",
    )

    assert body.model_dump(mode="json") == {
        "confirm_approved_eligibility_reads": True,
        "confirm_unknown_consumes_cycle": True,
        "expected_plan_sha256": "a" * 64,
        "reason": "Refresh this exact source-gated run",
    }
    for field_name in (
        "confirm_approved_eligibility_reads",
        "confirm_unknown_consumes_cycle",
    ):
        with pytest.raises(ValidationError):
            AutomationEligibilityRefreshRequest.model_validate(
                {
                    key: value
                    for key, value in body.model_dump(mode="json").items()
                    if key != field_name
                }
            )


def test_spot_eligibility_refresh_activity_is_read_only_and_truthful():
    exact = AutomationEligibilityRefreshActivity(
        coinbase_api_call_count=8,
        call_count_exact=True,
    )
    assert exact.model_dump(mode="json") == {
        "coinbase_api_call_count": 8,
        "exchange_mutation_count": 0,
        "create_call_count": 0,
        "cancel_call_count": 0,
        "call_count_exact": True,
        "recurring_worker_started": False,
    }

    unknown = AutomationEligibilityRefreshActivity(
        coinbase_api_call_count=None,
        call_count_exact=False,
    )
    assert unknown.coinbase_api_call_count is None

    with pytest.raises(ValidationError):
        AutomationEligibilityRefreshActivity(
            coinbase_api_call_count=None,
            call_count_exact=True,
        )
    with pytest.raises(ValidationError):
        AutomationEligibilityRefreshActivity(
            coinbase_api_call_count=1,
            call_count_exact=False,
        )


def test_single_child_run_readback_is_backend_owned_and_truthful():
    plan = AutomationSingleChildPlanReadback(
        plan_sha256="b" * 64,
        portfolio_scope="Test",
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="50000.00",
        submitted_notional_usdc="0.50",
        possible_execution_notional_usdc="0.50",
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.00",
    )
    eligibility = AutomationSingleChildEligibilityReadback(
        cycle_number=1,
        required_categories=[
            "api_key_permissions",
            "portfolio_catalog",
            "wallet_balances",
            "product_metadata",
            "best_bid_ask",
            "fee_summary",
            "exact_order_reconciliation",
        ],
        completed_categories=["api_key_permissions"],
        eligible=False,
        blocker_code="automation_eligibility_incomplete",
        coinbase_api_call_count=1,
        call_count_exact=True,
    )
    item = AutomationRunItem.model_validate(
        {
            **_run(),
            "job_kind": "SPOT_CAMPAIGN",
            "state": "AWAITING_OPERATOR_AUTHORIZATION",
            "diagnostic_code": "awaiting_operator_authorization",
            "adapter_status": "AWAITING_OPERATOR_AUTHORIZATION",
            "single_child_plan": plan.model_dump(mode="json"),
            "eligibility": eligibility.model_dump(mode="json"),
            "allowed_actions": [],
        }
    )

    assert item.single_child_plan.product_id == "BTC-USDC"
    assert item.single_child_plan.max_submitted_notional_usdc == "3.10"
    assert item.single_child_plan.max_possible_execution_notional_usdc == "1.00"
    assert item.eligibility.blocker_code == "automation_eligibility_incomplete"
    assert item.live_execution_available is False


def test_source_gated_single_child_run_exposes_only_offline_eligibility_refresh():
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
    ]
    item = AutomationRunItem.model_validate(
        {
            **_run(),
            "job_kind": "SPOT_CAMPAIGN",
            "state": "BLOCKED",
            "diagnostic_code": (
                "automation_active_order_catalog_read_not_authorized"
            ),
            "adapter_status": "BLOCKED",
            "live_execution_available": False,
            "call_count_exact": True,
            "single_child_plan": {
                "plan_sha256": "b" * 64,
                "portfolio_scope": "CONFIGURED_UNVERIFIED",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "base_size": "0.00001",
                "limit_price": "50000.00",
                "submitted_notional_usdc": "0.50",
                "possible_execution_notional_usdc": "0.50",
            },
            "eligibility": {
                "cycle_number": None,
                "required_categories": categories,
                "completed_categories": [],
                "eligible": False,
                "blocker_code": (
                    "automation_active_order_catalog_read_not_authorized"
                ),
                "coinbase_api_call_count": 0,
                "call_count_exact": True,
            },
            "allowed_actions": ["REFRESH_ELIGIBILITY"],
        }
    )

    assert item.allowed_actions == ["REFRESH_ELIGIBILITY"]
    assert item.live_execution_available is False

    with pytest.raises(ValidationError):
        AutomationRunItem.model_validate(
            {
                **item.model_dump(mode="json"),
                "state": "PREPARING",
                "diagnostic_code": "automation_spot_source_gate_resumed",
            }
        )


def test_single_child_action_requires_trigger_create_and_cancel_permissions(
    monkeypatch: pytest.MonkeyPatch,
):
    from api.v1.routes import operator_automation as automation_routes
    from application.admin_api.models import AdminApiActor
    from core.enums import AdminApiPermission, AdminApiRole

    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
    ]
    item = AutomationRunItem.model_validate(
        {
            **_run(),
            "job_kind": "SPOT_CAMPAIGN",
            "state": "AWAITING_OPERATOR_AUTHORIZATION",
            "diagnostic_code": "awaiting_operator_authorization",
            "adapter_status": "AWAITING_OPERATOR_AUTHORIZATION",
            "live_execution_available": True,
            "single_child_plan": {
                "plan_sha256": "b" * 64,
                "portfolio_scope": "Test",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "base_size": "0.00001",
                "limit_price": "50000.00",
                "submitted_notional_usdc": "0.50",
                "possible_execution_notional_usdc": "0.50",
            },
            "eligibility": {
                "cycle_number": 1,
                "required_categories": categories,
                "completed_categories": categories,
                "eligible": True,
                "blocker_code": None,
                "coinbase_api_call_count": 7,
                "call_count_exact": True,
            },
            "allowed_actions": ["AUTHORIZE_SINGLE_CHILD"],
        }
    )
    actor = AdminApiActor(actor_id="trader", roles=[AdminApiRole.TRADER])
    required = {
        AdminApiPermission.AUTOMATION_TRIGGER,
        AdminApiPermission.ORDER_CREATE,
        AdminApiPermission.ORDER_CANCEL,
    }

    for missing in required:
        monkeypatch.setattr(
            automation_routes,
            "actor_has_permission",
            lambda _actor, permission, missing=missing: permission != missing,
        )
        scoped = automation_routes._scope_run_item(item, actor)
        assert scoped.allowed_actions == []
        assert scoped.live_execution_available is False

    monkeypatch.setattr(
        automation_routes,
        "actor_has_permission",
        lambda _actor, permission: permission in required,
    )
    scoped = automation_routes._scope_run_item(item, actor)
    assert scoped.allowed_actions == ["AUTHORIZE_SINGLE_CHILD"]
    assert scoped.live_execution_available is True


def test_eligibility_refresh_action_requires_trigger_resume_and_refresh_permissions(
    monkeypatch: pytest.MonkeyPatch,
):
    from api.v1.routes import operator_automation as automation_routes
    from application.admin_api.models import AdminApiActor
    from core.enums import AdminApiPermission, AdminApiRole

    item = AutomationRunItem.model_validate(_source_gated_single_child_run())
    actor = AdminApiActor(actor_id="trader", roles=[AdminApiRole.TRADER])
    required = {
        AdminApiPermission.AUTOMATION_TRIGGER,
        AdminApiPermission.AUTOMATION_RESUME,
        AdminApiPermission.ACCOUNT_REALITY_REFRESH,
    }

    for missing in required:
        monkeypatch.setattr(
            automation_routes,
            "actor_has_permission",
            lambda _actor, permission, missing=missing: permission != missing,
        )
        scoped = automation_routes._scope_run_item(item, actor)
        assert scoped.allowed_actions == []
        assert scoped.live_execution_available is False

    monkeypatch.setattr(
        automation_routes,
        "actor_has_permission",
        lambda _actor, permission: permission in required,
    )
    scoped = automation_routes._scope_run_item(item, actor)
    assert scoped.allowed_actions == ["REFRESH_ELIGIBILITY"]
    assert scoped.live_execution_available is False


def test_unknown_single_child_run_never_reports_an_exact_zero_call_count():
    with pytest.raises(ValidationError, match="automation_run_unknown_call_count_invalid"):
        AutomationRunItem.model_validate(
            {
                **_run(),
                "job_kind": "SPOT_CAMPAIGN",
                "state": "UNKNOWN_CONSUMED",
                "diagnostic_code": "unknown_consumed",
                "adapter_status": "UNKNOWN_CONSUMED",
                "live_attempt_consumed": True,
                "coinbase_api_call_count": 0,
                "create_call_count": 0,
                "call_count_exact": True,
            }
        )

    item = AutomationRunItem.model_validate(
        {
            **_run(),
            "job_kind": "SPOT_CAMPAIGN",
            "state": "UNKNOWN_CONSUMED",
            "diagnostic_code": "unknown_consumed",
            "adapter_status": "UNKNOWN_CONSUMED",
            "live_attempt_consumed": True,
            "coinbase_api_call_count": None,
            "create_call_count": None,
            "call_count_exact": False,
        }
    )
    assert item.coinbase_api_call_count is None
    assert item.create_call_count is None


def test_run_mutation_activity_supports_exact_create_cancel_and_unknown_boundaries():
    from application.admin_api.automation_models import (
        AutomationNoExchangeActivity,
        AutomationRunMutationActivity,
    )

    assert AutomationNoExchangeActivity().model_dump(mode="json") == {
        "coinbase_api_call_count": 0,
        "exchange_mutation_count": 0,
        "create_call_count": 0,
        "cancel_call_count": 0,
        "call_count_exact": True,
        "recurring_worker_started": False,
    }
    with pytest.raises(ValidationError):
        AutomationNoExchangeActivity(coinbase_api_call_count=1)

    exact_create_and_cancel = AutomationRunMutationActivity(
        coinbase_api_call_count=3,
        exchange_mutation_count=2,
        create_call_count=1,
        cancel_call_count=1,
        call_count_exact=True,
    )
    assert exact_create_and_cancel.exchange_mutation_count == 2

    unknown_create = AutomationRunMutationActivity(
        coinbase_api_call_count=None,
        exchange_mutation_count=None,
        create_call_count=None,
        cancel_call_count=0,
        call_count_exact=False,
    )
    assert unknown_create.create_call_count is None

    unknown_cancel = AutomationRunMutationActivity(
        coinbase_api_call_count=None,
        exchange_mutation_count=None,
        create_call_count=1,
        cancel_call_count=None,
        call_count_exact=False,
    )
    assert unknown_cancel.create_call_count == 1

    unknown_post_create_read = AutomationRunMutationActivity(
        coinbase_api_call_count=None,
        exchange_mutation_count=1,
        create_call_count=1,
        cancel_call_count=0,
        call_count_exact=False,
    )
    assert unknown_post_create_read.exchange_mutation_count == 1


@pytest.mark.parametrize(
    (
        "coinbase_api_call_count",
        "exchange_mutation_count",
        "create_call_count",
        "cancel_call_count",
        "call_count_exact",
    ),
    [
        (0, 1, 1, 0, True),
        (2, 1, 1, 1, True),
        (1, 1, 0, 1, True),
        (None, None, None, 0, True),
        (0, 0, 0, 0, False),
        (None, 0, 0, 0, False),
        (None, None, 1, 0, False),
        (None, 2, 1, None, False),
    ],
)
def test_run_mutation_activity_rejects_incoherent_partial_evidence(
    coinbase_api_call_count: int | None,
    exchange_mutation_count: int | None,
    create_call_count: int | None,
    cancel_call_count: int | None,
    call_count_exact: bool,
):
    from application.admin_api.automation_models import (
        AutomationRunMutationActivity,
    )

    with pytest.raises(ValidationError):
        AutomationRunMutationActivity(
            coinbase_api_call_count=coinbase_api_call_count,
            exchange_mutation_count=exchange_mutation_count,
            create_call_count=create_call_count,
            cancel_call_count=cancel_call_count,
            call_count_exact=call_count_exact,
        )


@pytest.mark.parametrize("invalid_text", ["   ", "operator\nwithheld"])
def test_operator_text_fields_reject_blank_or_multiline_values(invalid_text: str):
    with pytest.raises(ValidationError, match="automation_display_name_invalid"):
        AutomationDefinitionCreateRequest(
            display_name=invalid_text,
            job_kind=AutomationJobKind.SPOT_SWEEP,
            product_ids=["BTC-USDC"],
        )
    with pytest.raises(ValidationError, match="automation_reason_invalid"):
        AutomationDefinitionLifecycleRequest(reason=invalid_text)
    with pytest.raises(ValidationError, match="automation_reason_invalid"):
        AutomationControlRequest(reason=invalid_text)
    with pytest.raises(ValidationError, match="automation_reason_invalid"):
        AutomationOneShotRunRequest(
            confirm_one_shot=True,
            reason=invalid_text,
        )


def test_operator_text_fields_are_trimmed_before_hashing_or_readback():
    create = AutomationDefinitionCreateRequest(
        display_name="  Bounded Spot sweep  ",
        job_kind=AutomationJobKind.SPOT_SWEEP,
        product_ids=["BTC-USDC"],
    )
    lifecycle = AutomationDefinitionLifecycleRequest(reason="  Explicit pause  ")
    control = AutomationControlRequest(reason="  Explicit drain  ")
    one_shot = AutomationOneShotRunRequest(
        confirm_one_shot=True,
        reason="  Explicit one-shot  ",
    )
    assert create.display_name == "Bounded Spot sweep"
    assert lifecycle.reason == "Explicit pause"
    assert control.reason == "Explicit drain"
    assert one_shot.reason == "Explicit one-shot"


@pytest.mark.parametrize("product_ids", [[], ["AVP-20DEC30-CDE"], ["ETH-USDC"]])
def test_spot_definition_scope_is_bound_to_backend_approved_products(product_ids):
    with pytest.raises(ValidationError, match="automation_spot_product_policy_blocked"):
        AutomationDefinitionCreateRequest(
            display_name="Bounded Spot sweep",
            job_kind=AutomationJobKind.SPOT_SWEEP,
            product_ids=product_ids,
        )

    with pytest.raises(ValidationError, match="automation_spot_product_policy_blocked"):
        AutomationDefinitionItem.model_validate(
            _definition(product_ids=product_ids)
        )


def test_definition_and_control_event_models_reject_impossible_source_transitions():
    with pytest.raises(ValidationError, match="automation_definition_event_invalid"):
        AutomationDefinitionEventItem(
            event_id="318d5f34-a054-410b-9c92-ddd09dcd6b03",
            definition_id=DEFINITION_ID,
            from_state="ENABLED",
            to_state="ENABLED",
            diagnostic_code="automation_definition_resume",
            audit_id=AUDIT_ID,
            correlation_id="automation-correlation-1",
            recorded_at=NOW,
        )

    with pytest.raises(ValidationError, match="automation_control_event_invalid"):
        AutomationControlEventItem(
            event_id="418d5f34-a054-410b-9c92-ddd09dcd6b03",
            from_state="SHUTDOWN",
            to_state="PAUSED",
            diagnostic_code="automation_control_pause",
            audit_id=AUDIT_ID,
            correlation_id="automation-correlation-1",
            recorded_at=NOW,
        )


def test_run_event_model_accepts_durable_source_gate_rejection_without_state_change():
    event = AutomationRunEventItem(
        event_id="218d5f34-a054-410b-9c92-ddd09dcd6b09",
        run_id=RUN_ID,
        sequence=3,
        from_state="BLOCKED",
        state="BLOCKED",
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        audit_id=AUDIT_ID,
        correlation_id="automation-correlation-source-gate",
        recorded_at=NOW,
    )

    assert event.from_state is AutomationRunState.BLOCKED
    assert event.state is AutomationRunState.BLOCKED


@pytest.mark.parametrize(
    "events",
    [
        (
            (1, None, "CLAIMED", "one_shot_run_claimed"),
            (2, "PREPARING", "BLOCKED", "automation_run_blocked"),
        ),
        (
            (1, None, "CLAIMED", "one_shot_run_claimed"),
            (3, "CLAIMED", "BLOCKED", "automation_run_blocked"),
        ),
        (
            (2, "CLAIMED", "BLOCKED", "automation_run_blocked"),
            (1, None, "CLAIMED", "one_shot_run_claimed"),
        ),
    ],
)
def test_run_event_list_rejects_disconnected_gapped_or_out_of_order_history(events):
    items = [
        AutomationRunEventItem(
            event_id=f"218d5f34-a054-410b-9c92-ddd09dcd6b0{index}",
            run_id=RUN_ID,
            sequence=sequence,
            from_state=from_state,
            state=state,
            diagnostic_code=diagnostic,
            audit_id=AUDIT_ID,
            correlation_id="automation-correlation-1",
            recorded_at=NOW,
        )
        for index, (sequence, from_state, state, diagnostic) in enumerate(events, 1)
    ]
    with pytest.raises(ValidationError, match="automation_event_(sequence|chain)_invalid"):
        AutomationRunEventListResponse(
            run_id=RUN_ID,
            count=2,
            pagination=AutomationPagination(
                limit=100,
                offset=0,
                returned_count=2,
                total_matching_count=2,
                next_offset=None,
                has_more=False,
            ),
            items=items,
        )


def test_run_event_list_allows_only_terminal_empty_pages_after_the_root_event():
    terminal = AutomationRunEventListResponse(
        run_id=RUN_ID,
        count=0,
        pagination=AutomationPagination(
            limit=100,
            offset=2,
            returned_count=0,
            total_matching_count=2,
            next_offset=None,
            has_more=False,
        ),
        items=[],
    )
    assert terminal.items == []

    with pytest.raises(ValidationError, match="automation_event_chain_invalid"):
        AutomationRunEventListResponse(
            run_id=RUN_ID,
            count=0,
            pagination=AutomationPagination(
                limit=100,
                offset=0,
                returned_count=0,
                total_matching_count=0,
                next_offset=None,
                has_more=False,
            ),
            items=[],
        )
@pytest.mark.parametrize(
    ("job_kind", "expected_domain"),
    [
        (AutomationJobKind.SPOT_CAMPAIGN, AutomationDomain.SPOT),
        (AutomationJobKind.SPOT_SWEEP, AutomationDomain.SPOT),
        (AutomationJobKind.SPOT_LADDER, AutomationDomain.SPOT),
        (AutomationJobKind.FOLLOW_UP, AutomationDomain.ORDERS),
    ],
)
def test_service_derives_domain_from_typed_kind_and_browser_cannot_choose_it(
    job_kind: AutomationJobKind,
    expected_domain: AutomationDomain,
):
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)

    service.create_definition(
        AutomationDefinitionCreateRequest(
            display_name=f"{job_kind.value} definition",
            job_kind=job_kind,
            product_ids=(
                []
                if job_kind is AutomationJobKind.FOLLOW_UP
                else ["BTC-USDC"]
            ),
        ),
        _context(),
    )

    name, kwargs = repository.calls[-1]
    assert name == "create_definition"
    assert kwargs["definition"]["domain"] == expected_domain.value
    assert "domain" not in AutomationDefinitionCreateRequest.model_fields


def test_definition_model_rejects_cross_domain_kind_and_live_adapter_claims():
    invalid = _definition(
        job_kind=AutomationJobKind.SPOT_SWEEP.value,
        domain=AutomationDomain.ORDERS.value,
    )
    with pytest.raises(ValidationError):
        AutomationDefinitionItem.model_validate(invalid)

    live = _definition()
    live["live_execution_available"] = True
    with pytest.raises(ValidationError):
        AutomationDefinitionItem.model_validate(live)


def test_schedule_model_requires_interval_only_for_review_mode():
    manual = AutomationDefinitionSchedule(mode=AutomationScheduleMode.MANUAL_ONLY)
    assert manual.interval_minutes is None

    with pytest.raises(
        ValidationError,
        match="automation_schedule_next_review_required",
    ):
        AutomationDefinitionSchedule(
            mode=AutomationScheduleMode.INTERVAL_REVIEW_ONLY,
            interval_minutes=60,
        )
    interval = AutomationDefinitionSchedule(
        mode=AutomationScheduleMode.INTERVAL_REVIEW_ONLY,
        interval_minutes=60,
        next_review_at=NOW,
    )
    assert interval.next_review_at == NOW

    with pytest.raises(ValidationError):
        AutomationDefinitionScheduleRequest(
            mode=AutomationScheduleMode.INTERVAL_REVIEW_ONLY,
        )
    with pytest.raises(ValidationError):
        AutomationDefinitionScheduleRequest(
            mode=AutomationScheduleMode.MANUAL_ONLY,
            interval_minutes=60,
        )


def test_service_builds_backend_pagination_and_passes_typed_filters_once():
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)

    response = service.list_definitions(
        domain=AutomationDomain.SPOT,
        job_kind=AutomationJobKind.SPOT_SWEEP,
        lifecycle_state=None,
        limit=25,
        offset=0,
    )

    assert response.count == 1
    assert response.pagination.total_matching_count == 1
    assert response.pagination.has_more is False
    assert repository.calls == [
        (
            "list_definitions",
            {
                "domain": "SPOT",
                "job_kind": "SPOT_SWEEP",
                "lifecycle_state": None,
                "limit": 25,
                "offset": 0,
            },
        )
    ]


def test_service_rejects_cross_domain_filters_as_a_fixed_client_error():
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)

    with pytest.raises(OperatorAutomationError) as mismatch:
        service.list_definitions(
            domain=AutomationDomain.SPOT,
            job_kind=AutomationJobKind.FOLLOW_UP,
            lifecycle_state=None,
            limit=25,
            offset=0,
        )

    assert mismatch.value.code == "automation_filter_domain_kind_mismatch"
    assert mismatch.value.http_status_code == 422
    assert repository.calls == []


def test_one_shot_claim_is_terminally_blocked_and_reports_exact_zero_activity():
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)

    response = service.claim_one_shot_run(
        definition_id=DEFINITION_ID,
        request=AutomationOneShotRunRequest(
            confirm_one_shot=True,
            reason="Explicit local adapter-readiness review",
        ),
        context=_context().model_copy(
            update={"operator_intent": "claim_automation_one_shot_run"}
        ),
    )

    assert response.run.state is AutomationRunState.BLOCKED
    assert response.run.live_attempt_consumed is False
    assert response.run.coinbase_api_call_count == 0
    assert response.run.create_call_count == 0
    assert response.run.cancel_call_count == 0
    assert response.activity.coinbase_api_call_count == 0
    assert response.activity.exchange_mutation_count == 0


def test_single_child_authorization_forwards_only_exact_acknowledgements():
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)
    request = AutomationSingleChildAuthorizationRequest(
        confirm_single_child_create=True,
        confirm_exact_child_safe_closeout_cancel=True,
        confirm_unknown_consumes_allowance=True,
        expected_plan_sha256="d" * 64,
        reason="Authorize the exact prepared child",
    )

    response = service.authorize_single_child(
        run_id=RUN_ID,
        request=request,
        context=_context().model_copy(
            update={
                "operator_intent": (
                    "authorize_automation_single_child_create_and_safe_closeout"
                )
            }
        ),
    )

    name, kwargs = repository.calls[-1]
    assert name == "authorize_single_child"
    assert kwargs["run_id"] == RUN_ID
    assert kwargs["request"] == request.model_dump(mode="json")
    assert response.run.client_order_id is None
    assert response.activity.exchange_mutation_count == 0


def test_spot_eligibility_refresh_forwards_exact_request_and_current_cycle_activity():
    repository = _FakeRepository()
    request = AutomationEligibilityRefreshRequest(
        confirm_approved_eligibility_reads=True,
        confirm_unknown_consumes_cycle=True,
        expected_plan_sha256="b" * 64,
        reason="Refresh this exact source-gated run",
    )
    context = _context().model_copy(
        update={"operator_intent": "refresh_automation_spot_eligibility"}
    )

    response = OperatorAutomationService(repository).refresh_spot_eligibility(
        run_id=RUN_ID,
        request=request,
        context=context,
    )

    assert isinstance(response, AutomationEligibilityCycleMutationResponse)
    assert response.run.state is AutomationRunState.BLOCKED
    assert response.run.live_execution_available is False
    assert response.run.live_attempt_consumed is False
    assert response.activity.coinbase_api_call_count == 3
    assert response.activity.exchange_mutation_count == 0
    assert response.activity.create_call_count == 0
    assert response.activity.cancel_call_count == 0
    assert response.activity.call_count_exact is True
    name, kwargs = repository.calls[-1]
    assert name == "refresh_spot_eligibility"
    assert kwargs["run_id"] == RUN_ID
    assert kwargs["request"] == request.model_dump(mode="json")
    assert kwargs["context"] == context


def test_single_child_authorization_activity_excludes_prior_eligibility_reads():
    repository = _FakeRepository()
    categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallet_balances",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
        "exact_order_reconciliation",
    ]
    plan = AutomationSingleChildPlanReadback(
        plan_sha256="e" * 64,
        portfolio_scope="Test",
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="50000.00",
        submitted_notional_usdc="0.50",
        possible_execution_notional_usdc="0.50",
    )
    entity = {
        **_run(),
        "job_kind": "SPOT_CAMPAIGN",
        "state": "TERMINAL",
        "diagnostic_code": "automation_spot_create_rejected",
        "adapter_status": "TERMINAL",
        "live_attempt_consumed": True,
        "coinbase_api_call_count": 8,
        "create_call_count": 1,
        "cancel_call_count": 0,
        "call_count_exact": True,
        "client_order_id": "4dc878e7-f27b-42b5-adf3-4965b2b916d9",
        "child_terminal": False,
        "single_child_plan": plan.model_dump(mode="json"),
        "eligibility": {
            "cycle_number": 1,
            "required_categories": categories,
            "completed_categories": categories,
            "eligible": True,
            "blocker_code": None,
            "coinbase_api_call_count": 7,
            "call_count_exact": True,
        },
        "allowed_actions": [],
    }

    def authorize_single_child(**kwargs: Any) -> AutomationRepositoryMutation:
        repository._record("authorize_single_child", **kwargs)
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
        )

    repository.authorize_single_child = authorize_single_child  # type: ignore[method-assign]
    service = OperatorAutomationService(repository)
    response = service.authorize_single_child(
        run_id=RUN_ID,
        request=AutomationSingleChildAuthorizationRequest(
            confirm_single_child_create=True,
            confirm_exact_child_safe_closeout_cancel=True,
            confirm_unknown_consumes_allowance=True,
            expected_plan_sha256="e" * 64,
            reason="Authorize the exact prepared child",
        ),
        context=_context().model_copy(
            update={
                "operator_intent": (
                    "authorize_automation_single_child_create_and_safe_closeout"
                )
            }
        ),
    )

    assert response.run.coinbase_api_call_count == 8
    assert response.activity.coinbase_api_call_count == 1
    assert response.activity.create_call_count == 1
    assert response.activity.exchange_mutation_count == 1
    assert response.activity.call_count_exact is True


def test_single_child_authorization_activity_reports_optional_safe_closeout():
    repository = _FakeRepository()
    entity = _single_child_run(
        state=AutomationRunState.TERMINAL,
        diagnostic_code="automation_spot_cancel_accepted_terminal",
        coinbase_api_call_count=9,
        create_call_count=1,
        cancel_call_count=1,
        call_count_exact=True,
        child_terminal=True,
    )

    def authorize_single_child(**kwargs: Any) -> AutomationRepositoryMutation:
        repository._record("authorize_single_child", **kwargs)
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
        )

    repository.authorize_single_child = authorize_single_child  # type: ignore[method-assign]
    response = OperatorAutomationService(repository).authorize_single_child(
        run_id=RUN_ID,
        request=AutomationSingleChildAuthorizationRequest(
            confirm_single_child_create=True,
            confirm_exact_child_safe_closeout_cancel=True,
            confirm_unknown_consumes_allowance=True,
            expected_plan_sha256="e" * 64,
            reason="Authorize one child and its exact safe closeout",
        ),
        context=_context().model_copy(
            update={
                "operator_intent": (
                    "authorize_automation_single_child_create_and_safe_closeout"
                )
            }
        ),
    )

    assert response.activity.coinbase_api_call_count == 2
    assert response.activity.exchange_mutation_count == 2
    assert response.activity.create_call_count == 1
    assert response.activity.cancel_call_count == 1
    assert response.activity.call_count_exact is True


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        (
            _single_child_run(
                state=AutomationRunState.UNKNOWN_CONSUMED,
                diagnostic_code="automation_spot_create_unknown_consumed",
                coinbase_api_call_count=None,
                create_call_count=None,
                cancel_call_count=0,
                call_count_exact=False,
                child_terminal=None,
            ),
            (None, None, None, 0),
        ),
        (
            _single_child_run(
                state=AutomationRunState.UNKNOWN_CONSUMED,
                diagnostic_code="automation_spot_cancel_unknown_consumed",
                coinbase_api_call_count=None,
                create_call_count=1,
                cancel_call_count=None,
                call_count_exact=False,
                child_terminal=None,
            ),
            (None, None, 1, None),
        ),
        (
            _single_child_run(
                state=AutomationRunState.ACTIVE,
                diagnostic_code="automation_spot_create_accepted_active",
                coinbase_api_call_count=None,
                create_call_count=1,
                cancel_call_count=0,
                call_count_exact=False,
                child_terminal=False,
            ),
            (None, 1, 1, 0),
        ),
    ],
)
def test_single_child_authorization_activity_preserves_strict_unknown_boundary(
    entity: dict[str, Any],
    expected: tuple[int | None, int | None, int | None, int | None],
):
    repository = _FakeRepository()

    def authorize_single_child(**kwargs: Any) -> AutomationRepositoryMutation:
        repository._record("authorize_single_child", **kwargs)
        return AutomationRepositoryMutation(
            entity=entity,
            audit_id=AUDIT_ID,
            correlation_id=kwargs["context"].correlation_id,
        )

    repository.authorize_single_child = authorize_single_child  # type: ignore[method-assign]
    response = OperatorAutomationService(repository).authorize_single_child(
        run_id=RUN_ID,
        request=AutomationSingleChildAuthorizationRequest(
            confirm_single_child_create=True,
            confirm_exact_child_safe_closeout_cancel=True,
            confirm_unknown_consumes_allowance=True,
            expected_plan_sha256="e" * 64,
            reason="Authorize one child and its exact safe closeout",
        ),
        context=_context().model_copy(
            update={
                "operator_intent": (
                    "authorize_automation_single_child_create_and_safe_closeout"
                )
            }
        ),
    )

    assert (
        response.activity.coinbase_api_call_count,
        response.activity.exchange_mutation_count,
        response.activity.create_call_count,
        response.activity.cancel_call_count,
    ) == expected
    assert response.activity.call_count_exact is False


def test_run_model_projects_restart_recovery_without_weakening_v1_call_evidence():
    initial_claim = {
        **_run(),
        "state": AutomationRunState.CLAIMED.value,
        "diagnostic_code": "one_shot_run_claimed",
    }
    initial_claim_item = AutomationRunItem.model_validate(initial_claim)
    assert initial_claim_item.state is AutomationRunState.CLAIMED
    assert initial_claim_item.live_attempt_consumed is False

    recovered = {
        **_run(),
        "diagnostic_code": "restart_pre_invocation_blocked",
    }
    recovered_item = AutomationRunItem.model_validate(recovered)
    assert recovered_item.state is AutomationRunState.BLOCKED
    assert recovered_item.live_attempt_consumed is False

    quarantined = {
        **_run(),
        "state": AutomationRunState.UNKNOWN_CONSUMED.value,
        "diagnostic_code": "restart_unknown_consumed",
        "live_attempt_consumed": True,
        "coinbase_api_call_count": None,
        "create_call_count": None,
        "cancel_call_count": None,
        "call_count_exact": False,
    }
    quarantined_item = AutomationRunItem.model_validate(quarantined)
    assert quarantined_item.state is AutomationRunState.UNKNOWN_CONSUMED
    assert quarantined_item.live_attempt_consumed is True

    with pytest.raises(ValidationError):
        AutomationRunItem.model_validate(
            {
                **quarantined,
                "live_attempt_consumed": False,
            }
        )
    with pytest.raises(ValidationError):
        AutomationRunItem.model_validate(
            {
                **recovered,
                "coinbase_api_call_count": 1,
            }
        )


def test_lifecycle_and_control_actions_are_typed_not_arbitrary_executor_verbs():
    repository = _FakeRepository()
    service = OperatorAutomationService(repository)
    context = _context().model_copy(update={"operator_intent": "enable_automation_definition"})

    result = service.transition_definition(
        definition_id=DEFINITION_ID,
        action=AutomationDefinitionLifecycleAction.ENABLE,
        request=AutomationDefinitionLifecycleRequest(reason="Operator review complete"),
        context=context,
    )
    assert result.definition.lifecycle_state.value == "ENABLED"

    control = service.transition_control_posture(
        action=AutomationControlAction.PAUSE,
        request={"reason": "Bounded operator pause"},
        context=context.model_copy(update={"operator_intent": "pause_automation_control_plane"}),
    )
    assert isinstance(control.control_plane, AutomationControlPlaneItem)
    assert control.control_plane.posture.value == "PAUSED"


def test_repository_conflict_is_fixed_and_unknown_exception_text_is_withheld():
    repository = _FakeRepository(
        error=AutomationRepositoryConflict("automation_idempotency_payload_conflict")
    )
    service = OperatorAutomationService(repository)
    with pytest.raises(OperatorAutomationError) as conflict:
        service.create_definition(
            AutomationDefinitionCreateRequest(
                display_name="Spot sweep",
                job_kind=AutomationJobKind.SPOT_SWEEP,
                product_ids=["BTC-USDC"],
            ),
            _context(),
        )
    assert conflict.value.code == "automation_idempotency_payload_conflict"
    assert conflict.value.http_status_code == 409

    repository.error = RuntimeError("withheld-private-database-value")
    with pytest.raises(OperatorAutomationError) as unavailable:
        service.get_control_plane()
    assert unavailable.value.code == "automation_control_plane_unavailable"
    assert "withheld-private-database-value" not in str(unavailable.value)


def test_control_plane_modules_import_no_coinbase_sdk_or_domain_execution_modules():
    import application.admin_api.automation_models as automation_models
    import application.admin_api.operator_automation as operator_automation

    for module in (automation_models, operator_automation):
        tree = ast.parse(inspect.getsource(module))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(name == "coinbase" or name.startswith("coinbase.") for name in imports)
        assert not any(name.startswith("application.admin_api.futures") for name in imports)
        assert not any(name.startswith("business.spot_") for name in imports)
