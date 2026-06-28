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
    AdminApiGateStatus,
    AdminApiPermission,
    AdminApiRole,
    OrderSide,
    OrderType,
    ProductType,
)
from tools.run_admin_api_manual_spot_buy_live import (
    MAX_EXECUTED_NOTIONAL_USDC,
    MAX_SUBMITTED_NOTIONAL_USDC,
    _apply_runtime_config,
    _manual_order_body,
    _payload_hash,
    append_manual_spot_buy_live_admission_chain,
    AdminApiManualSpotBuyPlan,
)


pytestmark = pytest.mark.regression


def _plan() -> tuple[AdminApiManualSpotBuyPlan, dict[str, str]]:
    body = _manual_order_body(
        client_order_id="aslb-test-live-buy",
        product_id="TEST-USDC",
        quote_size=Decimal("1.00"),
    )
    actor = AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.TRADER])
    payload_hash = _payload_hash(
        actor=actor,
        operator_intent="manual_spot_buy_live_validation",
        body=body,
    )
    return (
        AdminApiManualSpotBuyPlan(
            run_id="test-live-buy",
            client_order_id="aslb-test-live-buy",
            idempotency_key="idem-test-live-buy",
            correlation_id="corr-test-live-buy",
            operator_intent="manual_spot_buy_live_validation",
            actor_id="operator-001",
            product_id="TEST-USDC",
            quote_size=Decimal("1.00"),
            payload_hash=payload_hash,
            approval_id="approval-test-live-buy",
            admission_audit_id="admission-test-live-buy",
            cap_guard_decision_id="cap-test-live-buy",
            reconciliation_plan_id="recon-test-live-buy",
        ),
        body,
    )


def test_manual_spot_buy_runner_builds_route_exact_payload_hash():
    plan, body = _plan()

    request = ManualOrderRequest.model_validate(body)

    assert request.side == OrderSide.BUY
    assert request.order_type == OrderType.MARKET
    assert request.manual_live_acknowledgement is True
    assert len(plan.payload_hash) == 64
    assert plan.payload_hash == _payload_hash(
        actor=AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.TRADER]),
        operator_intent=plan.operator_intent,
        body=body,
    )


def test_manual_spot_buy_runner_admission_chain_passes_exact_live_gate(tmp_path):
    plan, _body = _plan()
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )

    append_manual_spot_buy_live_admission_chain(
        plan=plan,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        max_submitted_notional=MAX_SUBMITTED_NOTIONAL_USDC,
        max_executed_notional=MAX_EXECUTED_NOTIONAL_USDC,
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
    assert cap_guard.max_submitted_notional_usdc == "3.10"
    assert cap_guard.max_executed_notional_usdc == "1.00"


def test_manual_spot_buy_runner_runtime_config_marks_selected_usdc_spot(
    monkeypatch,
):
    import configuration

    monkeypatch.setenv("COINBASE_API_KEY", "test-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "test-secret")
    monkeypatch.setattr(configuration, "PRODUCT_METADATA", {}, raising=False)
    monkeypatch.setattr(configuration, "SPOT_PRODUCT_IDS", [], raising=False)
    monkeypatch.setattr(configuration, "ACTION_CONDITION_GUARDS", {}, raising=False)

    _apply_runtime_config(
        product={
            "product_id": "TEST-USDC",
            "base_currency_id": "TEST",
            "quote_currency_id": "USDC",
            "base_increment": "0.0001",
            "quote_increment": "0.01",
            "price_increment": "0.0001",
            "base_min_size": "0.0001",
            "quote_min_size": "1",
            "display_name": "TEST-USDC",
            "status": "online",
            "price": "1",
            "trading_disabled": False,
        },
        max_submitted_notional=MAX_SUBMITTED_NOTIONAL_USDC,
    )

    assert configuration.PRODUCT_METADATA["TEST-USDC"]["product_type"] == (
        ProductType.SPOT.value
    )
    assert "TEST-USDC" in configuration.SPOT_PRODUCT_IDS
    assert configuration.ACTION_CONDITION_GUARDS["limits"][0]["max_notional"] == (
        "3.10"
    )
