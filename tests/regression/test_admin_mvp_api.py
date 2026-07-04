from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tomllib

import pytest
import yaml

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
    live_coinbase_execution_enabled_from_env,
)
from tools import run_admin_api


PRE_COINBASE_FAILURE_STAGES = {
    "product_capability",
    "manual_live_acknowledgement",
    "direct_spot_cap_required",
    "known_inventory_required",
    "action_condition_guard",
    "durable_audit_required",
}


def test_admin_live_decision_openapi_exposes_futures_scope_fields():
    openapi = yaml.safe_load(
        Path("openapi/coinbase-admin-api.yaml").read_text(encoding="utf-8")
    )
    schemas = openapi["components"]["schemas"]
    service_scope_fields = {
        "target_module_id",
        "account_family",
        "venue_scope",
        "intx_applicability",
        "product_scope",
    }
    adapter_scope_fields = {
        "account_family",
        "venue_scope",
        "intx_applicability",
        "product_scope",
    }

    assert service_scope_fields <= set(
        schemas["AdminLiveServiceDecisionCreateRequest"]["properties"]
    )
    assert service_scope_fields <= set(schemas["AdminLiveServiceDecisionItem"]["properties"])
    assert service_scope_fields <= set(schemas["AdminLiveServiceDecisionItem"]["required"])
    assert adapter_scope_fields <= set(
        schemas["AdminLiveAdapterDecisionCreateRequest"]["properties"]
    )
    assert adapter_scope_fields <= set(schemas["AdminLiveAdapterDecisionItem"]["properties"])
    assert adapter_scope_fields <= set(schemas["AdminLiveAdapterDecisionItem"]["required"])


def test_admin_account_management_openapi_exposes_live_read_evidence_fields():
    openapi = yaml.safe_load(
        Path("openapi/coinbase-admin-api.yaml").read_text(encoding="utf-8")
    )
    environment = openapi["components"]["schemas"]["AdminAccountManagementEnvironment"]
    live_read_fields = {
        "backend_account_reality_live_read_status",
        "backend_account_reality_live_read_backend_ref",
        "backend_account_reality_live_read_check_count",
        "backend_account_reality_live_read_credentials_present",
        "backend_account_reality_live_read_truststore_status",
        "backend_account_reality_live_read_live_coinbase_execution",
        "backend_account_reality_live_read_notional_usdc",
    }

    assert live_read_fields <= set(environment["properties"])
    assert live_read_fields <= set(environment["required"])


@dataclass
class FakeRestClient:
    create_order_calls: list[dict] = field(default_factory=list)
    cancel_order_calls: list[dict] = field(default_factory=list)
    close_position_calls: list[dict] = field(default_factory=list)
    create_order_response: dict = field(
        default_factory=lambda: {
            "success": True,
            "success_response": {"order_id": "exchange-order-live-1"},
        }
    )
    cancel_orders_response: dict = field(
        default_factory=lambda: {
            "results": [
                {
                    "success": True,
                    "order_id": "client-cancel-live",
                }
            ]
        }
    )
    close_position_response: dict = field(
        default_factory=lambda: {
            "success": True,
            "success_response": {"order_id": "exchange-close-position-live-1"},
        }
    )

    def create_order(self, **kwargs):
        self.create_order_calls.append(kwargs)
        return self.create_order_response

    def cancel_orders(self, **kwargs):
        self.cancel_order_calls.append(kwargs)
        return self.cancel_orders_response

    def close_position(self, **kwargs):
        self.close_position_calls.append(kwargs)
        return self.close_position_response


@dataclass
class FakeAccountRestClient(FakeRestClient):
    account_wallets: dict[str, dict] = field(
        default_factory=lambda: {
            "USDC": {
                "currency": "USDC",
                "available_balance": "12.34",
                "total_balance": "15.00",
                "hold_balance": "2.66",
                "updated_at": "2026-07-03T00:00:00Z",
            },
        },
    )
    portfolios: list[dict] = field(
        default_factory=lambda: [
            {
                "uuid": "portfolio-real-1",
                "name": "Real Backend Portfolio",
                "type": "DEFAULT",
            },
        ],
    )
    futures_positions: dict[str, dict] = field(
        default_factory=lambda: {
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "side": "LONG",
                "number_of_contracts": "2",
                "current_price": "100.00",
                "entry_price": "90.00",
            },
        },
    )
    futures_margin_collateral_snapshot: dict[str, dict] = field(
        default_factory=lambda: {
            "status": "ready",
            "account_family": "coinbase_futures_us_cfm",
            "source": "backend_rest_client",
            "balance_summary": {
                "available_margin": {"value": "250.00", "currency": "USD"},
                "total_usd_balance": {"value": "500.00", "currency": "USD"},
                "cfm_usd_balance": {"value": "500.00", "currency": "USD"},
                "futures_buying_power": {"value": "1000.00", "currency": "USD"},
                "initial_margin": {"value": "40.00", "currency": "USD"},
                "liquidation_threshold": {"value": "80.00", "currency": "USD"},
                "intraday_margin_window_measure": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
                    "maintenance_margin": "20.00",
                    "liquidation_buffer": "420.00",
                },
            },
            "intraday_margin_setting": {"setting": "INTRADAY_MARGIN_SETTING_ENABLED"},
            "current_margin_windows": [
                {
                    "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                    "status": "ready",
                    "margin_window": {
                        "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                    },
                }
            ],
            "futures_sweeps": [],
            "intx_applicability": "not_applicable_us_account",
        },
    )
    futures_margin_collateral_exception: Exception | None = None
    product_dicts: dict[str, dict] = field(
        default_factory=lambda: {
            "AVP-20DEC30-CDE": {
                "product_id": "AVP-20DEC30-CDE",
                "product_type": "FUTURE",
                "price": "6.92",
                "best_bid": "6.92",
                "best_ask": "6.93",
                "price_increment": "0.01",
                "base_increment": "1",
                "future_product_details": {"contract_size": "10"},
            },
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "price": "102.75",
                "best_bid": "102.75",
                "best_ask": "105.25",
                "price_increment": "5",
                "base_increment": "1",
                "future_product_details": {"contract_size": "0.01"},
            },
        },
    )
    get_account_wallets_calls: int = 0
    list_portfolios_calls: int = 0
    get_futures_positions_calls: int = 0
    get_futures_margin_collateral_snapshot_calls: int = 0
    get_product_dict_calls: list[str] = field(default_factory=list)

    def get_account_wallets(self):
        self.get_account_wallets_calls += 1
        return self.account_wallets

    def list_portfolios(self):
        self.list_portfolios_calls += 1
        return self.portfolios

    def get_futures_positions(self):
        self.get_futures_positions_calls += 1
        return self.futures_positions

    def get_futures_margin_collateral_snapshot(self):
        self.get_futures_margin_collateral_snapshot_calls += 1
        if self.futures_margin_collateral_exception is not None:
            raise self.futures_margin_collateral_exception
        return self.futures_margin_collateral_snapshot

    def get_product_dict(self, product_id: str):
        self.get_product_dict_calls.append(product_id)
        return self.product_dicts.get(product_id)


def context(
    *,
    idempotency_key: str = "command-dry-order",
    operator_intent: str = "local_mvp_test",
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=f"{idempotency_key}-correlation",
        operator_intent=operator_intent,
        actor_id="operator-1",
        roles=("operator",),
    )


def manual_order_body() -> dict:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "MARKET",
        "quote_size": "1.00",
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def limit_ioc_manual_order_body() -> dict:
    body = manual_order_body()
    body["order_type"] = "LIMIT"
    body["limit_price"] = "100000.00"
    body["time_in_force"] = "IOC"
    return body


def record_live_service_decision(service: AdminMvpService) -> None:
    result = service.record_live_service_decision(
        {
            "decision_id": "mvp-live-service",
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": "3.10",
            "max_executed_notional_usdc": "1.00",
        },
        context(idempotency_key="live-service-decision"),
    )
    assert result.status_code == 200
    assert result.body["type"] == "admin_live_service_decision"
    assert result.body["status"] == "accepted"
    assert result.body["service_method"] == "record_live_service_decision"
    assert result.body["message"] == "Live-service decision recorded."
    assert result.body["audit_id"] == "audit-live-service-decision"
    assert result.body["live_coinbase_orders_ran"] is False
    decision = result.body["decision"]
    assert decision["route"] == "/api/v1/admin/live-execution/service-decisions"
    assert decision["method"] == "POST"
    assert decision["module_id"] == "admin_system_health"
    assert decision["required_permission"] == "config:update"
    assert decision["service_method"] == "record_live_service_decision"
    assert decision["live_execution_service_status"] == "approval_required"
    assert decision["live_exchange_submitted"] is False


def record_live_adapter_decision(service: AdminMvpService) -> None:
    result = service.record_live_adapter_decision(
        {
            "decision_id": "mvp-live-adapter",
            "status": "blocked",
            "requested_adapter_status": "live_disabled",
            "target_route": "/api/v1/orders",
            "target_method": "POST",
            "target_module_id": "spot_operations",
            "target_service_method": "place_manual_order",
            "adapter_reference": "AdminApiCommandService.place_manual_order",
            "adapter_constructed": False,
            "adapter_enabled": False,
            "construction_review_ref": "adapter-construction-review-disabled",
            "decision_reason": "Document disabled local MVP live-adapter posture.",
            "live_coinbase_execution_approved": False,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
        },
        context(idempotency_key="live-adapter-decision"),
    )
    assert result.status_code == 200
    assert result.body["type"] == "admin_live_adapter_decision"
    assert result.body["status"] == "accepted"
    assert result.body["service_method"] == "record_live_adapter_decision"
    assert result.body["message"] == "Live-adapter decision recorded."
    assert result.body["audit_id"] == "audit-live-adapter-decision"
    assert result.body["live_coinbase_orders_ran"] is False
    decision = result.body["decision"]
    assert decision["route"] == "/api/v1/admin/live-execution/adapter-decisions"
    assert decision["method"] == "POST"
    assert decision["module_id"] == "admin_system_health"
    assert decision["required_permission"] == "config:update"
    assert decision["service_method"] == "record_live_adapter_decision"
    assert decision["target_service_method"] == "place_manual_order"
    assert decision["adapter_constructed"] is False
    assert decision["live_exchange_submitted"] is False


def record_futures_live_service_decision(
    service: AdminMvpService,
    *,
    decision_id: str = "futures-us-cfm-live-service",
    account_family: str = "coinbase_futures_us_cfm",
    intx_applicability: str = "not_applicable_us_account",
    product_scope: list[str] | None = None,
    max_submitted_notional_usdc: str = "100.00",
) -> None:
    result = service.record_live_service_decision(
        {
            "decision_id": decision_id,
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "target_module_id": "futures_perpetuals",
            "account_family": account_family,
            "intx_applicability": intx_applicability,
            "product_scope": product_scope or ["AVP-20DEC30-CDE"],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": max_submitted_notional_usdc,
            "max_executed_notional_usdc": "100.00",
        },
        context(idempotency_key=decision_id),
    )
    assert result.status_code == 200
    assert result.body["live_coinbase_orders_ran"] is False


def record_futures_live_adapter_decision(
    service: AdminMvpService,
    *,
    decision_id: str,
    target_route: str,
    target_service_method: str,
    account_family: str = "coinbase_futures_us_cfm",
    intx_applicability: str = "not_applicable_us_account",
    product_scope: list[str] | None = None,
    max_submitted_notional_usdc: str = "100.00",
) -> None:
    result = service.record_live_adapter_decision(
        {
            "decision_id": decision_id,
            "status": "passed",
            "requested_adapter_status": "approval_required",
            "target_route": target_route,
            "target_method": "POST",
            "target_module_id": "futures_perpetuals",
            "target_service_method": target_service_method,
            "adapter_reference": f"AdminApiCommandService.{target_service_method}",
            "adapter_constructed": True,
            "adapter_enabled": True,
            "account_family": account_family,
            "intx_applicability": intx_applicability,
            "product_scope": product_scope or ["AVP-20DEC30-CDE"],
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": max_submitted_notional_usdc,
            "max_executed_notional_usdc": "100.00",
        },
        context(idempotency_key=decision_id),
    )
    assert result.status_code == 200
    assert result.body["live_coinbase_orders_ran"] is False


def record_all_futures_live_adapter_decisions(
    service: AdminMvpService,
    *,
    max_submitted_notional_usdc: str = "100.00",
) -> None:
    record_futures_live_adapter_decision(
        service,
        decision_id="futures-us-cfm-place-adapter",
        target_route="/api/v1/futures/orders",
        target_service_method="place_futures_order",
        max_submitted_notional_usdc=max_submitted_notional_usdc,
    )
    record_futures_live_adapter_decision(
        service,
        decision_id="futures-us-cfm-close-reduce-adapter",
        target_route="/api/v1/futures/positions/{position_key}/close-reduce",
        target_service_method="close_or_reduce_futures_position",
        max_submitted_notional_usdc=max_submitted_notional_usdc,
    )
    record_futures_live_adapter_decision(
        service,
        decision_id="futures-us-cfm-cancel-adapter",
        target_route="/api/v1/futures/orders/{client_order_id}/cancel",
        target_service_method="cancel_futures_order",
        max_submitted_notional_usdc=max_submitted_notional_usdc,
    )
    record_futures_live_adapter_decision(
        service,
        decision_id="futures-us-cfm-reconcile-adapter",
        target_route="/api/v1/futures/positions/{position_key}/reconciliation",
        target_service_method="reconcile_futures_position",
        max_submitted_notional_usdc=max_submitted_notional_usdc,
    )


def first_manual_submit(service: AdminMvpService, body: dict | None = None) -> dict:
    result = service.submit_manual_order(
        body or manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert result.status_code == 501
    assert result.body["status"] == "not_implemented"
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False
    assert result.body["notional_usdc"] == "1.00"
    admission = result.body["admission_decision"]
    assert admission["live_execution_service_status"] == "approval_required"
    assert "approval_snapshot_missing" in admission["blockers"]
    assert admission["identity_value"]
    assert admission["payload_hash"]
    return admission


def assert_local_mutation_did_not_submit_exchange(result_body: dict) -> None:
    assert result_body["live_exchange_submitted"] is False
    assert result_body["live_coinbase_orders_ran"] is False


def record_proof_chain(
    service: AdminMvpService,
    admission: dict,
    *,
    wallet_check_status: str | None = "passed",
    wallet_available_notional_usdc: str | None = "3.10",
) -> None:
    approval_request = service.create_approval_request(
        {
            "route": admission["route"],
            "method": admission["method"],
            "module_id": admission["module_id"],
            "identity_key": admission["identity_key"],
            "identity_value": admission["identity_value"],
            "action_class": admission["action_class"],
            "required_permission": admission["required_permission"],
            "operator_intent": admission["operator_intent"],
            "command_idempotency_key": admission["idempotency_key"],
            "payload_hash": admission["payload_hash"],
            "request_reason": "test approval",
        },
        context(idempotency_key="approval-request"),
    )
    assert approval_request.status_code == 200
    assert_local_mutation_did_not_submit_exchange(approval_request.body)
    requested_approval = approval_request.body["approval"]
    assert requested_approval["status"] == "requested"
    assert requested_approval["approval_id"] is None
    assert requested_approval["snapshot_linked"] is False
    assert requested_approval["live_exchange_submitted"] is False
    assert requested_approval["browser_authority"] == "display_only"
    assert requested_approval["bff_authority"] == "forward_only_no_execution"
    approval_request_id = requested_approval["approval_request_id"]

    approval_list = service.get_read_response("/api/v1/admin/approvals", {}, context())
    assert approval_list.body["type"] == "admin_approval_lifecycle_list"
    assert approval_list.body["returned_count"] == 1
    assert approval_list.body["total_count"] == 1
    assert approval_list.body["pending_count"] == 1
    assert approval_list.body["approved_count"] == 0
    assert approval_list.body["approvals"][0]["status"] == "requested"

    approval_detail = service.get_read_response(
        f"/api/v1/admin/approvals/requests/{approval_request_id}",
        {},
        context(),
    )
    assert approval_detail.body["type"] == "admin_approval_lifecycle"
    assert approval_detail.body["status"] == "accepted"
    assert approval_detail.body["service_method"] == "get_approval_request"
    assert approval_detail.body["approval"]["approval_request_id"] == approval_request_id

    approval_decision = service.decide_approval_request(
        approval_request_id,
        {
            "decision": "approved",
            "decision_reason": "test approval",
            "cap_guard_decision_ref": "cap-ref",
            "reconciliation_plan_ref": "recon-ref",
        },
        context(idempotency_key="approval-decision"),
    )
    assert approval_decision.status_code == 200
    assert_local_mutation_did_not_submit_exchange(approval_decision.body)
    approved_approval = approval_decision.body["approval"]
    assert approved_approval["status"] == "approved"
    assert approved_approval["snapshot_linked"] is True
    assert approved_approval["decision_actor_id"] == "operator-1"
    assert approved_approval["cap_guard_decision_ref"] == "cap-ref"
    assert approved_approval["reconciliation_plan_ref"] == "recon-ref"
    assert approved_approval["live_exchange_submitted"] is False
    approval_id = approved_approval["approval_id"]

    proof_base = {
        "route": admission["route"],
        "method": admission["method"],
        "module_id": admission["module_id"],
        "identity_key": admission["identity_key"],
        "identity_value": admission["identity_value"],
        "action_class": admission["action_class"],
        "required_permission": admission["required_permission"],
        "service_method": admission["service_method"],
        "actor_id": admission["actor_id"],
        "operator_intent": admission["operator_intent"],
        "command_idempotency_key": admission["idempotency_key"],
        "payload_hash": admission["payload_hash"],
        "approval_snapshot_id": approval_id,
    }
    admission_audit = service.record_admission_audit(
        {
            **proof_base,
            "allowed": False,
            "status": "blocked",
        },
        context(idempotency_key="admission-audit"),
    )
    assert admission_audit.status_code == 200
    assert_local_mutation_did_not_submit_exchange(admission_audit.body)
    admission_audit_id = admission_audit.body["admission_audit"]["admission_audit_id"]

    cap_guard_body = {
        **proof_base,
        "admission_audit_id": admission_audit_id,
        "allowed": True,
        "status": "passed",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
    }
    if wallet_check_status is not None:
        cap_guard_body["wallet_check_required"] = True
        cap_guard_body["wallet_check_status"] = wallet_check_status
        cap_guard_body["wallet_check_source"] = "backend_admin_cap_guard_test"
    if wallet_available_notional_usdc is not None:
        cap_guard_body["wallet_available_notional_usdc"] = wallet_available_notional_usdc

    cap_guard = service.record_cap_guard_decision(
        cap_guard_body,
        context(idempotency_key="cap-guard"),
    )
    assert cap_guard.status_code == 200
    assert_local_mutation_did_not_submit_exchange(cap_guard.body)
    assert cap_guard.body["decision"]["wallet_check_required"] is True
    assert cap_guard.body["decision"]["wallet_check_status"] == (
        wallet_check_status or "blocked"
    )
    cap_guard_decision_id = cap_guard.body["decision"]["decision_id"]

    reconciliation = service.record_reconciliation_plan(
        {
            **proof_base,
            "admission_audit_id": admission_audit_id,
            "cap_guard_decision_id": cap_guard_decision_id,
            "allowed": True,
            "status": "passed",
            "exchange_submission_required": True,
            "max_submitted_notional_usdc": "3.10",
            "max_executed_notional_usdc": "1.00",
        },
        context(idempotency_key="reconciliation"),
    )
    assert reconciliation.status_code == 200
    assert_local_mutation_did_not_submit_exchange(reconciliation.body)


def preview_query(admission: dict) -> dict[str, str]:
    return {
        "route": admission["route"],
        "method": admission["method"],
        "module_id": admission["module_id"],
        "identity_key": admission["identity_key"],
        "identity_value": admission["identity_value"],
        "action_class": admission["action_class"],
        "required_permission": admission["required_permission"],
        "service_method": admission["service_method"],
        "actor_id": admission["actor_id"],
        "command_idempotency_key": admission["idempotency_key"],
        "operator_intent": admission["operator_intent"],
        "payload_hash": admission["payload_hash"],
    }


def configure_local_evidence_logs(tmp_path: Path, monkeypatch) -> None:
    logs = {
        "COINBASE_ADMIN_API_APPROVAL_LOG_PATH": "approval.jsonl",
        "COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH": "idempotency.jsonl",
        "COINBASE_ADMIN_API_AUDIT_LOG_PATH": "audit.jsonl",
        "COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH": "cap-guard.jsonl",
        "COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH": "reconciliation.jsonl",
        "COINBASE_ADMIN_API_LIVE_SERVICE_DECISION_LOG_PATH": "live-service.jsonl",
        "COINBASE_ADMIN_API_LIVE_ADAPTER_DECISION_LOG_PATH": "live-adapter.jsonl",
    }
    for env_name, filename in logs.items():
        monkeypatch.setenv(env_name, str(tmp_path / filename))


def test_admin_mvp_local_evidence_logs_survive_backend_restart(tmp_path, monkeypatch):
    configure_local_evidence_logs(tmp_path, monkeypatch)

    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    order_body = limit_ioc_manual_order_body()
    admission = first_manual_submit(service, order_body)
    record_proof_chain(service, admission)
    spot_attempt = service.submit_manual_order(
        order_body,
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert spot_attempt.status_code == 400
    assert spot_attempt.body["client_order_id"] == admission["identity_value"]

    futures_attempt = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0.50",
            "number_of_contracts": "1",
        },
        context(idempotency_key="futures-place-persisted-draft"),
    )
    assert futures_attempt.status_code == 400
    assert futures_attempt.body["submission_event_recorded"] is True

    restarted = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    assert restarted.store.command_identity_by_idempotency_key[
        "manual-order-proof-chain"
    ] == admission["identity_value"]

    preview = restarted.preview_admission(preview_query(admission), context())
    assert preview.status_code == 200
    assert preview.body["admission_decision"]["allowed"] is True

    spot_suite = restarted.get_read_response(
        "/api/v1/spot/command-suite",
        preview_query(admission),
        context(),
    )
    assert spot_suite.body["manual_order_proof_chain_status"] == "passed"
    manual_command = next(
        command
        for command in spot_suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    assert manual_command["admission_decision"]["allowed"] is True

    spot_workbench = restarted.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "spot", "client_order_id": admission["identity_value"]},
        context(),
    )
    assert spot_workbench.status_code == 200
    assert spot_workbench.body["count"] >= 1
    assert any(
        event["client_order_id"] == admission["identity_value"]
        for event in spot_workbench.body["events"]
    )

    futures_suite = restarted.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )
    assert futures_suite.body["futures_live_decision_evidence"]["service_decision_status"] == (
        "ready"
    )
    assert futures_suite.body["futures_live_decision_evidence"][
        "adapter_decision_ready_count"
    ] == 4

    futures_workbench = restarted.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals"},
        context(),
    )
    assert futures_workbench.status_code == 200
    assert futures_workbench.body["count"] >= 1
    assert any(
        event["event_id"] == futures_attempt.body["submission_event_id"]
        for event in futures_workbench.body["events"]
    )


def test_admin_account_management_read_contract_exposes_local_operator_scope(
    tmp_path,
    monkeypatch,
):
    frontend_manifest_path = tmp_path / "deployment-local-manifest.json"
    frontend_manifest_path.write_text(
        json.dumps(
            {
                "commit": "frontend-release-123",
                "currentPath": "C:\\coinbase-local\\current",
                "releasePath": "C:\\coinbase-local\\releases\\frontend-release-123",
                "backendContractRef": "backend-release-456",
                "smokeTiming": {"status": "passed"},
                "backendControlledLiveSmokeTiming": {"status": "passed"},
                "backendAccountRealityLiveReadSmoke": {
                    "status": "passed",
                    "backendContractRef": "backend-release-456",
                    "credentialsPresent": True,
                    "truststoreStatus": "enabled",
                    "checkCount": 13,
                    "liveCoinbaseExecution": "not_run",
                    "notionalUsdc": "0",
                },
                "liveCoinbaseExecution": "not_run",
                "notionalUsdc": "0",
            },
        ),
        encoding="utf-8",
    )
    backend_manifest_path = tmp_path / "coinbase-backend-local-deployment-manifest.json"
    backend_manifest_path.write_text(
        json.dumps(
            {
                "commit": "backend-release-456",
                "current_path": "C:\\coinbase-local\\backend\\current",
                "release_path": "C:\\coinbase-local\\backend\\releases\\backend-release-456",
                "live_coinbase_execution": "not_run",
                "notional_usdc": "0",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_FRONTEND_LOCAL_RELEASE_MANIFEST_PATH",
        str(frontend_manifest_path),
    )
    monkeypatch.setenv(
        "COINBASE_BACKEND_LOCAL_RELEASE_MANIFEST_PATH",
        str(backend_manifest_path),
    )

    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        context(idempotency_key="account-management-read"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["type"] == "admin_account_management"
    assert body["module_id"] == "account_management"
    assert body["read_only"] is True
    assert body["browser_authority"] == "display_only"
    assert body["bff_authority"] == "forward_only_no_execution"
    assert body["environment"]["deployment_target"] == "coinbase-local"
    assert body["environment"]["deployment_evidence_status"] == "visible"
    assert body["environment"]["frontend_release_commit"] == "frontend-release-123"
    assert body["environment"]["frontend_release_path"] == (
        "C:\\coinbase-local\\releases\\frontend-release-123"
    )
    assert body["environment"]["backend_release_commit"] == "backend-release-456"
    assert body["environment"]["backend_release_path"] == (
        "C:\\coinbase-local\\backend\\releases\\backend-release-456"
    )
    assert body["environment"]["deployment_smoke_status"] == "passed"
    assert body["environment"]["backend_smoke_status"] == "passed"
    assert body["environment"]["backend_account_reality_live_read_status"] == "passed"
    assert body["environment"]["backend_account_reality_live_read_backend_ref"] == (
        "backend-release-456"
    )
    assert body["environment"]["backend_account_reality_live_read_check_count"] == 13
    assert (
        body["environment"]["backend_account_reality_live_read_credentials_present"]
        is True
    )
    assert (
        body["environment"]["backend_account_reality_live_read_truststore_status"]
        == "enabled"
    )
    assert (
        body["environment"]["backend_account_reality_live_read_live_coinbase_execution"]
        == "not_run"
    )
    assert body["environment"]["backend_account_reality_live_read_notional_usdc"] == "0"
    assert "available_notional_usdc" not in json.dumps(body["environment"])
    assert body["environment"]["deployment_live_coinbase_execution"] == "not_run"
    assert body["environment"]["deployment_notional_usdc"] == "0"
    assert body["operator"]["actor_id"] == "operator-1"
    assert body["operator"]["roles"] == ["operator"]
    assert body["account_scope"]["scope_type"] == "local_admin_portfolio"
    assert body["portfolio_scope"]["portfolio_id"] == "local-admin-portfolio"
    assert body["wallet_inventory"]["currency"] == "USDC"
    assert body["wallet_inventory"]["freshness_status"] == "local_default_not_connected"
    assert body["wallet_inventory"]["available_notional_usdc"] == "0"
    assert body["coinbase_read_enabled"] is False
    assert body["live_coinbase_read_ran"] is False
    assert body["live_coinbase_orders_ran"] is False
    assert body["live_coinbase_execution"] == "not_run"
    assert body["notional_usdc"] == "0"
    assert body["audit"]["correlation_id"] == "account-management-read-correlation"
    assert body["audit"]["idempotency_key"] == "account-management-read"
    readiness = {item["name"]: item for item in body["command_readiness_prerequisites"]}
    assert readiness["rbac"]["status"] == "visible"
    assert readiness["wallet_inventory_evidence"]["status"] == "visible"
    assert readiness["backend_admin_api_contract"]["status"] == "visible"
    assert readiness["continuous_deployment_local_release"]["status"] == "visible"
    assert readiness["approval_admission_cap_reconciliation"]["status"] == "not_applicable"
    assert body["wallet_inventory"]["status"] == "visible"
    assert body["wallet_inventory"]["error"] == "not_applicable"

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    account_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "GET"
        and item["route"] == "/api/v1/admin/account-management"
    )
    assert account_capability["module_id"] == "account_management"
    assert account_capability["frontend_safe"] is True
    assert account_capability["live_enabled"] is False

    readiness_response = service.get_read_response(
        "/api/v1/admin/enterprise-readiness",
        {},
        context(),
    )
    account_module = next(
        item
        for item in readiness_response.body["modules"]
        if item["module_id"] == "account_management"
    )
    assert account_module["support_status"] == "mvp_read_ready"
    assert account_module["read_routes"] == [
        "GET /api/v1/admin/account-management",
        "GET /api/v1/admin/wallet",
    ]
    assert account_module["action_posture"]["browser_authority"] == "display_only"


def test_admin_account_management_exposes_backend_owned_account_reality():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    account_management = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        context(idempotency_key="account-reality-read"),
    )

    assert account_management.status_code == 200
    body = account_management.body
    assert body["account_reality"]["status"] == "ready"
    assert body["account_reality"]["source"] == "backend_rest_client"
    assert body["account_reality"]["coinbase_read_ran"] is True
    assert body["account_reality"]["browser_authority"] == "display_only"
    assert body["account_reality"]["bff_authority"] == "forward_only_no_execution"
    assert body["coinbase_read_enabled"] is True
    assert body["live_coinbase_read_ran"] is True
    assert body["live_coinbase_orders_ran"] is False
    assert body["account_scope"]["source"] == "backend_rest_client"
    assert body["account_scope"]["freshness_status"] == "backend_rest_fresh"
    assert body["account_scope"]["account_count"] == 1
    assert body["portfolio_scope"]["portfolio_id"] == "portfolio-real-1"
    assert body["portfolio_scope"]["portfolio_name"] == "Real Backend Portfolio"
    assert body["wallet_inventory"]["source"] == "backend_rest_client"
    assert body["wallet_inventory"]["freshness_status"] == "backend_rest_fresh"
    assert body["wallet_inventory"]["status"] == "ready"
    assert body["wallet_inventory"]["available_notional_usdc"] == "12.34"
    assert body["wallet_inventory"]["hold_notional_usdc"] == "2.66"
    assert body["wallet_inventory"]["total_notional_usdc"] == "15.00"
    assert body["readiness"]["spot_account_ready"] is True
    assert body["readiness"]["spot_wallet_inventory_ready"] is True
    assert body["readiness"]["futures_account_scope_ready"] is True
    assert body["readiness"]["futures_observed_position_scope_ready"] is True
    assert body["readiness"]["futures_margin_collateral_ready"] is True
    assert body["readiness"]["usable_for_spot_admission"] is True
    assert body["readiness"]["usable_for_futures_risk"] is True
    readiness = {item["name"]: item for item in body["command_readiness_prerequisites"]}
    assert readiness["backend_account_reality"]["status"] == "ready"
    assert readiness["wallet_inventory_evidence"]["status"] == "ready"
    assert rest_client.get_account_wallets_calls == 1
    assert rest_client.list_portfolios_calls == 1
    assert rest_client.get_futures_positions_calls == 1
    assert rest_client.get_futures_margin_collateral_snapshot_calls == 1


def test_admin_wallet_read_exposes_backend_owned_wallet_reality():
    rest_client = FakeAccountRestClient()
    rest_client.account_wallets["BTC"] = {
        "currency": "BTC",
        "available_balance": "0.01000000",
        "total_balance": "0.01500000",
        "hold_balance": "0.00500000",
        "updated_at": "2026-07-03T00:01:00Z",
    }
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        context(idempotency_key="wallet-read"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["type"] == "admin_wallet"
    assert body["module_id"] == "account_management"
    assert body["read_only"] is True
    assert body["browser_authority"] == "display_only"
    assert body["bff_authority"] == "forward_only_no_execution"
    assert body["account_reality"]["status"] == "ready"
    assert body["account_reality"]["source"] == "backend_rest_client"
    assert body["wallet_inventory"]["status"] == "ready"
    assert body["wallet_inventory"]["currency"] == "USDC"
    assert body["wallet_inventory"]["available_notional_usdc"] == "12.34"
    assert body["wallet_inventory"]["hold_notional_usdc"] == "2.66"
    assert body["wallet_inventory"]["total_notional_usdc"] == "15.00"
    assert body["wallet_count"] == 2
    wallet_rows = {wallet["currency"]: wallet for wallet in body["wallets"]}
    assert wallet_rows["USDC"]["available_balance"] == "12.34"
    assert wallet_rows["USDC"]["admission_asset"] is True
    assert wallet_rows["USDC"]["admission_ready"] is True
    assert wallet_rows["BTC"]["admission_asset"] is False
    assert wallet_rows["BTC"]["admission_ready"] is False
    assert body["readiness"]["spot_wallet_inventory_ready"] is True
    assert body["readiness"]["usable_for_spot_admission"] is True
    assert body["readiness"]["usable_for_futures_risk"] is True
    assert body["spot_admission_input"]["status"] == "ready"
    assert body["spot_admission_input"]["wallet_check_source"] == "account_management_snapshot"
    assert body["futures_risk_input"]["status"] == "ready"
    assert body["futures_risk_input"]["wallet_check_source"] == "account_management_snapshot"
    assert body["futures_risk_input"]["currency"] == "USD"
    assert body["futures_risk_input"]["available_notional_usdc"] == "250.00"
    assert body["futures_risk_input"]["first_blocker"] == "none"
    assert body["coinbase_read_enabled"] is True
    assert body["live_coinbase_read_ran"] is True
    assert body["live_coinbase_orders_ran"] is False
    assert body["live_coinbase_execution"] == "not_run"
    assert body["notional_usdc"] == "0"
    assert body["audit"]["correlation_id"] == "wallet-read-correlation"
    assert rest_client.get_account_wallets_calls == 1
    assert rest_client.list_portfolios_calls == 1
    assert rest_client.get_futures_positions_calls == 1
    assert rest_client.get_futures_margin_collateral_snapshot_calls == 1


def test_admin_wallet_read_blocks_futures_risk_when_cfm_margin_snapshot_fails():
    rest_client = FakeAccountRestClient(
        futures_margin_collateral_exception=RuntimeError("permission denied")
    )
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        context(idempotency_key="wallet-cfm-blocked"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["readiness"]["futures_account_scope_ready"] is True
    assert body["readiness"]["futures_margin_collateral_ready"] is False
    assert body["readiness"]["usable_for_futures_risk"] is False
    assert body["futures_risk_input"]["status"] == "blocked"
    assert body["futures_risk_input"]["currency"] == "USD"
    assert body["futures_risk_input"]["available_notional_usdc"] == "0"
    assert body["futures_risk_input"]["first_blocker"] == "futures_margin_collateral_read_failed"
    assert "get_futures_margin_collateral_snapshot_failed:RuntimeError" in body["account_reality"]["read_error"]

    futures = service.get_read_response(
        "/api/v1/futures/account",
        {},
        context(idempotency_key="futures-cfm-blocked"),
    )

    assert futures.status_code == 200
    assert futures.body["collateral"]["status"] == "blocked"
    assert futures.body["collateral"]["source"] == "backend_rest_client"
    assert futures.body["collateral"]["value"]["account_family"] == "coinbase_futures_us_cfm"
    assert futures.body["margin"]["status"] == "blocked"
    assert rest_client.get_futures_margin_collateral_snapshot_calls == 2


def test_admin_wallet_read_accepts_usd_quote_wallet_when_usdc_wallet_is_missing():
    rest_client = FakeAccountRestClient()
    rest_client.account_wallets = {
        "USD": {
            "currency": "USD",
            "available_balance": "9.25",
            "total_balance": "10.00",
            "hold_balance": "0.75",
            "updated_at": "2026-07-03T00:02:00Z",
        },
    }
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        context(idempotency_key="wallet-usd-read"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["wallet_inventory"]["status"] == "ready"
    assert body["wallet_inventory"]["currency"] == "USD"
    assert body["wallet_inventory"]["available_notional_usdc"] == "9.25"
    assert body["wallet_inventory"]["hold_notional_usdc"] == "0.75"
    assert body["wallet_inventory"]["total_notional_usdc"] == "10.00"
    assert body["wallet_inventory"]["freshness_status"] == "backend_rest_fresh"
    assert body["wallet_inventory"]["error"] == "none"
    assert body["readiness"]["spot_wallet_inventory_ready"] is True
    assert body["spot_admission_input"]["status"] == "ready"
    assert body["spot_admission_input"]["currency"] == "USD"
    wallet_rows = {wallet["currency"]: wallet for wallet in body["wallets"]}
    assert wallet_rows["USD"]["admission_asset"] is True
    assert wallet_rows["USD"]["admission_ready"] is True
    assert body["live_coinbase_orders_ran"] is False


def test_admin_wallet_read_keeps_inventory_live_when_quote_wallet_is_missing():
    rest_client = FakeAccountRestClient()
    rest_client.account_wallets = {
        "BTC": {
            "currency": "BTC",
            "available_balance": "0.01000000",
            "total_balance": "0.01500000",
            "hold_balance": "0.00500000",
            "updated_at": "2026-07-03T00:04:00Z",
        },
    }
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        context(idempotency_key="wallet-live-no-quote-read"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["wallet_inventory"]["status"] == "ready"
    assert body["wallet_inventory"]["freshness_status"] == "backend_rest_fresh"
    assert body["wallet_inventory"]["quote_wallet_status"] == "blocked"
    assert body["wallet_inventory"]["quote_wallet_error"] == "quote_wallet_missing"
    assert body["wallet_count"] == 1
    assert body["readiness"]["spot_wallet_inventory_ready"] is False
    assert body["spot_admission_input"]["status"] == "blocked"
    assert body["spot_admission_input"]["first_blocker"] == "quote_wallet_missing"
    wallet_rows = {wallet["currency"]: wallet for wallet in body["wallets"]}
    assert wallet_rows["BTC"]["admission_asset"] is False
    assert wallet_rows["BTC"]["admission_ready"] is False
    assert body["live_coinbase_read_ran"] is True
    assert body["live_coinbase_orders_ran"] is False


def test_cap_guard_uses_usd_quote_wallet_from_backend_snapshot():
    rest_client = FakeAccountRestClient()
    rest_client.account_wallets = {
        "USD": {
            "currency": "USD",
            "available_balance": "9.25",
            "total_balance": "10.00",
            "hold_balance": "0.75",
            "updated_at": "2026-07-03T00:02:00Z",
        },
    }
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )

    result = service.record_cap_guard_decision(
        {
            "route": "/api/v1/orders",
            "method": "POST",
            "module_id": "spot_operations",
            "identity_key": "client_order_id",
            "identity_value": "spot-order-usd",
            "action_class": "live_exchange_place",
            "required_permission": "order:create",
            "service_method": "place_manual_order",
            "actor_id": "operator-1",
            "operator_intent": "use backend USD quote wallet snapshot",
            "command_idempotency_key": "spot-order-usd",
            "payload_hash": "payload-hash",
            "wallet_check_source": "account_management_snapshot",
        },
        context(idempotency_key="cap-guard-usd-account-snapshot"),
    )

    assert result.status_code == 200
    decision = result.body["decision"]
    assert decision["wallet_check_required"] is True
    assert decision["wallet_check_status"] == "passed"
    assert decision["wallet_available_notional_usdc"] == "9.25"
    assert decision["wallet_check_source"] == "account_management_snapshot"
    assert decision["account_snapshot_status"] == "ready"
    assert decision["account_snapshot_source"] == "backend_rest_client"
    assert result.body["live_coinbase_orders_ran"] is False


def test_futures_scoped_cap_records_default_to_futures_notional_cap():
    service = AdminMvpService(AdminMvpDependencies())

    futures_body = {
        "route": "/api/v1/futures/orders",
        "method": "POST",
        "module_id": "futures_perpetuals",
        "identity_key": "product_id",
        "identity_value": "AVP-20DEC30-CDE",
        "action_class": "live_exchange_place",
        "required_permission": "order:create",
        "service_method": "place_futures_order",
        "account_family": "coinbase_futures_us_cfm",
        "product_scope": ["AVP-20DEC30-CDE"],
    }

    cap_guard = service.record_cap_guard_decision(
        futures_body,
        context(idempotency_key="futures-default-cap-guard"),
    )
    reconciliation = service.record_reconciliation_plan(
        futures_body,
        context(idempotency_key="futures-default-reconciliation"),
    )
    spot_cap_guard = service.record_cap_guard_decision(
        {"module_id": "spot_operations"},
        context(idempotency_key="spot-default-cap-guard"),
    )

    assert cap_guard.status_code == 200
    assert cap_guard.body["decision"]["max_submitted_notional_usdc"] == "100.00"
    assert cap_guard.body["decision"]["max_executed_notional_usdc"] == "100.00"
    assert reconciliation.status_code == 200
    assert reconciliation.body["plan"]["max_submitted_notional_usdc"] == "100.00"
    assert reconciliation.body["plan"]["max_executed_notional_usdc"] == "100.00"
    assert spot_cap_guard.body["decision"]["max_submitted_notional_usdc"] == "3.10"
    assert spot_cap_guard.body["decision"]["max_executed_notional_usdc"] == "1.00"
    assert cap_guard.body["live_coinbase_orders_ran"] is False
    assert reconciliation.body["live_coinbase_orders_ran"] is False
    assert spot_cap_guard.body["live_coinbase_orders_ran"] is False


def test_admin_wallet_route_is_registered_as_account_management_capability():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    wallet_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "GET" and item["route"] == "/api/v1/admin/wallet"
    )
    assert wallet_capability["module_id"] == "account_management"
    assert wallet_capability["frontend_safe"] is True
    assert wallet_capability["live_enabled"] is False

    readiness_response = service.get_read_response(
        "/api/v1/admin/enterprise-readiness",
        {},
        context(),
    )
    account_module = next(
        item
        for item in readiness_response.body["modules"]
        if item["module_id"] == "account_management"
    )
    assert "GET /api/v1/admin/wallet" in account_module["read_routes"]
    assert "/api/v1/admin/wallet" in account_module["evidence_routes"]
    assert account_module["action_posture"]["browser_authority"] == "display_only"


def test_spot_and_futures_reads_consume_backend_account_snapshot():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    spot = service.get_read_response(
        "/api/v1/spot/readiness",
        {"product_id": ["BTC-USDC"]},
        context(),
    )
    assert spot.status_code == 200
    assert spot.body["status"] == "ready"
    assert spot.body["account_reality"]["status"] == "ready"
    assert spot.body["account_reality"]["source"] == "backend_rest_client"
    assert spot.body["account_scope"]["scope_id"] == "portfolio-real-1"
    assert spot.body["portfolio_scope"]["portfolio_id"] == "portfolio-real-1"
    assert spot.body["wallet_snapshot"]["source"] == "backend_rest_client"
    assert spot.body["wallet_snapshot"]["status"] == "ready"
    assert spot.body["wallet_snapshot"]["available_notional_usdc"] == "12.34"
    assert spot.body["wallet_snapshot"]["available"] is True
    assert spot.body["spot_admission_input"] == {
        "status": "ready",
        "wallet_check_source": "account_management_snapshot",
        "currency": "USDC",
        "available_notional_usdc": "12.34",
        "proof_id": spot.body["account_reality"]["proof_id"],
        "first_blocker": "none",
    }
    assert spot.body["account_readiness"]["spot_wallet_inventory_ready"] is True
    assert spot.body["account_readiness"]["usable_for_spot_admission"] is True
    assert spot.body["products"][0]["product_id"] == "BTC-USDC"
    assert spot.body["products"][0]["capabilities"]["wallet_inventory"]["mode"] == "enabled"
    assert spot.body["products"][0]["capabilities"]["product_capability_contract"]["mode"] == "pending"
    guards = {
        item["condition"]: item
        for item in spot.body["action_guard_summary"]
    }
    assert guards["backend_account_reality"]["mode"] == "enabled"
    assert guards["spot_wallet_inventory"]["mode"] == "enabled"
    assert guards["spot_admission_input"]["mode"] == "enabled"
    assert guards["product_capability_contract"]["mode"] == "pending"
    assert spot.body["browser_authority"] == "display_only"
    assert spot.body["bff_authority"] == "read_only_forward"
    assert spot.body["live_coinbase_execution"] == "not_run"
    assert spot.body["live_coinbase_orders_ran"] is False

    futures = service.get_read_response("/api/v1/futures/account", {}, context())
    assert futures.status_code == 200
    assert futures.body["account_reality"]["source"] == "backend_rest_client"
    assert futures.body["account_readiness"]["futures_account_scope_ready"] is True
    assert futures.body["account_readiness"]["futures_observed_position_scope_ready"] is True
    assert futures.body["account_readiness"]["futures_margin_collateral_ready"] is True
    assert futures.body["account_readiness"]["usable_for_futures_risk"] is True
    assert futures.body["observed_position_scope"] == ["BIP-20DEC30-CDE"]
    assert futures.body["position_count"] == 1
    assert futures.body["collateral"]["status"] == "ready"
    assert futures.body["collateral"]["source"] == "backend_rest_client"
    assert futures.body["collateral"]["value"]["account_family"] == "coinbase_futures_us_cfm"
    assert futures.body["collateral"]["value"]["available_margin"]["value"] == "250.00"
    assert futures.body["collateral"]["value"]["intx_applicability"] == "not_applicable_us_account"
    assert futures.body["margin"]["status"] == "ready"
    assert futures.body["margin"]["value"]["margin_window_type"] == "FCM_MARGIN_WINDOW_TYPE_INTRADAY"
    assert futures.body["funding"]["status"] == "ready"
    assert futures.body["funding"]["source"] == "backend_rest_client"
    assert futures.body["funding"]["value"]["funding_applicability"] == "not_applicable_us_cfm"
    assert futures.body["funding"]["value"]["funding_required"] is False
    assert futures.body["funding"]["value"]["intx_applicability"] == "not_applicable_us_account"
    assert futures.body["liquidation"]["status"] == "ready"
    assert futures.body["liquidation"]["source"] == "backend_rest_client"
    assert futures.body["liquidation"]["value"]["liquidation_threshold_present"] is True
    assert futures.body["liquidation"]["value"]["liquidation_buffer_present"] is True
    assert futures.body["reduce_only_close_only"]["status"] == "ready"
    assert futures.body["reduce_only_close_only"]["source"] == "runtime_positions"
    assert futures.body["reduce_only_close_only"]["value"]["position_side_observed_count"] == 1
    assert futures.body["reduce_only_close_only"]["value"]["backend_derives_close_reduce_side"] is True
    assert futures.body["live_coinbase_orders_ran"] is False

    positions = service.get_read_response("/api/v1/futures/positions", {}, context())
    assert positions.status_code == 200
    assert positions.body["count"] == 1
    assert positions.body["items"][0]["position_key"] == "futures_position:runtime:BIP-20DEC30-CDE"
    assert positions.body["items"][0]["product_id"] == "BIP-20DEC30-CDE"


def test_cap_guard_can_use_backend_account_snapshot_for_wallet_evidence():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    result = service.record_cap_guard_decision(
        {
            "route": "/api/v1/orders",
            "method": "POST",
            "module_id": "spot_operations",
            "identity_key": "client_order_id",
            "identity_value": "spot-order-1",
            "action_class": "live_exchange_place",
            "required_permission": "order:create",
            "service_method": "place_manual_order",
            "actor_id": "operator-1",
            "operator_intent": "use backend account snapshot",
            "command_idempotency_key": "spot-order-1",
            "payload_hash": "payload-hash",
            "wallet_check_source": "account_management_snapshot",
        },
        context(idempotency_key="cap-guard-account-snapshot"),
    )

    assert result.status_code == 200
    decision = result.body["decision"]
    assert decision["wallet_check_required"] is True
    assert decision["wallet_check_status"] == "passed"
    assert decision["wallet_available_notional_usdc"] == "12.34"
    assert decision["wallet_check_source"] == "account_management_snapshot"
    assert decision["account_snapshot_status"] == "ready"
    assert decision["account_snapshot_source"] == "backend_rest_client"
    assert result.body["live_coinbase_orders_ran"] is False


def test_admin_futures_perpetuals_read_contract_exposes_blocked_contract_evidence():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )

    account = service.get_read_response("/api/v1/futures/account", {}, context())
    assert account.status_code == 200
    account_body = account.body
    assert account_body["type"] == "admin_futures_account"
    assert account_body["configured_product_scope"] == [
        "AVP-20DEC30-CDE",
        "BIP-20DEC30-CDE",
    ]
    assert account_body["observed_position_scope"] == []
    assert account_body["position_count"] == 0
    assert account_body["collateral"]["status"] == "blocked"
    assert account_body["collateral"]["value"]["account_family"] == "coinbase_futures_us_cfm"
    assert account_body["collateral"]["value"]["intx_applicability"] == "not_applicable_us_account"
    assert account_body["margin"]["name"] == "margin"
    assert account_body["margin"]["status"] == "blocked"
    assert account_body["funding"]["status"] == "unavailable"
    assert account_body["funding"]["value"]["funding_required"] is None
    assert account_body["liquidation"]["source"] == "runtime_unavailable"
    assert account_body["reduce_only_close_only"]["status"] == "unavailable"
    assert account_body["position_pnl"]["status"] == "unavailable"
    assert account_body["read_only"] is True
    assert account_body["command_routes_mode"] == "backend_admin_api_blocked"
    assert account_body["live_coinbase_orders_ran"] is False

    positions = service.get_read_response(
        "/api/v1/futures/positions",
        {"limit": "2", "offset": "0"},
        context(),
    )
    assert positions.status_code == 200
    assert positions.body["type"] == "admin_futures_positions"
    assert positions.body["count"] == 0
    assert positions.body["items"] == []
    assert positions.body["pagination"]["limit"] == 2
    assert positions.body["read_only"] is True

    detail = service.get_read_response(
        "/api/v1/futures/positions/futures_position:runtime:BIP-20DEC30-CDE",
        {},
        context(),
    )
    assert detail.status_code == 200
    assert detail.body["type"] == "admin_futures_position_detail"
    assert detail.body["found"] is False
    assert detail.body["position"] is None

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )
    assert command_suite.status_code == 200
    suite = command_suite.body
    assert suite["type"] == "admin_futures_command_suite"
    assert suite["module_id"] == "futures_perpetuals"
    assert suite["approved_phase_range"] == "futures-perpetuals-read-contract"
    assert "mvp" not in suite["approved_phase_range"].lower()
    assert suite["status"] == "blocked"
    assert suite["command_count"] == 4
    assert suite["blocked_command_count"] == 4
    assert suite["executable_command_count"] == 0
    assert suite["command_route_count"] == 4
    assert suite["command_draft_allowed_count"] == 4
    assert suite["spot_rule_authority"] is False
    assert suite["browser_authority"] == "display_only"
    assert suite["bff_authority"] == "forward_only_no_execution"
    assert suite["live_coinbase_orders_ran"] is False
    assert suite["submitted_notional_usdc"] == "0"
    assert suite["executed_notional_usdc"] == "0"
    assert "spot_no_shorting" in suite["forbidden_spot_assumptions"]
    assert "futures_margin_collateral_risk_proof" in suite["missing_backend_contracts"]
    commands = {command["command"]: command for command in suite["commands"]}
    assert set(commands) == {
        "futures_place",
        "futures_close_reduce",
        "futures_cancel",
        "futures_reconcile",
    }
    assert commands["futures_place"]["route"] == "/api/v1/futures/orders"
    assert commands["futures_place"]["status"] == "blocked"
    assert commands["futures_place"]["command_draft_allowed"] is True
    assert commands["futures_place"]["execution_allowed"] is False
    assert commands["futures_place"]["spot_rule_authority"] is False
    assert commands["futures_close_reduce"]["identity_key"] == "position_key"
    assert commands["futures_cancel"]["identity_key"] == "client_order_id"
    assert commands["futures_reconcile"]["action_class"] == "local_state_mutation"

    risk_proofs = service.get_read_response("/api/v1/futures/risk-proofs", {}, context())
    assert risk_proofs.status_code == 200
    assert risk_proofs.body["type"] == "admin_futures_risk_proofs"
    assert risk_proofs.body["module_id"] == "futures_perpetuals"
    assert risk_proofs.body["count"] == 0
    assert risk_proofs.body["proof_records_created"] is False
    assert risk_proofs.body["browser_authority"] == "display_only"
    assert risk_proofs.body["bff_authority"] == "forward_only_no_execution"

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    futures_read_routes = {
        item["route"]
        for item in capabilities.body["capabilities"]
        if item["method"] == "GET" and item["module_id"] == "futures_perpetuals"
    }
    assert {
        "/api/v1/futures/command-suite",
        "/api/v1/futures/account",
        "/api/v1/futures/positions",
        "/api/v1/futures/positions/{position_key}",
        "/api/v1/futures/risk-proofs",
        "/api/v1/futures/risk-proofs/{futures_risk_proof_id}",
    }.issubset(futures_read_routes)

    readiness_response = service.get_read_response(
        "/api/v1/admin/enterprise-readiness",
        {},
        context(),
    )
    futures_module = next(
        item
        for item in readiness_response.body["modules"]
        if item["module_id"] == "futures_perpetuals"
    )
    assert futures_module["support_status"] == "mvp_read_ready"
    assert "GET /api/v1/futures/account" in futures_module["read_routes"]
    assert futures_module["action_posture"]["bff_authority"] == "forward_only_no_execution"


def test_admin_futures_command_suite_resolves_account_and_risk_proof_evidence():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    account = service.get_read_response("/api/v1/futures/account", {}, context())
    assert account.status_code == 200
    assert account.body["account_readiness"]["futures_account_scope_ready"] is True
    assert account.body["account_readiness"]["futures_observed_position_scope_ready"] is True
    assert account.body["account_readiness"]["futures_margin_collateral_ready"] is True
    assert account.body["account_readiness"]["usable_for_futures_risk"] is True

    risk_proofs = service.get_read_response("/api/v1/futures/risk-proofs", {}, context())
    assert risk_proofs.status_code == 200
    assert risk_proofs.body["type"] == "admin_futures_risk_proofs"
    assert risk_proofs.body["status"] == "ready"
    assert risk_proofs.body["count"] == 4
    assert risk_proofs.body["proof_records_created"] is False
    assert risk_proofs.body["proof_records_generated_from_account_snapshot"] is True
    proof = risk_proofs.body["items"][0]
    assert proof["futures_risk_proof_id"] == "futures-risk-proof-account-snapshot-futures-place"
    assert proof["command"] == "futures_place"
    assert proof["proof_kind"] == "margin_collateral"
    assert proof["product_id"] == "BIP-20DEC30-CDE"
    assert proof["risk_proof_verified"] is True
    assert proof["risk_proof_accepted"] is False
    assert proof["funding_validated"] is True
    assert proof["command_execution_allowed"] is False
    assert proof["live_coinbase_orders_ran"] is False

    detail = service.get_read_response(
        "/api/v1/futures/risk-proofs/futures-risk-proof-account-snapshot-futures-place",
        {},
        context(),
    )
    assert detail.status_code == 200
    assert detail.body["found"] is True
    assert detail.body["record"]["futures_risk_proof_id"] == proof["futures_risk_proof_id"]
    assert detail.body["proof_record_created"] is False
    assert detail.body["live_coinbase_orders_ran"] is False

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )
    assert command_suite.status_code == 200
    suite = command_suite.body
    assert suite["status"] == "evidence_ready"
    assert suite["blocked_command_count"] == 4
    assert suite["executable_command_count"] == 0
    assert suite["command_draft_allowed_count"] == 4
    assert suite["resolved_backend_contracts"] == [
        "futures_account_scope_contract",
        "futures_margin_collateral_risk_proof",
        "futures_reconciliation_contract",
        "futures_live_adapter_contract",
    ]
    assert suite["missing_backend_contracts"] == []
    assert suite["command_enablement_blocker_summary_count"] == 1
    assert suite["command_enablement_blocker_summaries"][0]["blocker"] == "execution_disabled"
    assert suite["command_enablement_blocker_summaries"][0]["blocking"] is True
    commands = {command["command"]: command for command in suite["commands"]}
    assert commands["futures_place"]["missing_backend_contracts"] == []
    assert commands["futures_place"]["readiness_decision"]["first_blocker"] == "execution_disabled"
    assert commands["futures_place"]["readiness_decision"]["next_required_backend_contract"] is None
    assert commands["futures_place"]["risk_proof_id"] == proof["futures_risk_proof_id"]
    assert commands["futures_place"]["execution_allowed"] is False
    assert suite["live_coinbase_orders_ran"] is False

    recorded = service.record_futures_risk_proof(
        {
            "futures_risk_proof_id": "futures-risk-proof-operator-recorded",
            "command": "futures_place",
            "proof_kind": "margin_collateral",
            "product_id": "BIP-20DEC30-CDE",
            "risk_proof_verified": True,
            "risk_proof_accepted": False,
            "evidence_ref": proof["evidence_ref"],
        },
        context(idempotency_key="record-futures-risk-proof"),
    )
    assert recorded.status_code == 200
    assert recorded.body["proof_record_created"] is True
    assert recorded.body["live_coinbase_orders_ran"] is False

    recorded_detail = service.get_read_response(
        "/api/v1/futures/risk-proofs/futures-risk-proof-operator-recorded",
        {},
        context(),
    )
    assert recorded_detail.body["found"] is True
    assert recorded_detail.body["proof_record_created"] is True
    assert recorded_detail.body["record"]["command_execution_allowed"] is False


def test_admin_futures_command_suite_exposes_backend_payload_field_contracts():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    suite_result = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )

    assert suite_result.status_code == 200
    suite = suite_result.body
    assert suite["request_field_count"] == 11
    assert suite["required_request_field_count"] == 11
    assert suite["blocking_request_field_count"] == 0
    assert suite["request_field_summary_count"] == 8
    assert suite["request_field_summary_blocking_count"] == 0
    summaries = {item["field"]: item for item in suite["request_field_summaries"]}
    assert summaries["product_id"]["affected_commands"] == ["futures_place"]
    assert summaries["product_id"]["status"] == "passed"
    assert summaries["product_id"]["validation_gate_ref_count"] == 1
    assert summaries["position_key"]["affected_commands"] == [
        "futures_close_reduce",
        "futures_reconcile",
    ]
    assert summaries["client_order_id"]["affected_commands"] == ["futures_cancel"]
    assert summaries["limit_price"]["risk_field_command_count"] == 2
    assert summaries["size"]["risk_field_command_count"] == 2

    commands = {command["command"]: command for command in suite["commands"]}
    place = commands["futures_place"]
    assert place["request_field_count"] == 5
    assert place["required_request_field_count"] == 5
    assert place["blocking_request_field_count"] == 0
    assert [field["field"] for field in place["request_fields"]] == [
        "product_id",
        "order_side",
        "order_type",
        "limit_price",
        "size",
    ]
    assert all(field["request_payload_validated"] is True for field in place["request_fields"])


def test_admin_futures_command_suite_exposes_backend_enablement_sequence_traces():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    suite_result = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )

    assert suite_result.status_code == 200
    suite = suite_result.body
    assert suite["command_enablement_sequence_step_count"] == 5
    assert suite["command_enablement_sequence_step_blocking_count"] == 1
    assert [
        step["step"]
        for step in suite["command_enablement_sequence_steps"]
    ] == [
        "resolve_prerequisite_contracts",
        "define_request_payload_contract",
        "define_backend_command_service",
        "register_admin_command_route",
        "bind_live_service_adapter",
    ]
    payload_step = suite["command_enablement_sequence_steps"][1]
    assert payload_step["status"] == "passed"
    assert payload_step["blocking"] is False
    assert payload_step["source_blockers"] == []
    assert payload_step["command_route_registered"] is True
    assert payload_step["execution_allowed"] is False

    service_step = suite["command_enablement_sequence_steps"][2]
    assert service_step["status"] == "passed"
    assert service_step["blocking"] is False
    assert service_step["required_backend_contracts"] == [
        "admin_futures_command_service_contract"
    ]
    assert service_step["execution_allowed"] is False

    live_step = suite["command_enablement_sequence_steps"][4]
    assert live_step["status"] == "blocked"
    assert live_step["blocking"] is True
    assert "local MVP" not in live_step["detail"]
    assert "local runtime" in live_step["detail"]
    assert live_step["source_blockers"] == ["live_service_adapter"]
    assert live_step["affected_commands"] == [
        "futures_place",
        "futures_close_reduce",
        "futures_cancel",
        "futures_reconcile",
    ]
    assert live_step["required_backend_contracts"] == ["futures_live_adapter_contract"]
    assert live_step["required_evidence_refs"] == [
        "/api/v1/admin/live-execution/service-decisions",
        "/api/v1/admin/live-execution/adapter-decisions",
    ]
    assert live_step["live_coinbase_orders_ran"] is False
    assert live_step["spot_rule_authority"] is False

    assert suite["command_enablement_sequence_command_trace_count"] == 20
    assert suite["command_enablement_sequence_command_trace_blocking_count"] == 4
    traces = {
        trace["trace_id"]: trace
        for trace in suite["command_enablement_sequence_command_traces"]
    }
    place_payload_trace = traces["define_request_payload_contract::futures_place"]
    assert place_payload_trace["status"] == "passed"
    assert place_payload_trace["blocking"] is False
    assert place_payload_trace["command_sequence"] == 1
    assert place_payload_trace["command_step_sequence"] == 2
    assert place_payload_trace["execution_allowed"] is False
    assert place_payload_trace["futures_state_mutation_allowed"] is False

    cancel_live_trace = traces["bind_live_service_adapter::futures_cancel"]
    assert cancel_live_trace["status"] == "blocked"
    assert cancel_live_trace["blocking"] is True
    assert cancel_live_trace["source_blockers"] == ["live_service_adapter"]
    assert cancel_live_trace["required_backend_contract"] == "futures_live_adapter_contract"
    assert cancel_live_trace["required_evidence_ref_count"] == 2
    assert cancel_live_trace["live_coinbase_orders_ran"] is False
    assert cancel_live_trace["browser_authority"] == "display_only"
    assert cancel_live_trace["bff_authority"] == "forward_only_no_execution"


def test_admin_futures_commands_expose_readiness_closure_steps():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    suite_result = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )

    assert suite_result.status_code == 200
    commands = {
        command["command"]: command
        for command in suite_result.body["commands"]
    }
    place = commands["futures_place"]
    assert place["semantic_guard_count"] == 0
    assert place["blocking_semantic_guard_count"] == 0
    assert place["readiness_closure_step_count"] == 5
    assert place["blocking_readiness_closure_step_count"] == 1
    assert [
        step["step"]
        for step in place["readiness_closure_steps"]
    ] == [
        "resolve_prerequisite_contracts",
        "define_request_payload_contract",
        "define_backend_command_service",
        "register_admin_command_route",
        "bind_live_service_adapter",
    ]
    assert all(
        step["execution_allowed"] is False
        and step["backend_owned"] is True
        and step["read_only"] is True
        and step["spot_rule_authority"] is False
        and step["browser_authority"] == "display_only"
        and step["bff_authority"] == "forward_only_no_execution"
        for step in place["readiness_closure_steps"]
    )
    service_step = place["readiness_closure_steps"][2]
    assert service_step["status"] == "passed"
    assert service_step["required_backend_contract"] == (
        "admin_futures_command_service.futures_place"
    )
    assert service_step["required_evidence_refs"] == [
        "place_futures_order",
        "/api/v1/futures/orders",
    ]
    live_step = place["readiness_closure_steps"][4]
    assert live_step["status"] == "blocked"
    assert live_step["blocking"] is True
    assert live_step["required_backend_contract"] == "futures_live_adapter_contract"
    assert live_step["required_evidence_refs"] == [
        "/api/v1/admin/live-execution/service-decisions",
        "/api/v1/admin/live-execution/adapter-decisions",
    ]
    assert live_step["proof_writer_enabled"] is False


def test_admin_futures_place_rejects_invalid_payload_before_executor_boundary():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0",
            "size": "0",
        },
        context(idempotency_key="futures-place-invalid-payload"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "futures_payload_validation_failed"
    assert result.body["payload_validation"]["status"] == "blocked"
    assert result.body["payload_validation"]["blocking_request_field_count"] == 2
    assert result.body["payload_validation"]["missing_request_fields"] == []
    assert set(result.body["payload_validation"]["invalid_request_fields"]) == {
        "limit_price",
        "size",
    }
    assert result.body["admission_decision"]["failure_stage"] == (
        "futures_payload_validation_failed"
    )
    assert result.body["executor_decision_id"] is None
    assert service.store.futures_executor_decisions == {}
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False


def test_admin_futures_command_suite_ignores_intx_live_decisions_for_us_cfm_scope():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )
    record_futures_live_service_decision(
        service,
        decision_id="futures-intx-live-service",
        account_family="coinbase_intx_perpetuals",
        intx_applicability="requires_intx_account",
        product_scope=["BTC-PERP"],
    )
    record_futures_live_adapter_decision(
        service,
        decision_id="futures-intx-place-adapter",
        target_route="/api/v1/futures/orders",
        target_service_method="place_futures_order",
        account_family="coinbase_intx_perpetuals",
        intx_applicability="requires_intx_account",
        product_scope=["BTC-PERP"],
    )

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )

    assert command_suite.status_code == 200
    suite = command_suite.body
    assert suite["futures_live_execution_scope"] == {
        "account_family": "coinbase_futures_us_cfm",
        "intx_applicability": "not_applicable_us_account",
        "product_scope": ["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"],
        "execution_allowed": False,
    }
    assert suite["futures_live_decision_evidence"]["service_decision_status"] == (
        "missing_matching_us_cfm_service_decision"
    )
    assert suite["futures_live_decision_evidence"]["matching_service_decision_id"] is None
    assert suite["futures_live_decision_evidence"]["adapter_decision_ready_count"] == 0
    commands = {command["command"]: command for command in suite["commands"]}
    place_evidence = commands["futures_place"]["readiness_decision"]["live_decision_evidence"]
    assert place_evidence["account_family"] == "coinbase_futures_us_cfm"
    assert place_evidence["intx_applicability"] == "not_applicable_us_account"
    assert place_evidence["service_decision_status"] == (
        "missing_matching_us_cfm_service_decision"
    )
    assert place_evidence["adapter_decision_status"] == (
        "missing_matching_us_cfm_adapter_decision"
    )
    assert place_evidence["matching_adapter_decision_id"] is None
    assert commands["futures_place"]["readiness_decision"]["first_blocker"] == (
        "execution_disabled"
    )
    assert commands["futures_place"]["execution_allowed"] is False


def test_admin_futures_command_suite_binds_us_cfm_live_decisions_to_disabled_executor():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )

    assert command_suite.status_code == 200
    suite = command_suite.body
    assert suite["futures_live_decision_evidence"]["service_decision_status"] == "ready"
    assert suite["futures_live_decision_evidence"]["matching_service_decision_id"] == (
        "futures-us-cfm-live-service"
    )
    assert suite["futures_live_decision_evidence"]["adapter_decision_ready_count"] == 4
    assert suite["futures_live_decision_evidence"]["adapter_decision_missing_count"] == 0
    assert suite["futures_live_decision_evidence"]["executor_boundary_status"] == (
        "observed_live_disabled"
    )
    assert suite["futures_live_decision_evidence"]["executor_boundary_ready"] is True
    assert suite["command_enablement_blocker_summaries"][0]["blocker"] == (
        "futures_executor_live_disabled"
    )
    commands = {command["command"]: command for command in suite["commands"]}
    place_readiness = commands["futures_place"]["readiness_decision"]
    assert place_readiness["decision"] == "executor_observed_live_disabled"
    assert place_readiness["first_blocker"] == "futures_executor_live_disabled"
    assert place_readiness["live_decision_evidence"]["service_decision_status"] == "ready"
    assert place_readiness["live_decision_evidence"]["adapter_decision_status"] == "ready"
    assert place_readiness["live_decision_evidence"]["matching_adapter_decision_id"] == (
        "futures-us-cfm-place-adapter"
    )
    assert place_readiness["live_decision_evidence"]["executor_boundary_status"] == (
        "observed_live_disabled"
    )
    assert place_readiness["execution_allowed"] is False

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0.50",
            "number_of_contracts": "1",
        },
        context(idempotency_key="futures-place-us-cfm-evidence"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "futures_executor_live_disabled"
    assert result.body["readiness_decision"]["live_decision_evidence"][
        "matching_service_decision_id"
    ] == "futures-us-cfm-live-service"
    assert result.body["readiness_decision"]["live_decision_evidence"][
        "matching_adapter_decision_id"
    ] == "futures-us-cfm-place-adapter"
    assert result.body["admission_decision"]["allowed"] is False
    assert result.body["admission_decision"]["failure_stage"] == (
        "futures_executor_live_disabled"
    )
    assert result.body["admission_decision"]["account_family"] == (
        "coinbase_futures_us_cfm"
    )
    assert result.body["admission_decision"]["intx_applicability"] == (
        "not_applicable_us_account"
    )
    assert result.body["executor_decision"]["executor_status"] == (
        "observed_live_disabled"
    )
    assert result.body["executor_decision"]["account_family"] == (
        "coinbase_futures_us_cfm"
    )
    assert result.body["executor_decision"]["intx_applicability"] == (
        "not_applicable_us_account"
    )
    assert result.body["executor_decision"]["payload_hash"] == result.body["payload_hash"]
    assert result.body["executor_decision"]["live_exchange_submitted"] is False
    assert "local MVP" not in result.body["executor_decision"]["detail"]
    assert "local runtime" in result.body["executor_decision"]["detail"]
    assert result.body["executor_decision_id"] in service.store.futures_executor_decisions
    assert result.body["execution_allowed"] is False
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals"},
        context(),
    )

    assert workbench.status_code == 200
    assert workbench.body["count"] == 1
    assert workbench.body["pagination"]["total_matching_count"] == 1
    assert workbench.body["module_summary"][0]["module"] == "futures_perpetuals"
    event = workbench.body["events"][0]
    assert event["event_id"] == result.body["executor_decision_id"]
    assert event["module"] == "futures_perpetuals"
    assert event["source"] == "admin_api_futures_executor_boundary"
    assert event["endpoint"] == "/api/v1/futures/orders"
    assert event["status"] == "rejected"
    assert event["product_id"] == "BIP-20DEC30-CDE"
    assert event["admission_decision"]["status"] == "blocked"
    assert event["admission_decision"]["allowed"] is False
    assert event["admission_decision"]["blockers"] == ["futures_executor_live_disabled"]
    assert event["executor_decision"]["executor_status"] == "observed_live_disabled"
    assert event["executor_decision"]["live_exchange_submitted"] is False
    assert event["exchange_order_id_evidence_only"] is True
    assert event["live_exchange_submitted"] is False


def test_admin_futures_place_live_execution_uses_backend_rest_adapter_when_confirmed():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "100",
            "size": "1",
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
        context(idempotency_key="futures-place-live-submit"),
    )

    assert result.status_code == 200
    assert result.body["status"] == "accepted"
    assert result.body["failure_stage"] is None
    assert result.body["command"] == "futures_place"
    assert result.body["client_order_id"] == "futures-place-live-submit"
    assert result.body["coinbase_order_id"] == "exchange-order-live-1"
    assert result.body["submitted_notional_usdc"] == "1.00"
    assert result.body["notional_usdc"] == "1.00"
    assert result.body["live_exchange_submitted"] is True
    assert result.body["live_coinbase_orders_ran"] is True
    assert result.body["live_coinbase_execution"] == "submitted"
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "futures-place-live-submit",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "100",
                    "post_only": False,
                }
            },
        }
    ]

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals"},
        context(),
    )

    assert workbench.status_code == 200
    assert workbench.body["count"] == 1
    event = workbench.body["events"][0]
    assert event["event_id"] == result.body["submission_event_id"]
    assert event["status"] == "accepted"
    assert event["source"] == "admin_api_futures_command_log"
    assert event["exchange_order_id"] == "exchange-order-live-1"
    assert event["exchange_order_id_evidence_only"] is True
    assert event["live_exchange_submitted"] is True
    assert event["live_coinbase_orders_ran"] is True


def test_admin_futures_place_live_execution_requires_explicit_acknowledgement():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0.50",
            "size": "1",
            "dry_run": False,
        },
        context(idempotency_key="futures-place-draft-no-ack"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "futures_executor_live_disabled"
    assert result.body["live_exchange_submitted"] is False
    assert rest_client.create_order_calls == []


def test_admin_futures_place_live_execution_rejects_above_backend_cap():
    rest_client = FakeAccountRestClient()
    rest_client.product_dicts["BIP-20DEC30-CDE"] = {
        "product_id": "BIP-20DEC30-CDE",
        "product_type": "FUTURE",
        "price": "62625",
        "best_bid": "62625",
        "best_ask": "62630",
        "price_increment": "5",
        "base_increment": "1",
        "future_product_details": {"contract_size": "0.01"},
    }
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "80000",
            "size": "1",
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
        context(idempotency_key="futures-place-live-over-cap"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "futures_cap_required"
    assert result.body["submitted_notional_usdc"] == "0"
    assert result.body["notional_usdc"] == "800.00"
    assert result.body["live_exchange_submitted"] is False
    assert rest_client.create_order_calls == []

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(idempotency_key="futures-place-live-over-cap-suite"),
    )

    assert command_suite.status_code == 200
    exposure = command_suite.body["futures_product_exposure_evidence"]
    assert exposure["status"] == "ready"
    assert exposure["max_submitted_notional_usdc"] == "100.00"
    assert exposure["any_product_within_backend_cap"] is True
    assert exposure["next_required_operator_decision"] == (
        "select_configured_us_cfm_product_within_cap"
    )
    assert exposure["items"] == [
        {
            "product_id": "AVP-20DEC30-CDE",
            "status": "ready",
            "metadata_read_status": "ready",
            "metadata_read_error": None,
            "source": "backend_rest_client",
            "reference_side": "BUY",
            "reference_limit_price": "6.92",
            "price_increment": "0.01",
            "contract_size": "10.00",
            "minimum_contracts": "1",
            "minimum_contract_notional_usdc": "69.20",
            "minimum_contract_notional_source": "backend_product_metadata",
            "max_submitted_notional_usdc": "100.00",
            "within_backend_cap": True,
            "execution_allowed": False,
            "live_coinbase_orders_ran": False,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
        {
            "product_id": "BIP-20DEC30-CDE",
            "status": "blocked",
            "metadata_read_status": "ready",
            "metadata_read_error": None,
            "source": "backend_rest_client",
            "reference_side": "BUY",
            "reference_limit_price": "62625.00",
            "price_increment": "5.00",
            "contract_size": "0.01",
            "minimum_contracts": "1",
            "minimum_contract_notional_usdc": "626.25",
            "minimum_contract_notional_source": "backend_product_metadata",
            "max_submitted_notional_usdc": "100.00",
            "within_backend_cap": False,
            "execution_allowed": False,
            "live_coinbase_orders_ran": False,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
    ]
    assert command_suite.body["futures_live_decision_evidence"][
        "futures_product_exposure_evidence"
    ]["any_product_within_backend_cap"] is True
    failure = command_suite.body["latest_live_submit_failure"]
    assert command_suite.body["latest_live_submit_failure_present"] is True
    assert failure["failure_stage"] == "futures_cap_required"
    assert failure["product_id"] == "BIP-20DEC30-CDE"
    assert failure["client_order_id"] == "futures-place-live-over-cap"
    assert failure["attempted_notional_usdc"] == "800.00"
    assert failure["submitted_notional_usdc"] == "0.00"
    assert failure["max_submitted_notional_usdc"] == "100.00"
    assert failure["live_exchange_submitted"] is False
    assert failure["next_required_operator_decision"] == (
        "choose_lower_notional_us_cfm_product_or_raise_futures_cap"
    )
    live_evidence = command_suite.body["futures_live_decision_evidence"]
    assert live_evidence["latest_live_submit_failure_present"] is True
    assert live_evidence["latest_live_submit_failure"]["failure_stage"] == (
        "futures_cap_required"
    )
    assert command_suite.body["command_enablement_blocker_summaries"][0][
        "latest_live_submit_failure"
    ]["attempted_notional_usdc"] == "800.00"


def test_admin_futures_product_exposure_falls_back_to_latest_live_submit_failure():
    rest_client = FakeAccountRestClient()
    rest_client.product_dicts = {}
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "80000",
            "size": "1",
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
        context(idempotency_key="futures-place-live-over-cap-metadata-missing"),
    )

    assert result.status_code == 400
    assert result.body["failure_stage"] == "futures_cap_required"

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(idempotency_key="futures-place-live-over-cap-metadata-missing-suite"),
    )

    assert command_suite.status_code == 200
    exposure = command_suite.body["futures_product_exposure_evidence"]
    assert exposure["status"] == "blocked"
    bip_exposure = next(
        item
        for item in exposure["items"]
        if item["product_id"] == "BIP-20DEC30-CDE"
    )
    assert bip_exposure["metadata_read_status"] == "blocked"
    assert bip_exposure["metadata_read_error"] == "product_metadata_missing"
    assert bip_exposure["minimum_contract_notional_usdc"] == "800.00"
    assert bip_exposure["minimum_contract_notional_source"] == (
        "latest_live_submit_failure"
    )
    assert bip_exposure["within_backend_cap"] is False


def test_admin_futures_place_live_execution_requires_runtime_enablement():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0.50",
            "size": "1",
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
        context(idempotency_key="futures-place-live-runtime-disabled"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "futures_live_runtime_disabled"
    assert result.body["live_exchange_submitted"] is False
    assert rest_client.create_order_calls == []


def test_admin_futures_close_reduce_live_execution_uses_backend_rest_adapter_when_confirmed():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/positions/futures_position:runtime:AVP-20DEC30-CDE/close-reduce",
        {
            "limit_price": "6.92",
            "size": "1",
            "dry_run": False,
            "manual_live_acknowledgement": True,
            "operator_reason": "operator confirmed backend-controlled futures close reduce",
        },
        context(idempotency_key="futures-close-reduce-live-submit"),
    )

    assert result.status_code == 200
    assert result.body["status"] == "accepted"
    assert result.body["failure_stage"] is None
    assert result.body["command"] == "futures_close_reduce"
    assert result.body["mutation_family"] == "futures_live_close_reduce"
    assert result.body["identity_key"] == "position_key"
    assert result.body["identity_value"] == "futures_position:runtime:AVP-20DEC30-CDE"
    assert result.body["product_id"] == "AVP-20DEC30-CDE"
    assert result.body["client_order_id"] == "futures-close-reduce-live-submit"
    assert result.body["coinbase_order_id"] == "exchange-close-position-live-1"
    assert result.body["coinbase_close_position_submission_allowed"] is True
    assert result.body["submitted_notional_usdc"] == "69.20"
    assert result.body["executed_notional_usdc"] == "0"
    assert result.body["live_exchange_submitted"] is True
    assert result.body["live_coinbase_orders_ran"] is True
    assert result.body["live_coinbase_execution"] == "submitted"
    assert result.body["spot_rule_authority"] is False
    assert result.body["exchange_order_id_evidence_only"] is True
    assert rest_client.close_position_calls == [
        {
            "client_order_id": "futures-close-reduce-live-submit",
            "product_id": "AVP-20DEC30-CDE",
            "size": "1",
        }
    ]
    assert rest_client.cancel_order_calls == []
    assert rest_client.create_order_calls == []

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {
            "module": "futures_perpetuals",
            "client_order_id": "futures-close-reduce-live-submit",
        },
        context(),
    )

    assert workbench.status_code == 200
    assert workbench.body["count"] == 1
    event = workbench.body["events"][0]
    assert event["event_id"] == result.body["submission_event_id"]
    assert event["status"] == "accepted"
    assert event["source"] == "admin_api_futures_command_log"
    assert event["endpoint"] == "/api/v1/futures/positions/{position_key}/close-reduce"
    assert event["client_order_id"] == "futures-close-reduce-live-submit"
    assert event["exchange_order_id"] == "exchange-close-position-live-1"
    assert event["exchange_order_id_evidence_only"] is True
    assert event["live_exchange_submitted"] is True
    assert event["live_coinbase_orders_ran"] is True


def test_admin_futures_cancel_live_execution_uses_backend_rest_adapter_when_confirmed():
    rest_client = FakeAccountRestClient()
    rest_client.cancel_orders_response = {
        "results": [
            {
                "success": True,
                "order_id": "client-futures-live-cancel",
            }
        ]
    }
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders/client-futures-live-cancel/cancel",
        {
            "product_id": "BIP-20DEC30-CDE",
            "dry_run": False,
            "manual_live_acknowledgement": True,
            "operator_reason": "operator confirmed backend-controlled futures cancel",
        },
        context(idempotency_key="futures-cancel-live-submit"),
    )

    assert result.status_code == 200
    assert result.body["status"] == "accepted"
    assert result.body["failure_stage"] is None
    assert result.body["command"] == "futures_cancel"
    assert result.body["mutation_family"] == "futures_live_cancel"
    assert result.body["identity_key"] == "client_order_id"
    assert result.body["identity_value"] == "client-futures-live-cancel"
    assert result.body["client_order_id"] == "client-futures-live-cancel"
    assert result.body["coinbase_cancel_submission_allowed"] is True
    assert result.body["live_exchange_submitted"] is True
    assert result.body["live_coinbase_orders_ran"] is True
    assert result.body["live_coinbase_execution"] == "submitted"
    assert result.body["submitted_notional_usdc"] == "0"
    assert result.body["executed_notional_usdc"] == "0"
    assert result.body["spot_rule_authority"] is False
    assert result.body["exchange_order_id_evidence_only"] is True
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-futures-live-cancel"]}
    ]
    assert rest_client.create_order_calls == []

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals", "client_order_id": "client-futures-live-cancel"},
        context(),
    )

    assert workbench.status_code == 200
    assert workbench.body["count"] == 1
    event = workbench.body["events"][0]
    assert event["event_id"] == result.body["submission_event_id"]
    assert event["status"] == "accepted"
    assert event["source"] == "admin_api_futures_command_log"
    assert event["endpoint"] == "/api/v1/futures/orders/{client_order_id}/cancel"
    assert event["client_order_id"] == "client-futures-live-cancel"
    assert event["exchange_order_id_evidence_only"] is True
    assert event["live_exchange_submitted"] is True
    assert event["live_coinbase_orders_ran"] is True


def test_admin_futures_cancel_live_execution_requires_runtime_enablement():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )
    record_futures_live_service_decision(service)
    record_all_futures_live_adapter_decisions(service)

    result = service.submit_futures_command(
        "/api/v1/futures/orders/client-futures-runtime-disabled/cancel",
        {
            "product_id": "BIP-20DEC30-CDE",
            "dry_run": False,
            "manual_live_acknowledgement": True,
            "operator_reason": "operator confirmed backend-controlled futures cancel",
        },
        context(idempotency_key="futures-cancel-live-runtime-disabled"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["mutation_family"] == "futures_live_cancel"
    assert result.body["failure_stage"] == "futures_live_runtime_disabled"
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False
    assert rest_client.cancel_order_calls == []
    assert rest_client.create_order_calls == []


def test_admin_futures_command_routes_are_registered_as_blocked_drafts():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeAccountRestClient(), rest_client_available=True)
    )

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    futures_commands = {
        item["route"]: item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST" and item["module_id"] == "futures_perpetuals"
    }

    assert set(futures_commands) >= {
        "/api/v1/futures/orders",
        "/api/v1/futures/positions/{position_key}/close-reduce",
        "/api/v1/futures/orders/{client_order_id}/cancel",
        "/api/v1/futures/positions/{position_key}/reconciliation",
        "/api/v1/futures/risk-proofs",
    }
    assert futures_commands["/api/v1/futures/orders"]["shared_method"] == "place_futures_order"
    assert futures_commands["/api/v1/futures/orders"]["live_enabled"] is False
    assert futures_commands["/api/v1/futures/orders"]["frontend_safe"] is True

    result = service.submit_futures_command(
        "/api/v1/futures/orders",
        {
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT",
            "limit_price": "0.50",
            "number_of_contracts": "1",
        },
        context(idempotency_key="futures-place-draft"),
    )

    assert result.status_code == 501
    assert result.body["type"] == "admin_api_command_result"
    assert result.body["module_id"] == "futures_perpetuals"
    assert result.body["command"] == "futures_place"
    assert result.body["route"] == "/api/v1/futures/orders"
    assert result.body["identity_key"] == "product_id"
    assert result.body["identity_value"] == "BIP-20DEC30-CDE"
    assert result.body["status"] == "not_implemented"
    assert result.body["failure_stage"] == "execution_disabled"
    assert result.body["command_route_registered"] is True
    assert result.body["command_draft_allowed"] is True
    assert result.body["execution_allowed"] is False
    assert result.body["local_state_mutated"] is False
    assert result.body["exchange_state_mutated"] is False
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False
    assert result.body["notional_usdc"] == "0.00"
    assert result.body["readiness_decision"]["first_blocker"] == "execution_disabled"
    assert result.body["submission_event_recorded"] is True
    assert result.body["submission_event_id"] in service.store.futures_command_decisions

    cancel = service.submit_futures_command(
        "/api/v1/futures/orders/client-futures-001/cancel",
        {"operator_reason": "operator_cancel_review"},
        context(idempotency_key="futures-cancel-draft"),
    )
    assert cancel.status_code == 501
    assert cancel.body["command"] == "futures_cancel"
    assert cancel.body["identity_key"] == "client_order_id"
    assert cancel.body["identity_value"] == "client-futures-001"
    assert cancel.body["live_coinbase_orders_ran"] is False
    assert cancel.body["submission_event_recorded"] is True
    assert cancel.body["submission_event_id"] in service.store.futures_command_decisions

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals"},
        context(),
    )

    assert workbench.status_code == 200
    assert workbench.body["count"] == 2
    assert workbench.body["module_summary"][0]["module"] == "futures_perpetuals"
    assert workbench.body["module_summary"][0]["primary_identity"] == (
        "position_key/product_id/client_order_id"
    )
    assert workbench.body["module_summary"][0]["notes"] == (
        "Futures command and executor decisions are read-only audit evidence; live "
        "Coinbase execution remains disabled."
    )
    place_event = next(
        event
        for event in workbench.body["events"]
        if event["event_id"] == result.body["submission_event_id"]
    )
    assert place_event["source"] == "admin_api_futures_command_log"
    assert place_event["endpoint"] == "/api/v1/futures/orders"
    assert place_event["status"] == "not_implemented"
    assert place_event["product_id"] == "BIP-20DEC30-CDE"
    assert place_event["client_order_id"] is None
    assert place_event["admission_decision"]["failure_stage"] == "execution_disabled"
    assert place_event["readiness_decision"]["first_blocker"] == "execution_disabled"
    assert place_event["exchange_order_id_evidence_only"] is True
    assert place_event["live_exchange_submitted"] is False
    assert place_event["live_coinbase_orders_ran"] is False

    cancel_workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "futures_perpetuals", "client_order_id": "client-futures-001"},
        context(),
    )
    assert cancel_workbench.status_code == 200
    assert cancel_workbench.body["count"] == 1
    assert cancel_workbench.body["events"][0]["event_id"] == cancel.body["submission_event_id"]
    assert cancel_workbench.body["events"][0]["client_order_id"] == "client-futures-001"
    assert cancel_workbench.body["events"][0]["product_id"] == "AVP-20DEC30-CDE"


def test_admin_mvp_read_contract_exposes_frontend_manual_order_readiness():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    record_live_adapter_decision(service)

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    manual_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST" and item["route"] == "/api/v1/orders"
    )
    cancel_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    live_service_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/admin/live-execution/service-decisions"
    )
    live_adapter_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/admin/live-execution/adapter-decisions"
    )
    proof_chain_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/spot/manual-order/proof-chain"
    )
    cancel_proof_chain_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/spot/cancel-order/proof-chain"
    )
    command_permissions = {
        item["route"]: item["permission"]
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
    }
    assert manual_capability["availability"] == "available"
    assert manual_capability["live_enabled"] is True
    assert manual_capability["frontend_safe"] is True
    assert manual_capability["permission"] == "order:create"
    assert cancel_capability["live_enabled"] is True
    assert cancel_capability["permission"] == "order:cancel"
    assert live_service_capability["permission"] == "config:update"
    assert live_service_capability["shared_method"] == "record_live_service_decision"
    assert live_service_capability["frontend_safe"] is True
    assert live_service_capability["live_enabled"] is False
    assert live_adapter_capability["permission"] == "config:update"
    assert live_adapter_capability["shared_method"] == "record_live_adapter_decision"
    assert live_adapter_capability["frontend_safe"] is True
    assert live_adapter_capability["live_enabled"] is False
    assert proof_chain_capability["module_id"] == "spot_operations"
    assert proof_chain_capability["permission"] == "spot_manual_order_proof:record"
    assert proof_chain_capability["shared_method"] == "record_spot_manual_order_proof_chain"
    assert proof_chain_capability["frontend_safe"] is True
    assert proof_chain_capability["live_enabled"] is False
    assert cancel_proof_chain_capability["module_id"] == "spot_operations"
    assert cancel_proof_chain_capability["permission"] == "spot_order_cancel_proof:record"
    assert (
        cancel_proof_chain_capability["shared_method"]
        == "record_spot_cancel_order_proof_chain"
    )
    assert cancel_proof_chain_capability["frontend_safe"] is True
    assert cancel_proof_chain_capability["live_enabled"] is False
    assert command_permissions["/api/v1/admin/approvals/requests"] == "approval:request"
    assert (
        command_permissions[
            "/api/v1/admin/approvals/requests/{approval_request_id}/decisions"
        ]
        == "approval:manage"
    )
    assert command_permissions["/api/v1/admin/admission-audits"] == "admission_audit:record"
    assert command_permissions["/api/v1/admin/cap-guard/decisions"] == "cap_guard:record"
    assert command_permissions["/api/v1/admin/reconciliation/plans"] == "reconciliation:record"
    assert command_permissions["/api/v1/futures/risk-proofs"] == "futures_risk_proof:record"
    assert (
        command_permissions["/api/v1/spot/cancel-order/proof-chain"]
        == "spot_order_cancel_proof:record"
    )
    assert (
        command_permissions["/api/v1/admin/live-execution/adapter-decisions"]
        == "config:update"
    )

    service_decisions = service.get_read_response(
        "/api/v1/admin/live-execution/service-decisions",
        {},
        context(),
    )
    assert service_decisions.body["type"] == "admin_live_service_decision_list"
    assert service_decisions.body["total_count"] == 1
    assert service_decisions.body["returned_count"] == 1
    assert service_decisions.body["passed_count"] == 1
    assert service_decisions.body["live_coinbase_orders_ran"] is False

    service_detail = service.get_read_response(
        "/api/v1/admin/live-execution/service-decisions/mvp-live-service",
        {},
        context(),
    )
    assert service_detail.body["type"] == "admin_live_service_decision"
    assert service_detail.body["status"] == "accepted"
    assert service_detail.body["service_method"] == "get_live_service_decision"
    assert service_detail.body["decision"]["decision_id"] == "mvp-live-service"

    adapter_decisions = service.get_read_response(
        "/api/v1/admin/live-execution/adapter-decisions",
        {},
        context(),
    )
    assert adapter_decisions.body["type"] == "admin_live_adapter_decision_list"
    assert adapter_decisions.body["total_count"] == 1
    assert adapter_decisions.body["returned_count"] == 1
    assert adapter_decisions.body["blocked_count"] == 1
    assert adapter_decisions.body["constructed_count"] == 0
    assert adapter_decisions.body["live_coinbase_orders_ran"] is False

    adapter_detail = service.get_read_response(
        "/api/v1/admin/live-execution/adapter-decisions/mvp-live-adapter",
        {},
        context(),
    )
    assert adapter_detail.body["type"] == "admin_live_adapter_decision"
    assert adapter_detail.body["status"] == "accepted"
    assert adapter_detail.body["service_method"] == "get_live_adapter_decision"
    assert adapter_detail.body["decision"]["decision_id"] == "mvp-live-adapter"

    live_enablement = service.get_read_response(
        "/api/v1/admin/live-enablement",
        {},
        context(),
    )
    manual_path = next(
        path
        for path in live_enablement.body["paths"]
        if path["route"] == "/api/v1/orders"
    )
    assert live_enablement.body["status"] == "live_disabled"
    assert live_enablement.body["live_enabled_path_count"] == 0
    assert live_enablement.body["live_eligible_path_count"] == 2
    assert live_enablement.body["live_executable_path_count"] == 0
    assert live_enablement.body["live_service_decision_enabled"] is True
    assert live_enablement.body["backend_live_execution_opt_in"] is False
    assert manual_path["live_enabled"] is False
    assert manual_path["live_eligible"] is True
    assert manual_path["live_command_runtime_ready"] is True
    assert manual_path["live_service_decision_enabled"] is True
    assert manual_path["backend_live_execution_opt_in"] is False
    assert manual_path["live_executable"] is False
    assert manual_path["live_blocker"] == "backend_live_execution_disabled"
    assert live_enablement.body["live_coinbase_orders_ran"] is False

    command_suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    manual_command = next(
        command
        for command in command_suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    assert command_suite.body["live_enabled_command_count"] == 1
    assert manual_command["live_enabled"] is True
    assert manual_command["executable"] is False


def test_spot_command_suite_resolves_manual_order_proof_chain_from_backend_records():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)

    initial_suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    initial_manual = next(
        command
        for command in initial_suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    assert initial_manual["missing_gate_chain"] == [
        "approval_snapshot",
        "admission_audit",
        "cap_guard",
        "reconciliation_plan",
    ]

    record_proof_chain(service, admission)

    suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    manual_command = next(
        command
        for command in suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )

    assert suite.status_code == 200
    assert suite.body["manual_order_proof_chain_status"] == "passed"
    assert suite.body["manual_order_missing_gate_count"] == 0
    assert manual_command["proof_chain_status"] == "passed"
    assert manual_command["missing_gate_chain"] == []
    assert manual_command["resolved_gate_chain"] == [
        "approval_snapshot",
        "admission_audit",
        "cap_guard",
        "reconciliation_plan",
    ]
    assert manual_command["proof_chain_blocker_count"] == 0
    assert manual_command["admission_context"]["identity_value"] == admission["identity_value"]
    assert manual_command["admission_decision"]["allowed"] is True
    assert manual_command["live_exchange_submitted"] is False
    assert manual_command["live_coinbase_orders_ran"] is False
    assert suite.body["live_coinbase_orders_ran"] is False


def test_spot_command_suite_marks_manual_order_executable_after_backend_live_evidence():
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=FakeAccountRestClient(),
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    order_body = limit_ioc_manual_order_body()
    record_live_service_decision(service)
    admission = first_manual_submit(service, order_body)
    record_proof_chain(service, admission)

    suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        preview_query(admission),
        context(),
    )
    manual_command = next(
        command
        for command in suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    readiness = {
        item["precondition"]: item
        for item in manual_command["readiness_preconditions"]
    }

    assert suite.status_code == 200
    assert suite.body["executable_command_count"] == 1
    assert suite.body["blocked_command_count"] == 1
    assert manual_command["status"] == "ready"
    assert manual_command["executable"] is True
    assert manual_command["proof_chain_status"] == "passed"
    assert manual_command["readiness_precondition_count"] == 5
    assert manual_command["blocking_readiness_precondition_count"] == 0
    assert manual_command["passed_readiness_precondition_count"] == 5
    assert readiness["manual_order_proof_chain"]["status"] == "passed"
    assert readiness["live_service_decision"]["status"] == "passed"
    assert readiness["backend_live_execution_opt_in"]["status"] == "passed"
    assert readiness["live_command_runtime"]["status"] == "passed"
    assert readiness["wallet_inventory"]["status"] == "passed"
    assert manual_command["live_exchange_submitted"] is False
    assert manual_command["live_coinbase_orders_ran"] is False
    assert suite.body["live_coinbase_orders_ran"] is False


def test_spot_manual_order_proof_chain_route_records_backend_evidence_from_command_context():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )
    record_live_service_decision(service)
    order_body = limit_ioc_manual_order_body()
    admission = first_manual_submit(service, order_body)

    recorded = service.record_spot_manual_order_proof_chain(
        preview_query(admission),
        context(idempotency_key="spot-manual-order-proof-chain-record"),
    )

    assert recorded.status_code == 200
    assert recorded.body["type"] == "spot_manual_order_proof_chain_result"
    assert recorded.body["status"] == "accepted"
    assert recorded.body["proof_chain_status"] == "passed"
    assert recorded.body["missing_gate_chain"] == []
    assert recorded.body["resolved_gate_chain"] == [
        "approval_snapshot",
        "admission_audit",
        "cap_guard",
        "reconciliation_plan",
    ]
    assert recorded.body["live_exchange_submitted"] is False
    assert recorded.body["live_coinbase_orders_ran"] is False
    assert recorded.body["admission_decision"]["allowed"] is True
    assert recorded.body["admission_decision"]["identity_value"] == admission["identity_value"]
    assert recorded.body["admission_decision"]["payload_hash"] == admission["payload_hash"]
    assert recorded.body["approval_request_id"]
    assert recorded.body["approval_snapshot_id"]
    assert recorded.body["admission_audit_id"]
    assert recorded.body["cap_guard_decision_id"]
    assert recorded.body["reconciliation_plan_id"]
    assert rest_client.create_order_calls == []
    assert rest_client.get_account_wallets_calls >= 1

    cap_guard = service.store.cap_guard_decisions[recorded.body["cap_guard_decision_id"]]
    assert cap_guard["wallet_check_source"] == "account_management_snapshot"
    assert cap_guard["wallet_check_status"] == "passed"
    assert cap_guard["allowed"] is True

    suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        preview_query(admission),
        context(),
    )
    manual_command = next(
        command
        for command in suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    assert suite.body["manual_order_proof_chain_status"] == "passed"
    assert suite.body["manual_order_missing_gate_count"] == 0
    assert manual_command["admission_decision"]["allowed"] is True
    assert manual_command["live_exchange_submitted"] is False
    assert manual_command["live_coinbase_orders_ran"] is False

    admitted_submit = service.submit_manual_order(
        order_body,
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert admitted_submit.status_code == 400
    assert admitted_submit.body["admission_decision"]["allowed"] is True
    assert admitted_submit.body["live_exchange_submitted"] is False
    assert admitted_submit.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []


def test_spot_cancel_order_proof_chain_route_records_backend_evidence_from_client_order_context():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=rest_client, rest_client_available=True)
    )
    cancel_body = {
        "route": "/api/v1/orders/{client_order_id}/cancel",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": "client-cancel-proof",
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": "cancel_order_by_client_order_id",
        "actor_id": "operator-1",
        "operator_intent": "cancel_by_client_order_id",
        "command_idempotency_key": "cancel-command-proof",
        "payload_hash": "d" * 64,
    }

    recorded = service.record_spot_cancel_order_proof_chain(
        cancel_body,
        context(idempotency_key="spot-cancel-order-proof-chain-record"),
    )

    assert recorded.status_code == 200
    assert recorded.body["type"] == "spot_cancel_order_proof_chain_result"
    assert recorded.body["status"] == "accepted"
    assert recorded.body["proof_chain_status"] == "passed"
    assert recorded.body["missing_gate_chain"] == []
    assert recorded.body["resolved_gate_chain"] == ["cancel_proof_chain"]
    assert recorded.body["identity_value"] == "client-cancel-proof"
    assert recorded.body["command_idempotency_key"] == "cancel-command-proof"
    assert recorded.body["cancel_proof_chain_id"]
    assert recorded.body["live_exchange_submitted"] is False
    assert recorded.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []

    suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    cancel_command = next(
        command
        for command in suite.body["commands"]
        if command["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    assert suite.body["cancel_order_proof_chain_status"] == "passed"
    assert suite.body["cancel_order_missing_gate_count"] == 0
    assert cancel_command["proof_chain_status"] == "passed"
    assert cancel_command["missing_gate_chain"] == []
    assert cancel_command["resolved_gate_chain"] == ["cancel_proof_chain"]
    assert cancel_command["proof_chain_blocker_count"] == 0
    assert cancel_command["cancel_context"]["identity_value"] == "client-cancel-proof"
    assert cancel_command["live_enabled"] is False
    assert cancel_command["executable"] is False
    assert cancel_command["live_exchange_submitted"] is False
    assert cancel_command["live_coinbase_orders_ran"] is False

    cancel_result = service.cancel_order_by_client_order_id(
        "client-cancel-proof",
        {"reason": "operator_requested_cancel"},
        context(idempotency_key="cancel-command-proof"),
    )
    assert cancel_result.status_code == 501
    assert cancel_result.body["status"] == "not_implemented"
    assert cancel_result.body["proof_context"]["identity_value"] == "client-cancel-proof"
    assert cancel_result.body["live_exchange_submitted"] is False
    assert cancel_result.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []


def test_spot_cancel_order_live_execution_flows_through_backend_cancel_adapter():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_live_service_decision(service)
    cancel_body = {
        "route": "/api/v1/orders/{client_order_id}/cancel",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": "client-cancel-live",
        "action_class": "live_exchange_cancel",
        "required_permission": "order:cancel",
        "service_method": "cancel_order_by_client_order_id",
        "actor_id": "operator-1",
        "operator_intent": "cancel_by_client_order_id",
        "command_idempotency_key": "cancel-command-live",
        "payload_hash": "e" * 64,
    }
    recorded = service.record_spot_cancel_order_proof_chain(
        cancel_body,
        context(idempotency_key="spot-cancel-order-live-proof-chain-record"),
    )
    assert recorded.status_code == 200

    cancel_result = service.cancel_order_by_client_order_id(
        "client-cancel-live",
        {
            "reason": "operator_requested_cancel",
            "payload_hash": "e" * 64,
            "manual_live_acknowledgement": True,
        },
        context(idempotency_key="cancel-command-live"),
    )

    assert cancel_result.status_code == 200
    assert cancel_result.body["status"] == "accepted"
    assert cancel_result.body["failure_stage"] is None
    assert cancel_result.body["client_order_id"] == "client-cancel-live"
    assert cancel_result.body["coinbase_cancel_submission_allowed"] is True
    assert cancel_result.body["live_exchange_submitted"] is True
    assert cancel_result.body["live_coinbase_orders_ran"] is True
    assert cancel_result.body["live_coinbase_execution"] == "submitted"
    assert cancel_result.body["submitted_notional_usdc"] == "0"
    assert cancel_result.body["cancel_event_recorded"] is True
    assert rest_client.cancel_order_calls == [{"order_ids": ["client-cancel-live"]}]
    assert rest_client.create_order_calls == []

    suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    cancel_command = next(
        command
        for command in suite.body["commands"]
        if command["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    assert suite.body["cancel_order_proof_chain_status"] == "passed"
    assert suite.body["cancel_order_missing_gate_count"] == 0
    assert cancel_command["status"] == "ready"
    assert cancel_command["live_enabled"] is True
    assert cancel_command["live_eligible"] is True
    assert cancel_command["live_adapter_configured"] is True

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    cancel_capability = next(
        capability
        for capability in capabilities.body["capabilities"]
        if capability["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    assert cancel_capability["live_enabled"] is True

    live_enablement = service.get_read_response(
        "/api/v1/admin/live-enablement",
        {},
        context(),
    )
    cancel_path = next(
        path
        for path in live_enablement.body["paths"]
        if path["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    assert live_enablement.body["live_enabled_path_count"] == 2
    assert live_enablement.body["live_eligible_path_count"] == 2
    assert live_enablement.body["live_executable_path_count"] == 2
    assert cancel_path["live_enabled"] is True
    assert cancel_path["live_eligible"] is True
    assert cancel_path["live_executable"] is True

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "spot", "client_order_id": "client-cancel-live"},
        context(),
    )
    assert workbench.status_code == 200
    assert workbench.body["count"] == 1
    event = workbench.body["events"][0]
    assert event["endpoint"] == "/api/v1/orders/{client_order_id}/cancel"
    assert event["status"] == "accepted"
    assert event["client_order_id"] == "client-cancel-live"
    assert event["live_exchange_submitted"] is True
    assert event["live_coinbase_orders_ran"] is True


def test_admin_mvp_proof_chain_admits_manual_order_but_default_stays_pre_coinbase():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(service, admission)

    preview = service.preview_admission(preview_query(admission), context())
    assert preview.status_code == 200
    assert preview.body["admission_decision"]["status"] == "passed"
    assert preview.body["admission_decision"]["allowed"] is True
    assert preview.body["live_exchange_submitted"] is False
    assert preview.body["live_coinbase_orders_ran"] is False

    admitted_submit = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert admitted_submit.status_code == 400
    assert admitted_submit.body["status"] == "rejected"
    assert admitted_submit.body["failure_stage"] in PRE_COINBASE_FAILURE_STAGES
    assert admitted_submit.body["admission_decision"]["status"] == "passed"
    assert admitted_submit.body["admission_decision"]["allowed"] is True
    assert admitted_submit.body["live_command_runtime_ready"] is True
    assert admitted_submit.body["live_exchange_submitted"] is False
    assert admitted_submit.body["live_coinbase_orders_ran"] is False
    assert admitted_submit.body["notional_usdc"] == "1.00"


def test_admin_mvp_explicit_live_execution_flows_through_backend_service_only():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    body = limit_ioc_manual_order_body()
    record_live_service_decision(service)
    admission = first_manual_submit(service, body)
    record_proof_chain(service, admission)

    live_submit = service.submit_manual_order(
        body,
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert live_submit.status_code == 200
    assert live_submit.body["status"] == "accepted"
    assert live_submit.body["live_exchange_submitted"] is True
    assert live_submit.body["live_coinbase_orders_ran"] is True
    assert live_submit.body["notional_usdc"] == "1.00"
    assert live_submit.body["coinbase_order_id"] == "exchange-order-live-1"
    assert live_submit.body["paired_sell_required"] is False
    assert rest_client.create_order_calls == [
        {
            "client_order_id": admission["identity_value"],
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "sor_limit_ioc": {
                    "quote_size": "1.00",
                    "limit_price": "100000.00",
                },
            },
        }
    ]
    assert all(call["side"] != "SELL" for call in rest_client.create_order_calls)

    health = service.get_read_response("/api/v1/admin/health", {}, context())
    live_enablement = service.get_read_response(
        "/api/v1/admin/live-enablement",
        {},
        context(),
    )
    command_suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    assert health.body["live_coinbase_orders_ran"] is True
    assert health.body["live_coinbase_execution"] == "submitted"
    assert health.body["notional_usdc"] == "1.00"
    assert live_enablement.body["live_coinbase_orders_ran"] is True
    assert live_enablement.body["default_live_coinbase_execution"] == "submitted"
    assert live_enablement.body["status"] == "approval_required"
    assert live_enablement.body["live_enabled_path_count"] == 2
    assert live_enablement.body["live_executable_path_count"] == 2
    assert live_enablement.body["backend_live_execution_opt_in"] is True
    assert command_suite.body["live_coinbase_orders_ran"] is True
    assert command_suite.body["submitted_notional_usdc"] == "1.00"

    workbench = service.get_read_response(
        "/api/v1/admin/audit-workbench",
        {"module": "spot", "client_order_id": admission["identity_value"]},
        context(),
    )
    assert workbench.status_code == 200
    assert workbench.body["count"] == 2
    assert workbench.body["pagination"]["total_matching_count"] == 2
    assert workbench.body["module_summary"][0]["module"] == "spot"
    assert workbench.body["module_summary"][0]["live_enabled"] is True
    assert workbench.body["live_coinbase_orders_ran"] is True
    accepted_event = next(
        event for event in workbench.body["events"] if event["status"] == "accepted"
    )
    assert accepted_event["module"] == "spot"
    assert accepted_event["source"] == "admin_api_audit_log"
    assert accepted_event["endpoint"] == "/api/v1/orders"
    assert accepted_event["client_order_id"] == admission["identity_value"]
    assert accepted_event["product_id"] == "BTC-USDC"
    assert accepted_event["exchange_order_id"] == "exchange-order-live-1"
    assert accepted_event["exchange_order_id_evidence_only"] is True
    assert accepted_event["live_exchange_submitted"] is True
    assert accepted_event["live_coinbase_orders_ran"] is True
    assert accepted_event["admission_decision"]["status"] == "passed"
    assert accepted_event["admission_decision"]["allowed"] is True
    for module_alias in ("spot_operations", "orders"):
        alias_workbench = service.get_read_response(
            "/api/v1/admin/audit-workbench",
            {"module": module_alias, "client_order_id": admission["identity_value"]},
            context(),
        )
        assert alias_workbench.status_code == 200
        assert alias_workbench.body["count"] == 2
        assert alias_workbench.body["pagination"]["total_matching_count"] == 2
        assert alias_workbench.body["module_summary"][0]["module"] == "spot"
        assert alias_workbench.body["live_coinbase_orders_ran"] is True
        assert any(
            event["status"] == "accepted"
            and event["client_order_id"] == admission["identity_value"]
            and event["live_exchange_submitted"] is True
            for event in alias_workbench.body["events"]
        )


def test_admin_mvp_live_execution_rejects_unsuccessful_coinbase_create_order_response():
    rest_client = FakeRestClient(
        create_order_response={
            "success": False,
            "error_response": {
                "message": "The order configuration was invalid",
                "error_details": "quote_size is below the product minimum",
            },
        }
    )
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    body = limit_ioc_manual_order_body()
    record_live_service_decision(service)
    admission = first_manual_submit(service, body)
    record_proof_chain(service, admission)

    live_submit = service.submit_manual_order(
        body,
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert live_submit.status_code == 400
    assert live_submit.body["status"] == "rejected"
    assert live_submit.body["failure_stage"] == "coinbase_rest"
    assert live_submit.body["message"] == (
        "Coinbase order submission was not accepted: "
        "The order configuration was invalid; quote_size is below the product minimum"
    )
    assert live_submit.body["live_exchange_submitted"] is False
    assert live_submit.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == [
        {
            "client_order_id": admission["identity_value"],
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "sor_limit_ioc": {
                    "quote_size": "1.00",
                    "limit_price": "100000.00",
                },
            },
        }
    ]


@pytest.mark.parametrize(
    ("wallet_check_status", "wallet_available_notional_usdc"),
    [
        (None, None),
        ("passed", "0.50"),
    ],
)
def test_admin_mvp_live_execution_requires_backend_wallet_inventory_evidence(
    wallet_check_status: str | None,
    wallet_available_notional_usdc: str | None,
):
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(
        service,
        admission,
        wallet_check_status=wallet_check_status,
        wallet_available_notional_usdc=wallet_available_notional_usdc,
    )

    live_submit = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert live_submit.status_code == 400
    assert live_submit.body["status"] == "rejected"
    assert live_submit.body["failure_stage"] == "known_inventory_required"
    assert live_submit.body["live_exchange_submitted"] is False
    assert live_submit.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []


def test_admin_mvp_runner_matches_frontend_local_stack_contract():
    args = run_admin_api.parse_args(["--dev-token", "local-admin-token"])

    assert args.host == "127.0.0.1"
    assert args.port == 8787
    assert args.cors_origins == ("http://127.0.0.1:3000",)

    environ: dict[str, str] = {}
    applied = run_admin_api.apply_local_environment(args, environ=environ)

    assert environ[run_admin_api.AUTH_TOKEN_ENV] == "local-admin-token"
    assert environ[run_admin_api.CORS_ORIGINS_ENV] == "http://127.0.0.1:3000"
    assert environ[run_admin_api.ENVIRONMENT_ENV] == "local"
    assert applied[run_admin_api.AUTH_TOKEN_ENV] == "set_from_dev_token"


def test_admin_mvp_runner_enables_os_truststore_for_live_wallet_reads(monkeypatch):
    calls: list[bool] = []

    def fake_enable_os_truststore() -> str:
        calls.append(True)
        return "enabled"

    monkeypatch.setattr(
        run_admin_api,
        "enable_os_truststore",
        fake_enable_os_truststore,
    )
    args = run_admin_api.parse_args(["--dev-token", "local-admin-token"])

    applied = run_admin_api.apply_local_environment(args, environ={})

    assert calls == [True]
    assert applied[run_admin_api.OS_TRUSTSTORE_ENV] == "enabled"


def test_admin_mvp_declares_os_truststore_dependency_for_local_live_reads():
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    )

    assert "truststore>=0.10.4" in pyproject["project"]["dependencies"]


def test_admin_mvp_live_execution_env_requires_coinbase_specific_opt_in(monkeypatch):
    monkeypatch.delenv("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION", raising=False)
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED",
        raising=False,
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED", "true")

    assert live_coinbase_execution_enabled_from_env() is False

    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED", "true")

    assert live_coinbase_execution_enabled_from_env() is True
