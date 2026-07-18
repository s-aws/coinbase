"""Operator-surface safety tests for parked M58 exchange mutations."""

from __future__ import annotations

import json
import inspect

import pytest

from api.v1.routes import automation
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import AdminApiActor
from application.admin_api.futures_route_contracts import FUTURES_ROUTE_CONTRACTS
from application.admin_api.usdc_pair_snapshot import (
    FileUsdcPairSnapshotOrderPlanLiveReadinessStore,
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    UsdcPairSnapshotOrderPlanLiveReadinessRecord,
    UsdcPairSnapshotOrderPlanLiveSubmitRecord,
)
from application.admin_api.read_service import (
    FUTURES_SOURCE_DISABLED_COMMAND_ROUTES,
    M58_SOURCE_PARKED_EXCHANGE_ROUTES,
    AdminApiReadService,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiFunctionalityExposureStatus,
    AdminApiModuleSupportStatus,
    AdminApiMutationFamilyType,
    AdminApiCommandStatus,
    AdminApiRole,
    AdminApiRouteAvailability,
)


_FUTURES_COMMAND_SURFACES = {
    f"{method} {route}" for method, route in FUTURES_SOURCE_DISABLED_COMMAND_ROUTES
}
_M58_EXCHANGE_SURFACES = {
    f"{method} {route}" for method, route in M58_SOURCE_PARKED_EXCHANGE_ROUTES
}


def test_default_m58_fastapi_executors_are_source_parked():
    order_executor = automation.get_usdc_pair_snapshot_live_order_executor()
    fanout_executor = automation.get_usdc_pair_snapshot_live_fanout_executor()

    assert isinstance(
        order_executor,
        automation.ParkedUsdcPairSnapshotLiveOrderExecutor,
    )
    assert isinstance(
        fanout_executor,
        automation.ParkedUsdcPairSnapshotLiveFanoutExecutor,
    )
    with pytest.raises(
        automation.M58OperatorWorkflowUnavailableError,
        match=automation.M58_OPERATOR_WORKFLOW_UNAVAILABLE,
    ):
        order_executor.submit_and_cancel()
    with pytest.raises(
        automation.M58OperatorWorkflowUnavailableError,
        match=automation.M58_OPERATOR_WORKFLOW_UNAVAILABLE,
    ):
        fanout_executor.submit_and_cancel_all()


def test_m58_capability_readback_truthfully_reports_every_exchange_route_parked():
    capabilities = AdminApiReadService().build_admin_capabilities().capabilities
    parked = {
        (item.method, item.route): item
        for item in capabilities
        if (item.method, item.route) in M58_SOURCE_PARKED_EXCHANGE_ROUTES
    }

    assert set(parked) == M58_SOURCE_PARKED_EXCHANGE_ROUTES
    for item in parked.values():
        assert item.availability == AdminApiRouteAvailability.BACKEND_BLOCKED
        assert item.live_enabled is False
        assert item.frontend_safe is False
        assert item.compatibility_mode == "source_disabled"
        assert item.idempotency == "not_applicable_source_disabled"
        assert item.approval == "not_applicable_source_disabled"
        assert item.caps == "not_applicable_source_disabled"
        assert item.audit == "not_implemented_no_mutation"
        assert item.notes == (
            "M58 exchange execution is source-parked: "
            "m58_operator_workflow_unavailable"
        )


def test_futures_capability_readback_reports_every_command_source_disabled():
    capabilities = AdminApiReadService().build_admin_capabilities().capabilities
    source_disabled = {
        (item.method, item.route): item
        for item in capabilities
        if (item.method, item.route) in FUTURES_SOURCE_DISABLED_COMMAND_ROUTES
    }

    assert set(source_disabled) == FUTURES_SOURCE_DISABLED_COMMAND_ROUTES
    for item in source_disabled.values():
        assert item.availability == AdminApiRouteAvailability.BACKEND_BLOCKED
        assert item.live_enabled is False
        assert item.frontend_safe is False
        assert item.compatibility_mode == "source_disabled"
        assert item.idempotency == "not_applicable_source_disabled"
        assert item.approval == "not_applicable_source_disabled"
        assert item.caps == "not_applicable_source_disabled"
        assert item.audit == "not_implemented_no_mutation"
        assert item.notes == (
            "Futures command execution is source-disabled: "
            "futures_command_service_source_disabled"
        )


def test_futures_route_contracts_and_inventory_are_literal_source_disabled():
    assert len(FUTURES_ROUTE_CONTRACTS) == 4
    for contract in FUTURES_ROUTE_CONTRACTS.values():
        assert contract.route_registered is True
        assert contract.command_draft_allowed is False
        assert contract.execution_allowed is False
        assert contract.bff_authority == "source_disabled_not_forwarded"

    inventory = {
        item.surface: item
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface in _FUTURES_COMMAND_SURFACES
    }
    assert set(inventory) == _FUTURES_COMMAND_SURFACES
    for item in inventory.values():
        assert "source-disabled" in item.parity_test
        assert "NOT_IMPLEMENTED" in item.parity_test
        assert item.idempotency == "not_applicable_source_disabled"
        assert item.approval == "not_applicable_source_disabled"
        assert item.caps == "not_applicable_source_disabled"
        assert item.audit == "not_implemented_no_mutation"


def test_enterprise_functionality_inventory_reports_installed_source_parks():
    readiness = AdminApiReadService().build_enterprise_readiness()
    workflows = {
        item.workflow_id: item for item in readiness.functionality_inventory
    }

    futures = workflows["futures.command_drafts_live_disabled"]
    assert set(futures.command_routes) == _FUTURES_COMMAND_SURFACES
    assert futures.backend_supported is False
    assert futures.frontend_exposed is False
    assert futures.command_capable is False
    assert futures.live_designated is False
    assert futures.live_enabled is False
    assert futures.exposure_status == (
        AdminApiFunctionalityExposureStatus.ADMIN_UNSUPPORTED
    )
    assert futures.support_status == AdminApiModuleSupportStatus.UNSUPPORTED
    assert futures.blockers == ["futures_command_service_source_disabled"]
    assert "source-disabled" in futures.summary
    assert "not_implemented" in futures.summary
    assert "must not forward" in futures.frontend_boundary

    m58 = workflows["spot.sweep_automation_and_live_executor"]
    assert _M58_EXCHANGE_SURFACES < set(m58.command_routes)
    assert any("live-readiness" in route for route in m58.command_routes)
    assert "source-parked" in m58.summary
    assert "offline" in m58.summary
    assert "m58_operator_workflow_unavailable" in m58.blockers
    assert "tools/run_admin_api_usdc_pair_snapshot_live_submit.py" not in (
        m58.automation_routes
    )
    assert "must not forward" in m58.frontend_boundary


def test_enterprise_mutation_taxonomy_separates_source_disabled_futures_commands():
    readiness = AdminApiReadService().build_enterprise_readiness()
    taxonomy = {item.mutation_id: item for item in readiness.mutation_taxonomy}

    futures = taxonomy["futures.commands_contract_required"]
    assert set(futures.command_surfaces) == _FUTURES_COMMAND_SURFACES
    assert futures.mutation_family == (
        AdminApiMutationFamilyType.FUTURES_CONTRACT_REQUIRED
    )
    assert futures.idempotency_required is False
    assert futures.approval_required is False
    assert futures.cap_guard_required is False
    assert futures.admission_audit_required is False
    assert futures.reconciliation_required is False
    assert futures.live_adapter_required is False
    assert futures.blockers == ["futures_command_service_source_disabled"]
    assert "source-disabled" in futures.summary
    assert "must not forward" in futures.bff_boundary
    assert "fixed typed 501" in futures.route_local_boundary

    risk_proof = taxonomy["futures.risk_proof_recording"]
    assert risk_proof.mutation_family == AdminApiMutationFamilyType.FUTURES_RISK_PROOF
    assert risk_proof.command_surfaces == ["POST /api/v1/futures/risk-proofs"]
    assert risk_proof.live_adapter_required is False
    assert risk_proof.approval_required is False
    assert risk_proof.cap_guard_required is False
    assert risk_proof.reconciliation_required is False
    assert "append-only local evidence" in risk_proof.summary


def test_futures_module_registry_has_no_gate_clearable_command_path():
    readiness = AdminApiReadService().build_enterprise_readiness()
    modules = {item.module_id: item for item in readiness.modules}
    futures = modules["futures_perpetuals"]

    assert futures.support_status == AdminApiModuleSupportStatus.UNSUPPORTED
    for gap in futures.command_gaps[:2]:
        assert gap.status == AdminApiModuleSupportStatus.UNSUPPORTED
        assert "source-disabled" in gap.reason
        assert "separate source restoration and authorization" in (
            gap.required_backend_contract
        )
        assert "must not forward" in gap.frontend_boundary
        assert "until" not in gap.reason


def test_generic_live_enablement_excludes_source_parked_routes():
    live_enablement = AdminApiReadService().build_live_enablement()
    routes = {
        (item.method, item.route): item
        for item in live_enablement.paths
        if (item.method, item.route)
        in FUTURES_SOURCE_DISABLED_COMMAND_ROUTES
        | M58_SOURCE_PARKED_EXCHANGE_ROUTES
    }

    assert routes == {}


def test_futures_command_suite_fixed_source_blocker_is_counted_and_not_gate_clearable():
    suite = AdminApiReadService().build_futures_command_suite()

    assert suite.blocked_command_count == suite.command_count == 4
    assert suite.executable_command_count == 0
    assert suite.command_draft_allowed_count == 0
    for command in suite.commands:
        assert command.readiness_decision.ready is False
        assert command.readiness_decision.blocker_count >= 1
        assert command.readiness_decision.first_blocker == (
            "futures_command_service_source_disabled"
        )
        assert command.readiness_decision.command_draft_allowed is False
        assert command.readiness_decision.execution_allowed is False
        assert command.readiness_decision.bff_authority == (
            "source_disabled_not_forwarded"
        )
    for step in suite.command_enablement_sequence_steps:
        assert step.command_draft_allowed is False
        assert step.execution_allowed is False
        assert "separate source restoration and authorization" in step.detail.lower()
        assert "can become executable" not in step.detail
        assert "enablement can advance" not in step.detail


def test_m58_parked_route_inventory_reports_no_performed_mutation_gates():
    parked = {
        tuple(item.surface.split(" ", 1)): item
        for item in ADMIN_API_ROUTE_INVENTORY
        if tuple(item.surface.split(" ", 1)) in M58_SOURCE_PARKED_EXCHANGE_ROUTES
    }

    assert set(parked) == M58_SOURCE_PARKED_EXCHANGE_ROUTES
    for item in parked.values():
        assert item.idempotency == "not_applicable_source_disabled"
        assert item.approval == "not_applicable_source_disabled"
        assert item.caps == "not_applicable_source_disabled"
        assert item.audit == "not_implemented_no_mutation"
        assert "before idempotency, approval, cap, audit, or persistence" in (
            item.parity_test
        )
        assert "future restoration requires separate authorization" in (
            item.parity_test
        )


def test_m58_fastapi_contract_advertises_501_as_default_response():
    routes = {route.name: route for route in automation.router.routes}

    for route_name in (
        "submit_usdc_pair_snapshot_order_plan_live_order",
        "submit_usdc_pair_snapshot_allowlist_run_state_live_order",
        "submit_usdc_pair_snapshot_allowlist_run_state_live_fanout",
    ):
        route = routes[route_name]
        assert route.status_code == 501
        assert 501 in route.responses
        assert "source-parked" in route.summary.lower()
        assert set(inspect.signature(route.endpoint).parameters) <= {
            "plan_id",
            "run_state_id",
            "body",
            "idempotency_key",
            "correlation_id",
            "operator_intent",
            "actor",
        }


@pytest.mark.parametrize(
    ("endpoint", "service_method"),
    [
        (
            automation.USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
            automation.USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_SERVICE_METHOD,
        ),
        (
            automation.USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_ENDPOINT,
            automation.USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_SUBMIT_SERVICE_METHOD,
        ),
        (
            automation.USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_FANOUT_SUBMIT_ENDPOINT,
            automation.USDC_PAIR_SNAPSHOT_ALLOWLIST_RUN_STATE_LIVE_FANOUT_SUBMIT_SERVICE_METHOD,
        ),
    ],
)
def test_m58_admin_live_submit_contract_returns_typed_source_parked_response(
    tmp_path,
    endpoint: str,
    service_method: str,
):
    operation_calls: list[str] = []
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")

    def operation(audit_id: str):
        operation_calls.append(audit_id)
        automation._require_m58_admin_api_exchange_execution_available()

    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    response = automation._execute_idempotent_live_submit(
        idempotency_key="idem-m58-parked",
        payload_hash="a" * 64,
        actor=AdminApiActor(actor_id="trader-001", roles=[AdminApiRole.TRADER]),
        request_id="corr-m58-parked",
        operator_intent="inspect_parked_m58_operator_surface",
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=operation,
        endpoint=endpoint,
        service_method=service_method,
    )

    payload = json.loads(response.body)
    assert response.status_code == 501
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["service_method"] == service_method
    assert payload["failure_stage"] == automation.M58_OPERATOR_WORKFLOW_UNAVAILABLE
    assert payload["message"] == (
        "M58 exchange execution is parked: m58_operator_workflow_unavailable."
    )
    assert payload["live_exchange_submitted"] is False
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_execution"] == "not_run"
    assert payload["notional_usdc"] == "0"
    assert operation_calls == []

    events = audit_store.read_recent(limit=10)
    assert events == []
    assert idempotency_store.get_record("idem-m58-parked") is None


def test_m58_admin_live_submit_contract_cannot_replay_prior_accepted_evidence(
    tmp_path,
):
    operation_calls: list[str] = []
    store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    accepted = automation._live_submit_base_response(
        status_value=AdminApiCommandStatus.ACCEPTED,
        message="historical synthetic acceptance",
        correlation_id="historical-correlation",
        idempotency_key="idem-m58-prior-accepted",
    )
    from application.admin_api.idempotency import IdempotencyRecord

    store.put_record(
        IdempotencyRecord(
            idempotency_key="idem-m58-prior-accepted",
            payload_hash="b" * 64,
            status=AdminApiCommandStatus.ACCEPTED,
            response=accepted.model_dump(mode="json"),
            actor_id="trader-001",
            endpoint=automation.USDC_PAIR_SNAPSHOT_ORDER_PLAN_LIVE_SUBMIT_ENDPOINT,
        )
    )

    response = automation._execute_idempotent_live_submit(
        idempotency_key="idem-m58-prior-accepted",
        payload_hash="b" * 64,
        actor=AdminApiActor(actor_id="trader-001", roles=[AdminApiRole.TRADER]),
        request_id="corr-m58-current",
        operator_intent="inspect_parked_m58_operator_surface",
        idempotency_store=store,
        audit_store=FileAdminApiAuditStore(tmp_path / "audit.jsonl"),
        operation=lambda audit_id: operation_calls.append(audit_id),
    )

    payload = json.loads(response.body)
    assert response.status_code == 501
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["failure_stage"] == automation.M58_OPERATOR_WORKFLOW_UNAVAILABLE
    assert response.headers.get("x-idempotency-replayed") is None
    assert operation_calls == []
    assert FileAdminApiAuditStore(tmp_path / "audit.jsonl").read_recent(limit=10) == []
    assert store.get_record("idem-m58-prior-accepted").status == (
        AdminApiCommandStatus.ACCEPTED
    )


def test_m58_empty_and_historical_readbacks_label_current_source_park(tmp_path):
    readiness_store = FileUsdcPairSnapshotOrderPlanLiveReadinessStore(
        tmp_path / "readiness.jsonl"
    )
    submit_store = FileUsdcPairSnapshotOrderPlanLiveSubmitStore(
        tmp_path / "submissions.jsonl"
    )

    empty_readiness = automation._live_readiness_list_response(
        store=readiness_store,
        limit=10,
    )
    assert empty_readiness.submit_route_ready_count == 0
    assert "submit_route_ready is always false" in empty_readiness.detail
    assert "m58_operator_workflow_unavailable" in empty_readiness.detail
    assert "source-parked" in empty_readiness.detail

    empty_submissions = automation._live_submit_list_response(
        store=submit_store,
        limit=10,
    )
    assert "historical" in empty_submissions.detail.lower()
    assert "source-parked" in empty_submissions.detail

    readiness_store.append(
        UsdcPairSnapshotOrderPlanLiveReadinessRecord(
            readiness_id="historical-ready",
            plan_id="plan-1",
            snapshot_run_id="run-1",
            product_id="BTC-USDC",
            client_order_id="client-1",
            side="BUY",
            reference_bid_price="100",
            reference_bid_price_source="synthetic",
            reference_bid_price_captured_at="2026-07-17T00:00:00Z",
            reference_bid_price_freshness_status="fresh",
            last_filled_price="100",
            last_filled_price_source="synthetic",
            last_filled_price_captured_at="2026-07-17T00:00:00Z",
            last_filled_price_freshness_status="fresh",
            intended_limit_price="99",
            far_from_bid_status="passed",
            snapshot_non_fill_status="passed",
            submitted_notional_usdc="1",
            max_submitted_notional_usdc="1",
            max_executed_notional_usdc="1",
            planned_notional_usdc="1",
            quote_size="1",
            min_quote_size="1",
            preflight_passed=True,
            submit_route_ready=True,
            cancel_rollback_plan_ref="cancel-plan-1",
            approval_snapshot_id="approval-1",
            admission_audit_id="admission-1",
            cap_guard_decision_id="cap-1",
            reconciliation_plan_id="reconciliation-1",
            live_service_decision_id="service-1",
            actor_id="operator-1",
            operator_intent="historical fixture",
            idempotency_key="historical-ready-idem",
            payload_hash="a" * 64,
            detail="historical predecessor readiness",
        )
    )
    projected_readiness = automation._live_readiness_list_response(
        store=readiness_store,
        limit=10,
    )
    assert projected_readiness.readiness[0].preflight_passed is False
    assert projected_readiness.readiness[0].submit_route_ready is False
    assert projected_readiness.readiness[0].submit_blockers[0] == (
        "m58_operator_workflow_unavailable"
    )

    submit_store.append(
        UsdcPairSnapshotOrderPlanLiveSubmitRecord(
            submission_id="historical-submission",
            readiness_id="historical-ready",
            plan_id="plan-1",
            snapshot_run_id="run-1",
            product_id="BTC-USDC",
            client_order_id="client-1",
            submitted_at="2026-07-17T00:00:01Z",
            side="BUY",
            submitted_notional_usdc="1",
            executed_notional_usdc="1",
            max_executed_notional_usdc="1",
            intended_limit_price="99",
            reference_bid_price="100",
            last_filled_price="100",
            cancel_rollback_plan_ref="cancel-plan-1",
            approval_snapshot_id="approval-1",
            admission_audit_id="admission-1",
            cap_guard_decision_id="cap-1",
            reconciliation_plan_id="reconciliation-1",
            live_service_decision_id="service-1",
            coinbase_order_id="historical-exchange-evidence",
            actor_id="operator-1",
            operator_intent="historical fixture",
            idempotency_key="historical-submission-idem",
            payload_hash="b" * 64,
            live_exchange_submitted=True,
            live_coinbase_orders_ran=True,
            live_coinbase_execution="historical_submitted",
            notional_usdc="1",
            detail="historical controlled-live predecessor evidence",
        )
    )
    projected_submissions = automation._live_submit_list_response(
        store=submit_store,
        limit=10,
    )
    historical = projected_submissions.submissions[0]
    assert historical.live_exchange_submitted is True
    assert historical.live_coinbase_orders_ran is True
    assert historical.coinbase_order_id_evidence_only is True
    assert historical.coinbase_order_id == "historical-exchange-evidence"
    assert "Historical" in historical.detail
    assert "source-parked" in historical.detail
