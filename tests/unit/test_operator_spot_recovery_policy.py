from __future__ import annotations

import pytest

from application.admin_api.models import CancelOrderRequest
from application.admin_api.operator_spot_recovery import (
    OperatorSpotRecoveryEventItem,
    SpotRecoveryFillEvidence,
    SpotRecoveryLocalOrderEvidence,
    SpotRecoveryOrderEvidence,
    build_operator_spot_recovery_case_item,
    build_spot_recovery_plan,
)
from core.enums import (
    OrderOwnershipProvenance,
    OrderStatus,
    SpotRecoveryPlanKind,
)


def _local(*, status: OrderStatus) -> SpotRecoveryLocalOrderEvidence:
    return SpotRecoveryLocalOrderEvidence(
        client_order_id="8f1bf38c-90ad-4a7c-90fb-87cb56c72a80",
        product_id="BTC-USDC",
        side="BUY",
        status=status,
        ownership_provenance=OrderOwnershipProvenance.ADMIN_MANUAL_ROOT,
        portfolio_id_sha256="a" * 64,
        exchange_order_id_present=True,
    )


def _order(*, status: OrderStatus) -> SpotRecoveryOrderEvidence:
    return SpotRecoveryOrderEvidence(
        exact_identity_match=True,
        authoritative=True,
        confirmed_absent=False,
        status=status,
        page_count=1,
    )


def _fills(*, count: int) -> SpotRecoveryFillEvidence:
    return SpotRecoveryFillEvidence(
        authoritative=True,
        fill_count=count,
        page_count=1,
        pagination_complete=True,
    )


def test_terminal_exchange_truth_builds_status_repair_plan() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.OPEN),
        order=_order(status=OrderStatus.FILLED),
        fills=_fills(count=2),
    )

    assert plan.kind is SpotRecoveryPlanKind.SET_LOCAL_STATUS
    assert plan.from_status is OrderStatus.OPEN
    assert plan.to_status is OrderStatus.FILLED
    assert plan.apply_available is True
    assert plan.cancel_available is False
    assert plan.blockers == []
    assert plan.plan_sha256


def test_terminal_local_but_active_exchange_builds_zero_fill_cancel_plan() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.CANCELLED),
        order=_order(status=OrderStatus.OPEN),
        fills=_fills(count=0),
    )

    assert plan.kind is SpotRecoveryPlanKind.CANCEL_ACTIVE_ORPHAN
    assert plan.apply_available is False
    assert plan.cancel_available is True
    assert plan.blockers == []


def test_partial_fill_never_classifies_active_orphan_as_safe_cancel() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.CANCELLED),
        order=_order(status=OrderStatus.OPEN),
        fills=_fills(count=1),
    )

    assert plan.kind is SpotRecoveryPlanKind.BLOCKED
    assert plan.apply_available is False
    assert plan.cancel_available is False
    assert plan.blockers == ["active_exchange_order_has_fill_evidence"]


def test_in_sync_order_builds_noop_plan() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.OPEN),
        order=_order(status=OrderStatus.OPEN),
        fills=_fills(count=0),
    )

    assert plan.kind is SpotRecoveryPlanKind.NO_CHANGE
    assert plan.apply_available is False
    assert plan.cancel_available is False
    assert plan.blockers == []


def test_active_status_repair_never_advertises_unsafe_rollback() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.PENDING),
        order=_order(status=OrderStatus.OPEN),
        fills=_fills(count=0),
    )

    assert plan.kind is SpotRecoveryPlanKind.SET_LOCAL_STATUS
    assert plan.apply_available is True
    assert plan.rollback_after_apply_available is False


def test_absence_is_not_reinterpreted_as_terminal_truth() -> None:
    plan = build_spot_recovery_plan(
        local=_local(status=OrderStatus.OPEN),
        order=SpotRecoveryOrderEvidence(
            exact_identity_match=False,
            authoritative=True,
            confirmed_absent=True,
            status=None,
            page_count=1,
        ),
        fills=None,
    )

    assert plan.kind is SpotRecoveryPlanKind.BLOCKED
    assert plan.apply_available is False
    assert plan.cancel_available is False
    assert plan.blockers == ["exact_order_truth_absent"]


def test_external_order_provenance_is_never_repair_eligible() -> None:
    local = _local(status=OrderStatus.OPEN).model_copy(
        update={
            "ownership_provenance": OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED,
        }
    )

    plan = build_spot_recovery_plan(
        local=local,
        order=_order(status=OrderStatus.FILLED),
        fills=_fills(count=1),
    )

    assert plan.kind is SpotRecoveryPlanKind.BLOCKED
    assert plan.apply_available is False
    assert plan.cancel_available is False
    assert plan.blockers == ["order_not_system_owned"]


def test_cancel_request_requires_complete_recovery_binding() -> None:
    with pytest.raises(ValueError):
        CancelOrderRequest(
            manual_live_acknowledgement=True,
            recovery_case_id="0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
        )

    request = CancelOrderRequest(
        reason="cancel exact active orphan",
        manual_live_acknowledgement=True,
        recovery_case_id="0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
        recovery_case_revision=3,
        recovery_plan_sha256="a" * 64,
    )
    assert request.recovery_case_revision == 3


def test_public_recovery_event_rejects_non_allowlisted_evidence() -> None:
    with pytest.raises(ValueError):
        OperatorSpotRecoveryEventItem(
            event_id="1b81ae1a-b569-49c0-8c45-09350778e89a",
            case_id="0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            event_type="REFRESH_FAILED",
            actor_id="operator",
            correlation_id="recovery-correlation",
            evidence={"raw_response": "must-not-render"},
            recorded_at="2026-07-23T08:01:00Z",
        )


def test_stale_portfolio_binding_removes_every_recovery_action() -> None:
    item = build_operator_spot_recovery_case_item(
        {
            "case_id": "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            "goal_id": "operator_spot_recovery_execution_ui_v1",
            "goal_refresh_cycles_used": 0,
            "goal_cancel_outcome": "NOT_RUN",
            "client_order_id": "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80",
            "product_id": "BTC-USDC",
            "state": "OPEN",
            "revision": 1,
            "refresh_count": 0,
            "order_read_logical_count": 0,
            "fill_read_logical_count": 0,
            "cancel_call_count": 0,
            "cancel_allowance_consumed": False,
            "plan": None,
            "diagnostic_code": "recovery_case_created",
            "correlation_id": "recovery-correlation",
            "created_at": "2026-07-23T08:00:00Z",
            "updated_at": "2026-07-23T08:00:00Z",
        },
        portfolio_binding_verified=False,
    )

    assert item.portfolio_binding_verified is False
    assert item.allowed_actions == []


def test_successor_goal_budget_is_backend_owned_and_suppresses_actions() -> None:
    item = build_operator_spot_recovery_case_item(
        {
            "case_id": "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            "goal_id": "operator_spot_recovery_execution_ui_v1",
            "goal_refresh_cycles_used": 10,
            "goal_cancel_outcome": "ACCEPTED",
            "client_order_id": "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80",
            "product_id": "BTC-USDC",
            "state": "OPEN",
            "revision": 1,
            "refresh_count": 0,
            "order_read_logical_count": 0,
            "fill_read_logical_count": 0,
            "cancel_call_count": 0,
            "cancel_allowance_consumed": False,
            "plan": None,
            "diagnostic_code": "recovery_case_created",
            "correlation_id": "recovery-correlation",
            "created_at": "2026-07-23T08:00:00Z",
            "updated_at": "2026-07-23T08:00:00Z",
        },
        portfolio_binding_verified=True,
    )

    assert item.goal_id == "operator_spot_recovery_execution_ui_v1"
    assert item.goal_refresh_cycles_used == 10
    assert item.goal_refresh_cycle_limit == 10
    assert item.goal_cancel_outcome == "ACCEPTED"
    assert item.allowed_actions == []


def test_public_recovery_event_withholds_raw_actor_identity() -> None:
    item = build_operator_spot_recovery_case_item(
        {
            "case_id": "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            "goal_id": "operator_spot_recovery_execution_ui_v1",
            "goal_refresh_cycles_used": 0,
            "goal_cancel_outcome": "NOT_RUN",
            "client_order_id": "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80",
            "product_id": "BTC-USDC",
            "state": "OPEN",
            "revision": 1,
            "refresh_count": 0,
            "order_read_logical_count": 0,
            "fill_read_logical_count": 0,
            "cancel_call_count": 0,
            "cancel_allowance_consumed": False,
            "plan": None,
            "diagnostic_code": "recovery_case_created",
            "correlation_id": "recovery-correlation",
            "created_at": "2026-07-23T08:00:00Z",
            "updated_at": "2026-07-23T08:00:00Z",
        },
        events=[
            {
                "event_id": "1b81ae1a-b569-49c0-8c45-09350778e89a",
                "case_id": "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
                "event_type": "CASE_CREATED",
                "actor_id": "private-operator-identity",
                "correlation_id": "recovery-correlation",
                "evidence": {"revision": 1},
                "recorded_at": "2026-07-23T08:00:00Z",
            }
        ],
        portfolio_binding_verified=True,
    )

    assert item.events[0].actor_id == "withheld"
