"""Run a capped live Spot BUY through the enterprise Admin API route.

This tool is intentionally narrower than ``run_live_spot_usdc_smoke.py``:
it proves the Admin API manual-order route, auth/RBAC, live-admission stores,
shared command service, action-condition guard, durable submission audit, and
direct-order audit readback. It does not submit through a direct Coinbase
utility path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = str(PROJECT_ROOT)
sys.path = [path for path in sys.path if path != PROJECT_ROOT_PATH]
sys.path.insert(0, PROJECT_ROOT_PATH)

from coinbase.rest import RESTClient
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes.orders import (
    _idempotency_payload_hash,
    get_manual_order_live_execution_service,
)
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
from application.admin_api.live_execution import get_disabled_live_execution_service
from application.admin_api.models import AdminApiActor, ManualOrderRequest
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from business.spot_fill_backfill import backfill_fill_ledger_from_order_reports
from core.enums import (
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    AdminApiRole,
    OrderSide,
    OrderType,
    ProductType,
    SpotDirectOrderAuditStatus,
    SpotFillBackfillStatus,
)
from tools.run_live_spot_usdc_smoke import (
    _decimal,
    _first_previewable_product,
    _format_decimal,
    _load_live_usdc_products,
    _order_executed_notional,
    _poll_order,
)


SUMMARY_PREFIX = "ADMIN_API_MANUAL_SPOT_BUY_LIVE_SUMMARY "
DEFAULT_AUDIT_FILE = (
    Path("runtime_state") / "admin_api_manual_spot_buy_live.jsonl"
)
DEFAULT_STORE_DIR = Path("runtime_state") / "admin_api_manual_spot_buy_live"
MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
MAX_EXECUTED_NOTIONAL_USDC = Decimal("1.00")
DEFAULT_OPERATOR_INTENT = "manual_spot_buy_live_validation"


@dataclass(frozen=True)
class AdminApiManualSpotBuyPlan:
    run_id: str
    client_order_id: str
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    actor_id: str
    product_id: str
    quote_size: Decimal
    payload_hash: str
    approval_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    reconciliation_plan_id: str


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str))
        handle.write("\n")


def _format_usdc_cap(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:24]


def _client_order_id(prefix: str = "aslb") -> str:
    value = f"{prefix}-{_short_uuid()}"
    if len(value) > 40:
        raise ValueError("generated client_order_id exceeds Coinbase limit")
    return value


def _store_paths(store_dir: Path) -> dict[str, Path]:
    return {
        "approval": store_dir / "approvals.jsonl",
        "audit": store_dir / "audit.jsonl",
        "cap_guard": store_dir / "cap_guard.jsonl",
        "reconciliation": store_dir / "reconciliation.jsonl",
    }


def _configure_store_env(store_dir: Path) -> dict[str, Path]:
    paths = _store_paths(store_dir)
    os.environ["COINBASE_ADMIN_API_APPROVAL_LOG_PATH"] = str(paths["approval"])
    os.environ["COINBASE_ADMIN_API_AUDIT_LOG_PATH"] = str(paths["audit"])
    os.environ["COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH"] = str(paths["cap_guard"])
    os.environ["COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH"] = str(
        paths["reconciliation"]
    )
    return paths


def _product_metadata(product: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": ProductType.SPOT.value,
        "product_type": ProductType.SPOT.value,
        "base_currency": product.get("base_currency_id"),
        "quote_currency": product.get("quote_currency_id"),
        "base_increment": str(product.get("base_increment") or ""),
        "quote_increment": str(product.get("quote_increment") or ""),
        "price_increment": str(product.get("price_increment") or ""),
        "base_min_size": str(product.get("base_min_size") or ""),
        "quote_min_size": str(product.get("quote_min_size") or ""),
        "display_name": str(product.get("display_name") or ""),
        "status": str(product.get("status") or ""),
        "mid_price": str(product.get("price") or ""),
        "trading_disabled": bool(product.get("trading_disabled")),
    }


def _safe_action_guard_policy(max_submitted_notional: Decimal) -> dict[str, Any]:
    return {
        "wallet_available": {
            "enabled": True,
            "block_without_credentials": True,
        },
        "limits": [
            {
                "name": "admin_api_manual_live_spot_buy_cap",
                "enabled": True,
                "product_type": ProductType.SPOT.value,
                "side": OrderSide.BUY.value,
                "max_notional": _format_usdc_cap(max_submitted_notional),
                "phases": [ActionGuardPhase.PLANNING.value],
            }
        ],
    }


def _apply_runtime_config(
    *,
    product: Mapping[str, Any],
    max_submitted_notional: Decimal,
) -> None:
    import configuration

    product_id = str(product["product_id"])
    metadata = _product_metadata(product)
    configuration.API_KEY = os.environ.get("COINBASE_API_KEY")
    configuration.API_SECRET = os.environ.get("COINBASE_API_SECRET")
    configuration.PRODUCT_METADATA[product_id] = metadata
    if product_id not in configuration.SPOT_PRODUCT_IDS:
        configuration.SPOT_PRODUCT_IDS.append(product_id)
    configuration.ACTION_CONDITION_GUARDS.clear()
    configuration.ACTION_CONDITION_GUARDS.update(
        _safe_action_guard_policy(max_submitted_notional)
    )


def _manual_order_body(
    *,
    client_order_id: str,
    product_id: str,
    quote_size: Decimal,
) -> dict[str, Any]:
    return {
        "client_order_id": client_order_id,
        "product_id": product_id,
        "side": OrderSide.BUY.value,
        "order_type": OrderType.MARKET.value,
        "quote_size": _format_decimal(quote_size),
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


def append_manual_spot_buy_live_admission_chain(
    *,
    plan: AdminApiManualSpotBuyPlan,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    max_submitted_notional: Decimal,
    max_executed_notional: Decimal,
    expires_minutes: int = 5,
) -> None:
    now = datetime.now(timezone.utc)
    approval = AdminApiApprovalRecord(
        approval_id=plan.approval_id,
        expires_at=now + timedelta(minutes=expires_minutes),
        approved_by_actor_id="operator-live-approver",
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
            "Approved capped live Admin API manual Spot BUY validation."
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
            "submitted_notional_cap:"
            f"{_format_usdc_cap(max_submitted_notional)}"
        ),
        guard_policy_ref="action_condition_guard:manual_spot_buy_live",
        product_scope="USDC spot product scope",
        max_submitted_notional_usdc=_format_usdc_cap(max_submitted_notional),
        max_executed_notional_usdc=_format_usdc_cap(max_executed_notional),
        reason="Capped live Admin API manual Spot BUY validation.",
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
        reconciliation_policy_ref="post_submit_reconciliation:manual_spot_buy_live",
        product_scope="USDC spot product scope",
        exchange_submission_required=True,
        post_submit_reconciliation_required=True,
        retained_inventory_required=True,
        max_submitted_notional_usdc=_format_usdc_cap(max_submitted_notional),
        max_executed_notional_usdc=_format_usdc_cap(max_executed_notional),
        reason="Operator must read direct-order audit after live submission.",
    )
    reconciliation_store.append(reconciliation)


def _build_plan(
    *,
    product_id: str,
    quote_size: Decimal,
    actor_id: str,
    operator_intent: str,
) -> tuple[AdminApiManualSpotBuyPlan, dict[str, Any]]:
    run_id = _short_uuid()
    client_order_id = _client_order_id()
    idempotency_key = f"admin-spot-buy-{run_id}"
    correlation_id = f"corr-admin-spot-buy-{run_id}"
    body = _manual_order_body(
        client_order_id=client_order_id,
        product_id=product_id,
        quote_size=quote_size,
    )
    actor = AdminApiActor(actor_id=actor_id, roles=[AdminApiRole.TRADER])
    payload_hash = _payload_hash(
        actor=actor,
        operator_intent=operator_intent,
        body=body,
    )
    plan = AdminApiManualSpotBuyPlan(
        run_id=run_id,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor_id=actor_id,
        product_id=product_id,
        quote_size=quote_size,
        payload_hash=payload_hash,
        approval_id=f"approval-{run_id}",
        admission_audit_id=f"admission-{run_id}",
        cap_guard_decision_id=f"cap-{run_id}",
        reconciliation_plan_id=f"recon-{run_id}",
    )
    return plan, body


def _api_headers(plan: AdminApiManualSpotBuyPlan) -> dict[str, str]:
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


def build_manual_spot_buy_fill_backfill_order_report(
    *,
    plan: AdminApiManualSpotBuyPlan,
    exchange_order_id: str | None,
) -> dict[str, Any]:
    """Build the existing fill-backfill order-report shape for this run."""

    return {
        "source": "admin_api_manual_spot_buy_live",
        "source_file": str(DEFAULT_AUDIT_FILE),
        "run_id": plan.run_id,
        "config_id": None,
        "product_id": plan.product_id,
        "side": OrderSide.BUY.value,
        "client_order_id": plan.client_order_id,
        "exchange_order_id": exchange_order_id,
        "source_status": "admin_api_submitted",
        "submitted_notional_usdc": _format_decimal(plan.quote_size),
        "executed_notional_usdc": None,
    }


def _build_fill_ledger_repo() -> Any:
    from business.fill_ledger import FillLedgerRepository
    from database.database import PostgresDB

    return FillLedgerRepository(PostgresDB())


def _run_post_submit_fill_backfill(
    *,
    rest_client: Any,
    plan: AdminApiManualSpotBuyPlan,
    exchange_order_id: str | None,
) -> dict[str, Any]:
    """Run the existing REST-fill backfill path for this submitted order."""

    order_report = build_manual_spot_buy_fill_backfill_order_report(
        plan=plan,
        exchange_order_id=exchange_order_id,
    )
    backfill = backfill_fill_ledger_from_order_reports(
        fill_ledger_repo=_build_fill_ledger_repo(),
        rest_client=rest_client,
        order_reports=[order_report],
    )
    errored = [
        order
        for order in backfill.get("orders") or []
        if order.get("status") == SpotFillBackfillStatus.ERROR.value
    ]
    skipped = [
        order
        for order in backfill.get("orders") or []
        if order.get("status") == SpotFillBackfillStatus.SKIPPED.value
    ]
    return {
        "ran": True,
        "status": "failed" if errored else "passed",
        "shared_method": "business.spot_fill_backfill.backfill_fill_ledger_from_order_reports",
        "source": "tools.run_admin_api_manual_spot_buy_live",
        "client_order_id": plan.client_order_id,
        "exchange_order_id": exchange_order_id,
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "read_only_coinbase_requests": ["list_fills"],
        "live_coinbase_orders_ran": False,
        "coinbase_order_submitted": False,
        "order_state_mutated": False,
        "exchange_state_mutated": False,
        "fill_ledger_mutated": bool(backfill.get("total_appended_fill_count")),
        "errored_order_count": len(errored),
        "skipped_order_count": len(skipped),
        "fill_backfill": backfill,
    }


def _build_direct_order_audit(
    *,
    api_client: TestClient,
    headers: Mapping[str, str],
    client_order_id: str,
) -> dict[str, Any]:
    """Read direct-order audit evidence through the Admin API route."""

    response = api_client.get(
        f"/api/v1/spot/direct-orders/{client_order_id}/audit",
        headers=dict(headers),
        params={
            "include_events": "false",
            "include_fills": "false",
            "event_limit": "100",
            "fill_limit": "1000",
        },
    )
    payload = response.json()
    audit = payload.get("audit") if isinstance(payload, Mapping) else None
    if isinstance(audit, Mapping):
        result = dict(audit)
    else:
        result = {
            "status": "error",
            "error": "admin_api_direct_order_audit_missing_payload",
        }
    result["admin_api_route"] = (
        f"/api/v1/spot/direct-orders/{client_order_id}/audit"
    )
    result["admin_api_route_http_status_code"] = response.status_code
    result["admin_api_route_response_status"] = (
        payload.get("status") if isinstance(payload, Mapping) else None
    )
    result["admin_api_route_source"] = (
        payload.get("source") if isinstance(payload, Mapping) else None
    )
    result["admin_api_route_dashboard_dependency"] = (
        payload.get("dashboard_dependency") if isinstance(payload, Mapping) else None
    )
    return result


def _live_service_state_payload(state: Any) -> dict[str, Any]:
    status = getattr(state, "status", None)
    return {
        "required": bool(getattr(state, "required", False)),
        "present": bool(getattr(state, "present", False)),
        "status": getattr(status, "value", status),
        "source": getattr(state, "source", None),
        "missing_reason": getattr(state, "missing_reason", None),
    }


def _base_summary(
    *,
    plan: AdminApiManualSpotBuyPlan,
    store_dir: Path,
    product: Mapping[str, Any],
    preview: Mapping[str, Any],
    approved_live_orders: bool,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if approved_live_orders else "preflight_only",
        "approved_live_orders": approved_live_orders,
        "live_coinbase_orders_ran": False,
        "live_coinbase_execution": "not_run",
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "max_submitted_notional_usdc": _format_usdc_cap(
            MAX_SUBMITTED_NOTIONAL_USDC
        ),
        "max_executed_notional_usdc": _format_usdc_cap(MAX_EXECUTED_NOTIONAL_USDC),
        "product_id": plan.product_id,
        "quote_size": _format_decimal(plan.quote_size),
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
        "product_quote_min_size": str(product.get("quote_min_size") or ""),
        "product_quote_increment": str(product.get("quote_increment") or ""),
        "preview_best_bid": str(preview.get("best_bid") or ""),
        "preview_best_ask": str(preview.get("best_ask") or ""),
        "admin_api_route": "POST /api/v1/orders",
        "command_service_method": "place_manual_order",
        "direct_order_audit_command": (
            "python tools\\run_spot_direct_order_audit.py "
            f"--client-order-id {plan.client_order_id}"
        ),
    }


def _select_product_and_quote(
    *,
    requested_quote_size: Decimal,
) -> tuple[dict[str, Any], Decimal, dict[str, Any]]:
    client = RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        rate_limit_headers=True,
    )
    public_client = RESTClient(rate_limit_headers=True)
    product, quote_size, preview = _first_previewable_product(
        client,
        _load_live_usdc_products(public_client),
        requested_quote_size,
    )
    return product, quote_size, preview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight or run a capped live Coinbase Spot BUY through the "
            "enterprise Admin API POST /api/v1/orders route."
        )
    )
    parser.add_argument(
        "--approved-live-orders",
        action="store_true",
        help="Submit one real Coinbase market BUY through the Admin API route.",
    )
    parser.add_argument(
        "--quote-size",
        type=Decimal,
        default=MAX_EXECUTED_NOTIONAL_USDC,
        help="USDC quote size for the market BUY. Defaults to the executed cap.",
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
        help="Directory for this run's approval/audit/cap/reconciliation logs.",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=DEFAULT_AUDIT_FILE,
        help="Durable JSONL file to append the run summary.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the one-line machine-readable summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get(
        "COINBASE_API_SECRET"
    ):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")
    if args.quote_size <= 0:
        parser.error("--quote-size must be positive")
    if args.quote_size > MAX_EXECUTED_NOTIONAL_USDC:
        parser.error(
            "--quote-size exceeds the live executed-notional cap "
            f"{_format_usdc_cap(MAX_EXECUTED_NOTIONAL_USDC)} USDC"
        )

    os.environ.setdefault(
        "COINBASE_ADMIN_API_AUTH_MODE",
        AdminApiAuthMode.BOOTSTRAP_BEARER.value,
    )
    os.environ.setdefault("COINBASE_ADMIN_API_BEARER_TOKEN", "local-admin-token")
    os.environ["COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED"] = (
        "true" if args.approved_live_orders else "false"
    )

    store_paths = _configure_store_env(args.store_dir)
    product, quote_size, preview = _select_product_and_quote(
        requested_quote_size=args.quote_size,
    )
    if quote_size > MAX_EXECUTED_NOTIONAL_USDC:
        parser.error(
            "Selected product quote minimum exceeds the live executed-notional "
            f"cap: {_format_decimal(quote_size)} USDC > "
            f"{_format_usdc_cap(MAX_EXECUTED_NOTIONAL_USDC)} USDC"
        )
    if quote_size > MAX_SUBMITTED_NOTIONAL_USDC:
        parser.error(
            "Selected product quote size exceeds the live submitted-notional "
            f"cap: {_format_decimal(quote_size)} USDC > "
            f"{_format_usdc_cap(MAX_SUBMITTED_NOTIONAL_USDC)} USDC"
        )

    _apply_runtime_config(
        product=product,
        max_submitted_notional=MAX_SUBMITTED_NOTIONAL_USDC,
    )
    plan, body = _build_plan(
        product_id=str(product["product_id"]),
        quote_size=quote_size,
        actor_id=args.actor_id,
        operator_intent=args.operator_intent,
    )
    summary = _base_summary(
        plan=plan,
        store_dir=args.store_dir,
        product=product,
        preview=preview,
        approved_live_orders=args.approved_live_orders,
    )
    summary["store_paths"] = {key: str(value) for key, value in store_paths.items()}

    append_manual_spot_buy_live_admission_chain(
        plan=plan,
        approval_store=FileAdminApiApprovalStore(store_paths["approval"]),
        audit_store=FileAdminApiAuditStore(store_paths["audit"]),
        cap_guard_store=FileAdminApiCapGuardStore(store_paths["cap_guard"]),
        reconciliation_store=FileAdminApiReconciliationStore(
            store_paths["reconciliation"]
        ),
        max_submitted_notional=MAX_SUBMITTED_NOTIONAL_USDC,
        max_executed_notional=MAX_EXECUTED_NOTIONAL_USDC,
    )

    if not args.approved_live_orders:
        summary["status"] = "preflight_passed_no_live"
        summary["live_coinbase_execution"] = "not_run"
        _append_jsonl(args.audit_file, summary)
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True, default=str))
        return 0

    live_state = get_manual_order_live_execution_service().admission_state()
    summary["live_execution_service_state"] = _live_service_state_payload(
        live_state
    )
    if (
        live_state.status != AdminApiLiveExecutionStatus.COMPLETED
        or live_state.missing_reason
    ):
        summary["status"] = "blocked_before_coinbase"
        summary["failure_stage"] = "live_execution_service"
        summary["message"] = live_state.missing_reason
        _append_jsonl(args.audit_file, summary)
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True, default=str))
        return 1

    api_client = TestClient(create_app())
    request_headers = _api_headers(plan)
    response = api_client.post(
        "/api/v1/orders",
        headers=request_headers,
        json=body,
    )
    payload = response.json()
    summary["http_status_code"] = response.status_code
    summary["admin_api_response"] = payload if not args.summary_only else {
        "status": payload.get("status"),
        "failure_stage": payload.get("failure_stage"),
        "client_order_id": payload.get("client_order_id"),
        "coinbase_order_id": payload.get("coinbase_order_id"),
        "live_exchange_submitted": payload.get("live_exchange_submitted"),
        "submission_event_recorded": payload.get("submission_event_recorded"),
    }

    live_submitted = bool(payload.get("live_exchange_submitted"))
    summary["live_coinbase_orders_ran"] = live_submitted
    summary["live_coinbase_execution"] = "submitted" if live_submitted else "not_run"
    summary["submitted_notional_usdc"] = _format_decimal(quote_size) if live_submitted else "0"
    order_id = payload.get("coinbase_order_id")
    summary["coinbase_order_id"] = order_id

    if not live_submitted or response.status_code != 200:
        summary["status"] = "admin_api_rejected_before_coinbase"
        summary["failure_stage"] = payload.get("failure_stage")
        summary["message"] = payload.get("message")
        _append_jsonl(args.audit_file, summary)
        print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True, default=str))
        return 1

    client = RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        rate_limit_headers=True,
    )
    polled_order = _poll_order(client, order_id) if order_id else {}
    filled_size, executed_notional = _order_executed_notional(
        client,
        plan.product_id,
        order_id,
        polled_order,
    )
    summary["order_status"] = str(polled_order.get("status") or "")
    summary["base_size"] = _format_decimal(filled_size)
    summary["executed_notional_usdc"] = _format_decimal(executed_notional)

    try:
        post_submit_reconciliation = _run_post_submit_fill_backfill(
            rest_client=client,
            plan=plan,
            exchange_order_id=order_id,
        )
    except Exception as exc:
        post_submit_reconciliation = {
            "ran": True,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "shared_method": (
                "business.spot_fill_backfill.backfill_fill_ledger_from_order_reports"
            ),
            "read_only_coinbase_requests": ["list_fills"],
            "live_coinbase_orders_ran": False,
        }
    summary["post_submit_reconciliation_execution"] = post_submit_reconciliation

    try:
        direct_audit = _build_direct_order_audit(
            api_client=api_client,
            headers=request_headers,
            client_order_id=plan.client_order_id,
        )
    except Exception as exc:
        direct_audit = {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    summary["direct_order_audit"] = direct_audit

    failures: list[str] = []
    if executed_notional > MAX_EXECUTED_NOTIONAL_USDC:
        failures.append(
            "executed_notional_exceeded_cap:"
            f"{_format_decimal(executed_notional)}"
        )
    if _decimal(summary["submitted_notional_usdc"]) > MAX_SUBMITTED_NOTIONAL_USDC:
        failures.append(
            "submitted_notional_exceeded_cap:"
            f"{summary['submitted_notional_usdc']}"
        )
    if direct_audit.get("status") != SpotDirectOrderAuditStatus.FOUND.value:
        failures.append("direct_order_audit_missing")
    if direct_audit.get("admin_api_route_http_status_code") != 200:
        failures.append("admin_api_direct_order_audit_route_failed")
    if direct_audit.get("admin_api_route_dashboard_dependency") is not False:
        failures.append("admin_api_direct_order_audit_uses_dashboard_dependency")
    if post_submit_reconciliation.get("status") != "passed":
        failures.append("post_submit_reconciliation_execution_failed")
    if (
        executed_notional > 0
        and post_submit_reconciliation.get("fill_backfill", {}).get(
            "total_fetched_fill_count",
            0,
        )
        <= 0
    ):
        failures.append("post_submit_reconciliation_no_rest_fills")

    summary["failures"] = failures
    summary["status"] = "passed" if not failures else "failed"
    _append_jsonl(args.audit_file, summary)
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
