from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import futures as futures_routes
from api.v1.routes.orders import _idempotency_payload_hash
from application.admin_api.approval import (
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.cap_guard import (
    CapGuardDecisionRecord,
    FileAdminApiCapGuardStore,
)
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.futures_risk_proof import FileFuturesRiskProofStore
from application.admin_api.futures_command_service import (
    AdminApiFuturesCommandService,
    FUTURES_COMMAND_SERVICE_CONTRACTS,
    FuturesCommandServiceDisabledError,
)
from application.admin_api.futures_proof_payload_fields import (
    FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS,
    iter_futures_proof_payload_field_contracts,
)
from application.admin_api.futures_proof_routes import FUTURES_PROOF_ROUTE_CONTRACTS
from application.admin_api.futures_proof_writer import FUTURES_PROOF_WRITER_CONTRACTS
from application.admin_api.futures_request_payload_contracts import (
    FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS,
    iter_futures_request_payload_contracts,
)
from application.admin_api.futures_reconciliation import (
    AdminApiFuturesReconciliation,
    FUTURES_RECONCILIATION_CONTRACT,
    FuturesReconciliationDisabledError,
)
from application.admin_api.futures_route_contracts import (
    FUTURES_ROUTE_CONTRACTS,
    futures_coinbase_exchange_submission_contract_ref,
    futures_live_adapter_contract_ref,
    futures_live_adapter_construction_contract_ref,
    futures_live_adapter_decision_contract_ref,
    futures_live_adapter_decision_record_contract_ref,
    futures_live_adapter_execution_contract_ref,
    futures_live_adapter_invocation_contract_ref,
    futures_post_exchange_submission_reconciliation_contract_ref,
)
from application.admin_api.futures_risk_guard import (
    AdminApiFuturesRiskGuard,
    FUTURES_RISK_GUARD_CONTRACT,
    FuturesRiskGuardDisabledError,
)
from application.admin_api.futures_risk_proof_service import (
    AdminApiFuturesRiskProofService,
    FuturesRiskProofError,
)
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import (
    FUTURES_COINBASE_EXCHANGE_SUBMISSION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS,
    FUTURES_LIVE_ADAPTER_EXECUTION_CONTRACTS,
    FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACTS,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON,
    FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON,
    get_disabled_live_execution_service,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminLiveAdmissionDecisionEvidence,
    FuturesRiskProofRecordRequest,
)
from application.admin_api.read_service import (
    AdminApiReadService,
    futures_command_suite_api_payload,
)
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
    AdminApiRole,
    AdminFuturesCommandAction,
    AdminFuturesCommandEnablementBlocker,
    AdminFuturesCommandReadinessClosureStep,
    AdminFuturesCommandRiskProofAcceptanceBlocker,
    AdminFuturesCommandRiskProofKind,
    AdminFuturesEvidenceSource,
    AdminFuturesRiskProofEvidenceSource,
    OrderSide,
    OrderType,
    TimeInForce,
)

# This file imports the full FastAPI app/route graph. Keep it in the serial
# regression lane so xdist cannot multiply the route-model memory footprint.
pytestmark = pytest.mark.serial


PAYLOAD_HASH = "a" * 64


def test_futures_command_service_contracts_are_disabled() -> None:
    service = AdminApiFuturesCommandService()

    assert set(FUTURES_COMMAND_SERVICE_CONTRACTS) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    }
    assert (
        FUTURES_COMMAND_SERVICE_CONTRACTS[
            AdminFuturesCommandAction.PLACE
        ].contract_ref
        == "application/admin_api/futures_command_service.py::place_futures_order"
    )
    assert (
        FUTURES_COMMAND_SERVICE_CONTRACTS[
            AdminFuturesCommandAction.RECONCILE
        ].contract_ref
        == (
            "application/admin_api/futures_command_service.py::"
            "reconcile_futures_position"
        )
    )

    with pytest.raises(FuturesCommandServiceDisabledError) as exc_info:
        service.place_futures_order()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "Coinbase calls" in message

    with pytest.raises(FuturesCommandServiceDisabledError) as exc_info:
        service.reconcile_futures_position()

    message = str(exc_info.value)
    assert "reconcile_futures_position" in message
    assert "reconciliation execution" in message
    assert "Coinbase calls" in message


def test_futures_risk_proof_route_and_writer_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()
    emitted_route_refs: set[str] = set()
    emitted_writer_refs: set[str] = set()

    assert len(FUTURES_PROOF_ROUTE_CONTRACTS) == 20
    assert len(FUTURES_PROOF_WRITER_CONTRACTS) == 20
    assert set(FUTURES_PROOF_ROUTE_CONTRACTS) == set(FUTURES_PROOF_WRITER_CONTRACTS)

    for (command, proof_kind), route_contract in FUTURES_PROOF_ROUTE_CONTRACTS.items():
        writer_contract = FUTURES_PROOF_WRITER_CONTRACTS[(command, proof_kind)]
        assert route_contract.command == command
        assert route_contract.proof_kind == proof_kind
        assert route_contract.method_name == (
            f"post_{command.value}_{proof_kind.value}_proof"
        )
        assert route_contract.contract_ref == (
            "application/admin_api/futures_proof_routes.py::"
            f"post_{command.value}_{proof_kind.value}_proof"
        )
        assert route_contract.route_path == (
            f"/api/v1/futures/proofs/{command.value}/{proof_kind.value}"
        )
        assert route_contract.method == "POST"
        assert route_contract.route_registered is False
        assert route_contract.proof_payloads_accepted is False
        assert route_contract.command_route_registered is False
        assert route_contract.command_draft_allowed is False
        assert route_contract.execution_allowed is False
        assert route_contract.live_coinbase_orders_ran is False

        assert writer_contract.command == command
        assert writer_contract.proof_kind == proof_kind
        assert writer_contract.method_name == (
            f"write_{command.value}_{proof_kind.value}_proof"
        )
        assert writer_contract.contract_ref == (
            "application/admin_api/futures_proof_writer.py::"
            f"write_{command.value}_{proof_kind.value}_proof"
        )
        assert writer_contract.method == "LOCAL"
        assert writer_contract.writer_enabled is False
        assert writer_contract.proof_records_accepted is False
        assert writer_contract.proof_records_write_allowed is False
        assert writer_contract.command_route_registered is False
        assert writer_contract.command_draft_allowed is False
        assert writer_contract.execution_allowed is False
        assert writer_contract.live_coinbase_orders_ran is False

    for command in command_suite.commands:
        for proof_requirement in command.risk_proof_requirements:
            route_contract = FUTURES_PROOF_ROUTE_CONTRACTS[
                (command.command, proof_requirement.proof_kind)
            ]
            writer_contract = FUTURES_PROOF_WRITER_CONTRACTS[
                (command.command, proof_requirement.proof_kind)
            ]
            assert proof_requirement.proof_contract_count == 2
            assert proof_requirement.blocking_proof_contract_count == 2
            assert proof_requirement.registered_proof_route_count == 0
            assert proof_requirement.enabled_proof_writer_count == 0
            assert proof_requirement.proof_contracts[0].required_backend_contract == (
                route_contract.contract_ref
            )
            assert proof_requirement.proof_contracts[0].required_route_path == (
                route_contract.route_path
            )
            assert proof_requirement.proof_contracts[0].required_method == (
                route_contract.method
            )
            assert proof_requirement.proof_contracts[0].route_registered is False
            assert proof_requirement.proof_contracts[0].proof_route_registered is False
            assert proof_requirement.proof_contracts[1].required_backend_contract == (
                writer_contract.contract_ref
            )
            assert proof_requirement.proof_contracts[1].required_method == (
                writer_contract.method
            )
            assert proof_requirement.proof_contracts[1].writer_enabled is False
            assert proof_requirement.proof_contracts[1].proof_writer_enabled is False
            assert all(
                contract.execution_allowed is False
                and contract.command_route_registered is False
                and contract.command_draft_allowed is False
                and contract.backend_owned is True
                and contract.browser_authority == "display_only"
                and contract.bff_authority == "forward_only_no_execution"
                for contract in proof_requirement.proof_contracts
            )
            emitted_route_refs.add(route_contract.contract_ref)
            emitted_writer_refs.add(writer_contract.contract_ref)

    assert emitted_route_refs == {
        contract.contract_ref for contract in FUTURES_PROOF_ROUTE_CONTRACTS.values()
    }
    assert emitted_writer_refs == {
        contract.contract_ref for contract in FUTURES_PROOF_WRITER_CONTRACTS.values()
    }


def test_futures_risk_proof_payload_field_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS) == 10
    first_payload_fields = command_suite.commands[0].risk_proof_requirements[
        0
    ].payload_fields
    assert [contract.sequence for contract in first_payload_fields] == list(
        range(1, 11)
    )
    assert all(
        contract.payload_field_present is False
        and contract.validation_registered is False
        and contract.command_route_registered is False
        and contract.command_draft_allowed is False
        and contract.execution_allowed is False
        and contract.proof_route_registered is False
        and contract.proof_writer_enabled is False
        and contract.live_coinbase_orders_ran is False
        for contract in FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS
    )

    for command in command_suite.commands:
        for proof_requirement in command.risk_proof_requirements:
            registry_rows = list(
                iter_futures_proof_payload_field_contracts(
                    command=command.command,
                    proof_kind=proof_requirement.proof_kind,
                    identity_key=command.identity_key,
                )
            )
            assert proof_requirement.payload_field_count == len(registry_rows)
            assert proof_requirement.blocking_payload_field_count == len(
                registry_rows
            )
            assert proof_requirement.present_payload_field_count == 0
            for emitted, (
                contract,
                validation_rule,
                required_evidence_ref,
            ) in zip(proof_requirement.payload_fields, registry_rows, strict=True):
                assert emitted.field == contract.field
                assert emitted.payload_path == contract.payload_path
                assert emitted.validation_rule == validation_rule
                assert emitted.required_evidence_ref == required_evidence_ref
                assert emitted.missing_evidence_ref == required_evidence_ref
                assert emitted.payload_field_present is False
                assert emitted.validation_registered is False
                assert emitted.command_route_registered is False
                assert emitted.command_draft_allowed is False
                assert emitted.execution_allowed is False
                assert emitted.proof_route_registered is False
                assert emitted.proof_writer_enabled is False
                assert emitted.backend_owned is True
                assert emitted.read_only is True
                assert emitted.spot_rule_authority is False
                assert emitted.browser_authority == "display_only"
                assert emitted.bff_authority == "forward_only_no_execution"


def test_futures_request_payload_field_contracts_are_disabled() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()

    assert len(FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS) == 22
    assert all(
        contract.required is True
        and contract.status == AdminApiGateStatus.BLOCKED
        and contract.source == AdminFuturesEvidenceSource.BACKEND_CONTRACT
        and contract.backend_owned is True
        and contract.spot_rule_authority is False
        and contract.command_route_registered is True
        and contract.command_draft_allowed is True
        and contract.execution_allowed is False
        and contract.validation_registered is False
        and contract.live_coinbase_orders_ran is False
        and contract.browser_authority == "display_only"
        and contract.bff_authority == "forward_only_no_execution"
        for contract in FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )

    emitted_count = 0
    for command in command_suite.commands:
        registry_rows = list(iter_futures_request_payload_contracts(command.command))
        emitted_count += len(command.request_fields)
        assert command.request_field_count == len(registry_rows)
        assert command.required_request_field_count == len(registry_rows)
        assert command.blocking_request_field_count == len(registry_rows)
        assert all(
            contract.contract_ref in command.required_backend_contracts
            for contract in registry_rows
        )
        for emitted, contract in zip(
            command.request_fields,
            registry_rows,
            strict=True,
        ):
            assert emitted.field == contract.field
            assert emitted.status == contract.status
            assert emitted.source == contract.source
            assert emitted.required == contract.required
            assert emitted.identity_field == contract.identity_field
            assert emitted.risk_field == contract.risk_field
            assert emitted.payload_field == contract.payload_field
            assert emitted.backend_owned == contract.backend_owned
            assert emitted.spot_rule_authority == contract.spot_rule_authority
            assert emitted.browser_authority == contract.browser_authority
            assert emitted.bff_authority == contract.bff_authority
            assert emitted.detail == contract.detail

    assert emitted_count == len(FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS)
    assert command_suite.request_field_count == len(
        FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )
    assert command_suite.blocking_request_field_count == len(
        FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS
    )


def test_futures_risk_guard_contract_is_disabled() -> None:
    guard = AdminApiFuturesRiskGuard()

    assert FUTURES_RISK_GUARD_CONTRACT.method_name == (
        "evaluate_futures_margin_collateral_liquidation"
    )
    assert FUTURES_RISK_GUARD_CONTRACT.contract_ref == (
        "application/admin_api/futures_risk_guard.py::"
        "evaluate_futures_margin_collateral_liquidation"
    )
    assert set(FUTURES_RISK_GUARD_CONTRACT.commands) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.RECONCILE,
    }

    with pytest.raises(FuturesRiskGuardDisabledError) as exc_info:
        guard.evaluate_futures_margin_collateral_liquidation()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "risk proof acceptance" in message
    assert "Coinbase calls" in message


def test_futures_reconciliation_contract_is_disabled() -> None:
    reconciliation = AdminApiFuturesReconciliation()

    assert FUTURES_RECONCILIATION_CONTRACT.method_name == (
        "record_futures_reconciliation_plan"
    )
    assert FUTURES_RECONCILIATION_CONTRACT.contract_ref == (
        "application/admin_api/futures_reconciliation.py::"
        "record_futures_reconciliation_plan"
    )
    assert set(FUTURES_RECONCILIATION_CONTRACT.commands) == {
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    }

    with pytest.raises(FuturesReconciliationDisabledError) as exc_info:
        reconciliation.record_futures_reconciliation_plan()

    message = str(exc_info.value)
    assert "contract-defined but not executable" in message
    assert "reconciliation execution" in message
    assert "Coinbase calls" in message


def test_futures_route_contracts_register_no_live_command_drafts() -> None:
    expected_refs = {
        AdminFuturesCommandAction.PLACE: (
            "api/v1/routes/futures.py::futures_place_route_contract"
        ),
        AdminFuturesCommandAction.CLOSE_REDUCE: (
            "api/v1/routes/futures.py::futures_close_reduce_route_contract"
        ),
        AdminFuturesCommandAction.CANCEL: (
            "api/v1/routes/futures.py::futures_cancel_route_contract"
        ),
        AdminFuturesCommandAction.RECONCILE: (
            "api/v1/routes/futures.py::futures_reconcile_route_contract"
        ),
    }
    expected_routes = {
        AdminFuturesCommandAction.PLACE: "/api/v1/futures/orders",
        AdminFuturesCommandAction.CLOSE_REDUCE: (
            "/api/v1/futures/positions/{position_key}/close-reduce"
        ),
        AdminFuturesCommandAction.CANCEL: (
            "/api/v1/futures/orders/{client_order_id}/cancel"
        ),
        AdminFuturesCommandAction.RECONCILE: (
            "/api/v1/futures/positions/{position_key}/reconciliation"
        ),
    }

    assert set(FUTURES_ROUTE_CONTRACTS) == set(AdminFuturesCommandAction)
    assert futures_routes.futures_place_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.PLACE]
    )
    assert futures_routes.futures_close_reduce_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.CLOSE_REDUCE]
    )
    assert futures_routes.futures_cancel_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.CANCEL]
    )
    assert futures_routes.futures_reconcile_route_contract is (
        FUTURES_ROUTE_CONTRACTS[AdminFuturesCommandAction.RECONCILE]
    )

    for command, contract in FUTURES_ROUTE_CONTRACTS.items():
        assert contract.contract_ref == expected_refs[command]
        assert contract.route_template == expected_routes[command]
        assert contract.method == "POST"
        assert contract.route_registered is True
        assert contract.command_draft_allowed is True
        assert contract.live_adapter_bound is False
        assert contract.execution_allowed is False
        assert contract.reconciliation_execution_enabled is False
        assert contract.state_mutation_allowed is False
        assert contract.live_coinbase_orders_ran is False
        assert contract.browser_authority == "display_only"
        assert contract.bff_authority == "forward_only_no_execution"
        assert futures_live_adapter_contract_ref(command) == (
            f"application/admin_api/live_execution.py::{command.value}_adapter_contract"
        )
        adapter_contract = FUTURES_LIVE_ADAPTER_CONTRACTS[command]
        assert adapter_contract.contract_ref == futures_live_adapter_contract_ref(command)
        assert adapter_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert adapter_contract.present is True
        assert adapter_contract.adapter_configured is False
        assert adapter_contract.adapter_constructed is False
        assert adapter_contract.invocation_allowed is False
        assert adapter_contract.execution_allowed is False
        assert adapter_contract.live_coinbase_orders_ran is False
        assert adapter_contract.browser_authority == "display_only"
        assert adapter_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in adapter_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in adapter_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in adapter_contract.blockers
        )

        construction_contract = FUTURES_LIVE_ADAPTER_CONSTRUCTION_CONTRACTS[
            command
        ]
        assert construction_contract.contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert construction_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert construction_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert construction_contract.present is True
        assert construction_contract.construction_allowed is False
        assert construction_contract.adapter_constructed is False
        assert construction_contract.invocation_allowed is False
        assert construction_contract.execution_allowed is False
        assert construction_contract.live_coinbase_orders_ran is False
        assert construction_contract.browser_authority == "display_only"
        assert construction_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in construction_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in construction_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in construction_contract.blockers
        )

        decision_contract = FUTURES_LIVE_ADAPTER_DECISION_CONTRACTS[command]
        assert decision_contract.contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert decision_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert decision_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert decision_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert decision_contract.present is True
        assert decision_contract.decision_allowed is False
        assert decision_contract.decision_record_required is True
        assert decision_contract.decision_record_available is False
        assert decision_contract.adapter_constructed is False
        assert decision_contract.invocation_allowed is False
        assert decision_contract.execution_allowed is False
        assert decision_contract.live_coinbase_orders_ran is False
        assert decision_contract.browser_authority == "display_only"
        assert decision_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in decision_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in decision_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in decision_contract.blockers
        )

        decision_record_contract = FUTURES_LIVE_ADAPTER_DECISION_RECORD_CONTRACTS[
            command
        ]
        assert decision_record_contract.contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert decision_record_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert decision_record_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert decision_record_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert decision_record_contract.invocation_contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert decision_record_contract.present is True
        assert decision_record_contract.decision_record_writer_configured is False
        assert decision_record_contract.decision_record_allowed is False
        assert decision_record_contract.decision_record_available is False
        assert decision_record_contract.adapter_constructed is False
        assert decision_record_contract.invocation_allowed is False
        assert decision_record_contract.execution_allowed is False
        assert decision_record_contract.live_coinbase_orders_ran is False
        assert decision_record_contract.browser_authority == "display_only"
        assert decision_record_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in decision_record_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in decision_record_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in decision_record_contract.blockers
        )

        invocation_contract = FUTURES_LIVE_ADAPTER_INVOCATION_CONTRACTS[command]
        assert invocation_contract.contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert invocation_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert invocation_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert invocation_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert invocation_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert invocation_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert invocation_contract.present is True
        assert invocation_contract.invocation_adapter_configured is False
        assert invocation_contract.invocation_allowed is False
        assert invocation_contract.invocation_performed is False
        assert invocation_contract.execution_allowed is False
        assert invocation_contract.live_coinbase_orders_ran is False
        assert invocation_contract.browser_authority == "display_only"
        assert invocation_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in invocation_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in invocation_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in invocation_contract.blockers
        )

        execution_contract = FUTURES_LIVE_ADAPTER_EXECUTION_CONTRACTS[command]
        assert execution_contract.contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert execution_contract.adapter_contract_ref == (
            futures_live_adapter_contract_ref(command)
        )
        assert execution_contract.construction_contract_ref == (
            futures_live_adapter_construction_contract_ref(command)
        )
        assert execution_contract.decision_contract_ref == (
            futures_live_adapter_decision_contract_ref(command)
        )
        assert execution_contract.decision_record_contract_ref == (
            futures_live_adapter_decision_record_contract_ref(command)
        )
        assert execution_contract.invocation_contract_ref == (
            futures_live_adapter_invocation_contract_ref(command)
        )
        assert execution_contract.coinbase_exchange_submission_contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert execution_contract.present is True
        assert execution_contract.execution_adapter_configured is False
        assert execution_contract.execution_allowed is False
        assert execution_contract.execution_performed is False
        assert execution_contract.coinbase_submission_allowed is False
        assert execution_contract.coinbase_order_submit_ran is False
        assert execution_contract.live_coinbase_orders_ran is False
        assert execution_contract.browser_authority == "display_only"
        assert execution_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in execution_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in execution_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in execution_contract.blockers
        )

        submission_contract = FUTURES_COINBASE_EXCHANGE_SUBMISSION_CONTRACTS[command]
        assert submission_contract.contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert submission_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert submission_contract.post_exchange_submission_reconciliation_contract_ref == (
            futures_post_exchange_submission_reconciliation_contract_ref(command)
        )
        assert submission_contract.present is True
        assert submission_contract.coinbase_submission_allowed is False
        assert submission_contract.coinbase_order_submit_ran is False
        assert submission_contract.coinbase_cancel_submit_ran is False
        assert submission_contract.exchange_order_acknowledged is False
        assert submission_contract.post_exchange_reconciliation_required is True
        assert submission_contract.post_exchange_reconciliation_available is True
        assert submission_contract.command_route_registered is False
        assert submission_contract.command_draft_allowed is False
        assert submission_contract.execution_allowed is False
        assert submission_contract.reconciliation_execution_enabled is False
        assert submission_contract.state_mutation_allowed is False
        assert submission_contract.live_coinbase_orders_ran is False
        assert submission_contract.browser_authority == "display_only"
        assert submission_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in submission_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in submission_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in submission_contract.blockers
        )

        reconciliation_contract = (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACTS[command]
        )
        assert reconciliation_contract.contract_ref == (
            futures_post_exchange_submission_reconciliation_contract_ref(command)
        )
        assert reconciliation_contract.coinbase_exchange_submission_contract_ref == (
            futures_coinbase_exchange_submission_contract_ref(command)
        )
        assert reconciliation_contract.execution_contract_ref == (
            futures_live_adapter_execution_contract_ref(command)
        )
        assert reconciliation_contract.present is True
        assert reconciliation_contract.reconciliation_required is True
        assert reconciliation_contract.reconciliation_available is True
        assert reconciliation_contract.exchange_order_acknowledgement_required is True
        assert reconciliation_contract.exchange_order_acknowledged is False
        assert reconciliation_contract.reconciliation_execution_enabled is False
        assert reconciliation_contract.reconciliation_executed is False
        assert reconciliation_contract.command_route_registered is False
        assert reconciliation_contract.command_draft_allowed is False
        assert reconciliation_contract.execution_allowed is False
        assert reconciliation_contract.coinbase_submission_allowed is False
        assert reconciliation_contract.coinbase_order_submit_ran is False
        assert reconciliation_contract.coinbase_cancel_submit_ran is False
        assert reconciliation_contract.state_mutation_allowed is False
        assert reconciliation_contract.live_coinbase_orders_ran is False
        assert reconciliation_contract.browser_authority == "display_only"
        assert reconciliation_contract.bff_authority == "forward_only_no_execution"
        assert "create_order" in reconciliation_contract.forbidden_methods
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_EXECUTION_DISABLED_REASON
            in reconciliation_contract.blockers
        )
        assert (
            FUTURES_POST_EXCHANGE_SUBMISSION_RECONCILIATION_CONTRACT_MISSING_REASON
            not in reconciliation_contract.blockers
        )


def _headers(*, roles: str = "viewer") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "X-Admin-Actor": "operator-001",
        "X-Admin-Roles": roles,
    }


def _command_headers(
    *,
    idempotency_key: str,
    operator_intent: str,
    roles: str = AdminApiRole.ADMIN.value,
) -> dict[str, str]:
    headers = _headers(roles=roles)
    headers.update({
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-futures-risk-proof-route-001",
        "X-Operator-Intent": operator_intent,
    })
    return headers


def _risk_proof_request() -> FuturesRiskProofRecordRequest:
    return FuturesRiskProofRecordRequest(
        command=AdminFuturesCommandAction.PLACE,
        proof_kind=AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        proof_contract_ref="futures_place.margin_collateral.proof_contract",
        evidence_ref="futures_place.margin_collateral.runtime_margin_review",
        evidence_source=AdminFuturesRiskProofEvidenceSource.TEST_EVIDENCE,
        risk_evidence_refs=[
            "futures.account.margin",
            "futures.account.collateral",
        ],
        product_id="BIT-20DEC30-CDE",
        reconciliation_plan_id="futures-reconciliation-plan-001",
        approval_snapshot_id="futures-approval-snapshot-001",
        admission_audit_id="futures-admission-audit-001",
        cap_guard_decision_id="futures-cap-guard-001",
        operator_reason="focused regression proof",
    )


def _admission_decision(
    request: FuturesRiskProofRecordRequest,
) -> AdminLiveAdmissionDecisionEvidence:
    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route="/api/v1/futures/risk-proofs",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="futures_risk_proof",
        identity_value=f"{request.command.value}:{request.proof_kind.value}",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        service_method="record_futures_risk_proof",
        actor_id="operator-001",
        idempotency_key="futures-risk-proof-idem-001",
        operator_intent="record futures risk proof evidence",
        payload_hash=PAYLOAD_HASH,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=request.approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id="risk-reviewer-001",
        approval_snapshot_requested_by_actor_id="operator-001",
        approval_snapshot_expires_at="2099-01-01T00:00:00+00:00",
        admission_audit_present=True,
        admission_audit_id=request.admission_audit_id,
        cap_guard_present=True,
        cap_guard_decision_id=request.cap_guard_decision_id,
        reconciliation_plan_present=True,
        reconciliation_plan_id=request.reconciliation_plan_id,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["futures risk proof append-only contract test evidence"],
        detail="Futures risk proof admission evidence remains live-disabled.",
    )


def _payload_hash_for_route(
    *,
    request: FuturesRiskProofRecordRequest,
    idempotency_key: str,
    operator_intent: str,
) -> str:
    del idempotency_key
    actor = AdminApiActor(
        actor_id="operator-001",
        roles=[AdminApiRole.ADMIN],
    )
    return _idempotency_payload_hash(
        endpoint="POST /api/v1/futures/risk-proofs",
        actor=actor,
        operator_intent=operator_intent,
        body=request.model_dump(mode="json"),
    )


def _append_futures_risk_proof_admission_chain(
    *,
    request: FuturesRiskProofRecordRequest,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
) -> None:
    route = "/api/v1/futures/risk-proofs"
    method = "POST"
    module_id = "futures_perpetuals"
    identity_key = "futures_risk_proof"
    identity_value = f"{request.command.value}:{request.proof_kind.value}"
    action_class = AdminApiActionClass.LOCAL_STATE_MUTATION
    permission = AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    service_method = "record_futures_risk_proof"
    approval = AdminApiApprovalRecord(
        approval_id=request.approval_snapshot_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        approved_by_actor_id="risk-reviewer-001",
        requested_by_actor_id="operator-001",
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        cap_guard_decision_ref=request.cap_guard_decision_id,
        reconciliation_plan_ref=request.reconciliation_plan_id,
    )
    approval_store.append(approval)
    admission_decision = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        actor_id="operator-001",
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=approval.approval_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id=approval.approved_by_actor_id,
        approval_snapshot_requested_by_actor_id=approval.requested_by_actor_id,
        approval_snapshot_expires_at=approval.expires_at.isoformat(),
        admission_audit_present=False,
        cap_guard_present=False,
        reconciliation_plan_present=False,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["prior append-only futures risk-proof admission audit"],
        detail="Prior backend-owned futures risk-proof admission audit.",
    )
    audit_store.append(
        AdminApiAuditEvent(
            audit_id=request.admission_audit_id,
            actor_id="operator-001",
            action_class=action_class,
            permission=permission,
            endpoint=f"{method} {route}",
            request_id="corr-futures-risk-proof-admission",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            approval_id=approval.approval_id,
            status=AdminApiCommandStatus.REJECTED,
            failure_stage="approval",
            message="Prior futures risk-proof admission audit.",
            admission_decision=admission_decision,
        )
    )
    cap_guard_store.append(
        CapGuardDecisionRecord(
            decision_id=request.cap_guard_decision_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            cap_policy_ref="futures_risk_proof_cap:local_only",
            guard_policy_ref="futures_risk_proof_prerequisites",
            product_scope="futures risk proof local evidence",
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof cap/guard evidence.",
        )
    )
    reconciliation_store.append(
        ReconciliationPlanRecord(
            plan_id=request.reconciliation_plan_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            cap_guard_decision_id=request.cap_guard_decision_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            reconciliation_policy_ref="futures_risk_proof_reconciliation:local_only",
            product_scope="futures risk proof local evidence",
            exchange_submission_required=False,
            post_submit_reconciliation_required=False,
            retained_inventory_required=False,
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof reconciliation evidence.",
        )
    )


def test_futures_risk_proof_service_persists_no_live_record(tmp_path) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()

    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    assert record.mutation_family.value == "futures_risk_proof"
    assert record.required_permission == AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    assert record.proof_persisted is True
    assert record.risk_proof_accepted is False
    assert record.command_route_registered is False
    assert record.command_execution_allowed is False
    assert record.coinbase_order_submitted is False
    assert record.live_coinbase_orders_ran is False
    assert store.find_by_proof_id(record.futures_risk_proof_id) == record


def test_futures_risk_proof_identity_lookup_is_not_limited_to_recent_window(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    service = AdminApiFuturesRiskProofService()
    old_record = service.record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-old-idem",
        correlation_id="corr-futures-risk-proof-old",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-old",
    )

    for index in range(501):
        store.append(
            old_record.model_copy(
                update={
                    "futures_risk_proof_id": f"futures-risk-proof-new-{index}",
                    "idempotency_key": f"futures-risk-proof-new-idem-{index}",
                    "correlation_id": f"corr-futures-risk-proof-new-{index}",
                    "audit_id": f"audit-futures-risk-proof-new-{index}",
                }
            )
        )

    assert all(
        record.futures_risk_proof_id != old_record.futures_risk_proof_id
        for record in store.read_recent(limit=500)
    )
    assert store.find_by_proof_id(old_record.futures_risk_proof_id) == old_record

    with pytest.raises(FuturesRiskProofError, match="already exists"):
        service.record_proof(
            proof_store=store,
            body=request.model_copy(
                update={
                    "futures_risk_proof_id": old_record.futures_risk_proof_id,
                }
            ),
            admission_decision=_admission_decision(request),
            actor_id="operator-001",
            operator_intent="record futures risk proof duplicate evidence",
            idempotency_key="futures-risk-proof-duplicate-idem",
            correlation_id="corr-futures-risk-proof-duplicate",
            payload_hash=PAYLOAD_HASH,
            audit_id="audit-futures-risk-proof-duplicate",
        )


def test_futures_risk_proof_readback_routes_return_store_records(
    monkeypatch,
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: store
    )
    client = TestClient(app)

    list_response = client.get(
        "/api/v1/futures/risk-proofs",
        headers=_headers(),
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["proof_records_created"] is True
    assert list_payload["items"][0]["futures_risk_proof_id"] == (
        record.futures_risk_proof_id
    )
    assert list_payload["items"][0]["live_coinbase_orders_ran"] is False

    detail_response = client.get(
        f"/api/v1/futures/risk-proofs/{record.futures_risk_proof_id}",
        headers=_headers(),
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["found"] is True
    assert detail_payload["record"]["command"] == AdminFuturesCommandAction.PLACE.value
    assert detail_payload["record"]["risk_proof_accepted"] is False


def test_futures_risk_proof_post_route_records_through_shared_admission(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    proof_store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    command_service = AdminApiCommandService(
        AdminApiCommandDependencies(
            futures_risk_proof_store_getter=lambda: proof_store,
            audit_store_getter=lambda: audit_store,
            uuid_factory=lambda: "futures-risk-proof-command-audit",
        )
    )
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: proof_store
    )
    app.dependency_overrides[futures_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[futures_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[futures_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[futures_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[futures_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[futures_routes.get_live_execution_service] = (
        get_disabled_live_execution_service
    )
    app.dependency_overrides[futures_routes.get_command_service] = (
        lambda: command_service
    )
    request = _risk_proof_request()
    idempotency_key = "futures-risk-proof-route-idem"
    operator_intent = "record futures risk proof evidence"
    payload_hash = _payload_hash_for_route(
        request=request,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
    )
    _append_futures_risk_proof_admission_chain(
        request=request,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/futures/risk-proofs",
        headers=_command_headers(
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
        ),
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert payload["required_permission"] == "futures_risk_proof:record"
    assert payload["service_method"] == "record_futures_risk_proof"
    assert payload["live_exchange_submitted"] is False
    admission = payload["guard"]["admission_decision"]
    assert admission["approval_snapshot_present"] is True
    assert admission["admission_audit_present"] is True
    assert admission["cap_guard_present"] is True
    assert admission["reconciliation_plan_present"] is True
    data = payload["data"]
    assert data["proof_persisted"] is True
    assert data["risk_proof_accepted"] is False
    assert data["command_route_registered"] is False
    assert data["command_draft_created"] is False
    assert data["command_execution_allowed"] is False
    assert data["coinbase_order_submitted"] is False
    assert data["coinbase_order_cancel_submitted"] is False
    assert data["live_coinbase_orders_ran"] is False
    assert data["reconciliation_executed"] is False
    assert data["order_state_mutated"] is False
    assert data["exchange_state_mutated"] is False
    assert data["browser_authority"] == "display_only"
    assert data["bff_authority"] == "forward_only_no_execution"
    assert proof_store.read_recent(limit=10)[0].futures_risk_proof_id == (
        data["futures_risk_proof_id"]
    )
    assert idempotency_store.get_record(idempotency_key) is not None


def test_futures_command_draft_routes_are_registered_and_live_disabled(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    app = create_app()
    app.dependency_overrides[futures_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[futures_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[futures_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[futures_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[futures_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[futures_routes.get_live_execution_service] = (
        get_disabled_live_execution_service
    )

    client = TestClient(app)
    cases = [
        {
            "path": "/api/v1/futures/orders",
            "idempotency_key": "futures-place-draft-idem",
            "operator_intent": "draft disabled futures placement",
            "service_method": "place_futures_order",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            "required_permission": AdminApiPermission.ORDER_CREATE,
            "command": AdminFuturesCommandAction.PLACE,
            "identity_key": "product_id",
            "identity_value": "BIT-20DEC30-CDE",
            "payload": {
                "product_id": "BIT-20DEC30-CDE",
                "side": OrderSide.BUY.value,
                "order_type": OrderType.LIMIT.value,
                "size": "1",
                "limit_price": "1",
                "time_in_force": TimeInForce.GOOD_UNTIL_CANCELLED.value,
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/positions/BIT-20DEC30-CDE:long/close-reduce",
            "idempotency_key": "futures-close-reduce-draft-idem",
            "operator_intent": "draft disabled futures close reduce",
            "service_method": "close_or_reduce_futures_position",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "required_permission": AdminApiPermission.ORDER_CANCEL,
            "command": AdminFuturesCommandAction.CLOSE_REDUCE,
            "identity_key": "position_key",
            "identity_value": "BIT-20DEC30-CDE:long",
            "payload": {
                "order_type": OrderType.MARKET.value,
                "size": "1",
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/orders/client-order-futures-001/cancel",
            "idempotency_key": "futures-cancel-draft-idem",
            "operator_intent": "draft disabled futures cancel",
            "service_method": "cancel_futures_order",
            "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            "required_permission": AdminApiPermission.ORDER_CANCEL,
            "command": AdminFuturesCommandAction.CANCEL,
            "identity_key": "client_order_id",
            "identity_value": "client-order-futures-001",
            "payload": {
                "product_id": "BIT-20DEC30-CDE",
                "operator_reason": "focused no-live route smoke",
            },
        },
        {
            "path": "/api/v1/futures/positions/BIT-20DEC30-CDE:long/reconciliation",
            "idempotency_key": "futures-reconcile-draft-idem",
            "operator_intent": "draft disabled futures reconciliation",
            "service_method": "reconcile_futures_position",
            "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION,
            "required_permission": AdminApiPermission.RECONCILIATION_RECORD,
            "command": AdminFuturesCommandAction.RECONCILE,
            "identity_key": "position_key",
            "identity_value": "BIT-20DEC30-CDE:long",
            "payload": {
                "reconciliation_reason": "focused no-live route smoke",
                "expected_position_state": "not provided by fixture",
                "operator_reason": "focused no-live route smoke",
            },
        },
    ]

    for case in cases:
        response = client.post(
            str(case["path"]),
            headers=_command_headers(
                idempotency_key=str(case["idempotency_key"]),
                operator_intent=str(case["operator_intent"]),
            ),
            json=case["payload"],
        )

        assert response.status_code == 501, response.json()
        payload = response.json()
        assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
        assert payload["service_method"] == case["service_method"]
        assert payload["action_class"] == case["action_class"].value
        assert payload["required_permission"] == case["required_permission"].value
        assert payload["failure_stage"] == "approval"
        assert payload["live_exchange_submitted"] is False
        if case["identity_key"] == "client_order_id":
            assert payload["client_order_id"] == case["identity_value"]
        else:
            assert payload["client_order_id"] is None
        admission = payload["guard"]["admission_decision"]
        assert admission["allowed"] is False
        assert admission["live_exchange_submitted"] is False
        assert admission["module_id"] == "futures_perpetuals"
        assert admission["identity_key"] == case["identity_key"]
        assert admission["identity_value"] == case["identity_value"]
        data = payload["data"]
        assert data["command"] == case["command"].value
        assert data["identity_key"] == case["identity_key"]
        assert data["identity_value"] == case["identity_value"]
        assert data["coinbase_order_submitted"] is False
        assert data["coinbase_cancel_submitted"] is False
        assert data["reconciliation_executed"] is False
        assert data["futures_state_mutated"] is False
        assert data["order_state_mutated"] is False
        assert data["exchange_state_mutated"] is False
        assert data["live_adapter_invoked"] is False
        assert data["browser_authority"] == "display_only"
        assert data["bff_authority"] == "forward_only_no_execution"
        assert data["spot_rule_authority"] is False
        assert idempotency_store.get_record(str(case["idempotency_key"])) is not None


def test_futures_risk_proof_routes_are_inventory_and_openapi_bound(
    monkeypatch,
) -> None:
    surfaces = {item.surface: item for item in ADMIN_API_ROUTE_INVENTORY}
    command_surfaces = {
        "POST /api/v1/futures/orders": (
            AdminApiPermission.ORDER_CREATE,
            "place_futures_order",
            AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        ),
        "POST /api/v1/futures/positions/{position_key}/close-reduce": (
            AdminApiPermission.ORDER_CANCEL,
            "close_or_reduce_futures_position",
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        ),
        "POST /api/v1/futures/orders/{client_order_id}/cancel": (
            AdminApiPermission.ORDER_CANCEL,
            "cancel_futures_order",
            AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        ),
        "POST /api/v1/futures/positions/{position_key}/reconciliation": (
            AdminApiPermission.RECONCILIATION_RECORD,
            "reconcile_futures_position",
            AdminApiActionClass.LOCAL_STATE_MUTATION,
        ),
    }
    for surface, (
        required_permission,
        shared_method,
        action_class,
    ) in command_surfaces.items():
        assert surfaces[surface].permission == required_permission
        assert surfaces[surface].shared_method == shared_method
        assert surfaces[surface].action_class == action_class
        assert surfaces[surface].idempotency == "required"
        assert surfaces[surface].audit == "required"
        assert "route-bound draft only" in surfaces[surface].parity_test

    post_surface = "POST /api/v1/futures/risk-proofs"
    assert surfaces[post_surface].permission == (
        AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    )
    assert surfaces[post_surface].shared_method == "record_futures_risk_proof"
    assert surfaces[post_surface].action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert (
        surfaces["GET /api/v1/futures/risk-proofs"].shared_method
        == "list_futures_risk_proofs"
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    schema = create_app().openapi()
    assert "/api/v1/futures/risk-proofs" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert "get" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert "/api/v1/futures/orders" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/futures/orders"]
    assert "/api/v1/futures/orders/{client_order_id}/cancel" in schema["paths"]
    assert (
        "post"
        in schema["paths"]["/api/v1/futures/orders/{client_order_id}/cancel"]
    )
    assert (
        "/api/v1/futures/positions/{position_key}/close-reduce"
        in schema["paths"]
    )
    assert (
        "post"
        in schema["paths"][
            "/api/v1/futures/positions/{position_key}/close-reduce"
        ]
    )
    assert (
        "/api/v1/futures/positions/{position_key}/reconciliation"
        in schema["paths"]
    )
    assert (
        "post"
        in schema["paths"][
            "/api/v1/futures/positions/{position_key}/reconciliation"
        ]
    )
    assert (
        "/api/v1/futures/risk-proofs/{futures_risk_proof_id}"
        in schema["paths"]
    )


def test_futures_command_enablement_blocker_summaries_remain_read_only() -> None:
    command_suite = AdminApiReadService().build_futures_command_suite()
    summaries_by_blocker = {
        item.blocker: item for item in command_suite.command_enablement_blocker_summaries
    }

    assert command_suite.missing_backend_contracts == []
    assert all(not item.missing_backend_contracts for item in command_suite.commands)
    assert command_suite.command_enablement_blocker_summary_count == 6
    assert command_suite.command_enablement_blocker_summary_blocking_count == 6
    assert command_suite.command_enablement_sequence_step_count == 5
    assert command_suite.command_enablement_sequence_step_blocking_count == 5
    assert command_suite.command_enablement_sequence_command_trace_count == 20
    assert command_suite.command_enablement_sequence_command_trace_blocking_count == 20
    assert set(summaries_by_blocker) == {
        AdminFuturesCommandEnablementBlocker.UNRESOLVED_PREREQUISITES,
        AdminFuturesCommandEnablementBlocker.REQUEST_PAYLOAD_CONTRACTS,
        AdminFuturesCommandEnablementBlocker.SEMANTIC_GUARD_EVIDENCE,
        AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE,
        AdminFuturesCommandEnablementBlocker.LIVE_SERVICE_ADAPTER,
        AdminFuturesCommandEnablementBlocker.CONTEXTLESS_REVIEW_GATE,
    }
    affected_commands = [
        AdminFuturesCommandAction.PLACE,
        AdminFuturesCommandAction.CLOSE_REDUCE,
        AdminFuturesCommandAction.CANCEL,
        AdminFuturesCommandAction.RECONCILE,
    ]

    for blocker, summary in summaries_by_blocker.items():
        assert summary.status == AdminApiGateStatus.BLOCKED
        assert summary.blocking is True
        assert summary.command_count == 4
        assert summary.affected_commands == affected_commands
        assert summary.required_evidence_refs
        assert summary.required_backend_contracts
        assert summary.evidence_ref_count == len(summary.required_evidence_refs)
        assert summary.command_route_registered is True
        assert summary.command_draft_allowed is True
        assert summary.execution_allowed is False
        assert summary.live_coinbase_orders_ran is False
        assert summary.backend_owned is True
        assert summary.read_only is True
        assert summary.spot_rule_authority is False
        assert summary.browser_authority == "display_only"
        assert summary.bff_authority == "forward_only_no_execution"

    risk_summary = summaries_by_blocker[
        AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE
    ]
    assert "futures_place_product_scope_proof_record_acceptance" in (
        risk_summary.required_evidence_refs
    )
    assert "grant command authority" in risk_summary.detail

    assert (
        AdminFuturesCommandEnablementBlocker.ADMIN_COMMAND_ROUTE
        not in summaries_by_blocker
    )

    contextless_summary = summaries_by_blocker[
        AdminFuturesCommandEnablementBlocker.CONTEXTLESS_REVIEW_GATE
    ]
    assert "blind_contextless_agent_review" in (
        contextless_summary.required_evidence_refs
    )

    sequence_steps_by_step = {
        item.step: item for item in command_suite.command_enablement_sequence_steps
    }
    assert list(sequence_steps_by_step) == [
        AdminFuturesCommandReadinessClosureStep.RESOLVE_PREREQUISITE_CONTRACTS,
        AdminFuturesCommandReadinessClosureStep.DEFINE_REQUEST_PAYLOAD_CONTRACT,
        AdminFuturesCommandReadinessClosureStep.BIND_SEMANTIC_GUARD_EVIDENCE,
        AdminFuturesCommandReadinessClosureStep.BIND_LIVE_SERVICE_ADAPTER,
        AdminFuturesCommandReadinessClosureStep.RUN_CONTEXTLESS_REVIEW_GATE,
    ]
    for index, sequence_step in enumerate(
        command_suite.command_enablement_sequence_steps,
        start=1,
    ):
        assert sequence_step.sequence == index
        assert sequence_step.status == AdminApiGateStatus.BLOCKED
        assert sequence_step.blocking is True
        assert sequence_step.command_count == 4
        assert sequence_step.affected_commands == affected_commands
        assert sequence_step.source_blockers
        assert sequence_step.command_route_registered is True
        assert sequence_step.command_draft_allowed is True
        assert sequence_step.execution_allowed is False
        assert sequence_step.live_coinbase_orders_ran is False
        assert sequence_step.backend_owned is True
        assert sequence_step.read_only is True
        assert sequence_step.spot_rule_authority is False
        assert sequence_step.browser_authority == "display_only"
        assert sequence_step.bff_authority == "forward_only_no_execution"

    semantic_step = sequence_steps_by_step[
        AdminFuturesCommandReadinessClosureStep.BIND_SEMANTIC_GUARD_EVIDENCE
    ]
    assert AdminFuturesCommandEnablementBlocker.RISK_PROOF_ACCEPTANCE in (
        semantic_step.source_blockers
    )
    adapter_step = sequence_steps_by_step[
        AdminFuturesCommandReadinessClosureStep.BIND_LIVE_SERVICE_ADAPTER
    ]
    assert (
        "application/admin_api/live_execution.py::futures_place_adapter_contract"
        in adapter_step.required_backend_contracts
    )

    traces_by_step = {}
    for trace in command_suite.command_enablement_sequence_command_traces:
        traces_by_step.setdefault(trace.step, []).append(trace)
        assert trace.trace_id == f"{trace.step.value}::{trace.command.value}"
        assert trace.sequence == sequence_steps_by_step[trace.step].sequence
        assert trace.status == AdminApiGateStatus.BLOCKED
        assert trace.blocking is True
        assert trace.source_blockers == sequence_steps_by_step[trace.step].source_blockers
        assert trace.required_evidence_ref_count == len(trace.required_evidence_refs)
        assert trace.command_route_registered is True
        assert trace.command_draft_allowed is True
        assert trace.execution_allowed is False
        assert trace.reconciliation_execution_allowed is False
        assert trace.futures_state_mutation_allowed is False
        assert trace.live_coinbase_orders_ran is False
        assert trace.backend_owned is True
        assert trace.read_only is True
        assert trace.spot_rule_authority is False
        assert trace.browser_authority == "display_only"
        assert trace.bff_authority == "forward_only_no_execution"
        assert "This trace row is read-only evidence" in trace.detail

    assert list(traces_by_step) == list(sequence_steps_by_step)
    for step, traces in traces_by_step.items():
        assert [trace.command for trace in traces] == [
            AdminFuturesCommandAction.PLACE,
            AdminFuturesCommandAction.CLOSE_REDUCE,
            AdminFuturesCommandAction.CANCEL,
            AdminFuturesCommandAction.RECONCILE,
        ]
        assert all(trace.sequence == sequence_steps_by_step[step].sequence for trace in traces)

    first_trace = command_suite.command_enablement_sequence_command_traces[0]
    assert first_trace.step == (
        AdminFuturesCommandReadinessClosureStep.RESOLVE_PREREQUISITE_CONTRACTS
    )
    assert first_trace.command == AdminFuturesCommandAction.PLACE
    assert first_trace.command_sequence == 1
    assert first_trace.command_step_sequence == 1
    assert first_trace.required_evidence_refs

    assert command_suite.live_coinbase_orders_ran is False
    assert command_suite.submitted_notional_usdc == "0"
    assert command_suite.executed_notional_usdc == "0"


def test_futures_command_suite_resolves_safe_risk_proof_record_without_authority(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    command_suite = AdminApiReadService(
        futures_risk_proof_store=store,
    ).build_futures_command_suite()
    place = next(
        item
        for item in command_suite.commands
        if item.command == AdminFuturesCommandAction.PLACE
    )
    margin_collateral = next(
        item
        for item in place.risk_proof_requirements
        if item.proof_kind == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL
    )

    assert command_suite.risk_proof_record_resolver_count == 20
    assert command_suite.resolved_risk_proof_record_resolver_count == 1
    assert command_suite.missing_risk_proof_record_resolver_count == 19
    assert command_suite.stale_or_invalid_risk_proof_record_resolver_count == 0
    assert command_suite.risk_proof_acceptance_blocker_count == 120
    assert command_suite.proof_record_resolved_but_acceptance_blocked_count == 1
    assert command_suite.risk_proof_semantic_contract_requirement_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_requirement_count
        == 34
    )
    assert command_suite.registered_risk_proof_semantic_contract_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_requirement_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_definition_count == 34
    assert command_suite.blocking_risk_proof_semantic_contract_definition_count == 34
    assert command_suite.ready_risk_proof_semantic_contract_definition_count == 0
    assert command_suite.registered_risk_proof_semantic_contract_definition_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_definition_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_validation_gate_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_validation_gate_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_contract_validation_gate_count == 0
    assert command_suite.registered_risk_proof_semantic_contract_validator_count == 0
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_validation_gate_count
        == 8
    )
    assert command_suite.risk_proof_semantic_contract_validator_contract_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_contract_validator_contract_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_contract_validator_contract_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_contract_validator_contract_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_contract_validator_contract_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_input_schema_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_input_schema_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_input_schema_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_input_schema_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_input_schema_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_output_schema_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_output_schema_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_output_schema_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_output_schema_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_output_schema_count
        == 8
    )
    assert command_suite.risk_proof_semantic_validator_registration_count == 34
    assert (
        command_suite.blocking_risk_proof_semantic_validator_registration_count
        == 34
    )
    assert command_suite.ready_risk_proof_semantic_validator_registration_count == 0
    assert (
        command_suite.registered_risk_proof_semantic_validator_registration_count
        == 0
    )
    assert (
        command_suite.runtime_observed_risk_proof_semantic_validator_registration_count
        == 8
    )
    assert place.resolved_risk_proof_record_resolver_count == 1
    assert place.risk_proof_acceptance_blocker_count == 36
    assert place.proof_record_resolved_but_acceptance_blocked_count == 1
    assert place.risk_proof_semantic_contract_requirement_count == 10
    assert place.blocking_risk_proof_semantic_contract_requirement_count == 10
    assert place.registered_risk_proof_semantic_contract_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_requirement_count == 4
    assert place.risk_proof_semantic_contract_definition_count == 10
    assert place.blocking_risk_proof_semantic_contract_definition_count == 10
    assert place.ready_risk_proof_semantic_contract_definition_count == 0
    assert place.registered_risk_proof_semantic_contract_definition_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_definition_count == 4
    assert place.risk_proof_semantic_contract_validation_gate_count == 10
    assert place.blocking_risk_proof_semantic_contract_validation_gate_count == 10
    assert place.ready_risk_proof_semantic_contract_validation_gate_count == 0
    assert place.registered_risk_proof_semantic_contract_validator_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_validation_gate_count == 4
    assert place.risk_proof_semantic_contract_validator_contract_count == 10
    assert place.blocking_risk_proof_semantic_contract_validator_contract_count == 10
    assert place.ready_risk_proof_semantic_contract_validator_contract_count == 0
    assert place.registered_risk_proof_semantic_contract_validator_contract_count == 0
    assert place.runtime_observed_risk_proof_semantic_contract_validator_contract_count == 4
    assert place.risk_proof_semantic_validator_input_schema_count == 10
    assert place.blocking_risk_proof_semantic_validator_input_schema_count == 10
    assert place.ready_risk_proof_semantic_validator_input_schema_count == 0
    assert place.registered_risk_proof_semantic_validator_input_schema_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_input_schema_count == 4
    assert place.risk_proof_semantic_validator_output_schema_count == 10
    assert place.blocking_risk_proof_semantic_validator_output_schema_count == 10
    assert place.ready_risk_proof_semantic_validator_output_schema_count == 0
    assert place.registered_risk_proof_semantic_validator_output_schema_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_output_schema_count == 4
    assert place.risk_proof_semantic_validator_registration_count == 10
    assert place.blocking_risk_proof_semantic_validator_registration_count == 10
    assert place.ready_risk_proof_semantic_validator_registration_count == 0
    assert place.registered_risk_proof_semantic_validator_registration_count == 0
    assert place.runtime_observed_risk_proof_semantic_validator_registration_count == 4
    assert margin_collateral.proof_record_lookup_status.value == "resolved"
    assert margin_collateral.latest_futures_risk_proof_id == (
        record.futures_risk_proof_id
    )
    assert margin_collateral.proof_record_resolved is True
    assert margin_collateral.proof_record_stale_or_invalid is False
    assert margin_collateral.proof_record_satisfies_requirement is False
    assert margin_collateral.proof_acceptance_blocked is True
    assert margin_collateral.proof_acceptance_blocker_count == 6
    assert margin_collateral.proof_record_resolves_acceptance is False
    assert margin_collateral.semantic_contract_requirement_count == 2
    assert margin_collateral.blocking_semantic_contract_requirement_count == 2
    assert margin_collateral.registered_semantic_contract_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_requirement_count == 2
    assert margin_collateral.semantic_contract_definition_count == 2
    assert margin_collateral.blocking_semantic_contract_definition_count == 2
    assert margin_collateral.ready_semantic_contract_definition_count == 0
    assert margin_collateral.registered_semantic_contract_definition_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_definition_count == 2
    assert margin_collateral.semantic_contract_validation_gate_count == 2
    assert margin_collateral.blocking_semantic_contract_validation_gate_count == 2
    assert margin_collateral.ready_semantic_contract_validation_gate_count == 0
    assert margin_collateral.registered_semantic_contract_validator_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_validation_gate_count == 2
    assert margin_collateral.semantic_contract_validator_contract_count == 2
    assert margin_collateral.blocking_semantic_contract_validator_contract_count == 2
    assert margin_collateral.ready_semantic_contract_validator_contract_count == 0
    assert margin_collateral.registered_semantic_contract_validator_contract_count == 0
    assert margin_collateral.runtime_observed_semantic_contract_validator_contract_count == 2
    assert margin_collateral.semantic_validator_input_schema_count == 2
    assert margin_collateral.blocking_semantic_validator_input_schema_count == 2
    assert margin_collateral.ready_semantic_validator_input_schema_count == 0
    assert margin_collateral.registered_semantic_validator_input_schema_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_input_schema_count == 2
    assert margin_collateral.semantic_validator_output_schema_count == 2
    assert margin_collateral.blocking_semantic_validator_output_schema_count == 2
    assert margin_collateral.ready_semantic_validator_output_schema_count == 0
    assert margin_collateral.registered_semantic_validator_output_schema_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_output_schema_count == 2
    assert margin_collateral.semantic_validator_registration_count == 2
    assert margin_collateral.blocking_semantic_validator_registration_count == 2
    assert margin_collateral.ready_semantic_validator_registration_count == 0
    assert margin_collateral.registered_semantic_validator_registration_count == 0
    assert margin_collateral.runtime_observed_semantic_validator_registration_count == 2
    assert [
        item.required_contract_ref
        for item in margin_collateral.semantic_contract_requirements
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item.contract_ref
        for item in margin_collateral.semantic_contract_definitions
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item.semantic_contract_definition_ref
        for item in margin_collateral.semantic_contract_definitions
    ] == [
        "futures_margin_collateral_risk_contract_definition",
        "futures_cap_guard_margin_collateral_link_definition",
    ]
    assert [
        item.validation_contract_ref
        for item in margin_collateral.semantic_contract_validation_gates
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator"
        ),
    ]
    assert [
        item.validator_contract_ref
        for item in margin_collateral.semantic_contract_validator_contracts
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_contract"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_contract"
        ),
    ]
    assert [
        item.validator_input_schema_ref
        for item in margin_collateral.semantic_validator_input_schemas
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_input_schema"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_input_schema"
        ),
    ]
    assert [
        item.validator_output_schema_ref
        for item in margin_collateral.semantic_validator_output_schemas
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_output_schema"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_output_schema"
        ),
    ]
    assert [
        item.validator_registration_ref
        for item in margin_collateral.semantic_validator_registrations
    ] == [
        (
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_registration"
        ),
        (
            "futures_place_margin_collateral_"
            "futures_cap_guard_margin_collateral_link_"
            "semantic_contract_validation_validator_registration"
        ),
    ]
    assert all(
        item.blocking is True
        and item.contract_registered is False
        and item.runtime_evidence_satisfies_contract is False
        and item.acceptance_ready is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_requirements
    )
    assert all(
        item.blocking is True
        and item.contract_registered is False
        and item.definition_ready is False
        and item.validation_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_definition is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_definitions
    )
    assert all(
        item.blocking is True
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validation is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_validation_gates
    )
    assert all(
        item.blocking is True
        and item.validator_contract_registered is False
        and item.input_schema_registered is False
        and item.output_schema_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validator_contract is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_contract_validator_contracts
    )
    assert all(
        item.blocking is True
        and item.input_schema_registered is False
        and item.validator_contract_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_input_schema is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_input_schemas
    )
    assert all(
        item.blocking is True
        and item.output_schema_registered is False
        and item.validator_contract_registered is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_output_schema is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_output_schemas
    )
    assert all(
        item.blocking is True
        and item.validator_contract_registered is False
        and item.input_schema_registered is False
        and item.output_schema_registered is False
        and item.validator_registration_ready is False
        and item.validator_registered is False
        and item.validation_ready is False
        and item.definition_ready is False
        and item.acceptance_ready is False
        and item.runtime_evidence_satisfies_validator_registration is False
        and item.satisfies_risk_proof is False
        and item.command_route_registered is False
        and item.command_draft_allowed is False
        and item.execution_allowed is False
        and item.proof_route_registered is False
        and item.proof_writer_enabled is False
        and item.spot_rule_authority is False
        and item.browser_authority == "display_only"
        and item.bff_authority == "forward_only_no_execution"
        for item in margin_collateral.semantic_validator_registrations
    )
    assert margin_collateral.proof_acceptance_blockers == [
        AdminFuturesCommandRiskProofAcceptanceBlocker.FUTURES_SEMANTIC_CONTRACTS_MISSING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.PROOF_RECORD_NOT_ACCEPTED,
        AdminFuturesCommandRiskProofAcceptanceBlocker.ACCEPTANCE_CRITERIA_BLOCKING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.COMMAND_ROUTE_MISSING,
        AdminFuturesCommandRiskProofAcceptanceBlocker.COMMAND_DRAFT_DISABLED,
        AdminFuturesCommandRiskProofAcceptanceBlocker.LIVE_EXECUTION_DISABLED,
    ]
    assert (
        "futures_place_margin_collateral_acceptance_criteria"
        in margin_collateral.proof_acceptance_blocker_refs
    )
    assert margin_collateral.proof_acceptance_blocker_authority == (
        "backend_futures_semantics_no_execution"
    )
    assert margin_collateral.satisfies_risk_proof is False
    assert margin_collateral.command_route_registered is False
    assert margin_collateral.command_draft_allowed is False
    assert margin_collateral.execution_allowed is False
    assert margin_collateral.live_coinbase_orders_ran is False


def test_futures_command_suite_fails_closed_on_latest_unsafe_risk_proof_record(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    safe_record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )
    unsafe_record = safe_record.model_copy(
        update={
            "futures_risk_proof_id": "futures-risk-proof-unsafe-latest",
            "risk_proof_accepted": True,
            "command_route_registered": True,
            "command_execution_allowed": True,
            "live_coinbase_orders_ran": True,
            "idempotency_key": "futures-risk-proof-unsafe-idem",
            "correlation_id": "corr-futures-risk-proof-unsafe",
            "audit_id": "audit-futures-risk-proof-unsafe",
        }
    )
    store.append(unsafe_record)

    command_suite = AdminApiReadService(
        futures_risk_proof_store=store,
    ).build_futures_command_suite()
    place = next(
        item
        for item in command_suite.commands
        if item.command == AdminFuturesCommandAction.PLACE
    )
    margin_collateral = next(
        item
        for item in place.risk_proof_requirements
        if item.proof_kind == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL
    )

    assert command_suite.resolved_risk_proof_record_resolver_count == 0
    assert command_suite.stale_or_invalid_risk_proof_record_resolver_count == 1
    assert command_suite.risk_proof_acceptance_blocker_count == 120
    assert command_suite.proof_record_resolved_but_acceptance_blocked_count == 0
    assert command_suite.risk_proof_semantic_contract_requirement_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_count == 0
    assert command_suite.risk_proof_semantic_contract_definition_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_definition_count == 0
    assert command_suite.risk_proof_semantic_contract_validation_gate_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_validator_count == 0
    assert command_suite.risk_proof_semantic_contract_validator_contract_count == 34
    assert command_suite.registered_risk_proof_semantic_contract_validator_contract_count == 0
    assert command_suite.risk_proof_semantic_validator_input_schema_count == 34
    assert command_suite.registered_risk_proof_semantic_validator_input_schema_count == 0
    assert command_suite.risk_proof_semantic_validator_output_schema_count == 34
    assert (
        command_suite.registered_risk_proof_semantic_validator_output_schema_count
        == 0
    )
    assert command_suite.risk_proof_semantic_validator_registration_count == 34
    assert (
        command_suite.registered_risk_proof_semantic_validator_registration_count
        == 0
    )
    assert margin_collateral.proof_record_lookup_status.value == "stale_or_invalid"
    assert margin_collateral.latest_futures_risk_proof_id == (
        unsafe_record.futures_risk_proof_id
    )
    assert margin_collateral.latest_futures_risk_proof_id != (
        safe_record.futures_risk_proof_id
    )
    assert margin_collateral.proof_record_resolved is False
    assert margin_collateral.proof_record_stale_or_invalid is True
    assert margin_collateral.proof_record_missing_reason == (
        "latest_futures_risk_proof_record_unsafe_or_authority_claimed"
    )
    assert margin_collateral.proof_record_satisfies_requirement is False
    assert margin_collateral.proof_acceptance_blocked is True
    assert margin_collateral.proof_acceptance_blocker_count == 6
    assert margin_collateral.proof_record_resolves_acceptance is False
    assert margin_collateral.semantic_contract_requirement_count == 2
    assert margin_collateral.registered_semantic_contract_count == 0
    assert margin_collateral.semantic_contract_definition_count == 2
    assert margin_collateral.registered_semantic_contract_definition_count == 0
    assert margin_collateral.semantic_contract_validation_gate_count == 2
    assert margin_collateral.registered_semantic_contract_validator_count == 0
    assert margin_collateral.semantic_contract_validator_contract_count == 2
    assert margin_collateral.registered_semantic_contract_validator_contract_count == 0
    assert margin_collateral.semantic_validator_input_schema_count == 2
    assert margin_collateral.registered_semantic_validator_input_schema_count == 0
    assert margin_collateral.semantic_validator_output_schema_count == 2
    assert margin_collateral.registered_semantic_validator_output_schema_count == 0
    assert margin_collateral.semantic_validator_registration_count == 2
    assert margin_collateral.registered_semantic_validator_registration_count == 0
    assert (
        AdminFuturesCommandRiskProofAcceptanceBlocker.PROOF_RECORD_NOT_ACCEPTED
        in margin_collateral.proof_acceptance_blockers
    )
    assert margin_collateral.satisfies_risk_proof is False
    assert margin_collateral.command_execution_allowed is False


def test_futures_command_suite_dependency_uses_futures_risk_proof_store(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )
    service = futures_routes.get_read_service(store)
    assert service.futures_risk_proof_store is store

    payload = futures_command_suite_api_payload(service.build_futures_command_suite())
    place = next(
        item
        for item in payload["commands"]
        if item["command"] == AdminFuturesCommandAction.PLACE.value
    )
    margin_collateral = next(
        item
        for item in place["risk_proof_requirements"]
        if item["proof_kind"]
        == AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL.value
    )
    assert margin_collateral["proof_record_lookup_status"] == "resolved"
    assert margin_collateral["latest_futures_risk_proof_id"] == (
        record.futures_risk_proof_id
    )
    assert margin_collateral["proof_record_satisfies_requirement"] is False
    assert margin_collateral["proof_acceptance_blocked"] is True
    assert margin_collateral["proof_acceptance_blocker_count"] == 6
    assert margin_collateral["proof_record_resolves_acceptance"] is False
    assert margin_collateral["semantic_contract_requirement_count"] == 2
    assert margin_collateral["registered_semantic_contract_count"] == 0
    assert margin_collateral["semantic_contract_definition_count"] == 2
    assert margin_collateral["registered_semantic_contract_definition_count"] == 0
    assert margin_collateral["semantic_contract_validation_gate_count"] == 2
    assert margin_collateral["registered_semantic_contract_validator_count"] == 0
    assert margin_collateral["semantic_contract_validator_contract_count"] == 2
    assert (
        margin_collateral[
            "registered_semantic_contract_validator_contract_count"
        ]
        == 0
    )
    assert margin_collateral["semantic_validator_input_schema_count"] == 2
    assert margin_collateral["registered_semantic_validator_input_schema_count"] == 0
    assert margin_collateral["semantic_validator_output_schema_count"] == 2
    assert margin_collateral["registered_semantic_validator_output_schema_count"] == 0
    assert margin_collateral["semantic_validator_registration_count"] == 2
    assert margin_collateral["registered_semantic_validator_registration_count"] == 0
    assert [
        item["required_contract_ref"]
        for item in margin_collateral["semantic_contract_requirements"]
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert [
        item["contract_ref"]
        for item in margin_collateral["semantic_contract_definitions"]
    ] == [
        "futures_margin_collateral_risk_contract",
        "futures_cap_guard_margin_collateral_link",
    ]
    assert (
        margin_collateral["semantic_contract_definitions"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_margin_collateral_risk_contract_definition"
        )
    )
    assert (
        margin_collateral["semantic_contract_validation_gates"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator"
        )
    )
    assert (
        margin_collateral["semantic_contract_validation_gates"][0][
            "runtime_evidence_satisfies_validation"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_contract_validator_contracts"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_contract"
        )
    )
    assert (
        margin_collateral["semantic_contract_validator_contracts"][0][
            "runtime_evidence_satisfies_validator_contract"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_input_schemas"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_input_schema"
        )
    )
    assert (
        margin_collateral["semantic_validator_input_schemas"][0][
            "runtime_evidence_satisfies_input_schema"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_output_schemas"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_output_schema"
        )
    )
    assert (
        margin_collateral["semantic_validator_output_schemas"][0][
            "runtime_evidence_satisfies_output_schema"
        ]
        is False
    )
    assert (
        margin_collateral["semantic_validator_registrations"][0][
            "required_backend_contract"
        ]
        == (
            "application/admin_api/futures_semantic_contracts.py::"
            "futures_place_margin_collateral_"
            "futures_margin_collateral_risk_contract_"
            "semantic_contract_validation_validator_registration"
        )
    )
    assert (
        margin_collateral["semantic_validator_registrations"][0][
            "runtime_evidence_satisfies_validator_registration"
        ]
        is False
    )
    assert "acceptance_criteria_blocking" in (
        margin_collateral["proof_acceptance_blockers"]
    )
    assert margin_collateral["command_execution_allowed"] is False
