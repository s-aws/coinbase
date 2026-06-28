from __future__ import annotations

from decimal import Decimal

import pytest

from application.admin_api.approval import (
    FileAdminApiApprovalStore,
    evaluate_command_live_admission,
)
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.live_execution import get_configured_live_execution_service
from application.admin_api.models import AdminApiActor, ManualOrderRequest
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiPermission,
    AdminApiRole,
    OrderSide,
    OrderType,
)
from tools.run_admin_api_manual_spot_sell_validation import (
    DEFAULT_OPERATOR_INTENT,
    MAX_VALIDATED_NOTIONAL_USDC,
    _build_plan,
    _manual_order_body,
    _payload_hash,
    append_manual_spot_sell_validation_admission_chain,
    run_manual_spot_sell_validation,
)


pytestmark = pytest.mark.regression


def _plan():
    body = _manual_order_body(
        client_order_id="assv-test-sell",
        product_id="TEST-USDC",
        base_size=Decimal("0.01"),
        limit_price=Decimal("200.00"),
    )
    actor = AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.TRADER])
    payload_hash = _payload_hash(
        actor=actor,
        operator_intent=DEFAULT_OPERATOR_INTENT,
        body=body,
    )
    plan, _generated_body = _build_plan(
        product_id="TEST-USDC",
        base_size=Decimal("0.01"),
        limit_price=Decimal("200.00"),
        actor_id="operator-001",
        operator_intent=DEFAULT_OPERATOR_INTENT,
    )
    return (
        plan.__class__(
            run_id="test-sell-validation",
            client_order_id="assv-test-sell",
            idempotency_key="idem-test-sell-validation",
            correlation_id="corr-test-sell-validation",
            operator_intent=DEFAULT_OPERATOR_INTENT,
            actor_id="operator-001",
            product_id="TEST-USDC",
            base_size=Decimal("0.01"),
            limit_price=Decimal("200.00"),
            validated_notional_usdc=Decimal("2.0000"),
            payload_hash=payload_hash,
            approval_id="approval-test-sell-validation",
            admission_audit_id="admission-test-sell-validation",
            cap_guard_decision_id="cap-test-sell-validation",
            reconciliation_plan_id="recon-test-sell-validation",
        ),
        body,
    )


def test_manual_spot_sell_validation_builds_route_exact_payload_hash():
    plan, body = _plan()

    request = ManualOrderRequest.model_validate(body)

    assert request.side == OrderSide.SELL
    assert request.order_type == OrderType.LIMIT
    assert request.manual_live_acknowledgement is True
    assert request.base_size == "0.01"
    assert request.limit_price == "200.00"
    assert len(plan.payload_hash) == 64
    assert plan.payload_hash == _payload_hash(
        actor=AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.TRADER]),
        operator_intent=plan.operator_intent,
        body=body,
    )


def test_manual_spot_sell_validation_admission_chain_passes_exact_live_gate(
    tmp_path,
):
    plan, _body = _plan()
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )

    append_manual_spot_sell_validation_admission_chain(
        plan=plan,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        max_validated_notional=MAX_VALIDATED_NOTIONAL_USDC,
    )

    decision = evaluate_command_live_admission(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=plan.client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id=plan.actor_id,
        idempotency_key=plan.idempotency_key,
        operator_intent=plan.operator_intent,
        payload_hash=plan.payload_hash,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=get_configured_live_execution_service(
            enabled=True,
            rest_client_available=True,
            order_event_stream_available=True,
        ),
        manual_live_acknowledgement=True,
    )

    assert decision.status == AdminApiGateStatus.PASSED
    assert decision.allowed is True
    assert decision.blockers == []
    assert decision.approval_snapshot_id == plan.approval_id
    assert decision.admission_audit_id == plan.admission_audit_id
    assert decision.cap_guard_decision_id == plan.cap_guard_decision_id
    assert decision.reconciliation_plan_id == plan.reconciliation_plan_id

    cap_guard = cap_guard_store.find_by_decision_id(plan.cap_guard_decision_id)
    assert cap_guard is not None
    assert cap_guard.guard_policy_ref == (
        "action_condition_guard:manual_spot_sell_validation"
    )
    assert cap_guard.max_submitted_notional_usdc == "0.00"


def test_manual_spot_sell_validation_uses_route_and_fake_rest_only(tmp_path):
    summary = run_manual_spot_sell_validation(
        product_id="TEST-USDC",
        base_size=Decimal("0.01"),
        limit_price=Decimal("200.00"),
        baseline_quantity=Decimal("0.05"),
        baseline_entry_price=Decimal("100.00"),
        planned_base_commitment=Decimal("0.01"),
        wallet_available_base=Decimal("0.10"),
        max_validated_notional=MAX_VALIDATED_NOTIONAL_USDC,
        actor_id="operator-001",
        operator_intent=DEFAULT_OPERATOR_INTENT,
        store_dir=tmp_path / "stores",
        audit_file=tmp_path / "summary.jsonl",
        summary_only=True,
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_execution"] == "not_run_fake_rest_only"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["validated_notional_usdc"] == "2.00"
    assert summary["fake_rest_boundary_reached"] is True
    assert summary["submission_event_recorded"] is True
    assert summary["lot_authority_evaluator_call_count"] == 1

    response = summary["admin_api_response"]
    assert response["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert response["live_exchange_submitted"] is True
    assert response["submission_event_recorded"] is True

    fake_call = summary["fake_rest_create_order_calls"][0]
    assert fake_call["product_id"] == "TEST-USDC"
    assert fake_call["side"] == OrderSide.SELL.value
    assert fake_call["order_configuration"] == {
        "limit_limit_gtc": {
            "base_size": "0.01",
            "limit_price": "200.00",
            "post_only": False,
        }
    }

    lot_call = summary["lot_authority_evaluator_calls"][0]
    assert lot_call["product_id"] == "TEST-USDC"
    assert lot_call["side"] == OrderSide.SELL.value
    assert lot_call["size"] == pytest.approx(0.01)
