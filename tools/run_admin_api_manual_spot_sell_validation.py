"""Validate Admin API manual Spot SELL authority without live Coinbase orders.

This runner proves the enterprise Admin API route, exact live-admission chain,
shared command service, action-condition guard, planned-budget hook, and spot
SELL lot-authority hook on ``POST /api/v1/orders``. It intentionally injects a
fake REST client and never calls Coinbase.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = str(PROJECT_ROOT)
sys.path = [path for path in sys.path if path != PROJECT_ROOT_PATH]
sys.path.insert(0, PROJECT_ROOT_PATH)

from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import orders as order_routes
from api.v1.routes.orders import _idempotency_payload_hash
from application.admin_api.approval import (
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
    evaluate_command_live_admission,
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
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import (
    get_configured_live_execution_service,
    get_disabled_live_execution_service,
)
from application.admin_api.models import AdminApiActor, ManualOrderRequest
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from business.spot_inventory_authority import evaluate_spot_sell_lot_authority
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiPermission,
    AdminApiRole,
    InventoryAuthorityStatus,
    OrderSide,
    OrderType,
    ProductType,
)


SUMMARY_PREFIX = "ADMIN_API_MANUAL_SPOT_SELL_VALIDATION_SUMMARY "
DEFAULT_AUDIT_FILE = (
    Path("runtime_state") / "admin_api_manual_spot_sell_validation.jsonl"
)
DEFAULT_STORE_DIR = Path("runtime_state") / "admin_api_manual_spot_sell_validation"
DEFAULT_OPERATOR_INTENT = "manual_spot_sell_authority_validation"
DEFAULT_PRODUCT_ID = "BTC-USDC"
DEFAULT_BASE_SIZE = Decimal("0.01")
DEFAULT_LIMIT_PRICE = Decimal("200.00")
DEFAULT_BASELINE_QUANTITY = Decimal("0.05")
DEFAULT_BASELINE_ENTRY_PRICE = Decimal("100.00")
DEFAULT_PLANNED_BASE_COMMITMENT = Decimal("0.01")
DEFAULT_WALLET_AVAILABLE_BASE = Decimal("0.10")
MAX_VALIDATED_NOTIONAL_USDC = Decimal("3.10")


@dataclass(frozen=True)
class AdminApiManualSpotSellValidationPlan:
    run_id: str
    client_order_id: str
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    actor_id: str
    product_id: str
    base_size: Decimal
    limit_price: Decimal
    validated_notional_usdc: Decimal
    payload_hash: str
    approval_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    reconciliation_plan_id: str


class _FakeRestClient:
    def __init__(self, *, order_id: str) -> None:
        self.order_id = order_id
        self.create_order_calls: list[dict[str, Any]] = []

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.create_order_calls.append(dict(kwargs))
        return {
            "success": True,
            "success_response": {"order_id": self.order_id},
        }


class _FakeOrderEventPublisher:
    enabled = True

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish_event(self, **kwargs: Any) -> bool:
        self.events.append(dict(kwargs))
        return True


class _AdmittingRuntimeController:
    @contextmanager
    def track_inflight(self, _category: str):
        yield


class _EmptyFillLedgerRepo:
    def get_fills_by_product(self, _product_id: str) -> list[Any]:
        return []

    def get_fills_by_instrument(self, _instrument: str) -> list[Any]:
        return []


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str))
        handle.write("\n")


def _format_decimal(value: Decimal | float | str) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _format_usdc_cap(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:24]


def _client_order_id(prefix: str = "assv") -> str:
    value = f"{prefix}-{_short_uuid()}"
    if len(value) > 40:
        raise ValueError("generated client_order_id exceeds Coinbase limit")
    return value


def _currency_pair(product_id: str) -> tuple[str, str]:
    parts = [part.strip().upper() for part in product_id.split("-") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return product_id.upper(), "USDC"


def _store_paths(store_dir: Path) -> dict[str, Path]:
    return {
        "idempotency": store_dir / "idempotency.jsonl",
        "approval": store_dir / "approvals.jsonl",
        "audit": store_dir / "audit.jsonl",
        "cap_guard": store_dir / "cap_guard.jsonl",
        "reconciliation": store_dir / "reconciliation.jsonl",
    }


def _configure_store_env(store_dir: Path) -> dict[str, Path]:
    paths = _store_paths(store_dir)
    os.environ["COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH"] = str(
        paths["idempotency"]
    )
    os.environ["COINBASE_ADMIN_API_APPROVAL_LOG_PATH"] = str(paths["approval"])
    os.environ["COINBASE_ADMIN_API_AUDIT_LOG_PATH"] = str(paths["audit"])
    os.environ["COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH"] = str(paths["cap_guard"])
    os.environ["COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH"] = str(
        paths["reconciliation"]
    )
    return paths


def _product_metadata(product_id: str, *, limit_price: Decimal) -> dict[str, Any]:
    base_currency, quote_currency = _currency_pair(product_id)
    return {
        "type": ProductType.SPOT.value,
        "product_type": ProductType.SPOT.value,
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "0.01",
        "display_name": product_id,
        "status": "validation_only",
        "mid_price": _format_decimal(limit_price),
        "trading_disabled": False,
    }


def _safe_action_guard_policy(max_validated_notional: Decimal) -> dict[str, Any]:
    return {
        ActionConditionType.WALLET_AVAILABLE.value: {
            "enabled": True,
            "block_without_credentials": True,
        },
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
            "enabled": True,
            "phases": [ActionGuardPhase.PLANNING.value],
        },
        "limits": [
            {
                "name": "admin_api_manual_spot_sell_validation_cap",
                "enabled": True,
                "product_type": ProductType.SPOT.value,
                "side": OrderSide.SELL.value,
                "max_notional": _format_usdc_cap(max_validated_notional),
                "phases": [ActionGuardPhase.PLANNING.value],
            }
        ],
    }


def _inventory_baseline(
    *,
    product_id: str,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
) -> list[dict[str, Any]]:
    return [
        {
            "product_id": product_id,
            "side": OrderSide.BUY.value,
            "quantity": _format_decimal(baseline_quantity),
            "remaining_quantity": _format_decimal(baseline_quantity),
            "entry_price": _format_decimal(baseline_entry_price),
            "source_id": "admin-api-manual-spot-sell-validation",
        }
    ]


def _apply_runtime_config(
    *,
    product_id: str,
    limit_price: Decimal,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
    max_validated_notional: Decimal,
) -> None:
    import calculation.size_validation as size_validation
    import configuration

    metadata = _product_metadata(product_id, limit_price=limit_price)
    configuration.API_KEY = os.environ.get("COINBASE_API_KEY", "validation-key")
    configuration.API_SECRET = os.environ.get(
        "COINBASE_API_SECRET",
        "validation-secret",
    )
    configuration.PRODUCT_METADATA[product_id] = metadata
    size_validation.PRODUCT_METADATA[product_id] = metadata
    if product_id not in configuration.SPOT_PRODUCT_IDS:
        configuration.SPOT_PRODUCT_IDS.append(product_id)
    configuration.SPOT_INVENTORY_BASELINES = _inventory_baseline(
        product_id=product_id,
        baseline_quantity=baseline_quantity,
        baseline_entry_price=baseline_entry_price,
    )
    configuration.ACTION_CONDITION_GUARDS.clear()
    configuration.ACTION_CONDITION_GUARDS.update(
        _safe_action_guard_policy(max_validated_notional)
    )


def _install_validation_wallet_fetcher(
    *,
    product_id: str,
    wallet_available_base: Decimal,
) -> None:
    import core.action_condition_guard as guard_module

    base_currency, _quote_currency = _currency_pair(product_id)
    balance = _format_decimal(wallet_available_base)
    guard_module.fetch_account_wallets = lambda: {
        base_currency: {"available_balance": {"value": balance}}
    }


def _manual_order_body(
    *,
    client_order_id: str,
    product_id: str,
    base_size: Decimal,
    limit_price: Decimal,
) -> dict[str, Any]:
    return {
        "client_order_id": client_order_id,
        "product_id": product_id,
        "side": OrderSide.SELL.value,
        "order_type": OrderType.LIMIT.value,
        "base_size": _format_decimal(base_size),
        "limit_price": _format_usdc_cap(limit_price),
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def _payload_hash(
    *,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict[str, Any],
) -> str:
    return _idempotency_payload_hash(
        endpoint="POST /api/v1/orders",
        actor=actor,
        operator_intent=operator_intent,
        body=ManualOrderRequest.model_validate(body).model_dump(mode="json"),
    )


def _build_plan(
    *,
    product_id: str,
    base_size: Decimal,
    limit_price: Decimal,
    actor_id: str,
    operator_intent: str,
) -> tuple[AdminApiManualSpotSellValidationPlan, dict[str, Any]]:
    run_id = _short_uuid()
    client_order_id = _client_order_id()
    idempotency_key = f"admin-spot-sell-validation-{run_id}"
    correlation_id = f"corr-admin-spot-sell-validation-{run_id}"
    validated_notional = base_size * limit_price
    body = _manual_order_body(
        client_order_id=client_order_id,
        product_id=product_id,
        base_size=base_size,
        limit_price=limit_price,
    )
    actor = AdminApiActor(actor_id=actor_id, roles=[AdminApiRole.TRADER])
    payload_hash = _payload_hash(
        actor=actor,
        operator_intent=operator_intent,
        body=body,
    )
    plan = AdminApiManualSpotSellValidationPlan(
        run_id=run_id,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor_id=actor_id,
        product_id=product_id,
        base_size=base_size,
        limit_price=limit_price,
        validated_notional_usdc=validated_notional,
        payload_hash=payload_hash,
        approval_id=f"approval-{run_id}",
        admission_audit_id=f"admission-{run_id}",
        cap_guard_decision_id=f"cap-{run_id}",
        reconciliation_plan_id=f"recon-{run_id}",
    )
    return plan, body


def _api_headers(plan: AdminApiManualSpotSellValidationPlan) -> dict[str, str]:
    token = os.environ.get("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": plan.idempotency_key,
        "X-Correlation-Id": plan.correlation_id,
        "X-Operator-Intent": plan.operator_intent,
        "X-Admin-Actor": plan.actor_id,
        "X-Admin-Roles": AdminApiRole.TRADER.value,
    }
    csrf_token = os.environ.get("COINBASE_ADMIN_API_CSRF_TOKEN")
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    return headers


def append_manual_spot_sell_validation_admission_chain(
    *,
    plan: AdminApiManualSpotSellValidationPlan,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    max_validated_notional: Decimal,
    expires_minutes: int = 5,
) -> None:
    now = datetime.now(timezone.utc)
    approval = AdminApiApprovalRecord(
        approval_id=plan.approval_id,
        expires_at=now + timedelta(minutes=expires_minutes),
        approved_by_actor_id="operator-validation-approver",
        requested_by_actor_id=plan.actor_id,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=plan.client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        operator_intent=plan.operator_intent,
        idempotency_key=plan.idempotency_key,
        payload_hash=plan.payload_hash,
        cap_guard_decision_ref=plan.cap_guard_decision_id,
        reconciliation_plan_ref=plan.reconciliation_plan_id,
        approval_reason=(
            "Approved no-live Admin API manual Spot SELL validation."
        ),
    )
    approval_store.append(approval)

    preflight_decision = evaluate_command_live_admission(
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
        live_execution_service=get_disabled_live_execution_service(),
        manual_live_acknowledgement=True,
    )
    audit_event = AdminApiAuditEvent(
        audit_id=plan.admission_audit_id,
        actor_id=plan.actor_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        endpoint="POST /api/v1/orders",
        request_id=plan.correlation_id,
        operator_intent=plan.operator_intent,
        idempotency_key=plan.idempotency_key,
        approval_id=approval.approval_id,
        client_order_id=plan.client_order_id,
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        failure_stage="approval",
        message="Prior exact Admin API live-admission audit proof.",
        admission_decision=preflight_decision,
        approval_cap_guard_decision_ref=approval.cap_guard_decision_ref,
        approval_reconciliation_plan_ref=approval.reconciliation_plan_ref,
    )
    audit_store.append(audit_event)

    cap_guard = CapGuardDecisionRecord(
        decision_id=plan.cap_guard_decision_id,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=plan.client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id=plan.actor_id,
        operator_intent=plan.operator_intent,
        idempotency_key=plan.idempotency_key,
        payload_hash=plan.payload_hash,
        approval_snapshot_id=approval.approval_id,
        admission_audit_id=audit_event.audit_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        cap_policy_ref=(
            "validated_notional_cap:"
            f"{_format_usdc_cap(max_validated_notional)}"
        ),
        guard_policy_ref=(
            "action_condition_guard:manual_spot_sell_validation"
        ),
        product_scope="USDC spot SELL validation scope",
        max_submitted_notional_usdc="0.00",
        max_executed_notional_usdc="0.00",
        reason="No-live Admin API manual Spot SELL validation.",
    )
    cap_guard_store.append(cap_guard)

    reconciliation = ReconciliationPlanRecord(
        plan_id=plan.reconciliation_plan_id,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=plan.client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id=plan.actor_id,
        operator_intent=plan.operator_intent,
        idempotency_key=plan.idempotency_key,
        payload_hash=plan.payload_hash,
        approval_snapshot_id=approval.approval_id,
        admission_audit_id=audit_event.audit_id,
        cap_guard_decision_id=cap_guard.decision_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        reconciliation_policy_ref=(
            "post_submit_reconciliation:manual_spot_sell_validation"
        ),
        product_scope="USDC spot SELL validation scope",
        exchange_submission_required=False,
        post_submit_reconciliation_required=True,
        retained_inventory_required=True,
        max_submitted_notional_usdc="0.00",
        max_executed_notional_usdc="0.00",
        reason=(
            "Validation uses fake REST and proves backend guard wiring without "
            "mutating Coinbase state."
        ),
    )
    reconciliation_store.append(reconciliation)


def _build_lot_authority_evaluator(
    *,
    product_id: str,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
    calls: list[dict[str, Any]],
):
    inventory_baselines = _inventory_baseline(
        product_id=product_id,
        baseline_quantity=baseline_quantity,
        baseline_entry_price=baseline_entry_price,
    )
    fill_ledger_repo = _EmptyFillLedgerRepo()

    def _evaluate_spot_lot_authority(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return evaluate_spot_sell_lot_authority(
            product_id=kwargs.get("product_id", ""),
            side=kwargs.get("side", ""),
            size=kwargs.get("size"),
            limit_price=kwargs.get("limit_price"),
            fill_ledger_repo=fill_ledger_repo,
            inventory_baselines=inventory_baselines,
        ).to_dict()

    return _evaluate_spot_lot_authority


def _build_validation_command_service(
    *,
    product_id: str,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
    planned_base_commitment: Decimal,
    fake_order_id: str,
) -> tuple[AdminApiCommandService, _FakeRestClient, _FakeOrderEventPublisher, list[dict[str, Any]]]:
    fake_rest_client = _FakeRestClient(order_id=fake_order_id)
    fake_publisher = _FakeOrderEventPublisher()
    lot_authority_calls: list[dict[str, Any]] = []
    base_currency, _quote_currency = _currency_pair(product_id)
    planned_budget = {base_currency: float(planned_base_commitment)}

    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=fake_rest_client,
            rest_client_available=True,
            runtime_controller_factory=_AdmittingRuntimeController,
            order_event_publisher_getter=lambda: fake_publisher,
            planned_budget_fetcher=lambda: dict(planned_budget),
            lot_authority_evaluator_getter=lambda: _build_lot_authority_evaluator(
                product_id=product_id,
                baseline_quantity=baseline_quantity,
                baseline_entry_price=baseline_entry_price,
                calls=lot_authority_calls,
            ),
        )
    )
    return service, fake_rest_client, fake_publisher, lot_authority_calls


def _base_summary(
    *,
    plan: AdminApiManualSpotSellValidationPlan,
    store_dir: Path,
    max_validated_notional: Decimal,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
    planned_base_commitment: Decimal,
    wallet_available_base: Decimal,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "no_live_fake_rest_validation",
        "approved_live_orders": False,
        "live_coinbase_orders_ran": False,
        "live_coinbase_execution": "not_run_fake_rest_only",
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "validated_notional_usdc": _format_usdc_cap(
            plan.validated_notional_usdc
        ),
        "max_validated_notional_usdc": _format_usdc_cap(max_validated_notional),
        "product_id": plan.product_id,
        "base_size": _format_decimal(plan.base_size),
        "limit_price": _format_usdc_cap(plan.limit_price),
        "baseline_quantity": _format_decimal(baseline_quantity),
        "baseline_entry_price": _format_usdc_cap(baseline_entry_price),
        "planned_base_commitment": _format_decimal(planned_base_commitment),
        "wallet_available_base": _format_decimal(wallet_available_base),
        "client_order_id": plan.client_order_id,
        "idempotency_key": plan.idempotency_key,
        "correlation_id": plan.correlation_id,
        "operator_intent": plan.operator_intent,
        "payload_hash": plan.payload_hash,
        "approval_id": plan.approval_id,
        "admission_audit_id": plan.admission_audit_id,
        "cap_guard_decision_id": plan.cap_guard_decision_id,
        "reconciliation_plan_id": plan.reconciliation_plan_id,
        "store_dir": str(store_dir),
        "admin_api_route": "POST /api/v1/orders",
        "command_service_method": "place_manual_order",
        "backend_path_validated": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "coinbase_rest_client": "fake_validation_client",
    }


def run_manual_spot_sell_validation(
    *,
    product_id: str,
    base_size: Decimal,
    limit_price: Decimal,
    baseline_quantity: Decimal,
    baseline_entry_price: Decimal,
    planned_base_commitment: Decimal,
    wallet_available_base: Decimal,
    max_validated_notional: Decimal,
    actor_id: str,
    operator_intent: str,
    store_dir: Path,
    audit_file: Path,
    summary_only: bool = False,
) -> dict[str, Any]:
    if base_size <= 0:
        raise ValueError("base_size must be positive")
    if limit_price <= 0:
        raise ValueError("limit_price must be positive")
    validated_notional = base_size * limit_price
    if validated_notional > max_validated_notional:
        raise ValueError(
            "validated notional exceeds cap: "
            f"{_format_usdc_cap(validated_notional)} USDC > "
            f"{_format_usdc_cap(max_validated_notional)} USDC"
        )

    os.environ.setdefault(
        "COINBASE_ADMIN_API_AUTH_MODE",
        AdminApiAuthMode.BOOTSTRAP_BEARER.value,
    )
    os.environ.setdefault("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    os.environ["COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED"] = "false"

    store_paths = _configure_store_env(store_dir)
    _apply_runtime_config(
        product_id=product_id,
        limit_price=limit_price,
        baseline_quantity=baseline_quantity,
        baseline_entry_price=baseline_entry_price,
        max_validated_notional=max_validated_notional,
    )
    _install_validation_wallet_fetcher(
        product_id=product_id,
        wallet_available_base=wallet_available_base,
    )
    plan, body = _build_plan(
        product_id=product_id,
        base_size=base_size,
        limit_price=limit_price,
        actor_id=actor_id,
        operator_intent=operator_intent,
    )
    summary = _base_summary(
        plan=plan,
        store_dir=store_dir,
        max_validated_notional=max_validated_notional,
        baseline_quantity=baseline_quantity,
        baseline_entry_price=baseline_entry_price,
        planned_base_commitment=planned_base_commitment,
        wallet_available_base=wallet_available_base,
    )
    summary["store_paths"] = {key: str(value) for key, value in store_paths.items()}

    approval_store = FileAdminApiApprovalStore(store_paths["approval"])
    audit_store = FileAdminApiAuditStore(store_paths["audit"])
    cap_guard_store = FileAdminApiCapGuardStore(store_paths["cap_guard"])
    reconciliation_store = FileAdminApiReconciliationStore(
        store_paths["reconciliation"]
    )
    append_manual_spot_sell_validation_admission_chain(
        plan=plan,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        max_validated_notional=max_validated_notional,
    )

    service, fake_rest_client, fake_publisher, lot_authority_calls = (
        _build_validation_command_service(
            product_id=product_id,
            baseline_quantity=baseline_quantity,
            baseline_entry_price=baseline_entry_price,
            planned_base_commitment=planned_base_commitment,
            fake_order_id=f"fake-spot-sell-validation-{plan.run_id}",
        )
    )
    app = create_app()
    app.dependency_overrides[order_routes.get_idempotency_store] = (
        lambda: FileIdempotencyStore(store_paths["idempotency"])
    )
    app.dependency_overrides[order_routes.get_command_service] = lambda: service
    app.dependency_overrides[order_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[order_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[order_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[order_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[
        order_routes.get_manual_order_live_execution_service
    ] = lambda: get_configured_live_execution_service(
        enabled=True,
        rest_client_available=True,
        order_event_stream_available=True,
    )

    api_client = TestClient(app)
    response = api_client.post(
        "/api/v1/orders",
        headers=_api_headers(plan),
        json=body,
    )
    payload = response.json()
    summary["http_status_code"] = response.status_code
    summary["admin_api_response"] = payload if not summary_only else {
        "status": payload.get("status"),
        "failure_stage": payload.get("failure_stage"),
        "client_order_id": payload.get("client_order_id"),
        "coinbase_order_id": payload.get("coinbase_order_id"),
        "live_exchange_submitted": payload.get("live_exchange_submitted"),
        "submission_event_recorded": payload.get("submission_event_recorded"),
    }
    summary["fake_rest_boundary_reached"] = bool(
        fake_rest_client.create_order_calls
    )
    summary["fake_rest_create_order_calls"] = fake_rest_client.create_order_calls
    summary["submission_event_recorded"] = bool(fake_publisher.events)
    summary["fake_order_event_stream_events"] = fake_publisher.events
    summary["lot_authority_evaluator_calls"] = lot_authority_calls
    summary["lot_authority_evaluator_call_count"] = len(lot_authority_calls)

    post_submit = {}
    if isinstance(payload.get("data"), Mapping):
        post_submit = payload["data"].get("post_submit_reconciliation") or {}
    admission = payload.get("admission_decision") or {}
    failures: list[str] = []
    if response.status_code != 200:
        failures.append(f"admin_api_route_status:{response.status_code}")
    if payload.get("status") != AdminApiCommandStatus.ACCEPTED.value:
        failures.append(f"admin_api_status:{payload.get('status')}")
    if payload.get("live_exchange_submitted") is not True:
        failures.append("shared_command_service_did_not_reach_fake_rest")
    if len(fake_rest_client.create_order_calls) != 1:
        failures.append("fake_rest_boundary_call_count_mismatch")
    if len(lot_authority_calls) != 1:
        failures.append("lot_authority_evaluator_not_called_once")
    if admission.get("status") != AdminApiGateStatus.PASSED.value:
        failures.append(f"admission_status:{admission.get('status')}")
    if admission.get("allowed") is not True:
        failures.append("admission_not_allowed")
    if post_submit.get("browser_authority") != "display_only":
        failures.append("browser_authority_not_display_only")
    if post_submit.get("bff_authority") != "forward_only_no_execution":
        failures.append("bff_authority_not_forward_only")
    for call in fake_rest_client.create_order_calls:
        if call.get("side") != OrderSide.SELL.value:
            failures.append("fake_rest_side_not_sell")
        config = call.get("order_configuration") or {}
        if "limit_limit_gtc" not in config:
            failures.append("fake_rest_order_configuration_not_limit_gtc")
    if lot_authority_calls:
        call = lot_authority_calls[0]
        if call.get("side") != OrderSide.SELL.value:
            failures.append("lot_authority_side_not_sell")
        if call.get("product_id") != product_id:
            failures.append("lot_authority_product_mismatch")

    summary["failures"] = failures
    summary["status"] = "passed" if not failures else "failed"
    _append_jsonl(audit_file, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the Admin API manual Spot SELL authority path with fake "
            "REST. This command never places live Coinbase orders."
        )
    )
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    parser.add_argument("--base-size", type=Decimal, default=DEFAULT_BASE_SIZE)
    parser.add_argument("--limit-price", type=Decimal, default=DEFAULT_LIMIT_PRICE)
    parser.add_argument(
        "--baseline-quantity",
        type=Decimal,
        default=DEFAULT_BASELINE_QUANTITY,
    )
    parser.add_argument(
        "--baseline-entry-price",
        type=Decimal,
        default=DEFAULT_BASELINE_ENTRY_PRICE,
    )
    parser.add_argument(
        "--planned-base-commitment",
        type=Decimal,
        default=DEFAULT_PLANNED_BASE_COMMITMENT,
    )
    parser.add_argument(
        "--wallet-available-base",
        type=Decimal,
        default=DEFAULT_WALLET_AVAILABLE_BASE,
    )
    parser.add_argument(
        "--max-validated-notional",
        type=Decimal,
        default=MAX_VALIDATED_NOTIONAL_USDC,
    )
    parser.add_argument(
        "--actor-id",
        default="operator-001",
        help="Bootstrap Admin API actor id used for the route request.",
    )
    parser.add_argument(
        "--operator-intent",
        default=DEFAULT_OPERATOR_INTENT,
        help="Operator intent header and approval binding.",
    )
    parser.add_argument(
        "--store-dir",
        type=Path,
        default=DEFAULT_STORE_DIR,
        help="Directory for this run's isolated admission stores.",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=DEFAULT_AUDIT_FILE,
        help="Durable JSONL file to append the validation summary.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Trim the embedded Admin API response in the printed summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_manual_spot_sell_validation(
            product_id=args.product_id,
            base_size=args.base_size,
            limit_price=args.limit_price,
            baseline_quantity=args.baseline_quantity,
            baseline_entry_price=args.baseline_entry_price,
            planned_base_commitment=args.planned_base_commitment,
            wallet_available_base=args.wallet_available_base,
            max_validated_notional=args.max_validated_notional,
            actor_id=args.actor_id,
            operator_intent=args.operator_intent,
            store_dir=args.store_dir,
            audit_file=args.audit_file,
            summary_only=args.summary_only,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True, default=str))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
