"""Lightweight WebSocket server for trading engine dashboard.

Provides real-time order updates, engine status, and manual order placement.
Runs as a separate thread alongside the main trading engine.

Usage:
    python dashboard_server.py  # Starts on ws://localhost:8765
    Then open dashboard.html in browser
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread, Lock
from queue import Queue
from typing import Set, Dict, Any, Optional, Mapping
import websockets
from websockets.server import WebSocketServerProtocol

# Import REST client for order placement
try:
    from configuration import REST_CLIENT, rest_get_products
    REST_CLIENT_AVAILABLE = True
except ImportError:
    REST_CLIENT_AVAILABLE = False

# Use custom logging service
from logging_service import get_logger
from core.action_condition_guard import (
    ActionConditionGuard,
    fetch_account_wallets,
    get_action_condition_guard_policy,
    normalize_action_guard_known_inventory_policy,
    normalize_action_guard_wallet_policy,
    rest_credentials_configured,
)
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    EngineState,
    EventSourceChannel,
    EventStreamType,
    FollowUpRevealDirection,
    AdminApiRole,
    InventoryCostBasisStatus,
    InventoryLotSource,
    OrderStatus,
    OrderSide,
    OrderType,
    ProductCapability,
    ProductCapabilityMode,
    ProductType,
    RepricingReferenceSource,
    StealthOrderStatus,
)
from core.models import RepricingPolicy
from core.product_capability import evaluate_product_capability
from core.exceptions import WebSocketMessageError, OrderCreationError, CoinbaseAPIError
from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    EngineNotAdmittingError,
    get_runtime_controller,
)
from database.database import PostgresDB
from calculation.formatter import safe_float
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
    cancel_response_to_dashboard_payload,
    manual_order_response_to_dashboard_payload,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
)

# Message types that *originate* new work and are gated on EngineState.RUNNING.
# Cancellations, queries, and admin commands are intentionally excluded so the
# engine remains controllable and existing positions can be wound down while
# paused or draining.
_ORIGINATING_MSG_TYPES = frozenset({
    "place_order",
    "create_stealth_order",
    "create_parent_order",
    "reprice_now_stealth_order",
    "move_revealed_stealth_order",
    "move_order",
    "premark_move",
    "import_stealth_orders",
    "place_hotpoint_test_order",
})

# Stealth-order statuses considered "active" for export. Derived from the
# canonical StealthOrderStatus enum by excluding terminal states (EXECUTED,
# CANCELLED) — anything else represents a live order whose configuration we
# want to be able to back up and replay. REVEALED is included: the root is
# placed on the exchange but not yet filled, so re-importing after a wipe
# must recreate it. Hard-coding string literals here previously caused two
# regressions: invented values ("EXECUTING", "PARTIAL") that don't exist in
# the enum, and the omission of "REVEALED" — which silently dropped any
# revealed root from the export.
_TERMINAL_STEALTH_STATUSES = frozenset({
    StealthOrderStatus.EXECUTED.value,
    StealthOrderStatus.CANCELLED.value,
})
_ACTIVE_STEALTH_STATUSES = frozenset(
    s.value for s in StealthOrderStatus if s.value not in _TERMINAL_STEALTH_STATUSES
)

# Fields on the in-memory stealth order that map back to create_stealth_order
# kwargs (keys exactly match what the existing "create_stealth_order" message
# handler expects in `data["order"]`). Listing them explicitly avoids leaking
# runtime-only state (revealed_orders, executed_size, anchor state, etc.) into
# the export payload.
_EXPORT_FIELDS = (
    "product_id",
    "side",
    "total_size",
    "limit_price",
    "reveal_condition_json",       # → reveal_condition
    "reveal_pricing_policy",
    "sizing_strategy_json",        # → sizing_strategy
    "follow_up_reveal_direction",
    "notes",
    "max_order_replacements",
    "target_movement",
    "target_movement_type",
    "allow_partial_fills",
    "anchor_repricing_policy_json",  # → anchor_repricing_policy
    "cancel_reentry_policy_json",    # → cancel_reentry_policy
    "post_fill_retreat_policy_json", # → post_fill_retreat_policy
)

logger = get_logger("DashboardServer")

# Global state
connected_clients: Set[WebSocketServerProtocol] = set()
state_lock = Lock()
_order_event_stream_lock = Lock()
_order_event_stream_publisher = None
engine_state = {
    "orders": {},  # order_id -> order_data
    "positions": {},  # product_id -> position_data
    "stealth_orders": {},  # stealth_order_id -> order_data
    "engine_status": {
        "running": False,
        "threads_active": 0,
        "event_queue_depth": 0,
        "taker_fee_rate": None,
        "effective_fee_rate": None,
        "target_movement_factor": None,
        "fee_regime_factor": None,
        "volume_ratio": None,
        "overnight_margin_active": None,
        "margin_window_type": None,
        "last_update": None,
    },
    "logs": [],  # Recent log entries
    "market_metrics": {},  # product_id -> {price, as_of, windows: [{minutes, avg, delta_pct}]}
}
max_logs = 100


def _get_dashboard_order_event_stream_publisher():
    """Return the shared order-event publisher for dashboard REST placement."""
    global _order_event_stream_publisher
    if _order_event_stream_publisher is not None:
        return _order_event_stream_publisher

    with _order_event_stream_lock:
        if _order_event_stream_publisher is not None:
            return _order_event_stream_publisher
        try:
            import database.order as order_db
            from business.order_event_stream import OrderEventStreamPublisher

            _order_event_stream_publisher = OrderEventStreamPublisher(order_db)
        except Exception as exc:
            logger.warning(
                "dashboard order_event_stream publisher unavailable: %s",
                exc,
            )
            _order_event_stream_publisher = None
        return _order_event_stream_publisher


def _publish_direct_order_submission_event(
    *,
    client_order_id: str,
    order_id: Optional[str],
    order_params: Dict[str, Any],
    order_configuration: Dict[str, Any],
) -> bool:
    """Publish durable submission evidence for direct dashboard placement."""
    publisher = _get_dashboard_order_event_stream_publisher()
    if publisher is None or not getattr(publisher, "enabled", False):
        return False

    inner_key = next(iter(order_configuration), None)
    inner = order_configuration.get(inner_key, {}) if inner_key else {}
    payload = {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "product_id": order_params.get("product_id"),
        "side": order_params.get("side"),
        "order_configuration_type": inner_key,
        "order_configuration": order_configuration,
        "base_size": inner.get("base_size"),
        "quote_size": inner.get("quote_size"),
        "limit_price": inner.get("limit_price"),
        "post_only": inner.get("post_only"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"dashboard_submit:{client_order_id}:{order_id or ''}"
    return bool(
        publisher.publish_event(
            event_type=EventStreamType.ORDER_SUBMITTED.value,
            source_channel=EventSourceChannel.REST_SUBMIT.value,
            payload=payload,
            idempotency_key=key,
            status_to=OrderStatus.PENDING.value,
        )
    )


def _direct_spot_live_acknowledged(order_params: Mapping[str, Any]) -> bool:
    """Return True when a raw direct spot order includes manual live consent."""
    direct_ack = order_params.get("manual_live_acknowledgement")
    if direct_ack is None:
        direct_ack = order_params.get("manual_live_acknowledged")
    if isinstance(direct_ack, str):
        return direct_ack.strip().lower() in {"true", "yes", "1"}
    return bool(direct_ack)


def _coinbase_order_response_to_dict(result: Any) -> Dict[str, Any]:
    """Normalize Coinbase order response objects without losing nested fields."""
    converter = getattr(result, "to_dict", None)
    if callable(converter):
        data = converter()
    elif isinstance(result, Mapping):
        data = dict(result)
    elif hasattr(result, "__dict__"):
        data = dict(result.__dict__)
    else:
        data = {}
    return data if isinstance(data, dict) else {}


def _coinbase_order_response_success(
    result: Any,
    data: Mapping[str, Any],
) -> Optional[bool]:
    success_attr = getattr(result, "success", None)
    if isinstance(success_attr, bool):
        return success_attr
    success = data.get("success")
    if isinstance(success, bool):
        return success
    if data.get("success_response"):
        return True
    if data.get("error_response") or data.get("failure_reason"):
        return False
    return None


def _coinbase_order_response_error_message(
    result: Any,
    data: Mapping[str, Any],
) -> str:
    error_response = (
        data.get("error_response")
        or getattr(result, "error_response", None)
    )
    if isinstance(error_response, Mapping):
        return str(
            error_response.get("message")
            or error_response.get("error")
            or "Unknown error"
        )
    message = getattr(error_response, "message", None)
    if message:
        return str(message)
    error = getattr(error_response, "error", None)
    if error:
        return str(error)
    failure_reason = data.get("failure_reason")
    if failure_reason:
        return str(failure_reason)
    return "Unknown error"


def _coinbase_order_response_order_id(
    result: Any,
    data: Mapping[str, Any],
) -> Optional[str]:
    order_id = getattr(result, "order_id", None)
    if order_id:
        return str(order_id)
    success_response = data.get("success_response")
    if isinstance(success_response, Mapping) and success_response.get("order_id"):
        return str(success_response["order_id"])
    if data.get("order_id"):
        return str(data["order_id"])
    order = data.get("order")
    if isinstance(order, Mapping) and order.get("order_id"):
        return str(order["order_id"])
    return None


def _dashboard_admin_api_envelope(operator_intent: str) -> AdminApiCommandEnvelope:
    return AdminApiCommandEnvelope(
        idempotency_key=f"dashboard:{uuid.uuid4()}",
        correlation_id=f"dashboard:{uuid.uuid4()}",
        operator_intent=operator_intent,
        actor=AdminApiActor(
            actor_id="legacy-dashboard",
            roles=[AdminApiRole.TRADER],
        ),
    )


def _dashboard_command_service() -> AdminApiCommandService:
    return AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=REST_CLIENT if REST_CLIENT_AVAILABLE else None,
            rest_client_available=REST_CLIENT_AVAILABLE,
            runtime_controller_factory=get_runtime_controller,
            add_log_entry=add_log_entry,
            order_event_publisher_getter=_get_dashboard_order_event_stream_publisher,
            planned_budget_fetcher=_get_dashboard_spot_planned_budget_commitments,
            lot_authority_evaluator_getter=_get_dashboard_spot_lot_authority_evaluator,
            uuid_factory=lambda: str(uuid.uuid4()),
        )
    )


def _manual_order_request_from_dashboard_params(
    order_params: Mapping[str, Any],
) -> ManualOrderRequest:
    order_configuration = order_params.get("order_configuration") or {}
    inner_key = next(iter(order_configuration), None)
    inner = order_configuration.get(inner_key, {}) if inner_key else {}
    order_type = (
        OrderType.MARKET
        if str(inner_key or "").startswith("market_")
        else OrderType.LIMIT
    )
    return ManualOrderRequest(
        product_id=str(order_params.get("product_id") or ""),
        side=OrderSide(str(order_params.get("side") or "").upper()),
        order_type=order_type,
        base_size=inner.get("base_size"),
        quote_size=inner.get("quote_size"),
        limit_price=inner.get("limit_price"),
        post_only=bool(inner.get("post_only", False)),
        manual_live_acknowledgement=_direct_spot_live_acknowledged(order_params),
    )


# Custom JSON encoder for handling Decimal and other non-standard types
from decimal import Decimal

class CustomJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal, datetime, and other special types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, 'isoformat'):  # datetime, date, time
            return obj.isoformat()
        return super().default(obj)

# Event loop reference (set when server starts)
server_event_loop = None

# Stealth order bridge reference (set during integration)
stealth_order_bridge = None


def _get_dashboard_spot_planned_budget_commitments() -> Dict[str, float]:
    """Return stealth-manager planned spot commitments for dashboard actions."""
    bridge = stealth_order_bridge
    manager = getattr(bridge, "stealth_manager", None) if bridge else None
    if manager is None:
        return {}
    budget_getter = getattr(manager, "_get_spot_planned_budget_commitments", None)
    if not callable(budget_getter):
        return {}
    return budget_getter()


def _get_dashboard_spot_lot_authority_evaluator():
    """Return the stealth-manager lot authority evaluator when attached."""
    bridge = stealth_order_bridge
    manager = getattr(bridge, "stealth_manager", None) if bridge else None
    if manager is None:
        return None
    evaluator = getattr(manager, "_evaluate_spot_lot_authority_for_action", None)
    return evaluator if callable(evaluator) else None


def _extract_readiness_wallet_available(wallet: Any) -> float:
    raw_balance = None
    if isinstance(wallet, dict):
        raw_balance = wallet.get("available_balance")
        if raw_balance is None:
            raw_balance = wallet.get("available")
    else:
        raw_balance = getattr(wallet, "available_balance", None)
        if raw_balance is None:
            raw_balance = getattr(wallet, "available", None)
    if isinstance(raw_balance, dict):
        raw_balance = (
            raw_balance.get("value")
            if raw_balance.get("value") is not None
            else raw_balance.get("amount")
        )
    return safe_float(raw_balance, default=0.0) or 0.0


def _build_wallet_readiness_snapshot() -> Dict[str, Any]:
    fetched_at = datetime.utcnow()
    if not rest_credentials_configured():
        return {
            "available": False,
            "fetched_at": None,
            "age_seconds": None,
            "currencies": {},
            "reason": "Coinbase REST credentials are not configured",
        }
    try:
        wallets = fetch_account_wallets() or {}
    except Exception as exc:
        return {
            "available": False,
            "fetched_at": None,
            "age_seconds": None,
            "currencies": {},
            "reason": f"wallet fetch failed: {type(exc).__name__}: {exc}",
        }

    return {
        "available": True,
        "fetched_at": fetched_at.isoformat(),
        "age_seconds": 0.0,
        "currencies": {
            str(currency).upper(): {
                "available_balance": _extract_readiness_wallet_available(wallet),
            }
            for currency, wallet in wallets.items()
        },
    }


def _readiness_mode(enabled: bool) -> str:
    return (
        ProductCapabilityMode.ENABLED.value
        if enabled
        else ProductCapabilityMode.DISABLED.value
    )


def _readiness_policy_phases(policy: Dict[str, Any]) -> list[str]:
    phases = policy.get("phases")
    if phases is None:
        return [phase.value for phase in ActionGuardPhase]
    if isinstance(phases, str):
        phases = [phases]

    normalized = []
    for phase in phases or []:
        try:
            normalized.append(ActionGuardPhase(str(phase)).value)
        except ValueError:
            normalized.append(str(phase))
    return normalized


def _build_action_guard_readiness_summary(
    *,
    wallet_policy: Dict[str, Any],
    known_inventory_policy: Dict[str, Any],
) -> list[Dict[str, Any]]:
    wallet_enabled = wallet_policy.get("enabled", True) is not False
    known_inventory_enabled = bool(known_inventory_policy.get("enabled", False))

    return [
        {
            "condition": ActionConditionType.WALLET_AVAILABLE.value,
            "label": "wallet availability",
            "mode": _readiness_mode(wallet_enabled),
            "phases": _readiness_policy_phases(wallet_policy),
            "reason": (
                "Coinbase wallet balance is checked before spot placement"
                if wallet_enabled
                else "wallet_available guard is disabled by policy"
            ),
        },
        {
            "condition": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "label": "planned spot budget",
            "mode": _readiness_mode(wallet_enabled),
            "phases": _readiness_policy_phases(wallet_policy),
            "reason": (
                "spot wallet availability is reduced by local hidden, pending, "
                "and triggered spot commitments"
                if wallet_enabled
                else "planned-budget checks are disabled because wallet_available is disabled"
            ),
        },
        {
            "condition": ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value,
            "label": "known profitable inventory",
            "mode": _readiness_mode(known_inventory_enabled),
            "phases": _readiness_policy_phases(known_inventory_policy),
            "reason": (
                "spot SELL admission requires known profitable fill-ledger or baseline lots"
                if known_inventory_enabled
                else "known_inventory_available guard is disabled by policy"
            ),
        },
    ]


class _ReadinessEmptyFillLedgerRepo:
    def get_fills_by_instrument(self, _instrument: str) -> list:
        return []

    def get_fills_by_product(self, _product_id: str, *_args: Any) -> list:
        return []


def _baseline_source_id(product_id: str, lot_id: Any) -> str:
    lot_id_text = str(lot_id or "")
    prefix = f"baseline:{product_id}:"
    if lot_id_text.startswith(prefix):
        return lot_id_text[len(prefix):]
    return lot_id_text


def _build_spot_inventory_baseline_summary(product_id: str) -> Dict[str, Any]:
    try:
        from business.lot_builder import PositionLotBuilder
        from business.lot_config import get_profit_target_for_product
        from configuration import SPOT_INVENTORY_BASELINES

        position = PositionLotBuilder(
            _ReadinessEmptyFillLedgerRepo(),
            inventory_baselines=SPOT_INVENTORY_BASELINES,
        ).build_position_by_product(
            product_id,
            profit_target_pct=get_profit_target_for_product(product_id),
        )
    except Exception as exc:
        return {
            "configured": False,
            "known_quantity": 0.0,
            "unknown_cost_basis_quantity": 0.0,
            "lots": [],
            "reason": (
                "inventory baseline summary failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        }

    lots = []
    known_quantity = 0.0
    unknown_cost_basis_quantity = 0.0
    for lot in position.lots:
        if lot.lot_source != InventoryLotSource.IMPORTED_BASELINE:
            continue

        remaining_quantity = (
            safe_float(lot.remaining_quantity, default=0.0) or 0.0
        )
        cost_basis_status = lot.cost_basis_status
        if cost_basis_status == InventoryCostBasisStatus.KNOWN:
            known_quantity += remaining_quantity
            entry_price = safe_float(lot.entry_price, default=0.0) or 0.0
            min_exit = (
                safe_float(lot.min_profitable_exit_price, default=0.0) or 0.0
            )
        else:
            unknown_cost_basis_quantity += remaining_quantity
            entry_price = None
            min_exit = None

        lots.append({
            "lot_id": lot.lot_id,
            "source_id": _baseline_source_id(product_id, lot.lot_id),
            "lot_source": lot.lot_source.value,
            "cost_basis_status": cost_basis_status.value,
            "quantity": safe_float(lot.quantity, default=0.0) or 0.0,
            "remaining_quantity": remaining_quantity,
            "entry_price": entry_price,
            "min_profitable_exit_price": min_exit,
        })

    return {
        "configured": bool(lots),
        "known_quantity": known_quantity,
        "unknown_cost_basis_quantity": unknown_cost_basis_quantity,
        "lots": lots,
    }


def _exception_context_payload(exc: Exception) -> Dict[str, Any]:
    context = getattr(exc, "context", None)
    if not isinstance(context, dict):
        return {}
    return {
        key: value
        for key, value in context.items()
        if key not in {"type", "message", "status"}
    }


def _build_spot_readiness_payload(
    product_ids: Optional[list[str]] = None,
) -> Dict[str, Any]:
    from configuration import PRODUCT_METADATA, SPOT_PRODUCT_IDS

    requested_products = product_ids or SPOT_PRODUCT_IDS
    policy = get_action_condition_guard_policy()
    wallet_policy = normalize_action_guard_wallet_policy(policy)
    known_inventory_policy = normalize_action_guard_known_inventory_policy(policy)
    planned_budget = _get_dashboard_spot_planned_budget_commitments()
    wallet_snapshot = _build_wallet_readiness_snapshot()

    products = []
    for product_id in requested_products:
        metadata = PRODUCT_METADATA.get(product_id, {})
        capabilities = {
            capability.value: evaluate_product_capability(
                product_id=product_id,
                capability=capability,
                allow_conditional=True,
            ).to_dict()
            for capability in ProductCapability
        }
        products.append({
            "product_id": product_id,
            "product_type": metadata.get("product_type") or metadata.get("type"),
            "base_currency": metadata.get("base_currency"),
            "quote_currency": metadata.get("quote_currency"),
            "capabilities": capabilities,
            "inventory": {
                "imported_baselines": (
                    _build_spot_inventory_baseline_summary(product_id)
                ),
            },
        })

    return {
        "type": "spot_readiness",
        "status": "success",
        "generated_at": datetime.utcnow().isoformat(),
        "products": products,
        "planned_budget": {
            str(currency).upper(): amount
            for currency, amount in (planned_budget or {}).items()
        },
        "wallet_snapshot": wallet_snapshot,
        "action_guards": {
            "wallet_available": wallet_policy,
            "known_inventory_available": known_inventory_policy,
        },
        "action_guard_summary": _build_action_guard_readiness_summary(
            wallet_policy=wallet_policy,
            known_inventory_policy=known_inventory_policy,
        ),
    }


def _build_spot_sweep_status_payload(
    state_file: Optional[str] = None,
) -> Dict[str, Any]:
    from business.spot_portfolio_sweep import (
        build_sweep_operator_status,
        load_sweep_run_records,
    )

    ledger_path = Path(state_file) if state_file else (
        Path("runtime_state") / "spot_portfolio_sweeps.jsonl"
    )
    try:
        records = load_sweep_run_records(ledger_path)
        operator_status = build_sweep_operator_status(records=records)
        return {
            "type": "spot_sweep_status",
            "status": "success",
            "state_file": str(ledger_path),
            "operator_status": operator_status,
        }
    except Exception as exc:
        return {
            "type": "spot_sweep_status",
            "status": "error",
            "state_file": str(ledger_path),
            "message": f"sweep status failed: {type(exc).__name__}: {exc}",
        }


def _build_spot_sweep_pnl_payload(
    product_ids: Optional[list[str]] = None,
    include_coinbase_average_cost: bool = False,
) -> Dict[str, Any]:
    try:
        from coinbase.rest import RESTClient

        from business.fill_ledger import FillLedgerRepository
        from business.spot_cost_basis import fetch_coinbase_average_cost_records
        from business.spot_portfolio_sweep import build_spot_portfolio_pnl_report
        from database.database import PostgresDB
        from external.coinbase_client import coinbase_sdk_response_to_dict

        public_client = RESTClient(rate_limit_headers=True)
        products_response = coinbase_sdk_response_to_dict(
            public_client.get_public_products(
                product_type="SPOT",
                get_all_products=True,
                get_tradability_status=True,
            )
        )
        products = list(products_response.get("products") or [])
        cost_basis = {}
        if include_coinbase_average_cost:
            import configuration

            cost_basis = fetch_coinbase_average_cost_records(
                rest_client=configuration.get_rest_client(),
                products=products,
            )
        report = build_spot_portfolio_pnl_report(
            fill_ledger_repo=FillLedgerRepository(PostgresDB()),
            products=products,
            product_ids=product_ids,
            coinbase_average_costs=(
                cost_basis.get("records") if cost_basis else None
            ),
        )
        return {
            "type": "spot_sweep_pnl",
            "status": "success",
            "read_only_coinbase_requests": [
                "get_public_products",
                *cost_basis.get("read_only_coinbase_requests", []),
            ],
            "pnl_report": report,
        }
    except Exception as exc:
        return {
            "type": "spot_sweep_pnl",
            "status": "error",
            "message": f"sweep P/L report failed: {type(exc).__name__}: {exc}",
        }


def _build_spot_cost_basis_payload(
    state_file: Optional[str] = None,
) -> Dict[str, Any]:
    from business.spot_cost_basis import (
        build_cost_basis_operator_status,
        load_cost_basis_snapshot_records,
    )

    ledger_path = Path(state_file) if state_file else (
        Path("runtime_state") / "spot_cost_basis_snapshots.jsonl"
    )
    try:
        records = load_cost_basis_snapshot_records(ledger_path)
        operator_status = build_cost_basis_operator_status(records=records)
        return {
            "type": "spot_cost_basis_status",
            "status": "success",
            "state_file": str(ledger_path),
            "operator_status": operator_status,
        }
    except Exception as exc:
        return {
            "type": "spot_cost_basis_status",
            "status": "error",
            "state_file": str(ledger_path),
            "message": f"cost-basis status failed: {type(exc).__name__}: {exc}",
        }


def _build_spot_campaign_payload(
    state_file: Optional[str] = None,
) -> Dict[str, Any]:
    from business.spot_campaign import (
        build_spot_campaign_operator_status,
        load_spot_campaign_snapshot_records,
    )

    ledger_path = Path(state_file) if state_file else (
        Path("runtime_state") / "spot_campaigns.jsonl"
    )
    try:
        records = load_spot_campaign_snapshot_records(ledger_path)
        operator_status = build_spot_campaign_operator_status(records=records)
        return {
            "type": "spot_campaign_status",
            "status": "success",
            "state_file": str(ledger_path),
            "operator_status": operator_status,
        }
    except Exception as exc:
        return {
            "type": "spot_campaign_status",
            "status": "error",
            "state_file": str(ledger_path),
            "message": f"campaign status failed: {type(exc).__name__}: {exc}",
        }


def _build_spot_direct_order_audit_payload(
    *,
    client_order_id: Optional[str],
    include_events: bool = True,
    include_fills: bool = True,
    event_limit: int = 100,
    fill_limit: int = 1000,
) -> Dict[str, Any]:
    from business.spot_direct_order_audit import (
        build_spot_direct_order_audit,
        fetch_direct_order_event_rows,
        fetch_direct_order_fill_rows,
    )

    client_id = str(client_order_id or "").strip()
    if not client_id:
        audit = build_spot_direct_order_audit(
            client_order_id=client_id,
            event_rows=[],
            fill_rows=[],
            include_events=include_events,
            include_fills=include_fills,
        )
        return {
            "type": "spot_direct_order_audit",
            "status": "error",
            "client_order_id": client_id,
            "audit": audit,
            "message": "Missing client_order_id",
        }

    try:
        db_client = PostgresDB()
        event_rows = (
            fetch_direct_order_event_rows(
                db_client,
                client_id,
                limit=event_limit,
            )
            if include_events
            else []
        )
        fill_rows = (
            fetch_direct_order_fill_rows(
                db_client,
                client_id,
                limit=fill_limit,
            )
            if include_fills
            else []
        )
        audit = build_spot_direct_order_audit(
            client_order_id=client_id,
            event_rows=event_rows,
            fill_rows=fill_rows,
            include_events=include_events,
            include_fills=include_fills,
        )
        return {
            "type": "spot_direct_order_audit",
            "status": "success",
            "client_order_id": client_id,
            "audit": audit,
        }
    except Exception as exc:
        return {
            "type": "spot_direct_order_audit",
            "status": "error",
            "client_order_id": client_id,
            "message": f"direct order audit failed: {type(exc).__name__}: {exc}",
        }


# In-memory Fibonacci-window market metrics tracker. Optional dependency
# so the dashboard still imports cleanly in DB-less smoke tests where the
# business package may be partially mocked.
try:
    from business.market_metrics import (
        get_market_metrics_tracker as _get_market_metrics_tracker,
    )
    _MARKET_METRICS_AVAILABLE = True
except ImportError:
    _MARKET_METRICS_AVAILABLE = False
    def _get_market_metrics_tracker():
        return None


def _build_market_metrics_payload() -> Dict[str, Any]:
    """Snapshot the in-memory Fibonacci-window tracker for broadcast.

    Returns ``{}`` if the tracker is unavailable or empty so consumers
    can treat the field as always-present-but-possibly-empty (the same
    contract as ``stealth_orders``).
    """
    if not _MARKET_METRICS_AVAILABLE:
        return {}
    try:
        tracker = _get_market_metrics_tracker()
        if tracker is None:
            return {}
        return tracker.snapshot()
    except Exception as e:
        # Never let metrics fail a broadcast — log and degrade.
        logger.debug(f"Failed to build market metrics payload: {e}")
        return {}


async def register_client(websocket: WebSocketServerProtocol):
    """Register a new connected client."""
    connected_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")
    
    # Send products list first
    try:
        import json as json_lib
        from pathlib import Path
        products_file = Path(__file__).parent / "products.json"
        if products_file.exists():
            with open(products_file, 'r') as f:
                products_data = json_lib.load(f)
                products_payload = {
                    "type": "products_list",
                    "derivatives": products_data.get("derivatives", []),
                    "spot": products_data.get("spot", []),
                    "metadata": products_data.get("metadata", {}),
                }
                await websocket.send(json_lib.dumps(products_payload))
    except Exception as e:
        logger.error(f"Failed to send products list: {e}")
    
    # Send current state to newly connected client
    await broadcast_state(websocket)


async def unregister_client(websocket: WebSocketServerProtocol):
    """Unregister a disconnected client."""
    connected_clients.discard(websocket)
    logger.info(f"Client disconnected. Total clients: {len(connected_clients)}")


async def _async_broadcast_state():
    """Async version of broadcast_state for scheduling from event loop."""
    with state_lock:
        # Fold in the live Fibonacci-window market metrics so dashboard /
        # console clients can render multi-timeframe trend without a
        # separate channel. Snapshot is built outside the lock-protected
        # mutate path because the tracker has its own lock.
        engine_state["market_metrics"] = _build_market_metrics_payload()
        payload = {
            "type": "state_update",
            "data": engine_state,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    message = json.dumps(payload, cls=CustomJSONEncoder)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def _trigger_broadcast():
    """Trigger broadcast from sync code to all connected clients."""
    global server_event_loop
    if server_event_loop and connected_clients:
        try:
            asyncio.run_coroutine_threadsafe(_async_broadcast_state(), server_event_loop)
        except Exception as e:
            logger.error(f"Failed to trigger broadcast: {e}")


async def broadcast_state(websocket: WebSocketServerProtocol = None):
    """Broadcast current engine state to all connected clients."""
    with state_lock:
        engine_state["market_metrics"] = _build_market_metrics_payload()
        payload = {
            "type": "state_update",
            "data": engine_state,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    message = json.dumps(payload, cls=CustomJSONEncoder)
    
    if websocket:
        # Send to single client
        try:
            await websocket.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass
    else:
        # Broadcast to all
        for client in connected_clients.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                connected_clients.discard(client)


def _build_investor_storyboard_snapshot(
    window_minutes: int = 10080,  # default 7 days
    bucket_seconds: int = None,   # auto-scaled to window if not specified
    product_id: Optional[str] = None
) -> Dict[str, Any]:
    """Build candlestick OHLC data from fill_ledger for investor visualization.
    
    Args:
        window_minutes: Look back this many minutes for data (default: 10080 = 7 days)
        bucket_seconds: Group events into buckets of this size. Auto-scaled if None.
        product_id: Filter to specific product, or None for aggregate
    
    Returns:
        Dict with 'candles' list containing OHLC data for the chart
    """
    # Auto-scale bucket size to keep candle count reasonable (~50-100 candles)
    if bucket_seconds is None:
        if window_minutes <= 60:
            bucket_seconds = 60          # 1-min candles
        elif window_minutes <= 360:
            bucket_seconds = 300         # 5-min candles
        elif window_minutes <= 1440:
            bucket_seconds = 900         # 15-min candles
        elif window_minutes <= 10080:
            bucket_seconds = 3600        # 1-hour candles
        else:
            bucket_seconds = 86400       # 1-day candles
    db = None
    try:
        db = PostgresDB()
        
        # Use fill_ledger table which has actual execution data
        # fill_ledger has: derived_trade_key, exchange_trade_id, instrument, side, quantity, price, timestamp, fees, commission_percentage, client_order_id
        if product_id:
            query = """
            SELECT 
                timestamp as event_time,
                price,
                quantity as size,
                instrument as product_id,
                client_order_id
            FROM fill_ledger
            WHERE timestamp >= NOW() - (%s * INTERVAL '1 minute')
                AND price IS NOT NULL
                AND quantity IS NOT NULL
                AND instrument = %s
            ORDER BY timestamp
            """
        else:
            query = """
            SELECT 
                timestamp as event_time,
                price,
                quantity as size,
                instrument as product_id,
                client_order_id
            FROM fill_ledger
            WHERE timestamp >= NOW() - (%s * INTERVAL '1 minute')
                AND price IS NOT NULL
                AND quantity IS NOT NULL
            ORDER BY timestamp
            """

        try:
            params = (window_minutes, product_id) if product_id else (window_minutes,)
            results = db.execute_query(query, params)

            # Build mapping: client_order_id -> parent_order_id.
            # Stealth orders map to their parent; parent orders map to themselves.
            stealth_parents = db.execute_query(
                "SELECT stealth_order_id, parent_order_id FROM stealth_orders WHERE parent_order_id IS NOT NULL"
            )
            parent_orders = db.execute_query(
                "SELECT client_order_id FROM order_parent WHERE client_order_id IS NOT NULL"
            )
            client_to_parent = {}
            for row in parent_orders:
                client_order_id = row.get('client_order_id')
                if client_order_id:
                    client_to_parent[client_order_id] = client_order_id

            for row in stealth_parents:
                stealth_order_id = row.get('stealth_order_id')
                parent_order_id = row.get('parent_order_id')
                if stealth_order_id and parent_order_id:
                    client_to_parent[stealth_order_id] = parent_order_id

            # Convert results to candlesticks (group by time buckets in Python)
            from collections import defaultdict
            buckets = defaultdict(list)
            
            # Group events into time buckets
            for row in results:
                try:
                    event_time = row.get('event_time')
                    if not event_time:
                        continue
                    
                    # Get parent order ID for grouping
                    client_order_id = row.get('client_order_id')
                    parent_order_id = client_to_parent.get(client_order_id)  # None if not a stealth order
                    
                    # Round to nearest bucket_seconds
                    timestamp_seconds = int(event_time.timestamp())
                    bucket_index = timestamp_seconds // bucket_seconds
                    buckets[bucket_index].append({
                        'price': safe_float(row.get('price'), 0),
                        'size': safe_float(row.get('size'), 0),
                        'time': event_time,
                        'client_order_id': client_order_id,
                        'parent_order_id': parent_order_id,
                    })
                except Exception as e:
                    logger.debug(f"Error processing event: {e}")
                    continue
            
            # Build candlesticks from buckets
            candles = []
            for bucket_index in sorted(buckets.keys()):
                prices = [e['price'] for e in buckets[bucket_index]]
                sizes = [e['size'] for e in buckets[bucket_index]]
                times = [e['time'] for e in buckets[bucket_index]]
                parent_volume_by_id = defaultdict(float)
                for event in buckets[bucket_index]:
                    parent_order_id = event.get('parent_order_id')
                    if parent_order_id:
                        parent_volume_by_id[parent_order_id] += safe_float(event.get('size'), 0)

                group_slices = [
                    {
                        'group_id': parent_order_id,
                        'volume': volume,
                    }
                    for parent_order_id, volume in sorted(
                        parent_volume_by_id.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ]
                group_id = group_slices[0]['group_id'] if group_slices else None
                
                if not prices:
                    continue
                
                candle = {
                    'index': bucket_index,
                    'label': times[0].strftime('%H:%M') if times else f'T+{bucket_index}',
                    'open': prices[0] if prices else 0,
                    'high': max(prices) if prices else 0,
                    'low': min(prices) if prices else 0,
                    'close': prices[-1] if prices else 0,
                    'volume': sum(sizes) if sizes else 0,
                    'group_id': group_id,  # Parent order ID for chaining
                    'group_slices': group_slices,
                }
                candles.append(candle)
            
            # If no data, generate mock data for testing
            if not candles:
                logger.info("No order events found, generating placeholder candles")
                import random
                price = 100.0
                for i in range(20):
                    drift = random.gauss(0, 1.5)
                    price = max(50, price + drift)
                    candles.append({
                        'index': i,
                        'label': f'{9 + i//6:02d}:{(i%6)*10:02d}',
                        'open': price,
                        'high': price + abs(random.gauss(0, 0.8)),
                        'low': price - abs(random.gauss(0, 0.8)),
                        'close': price + random.gauss(0, 0.5),
                        'volume': random.randint(1000, 50000),
                    })
            
            return {
                'type': 'investor_storyboard',
                'candles': candles,
                'timestamp': datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.warning(f"Query failed: {str(e)}. Using placeholder data.")
            logger.debug(f"Full error trace: {repr(e)}", exc_info=True)
            # Return placeholder data if table doesn't exist yet
            import random
            candles = []
            price = 100.0
            for i in range(20):
                drift = random.gauss(0, 1.5)
                price = max(50, price + drift)
                candles.append({
                    'index': i,
                    'label': f'{9 + i//6:02d}:{(i%6)*10:02d}',
                    'open': price,
                    'high': price + abs(random.gauss(0, 0.8)),
                    'low': price - abs(random.gauss(0, 0.8)),
                    'close': price + random.gauss(0, 0.5),
                    'volume': random.randint(1000, 50000),
                })
            
            return {
                'type': 'investor_storyboard',
                'candles': candles,
                'timestamp': datetime.utcnow().isoformat(),
            }
        
    except Exception as e:
        logger.error(f"Failed to build storyboard snapshot: {e}")
        import random
        candles = []
        price = 100.0
        for i in range(20):
            drift = random.gauss(0, 1.5)
            price = max(50, price + drift)
            candles.append({
                'index': i,
                'label': f'{9 + i//6:02d}:{(i%6)*10:02d}',
                'open': price,
                'high': price + abs(random.gauss(0, 0.8)),
                'low': price - abs(random.gauss(0, 0.8)),
                'close': price + random.gauss(0, 0.5),
                'volume': random.randint(1000, 50000),
            })
        return {
            'type': 'investor_storyboard',
            'candles': candles,
            'timestamp': datetime.utcnow().isoformat(),
        }
    finally:
        if db:
            try:
                db.disconnect()
            except:
                pass


async def handle_client_message(websocket: WebSocketServerProtocol, message: str):
    """Handle incoming messages from client.
    
    Raises:
        WebSocketMessageError: If message parsing fails or required fields missing
        OrderCreationError: If order placement fails
        CoinbaseAPIError: If API call fails
    """
    try:
        # Parse incoming message
        try:
            data = json.loads(message)
        except json.JSONDecodeError as e:
            raise WebSocketMessageError(f"Invalid JSON: {e}", raw_data=message)
        
        msg_type = data.get("type")
        if not msg_type:
            raise WebSocketMessageError("Missing 'type' field in message", raw_data=message)
        
        # DEBUG: Log all incoming messages
        logger.debug(f"[HANDLER] Received message type: {msg_type}")

        # Admission gate: reject originating-work messages when the engine is
        # not RUNNING (paused / draining / stopped). Cancels, queries, and
        # admin messages pass through so operators can still control the
        # system and wind down existing positions.
        controller = get_runtime_controller()
        if msg_type in _ORIGINATING_MSG_TYPES and not controller.is_admitting():
            response = {
                "type": "admission_rejected",
                "rejected_type": msg_type,
                "engine_state": controller.state.value,
                "message": (
                    f"Engine is {controller.state.value}; new orders are not "
                    f"being accepted. Resume the engine to place new orders."
                ),
            }
            await websocket.send(json.dumps(response))
            add_log_entry(
                "WARNING",
                f"Rejected {msg_type}: engine state {controller.state.value}",
            )
            return

        if msg_type == "admin_status":
            response = {
                "type": "admin_status_response",
                "engine_state": controller.state.value,
                "is_admitting": controller.is_admitting(),
                "is_stopping": controller.is_stopping(),
                "inflight": controller.inflight_snapshot(),
                "total_inflight": controller.total_inflight(),
                "timestamp": datetime.utcnow().isoformat(),
            }
            await websocket.send(json.dumps(response))
            return

        if msg_type == "admin_pause":
            changed = controller.request_pause()
            response = {
                "type": "admin_pause_response",
                "changed": changed,
                "engine_state": controller.state.value,
            }
            if changed:
                add_log_entry("WARNING", "Engine paused via admin_pause")
            await websocket.send(json.dumps(response))
            return

        if msg_type == "admin_resume":
            changed = controller.resume()
            response = {
                "type": "admin_resume_response",
                "changed": changed,
                "engine_state": controller.state.value,
            }
            if changed:
                add_log_entry("INFO", "Engine resumed via admin_resume")
            await websocket.send(json.dumps(response))
            return

        if msg_type == "admin_shutdown":
            # Acknowledge first so the dashboard sees the response, then
            # kick off drain in a worker thread so we don't block the
            # asyncio event loop.
            timeout = float(data.get("timeout_seconds", 30.0))
            response = {
                "type": "admin_shutdown_response",
                "accepted": True,
                "timeout_seconds": timeout,
                "engine_state_before": controller.state.value,
            }
            await websocket.send(json.dumps(response))
            add_log_entry("WARNING", f"Engine shutdown requested (timeout={timeout}s)")

            def _drain_worker() -> None:
                try:
                    controller.drain_and_stop(timeout_seconds=timeout)
                except Exception:
                    logger.exception("Drain worker raised")

            Thread(target=_drain_worker, daemon=True, name="admin-shutdown-drain").start()
            return
        
        if msg_type == "place_order":
            order_params = data.get("params", {})
            logger.info(f"Order placement requested: {order_params}")

            try:
                command = ManualOrderCommand(
                    envelope=_dashboard_admin_api_envelope("dashboard_place_order"),
                    request=_manual_order_request_from_dashboard_params(order_params),
                    order_configuration_override=(
                        order_params.get("order_configuration") or {}
                    ),
                    allow_live_execution=True,
                )
                service_response = _dashboard_command_service().place_manual_order(
                    command
                )
                response = manual_order_response_to_dashboard_payload(
                    service_response
                )
            except Exception as e:
                logger.error(f"Order placement failed: {type(e).__name__}: {str(e)}")
                raise OrderCreationError(
                    f"Failed to place order: {e}",
                    client_order_id=None,
                ) from e

            await websocket.send(json.dumps(response))
            
        elif msg_type == "cancel_order":
            params = data.get("params") or {}
            client_order_id = data.get("client_order_id") or params.get("client_order_id")
            logger.info("Cancel requested for client_order_id=%s", client_order_id)

            if not client_order_id:
                await websocket.send(json.dumps({
                    "type": "cancel_response",
                    "status": "error",
                    "message": "Missing client_order_id",
                }))
                return

            command = CancelOrderCommand(
                envelope=_dashboard_admin_api_envelope("dashboard_cancel_order"),
                client_order_id=str(client_order_id),
                request=CancelOrderRequest(reason=params.get("reason")),
                allow_live_execution=True,
            )
            response = cancel_response_to_dashboard_payload(
                _dashboard_command_service().cancel_order_by_client_order_id(
                    command
                )
            )
            
            await websocket.send(json.dumps(response))
            
        elif msg_type == "request_stealth_orders":
            # Send current stealth orders snapshot
            await send_stealth_orders_snapshot(websocket)

        elif msg_type == "request_spot_readiness":
            params = data.get("params") or {}
            product_ids = params.get("product_ids")
            if isinstance(product_ids, str):
                product_ids = [product_ids]
            elif product_ids is not None and not isinstance(product_ids, list):
                product_ids = None
            response = _build_spot_readiness_payload(product_ids=product_ids)
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_spot_sweep_status":
            params = data.get("params") or {}
            state_file = params.get("state_file")
            response = _build_spot_sweep_status_payload(state_file=state_file)
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_spot_sweep_pnl":
            params = data.get("params") or {}
            product_ids = params.get("product_ids")
            if isinstance(product_ids, str):
                product_ids = [product_ids]
            elif product_ids is not None and not isinstance(product_ids, list):
                product_ids = None
            include_coinbase_average_cost = bool(
                params.get("include_coinbase_average_cost")
            )
            response = _build_spot_sweep_pnl_payload(
                product_ids=product_ids,
                include_coinbase_average_cost=include_coinbase_average_cost,
            )
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_spot_cost_basis_status":
            params = data.get("params") or {}
            state_file = params.get("state_file")
            response = _build_spot_cost_basis_payload(state_file=state_file)
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_spot_campaign_status":
            params = data.get("params") or {}
            state_file = params.get("state_file")
            response = _build_spot_campaign_payload(state_file=state_file)
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_spot_direct_order_audit":
            params = data.get("params") or {}
            client_order_id = (
                data.get("client_order_id")
                or params.get("client_order_id")
            )
            response = _build_spot_direct_order_audit_payload(
                client_order_id=client_order_id,
                include_events=bool(params.get("include_events", True)),
                include_fills=bool(params.get("include_fills", True)),
                event_limit=int(params.get("event_limit", 100)),
                fill_limit=int(params.get("fill_limit", 1000)),
            )
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_slide_calibration_summary":
            # Per-product fill / reprice / P&L snapshot used by the
            # Slide Calibration UI to tune sliding-order config against
            # daily volume + profit goals. Read-only; pure SQL over
            # existing tables (fill_ledger, order_parent, stealth_orders).
            try:
                from database.slide_calibration_helpers import (
                    get_slide_calibration_summary,
                )

                params = data.get("params") or {}
                window_minutes = int(params.get("window_minutes", 1440))
                product_id = params.get("product_id") or None
                daily_notional_target = float(
                    params.get("daily_notional_target_usd", 1_000_000.0)
                )
                account_balance = float(
                    params.get("account_balance_usd", 250_000.0)
                )

                # Pull contract sizes from the live OrderBook held by the
                # engine (via the stealth bridge). For FUTURE products
                # ``fill_ledger.quantity`` is contract count, not underlying
                # units, so notional must be scaled by ``contract_size``
                # (e.g. 0.01 BTC for ``BIT-29MAY26-CDE``). Authoritative
                # path matches calculation/profit_validator.py:151-166.
                # If no engine is wired (e.g. dashboard-only deployment),
                # fall back to no scaling — the summary will still be
                # internally consistent, just over-stated for futures.
                contract_size_by_product: dict = {}
                try:
                    if (stealth_order_bridge
                            and getattr(stealth_order_bridge, "order_engine", None)
                            and getattr(stealth_order_bridge.order_engine, "orderbook", None)):
                        products = stealth_order_bridge.order_engine.orderbook.product or {}
                        for pid, pdata in products.items():
                            if not isinstance(pdata, dict):
                                continue
                            fpd = pdata.get("future_product_details") or {}
                            cs = fpd.get("contract_size")
                            if cs is None:
                                continue
                            try:
                                cs_f = float(cs)
                            except (TypeError, ValueError):
                                continue
                            if cs_f > 0:
                                contract_size_by_product[pid] = cs_f
                except Exception as e:
                    logger.warning(
                        f"slide-calibration: contract-size lookup failed: {e}"
                    )

                summary = get_slide_calibration_summary(
                    window_minutes=window_minutes,
                    product_id=product_id,
                    daily_notional_target_usd=daily_notional_target,
                    account_balance_usd=account_balance,
                    contract_size_by_product=contract_size_by_product,
                )
                response = {
                    "type": "slide_calibration_summary",
                    "status": "success",
                    **summary,
                    "generated_at": datetime.utcnow().isoformat(),
                }
            except Exception as e:
                logger.exception("Failed to build slide-calibration summary")
                response = {
                    "type": "slide_calibration_summary",
                    "status": "error",
                    "message": f"Failed to build summary: {e}",
                }
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_market_chart_history":
            # Time series for the slide-calibration phase-2 chart: ticks
            # from market_tick + 1m candle fallback + anchor-reprice
            # events. Per-product, read-only.
            try:
                from database.market_chart_helpers import get_market_chart_history

                params = data.get("params") or {}
                product_id = params.get("product_id")
                window_minutes = int(params.get("window_minutes", 360))
                max_tick_points = int(params.get("max_tick_points", 5000))

                payload = get_market_chart_history(
                    product_id=product_id,
                    window_minutes=window_minutes,
                    max_tick_points=max_tick_points,
                )
                response = {
                    "type": "market_chart_history",
                    "status": "success",
                    **payload,
                    "generated_at": datetime.utcnow().isoformat(),
                }
            except ValueError as e:
                response = {
                    "type": "market_chart_history",
                    "status": "error",
                    "message": str(e),
                }
            except Exception as e:
                logger.exception("Failed to build market chart history")
                response = {
                    "type": "market_chart_history",
                    "status": "error",
                    "message": f"Failed to build chart history: {e}",
                }
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))

        elif msg_type == "request_storyboard_products":
            # Return distinct product IDs available in fill_ledger
            try:
                from database.database import PostgresDB
                db = PostgresDB()
                rows = db.execute_query("SELECT DISTINCT instrument FROM fill_ledger ORDER BY instrument")
                db.disconnect()
                products = [r["instrument"] for r in rows]
            except Exception as e:
                logger.warning(f"Could not fetch storyboard products: {e}")
                products = []
            await websocket.send(json.dumps({"type": "storyboard_products", "products": products}))

        elif msg_type == "request_investor_storyboard":
            # Send investor storyboard snapshot
            params = data.get("params", {})
            window_minutes = params.get("window_minutes", 10080)
            bucket_seconds = params.get("bucket_seconds", None)
            product_id = params.get("product_id", None)
            
            snapshot = _build_investor_storyboard_snapshot(
                window_minutes=window_minutes,
                bucket_seconds=bucket_seconds,
                product_id=product_id
            )
            
            response = {
                **snapshot,
                "message_id": str(uuid.uuid4()),
            }
            
            await websocket.send(json.dumps(response, cls=CustomJSONEncoder))
        
        elif msg_type == "export_active_stealth_orders":
            # Read-only export of all currently active root stealth orders.
            # Output is shaped so each entry can be replayed verbatim through
            # the existing "create_stealth_order" message handler. Only ROOT
            # orders (parent_order_id is None) are exported because follow-ups
            # are spawned automatically when their root fills.
            if not stealth_order_bridge:
                response = {
                    "type": "export_active_stealth_orders_response",
                    "status": "error",
                    "message": "Stealth order system not initialized",
                }
                await websocket.send(json.dumps(response))
                return

            try:
                from database.order import get_parent_order

                manager = stealth_order_bridge.stealth_manager
                exported: list[dict] = []
                # Snapshot the dict before iterating so concurrent mutations
                # by the evaluator thread don't raise RuntimeError.
                in_memory_snapshot = list(manager.in_memory_orders.items())
                for stealth_order_id, order in in_memory_snapshot:
                    if not isinstance(order, dict):
                        continue
                    if order.get("parent_order_id"):
                        # Skip follow-ups; they're recreated by the engine.
                        continue
                    status = str(order.get("status") or "").upper()
                    if status not in _ACTIVE_STEALTH_STATUSES:
                        continue

                    serialized = manager._serialize_order_for_json(order)

                    # Overlay canonical persisted fields from order_parent.
                    # Several create_stealth_order kwargs (target_movement,
                    # target_movement_type, max_order_replacements,
                    # allow_partial_fills) live ONLY in the order_parent row
                    # for root orders — they're not on the in-memory stealth
                    # dict. Without this merge the export is missing the
                    # config the user originally typed in.
                    try:
                        parent_row = get_parent_order(stealth_order_id) or {}
                    except Exception as e:
                        logger.warning(
                            f"export: get_parent_order failed for "
                            f"{stealth_order_id}: {e}"
                        )
                        parent_row = {}

                    tm = parent_row.get("target_movement")
                    if tm is not None and "target_movement" not in serialized:
                        serialized["target_movement"] = safe_float(tm, default=0.0)
                    if (
                        parent_row.get("target_movement_type")
                        and "target_movement_type" not in serialized
                    ):
                        serialized["target_movement_type"] = parent_row["target_movement_type"]
                    # NOTE: order_parent column is `max_order_replacement`
                    # (singular); the create_stealth_order kwarg is
                    # `max_order_replacements` (plural). Map across.
                    if parent_row.get("max_order_replacement") is not None:
                        serialized["max_order_replacements"] = int(
                            parent_row["max_order_replacement"]
                        )
                    if parent_row.get("allow_partial_fills") is not None:
                        serialized["allow_partial_fills"] = bool(
                            parent_row["allow_partial_fills"]
                        )

                    payload: dict = {
                        "stealth_order_id": stealth_order_id,
                    }
                    for src_key in _EXPORT_FIELDS:
                        if src_key not in serialized:
                            continue
                        # Map the in-memory _json suffix back to the
                        # create_stealth_order kwarg name.
                        if src_key == "reveal_condition_json":
                            dst_key = "reveal_condition"
                        elif src_key == "sizing_strategy_json":
                            dst_key = "sizing_strategy"
                        elif src_key == "anchor_repricing_policy_json":
                            dst_key = "anchor_repricing_policy"
                        elif src_key == "cancel_reentry_policy_json":
                            dst_key = "cancel_reentry_policy"
                        elif src_key == "post_fill_retreat_policy_json":
                            dst_key = "post_fill_retreat_policy"
                        else:
                            dst_key = src_key
                        payload[dst_key] = serialized[src_key]
                    exported.append(payload)

                response = {
                    "type": "export_active_stealth_orders_response",
                    "status": "success",
                    "exported_at": datetime.utcnow().isoformat(),
                    "count": len(exported),
                    "orders": exported,
                }
                add_log_entry(
                    "INFO",
                    f"Exported {len(exported)} active stealth orders for backup",
                )
                await websocket.send(json.dumps(response))
            except Exception as e:
                logger.exception("Failed to export active stealth orders")
                response = {
                    "type": "export_active_stealth_orders_response",
                    "status": "error",
                    "message": f"Export failed: {e}",
                }
                await websocket.send(json.dumps(response))

        elif msg_type == "import_stealth_orders":
            # Bulk-replay create_stealth_order for each entry in payload.
            # Each entry must already be in the create_stealth_order shape (as
            # produced by export_active_stealth_orders). Per-entry results are
            # returned so a partial failure doesn't lose the whole batch.
            orders_to_import = data.get("orders") or []
            if not isinstance(orders_to_import, list):
                response = {
                    "type": "import_stealth_orders_response",
                    "status": "error",
                    "message": "'orders' must be a list",
                }
                await websocket.send(json.dumps(response))
                return

            if not stealth_order_bridge:
                response = {
                    "type": "import_stealth_orders_response",
                    "status": "error",
                    "message": "Stealth order system not initialized",
                }
                await websocket.send(json.dumps(response))
                return

            results: list[dict] = []
            success_count = 0
            for entry in orders_to_import:
                if not isinstance(entry, dict):
                    results.append({
                        "status": "error",
                        "error": "entry not a dict",
                    })
                    continue
                requested_id = entry.get("stealth_order_id")
                try:
                    new_id = stealth_order_bridge.create_stealth_order(
                        stealth_order_id=requested_id,
                        product_id=entry["product_id"],
                        side=entry["side"],
                        total_size=entry["total_size"],
                        limit_price=entry["limit_price"],
                        reveal_condition=entry["reveal_condition"],
                        reveal_pricing_policy=entry.get("reveal_pricing_policy"),
                        sizing_strategy=entry.get("sizing_strategy", {}),
                        parent_order_id=None,  # imports are always roots
                        follow_up_reveal_direction=entry.get(
                            "follow_up_reveal_direction",
                            FollowUpRevealDirection.OPPOSITE.value,
                        ),
                        notes=entry.get("notes", ""),
                        max_order_replacements=entry.get("max_order_replacements"),
                        target_movement=entry.get("target_movement", 0.002),
                        target_movement_type=entry.get("target_movement_type", "P"),
                        allow_partial_fills=bool(entry.get("allow_partial_fills", True)),
                        anchor_repricing_policy=entry.get("anchor_repricing_policy"),
                        cancel_reentry_policy=entry.get("cancel_reentry_policy"),
                        post_fill_retreat_policy=entry.get("post_fill_retreat_policy"),
                    )
                    results.append({
                        "status": "success",
                        "requested_id": requested_id,
                        "stealth_order_id": str(new_id),
                        "product_id": entry.get("product_id"),
                        "side": entry.get("side"),
                    })
                    success_count += 1
                except Exception as e:
                    logger.exception(
                        f"Import failed for stealth order {requested_id}: {e}"
                    )
                    results.append({
                        "status": "error",
                        "requested_id": requested_id,
                        "product_id": entry.get("product_id"),
                        "side": entry.get("side"),
                        "error": str(e),
                    })

            response = {
                "type": "import_stealth_orders_response",
                "status": "success" if success_count == len(orders_to_import) else "partial",
                "imported": success_count,
                "total": len(orders_to_import),
                "results": results,
            }
            add_log_entry(
                "INFO",
                f"Imported {success_count}/{len(orders_to_import)} stealth orders",
            )
            await websocket.send(json.dumps(response))
            # Push fresh state to all clients so the new orders show up.
            await broadcast_stealth_order_update({
                "type": "stealth_orders_imported",
                "imported": success_count,
                "total": len(orders_to_import),
            })

        elif msg_type == "create_stealth_order":
            # Create new stealth order
            logger.info("[HANDLER] create_stealth_order message received")
            order = data.get("order")
            
            if not order:
                response = {
                    "type": "error",
                    "message": "Missing order data"
                }
                await websocket.send(json.dumps(response))
                return
            
            if not stealth_order_bridge:
                response = {
                    "type": "error",
                    "message": "Stealth order system not initialized"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                stealth_id = stealth_order_bridge.create_stealth_order(
                    stealth_order_id=order.get('stealth_order_id'),  # Allow UI to provide UUID
                    product_id=order['product_id'],
                    side=order['side'],
                    total_size=order['total_size'],
                    limit_price=order['limit_price'],
                    reveal_condition=order['reveal_condition'],
                    reveal_pricing_policy=order.get('reveal_pricing_policy'),
                    sizing_strategy=order.get('sizing_strategy', {}),
                    parent_order_id=order.get('parent_order_id'),  # Support parent-child relationships for order spans
                    follow_up_reveal_direction=order.get('follow_up_reveal_direction', FollowUpRevealDirection.OPPOSITE.value),
                    notes=order.get('notes', ''),
                    max_order_replacements=order.get('max_order_replacements'),
                    target_movement=order.get('target_movement', 0.002),
                    target_movement_type=order.get('target_movement_type', 'P'),
                    allow_partial_fills=bool(order.get('allow_partial_fills', True)),
                    anchor_repricing_policy=order.get('anchor_repricing_policy'),
                    cancel_reentry_policy=order.get('cancel_reentry_policy'),
                    post_fill_retreat_policy=order.get('post_fill_retreat_policy'),
                    enable_hotpoint_replication=bool(order.get('enable_hotpoint_replication', False)),
                )
                
                # Get the created order data and serialize for JSON
                order_data = stealth_order_bridge.stealth_manager.in_memory_orders.get(stealth_id)
                serialized_order = stealth_order_bridge.stealth_manager._serialize_order_for_json(order_data) if order_data else None
                
                response = {
                    "type": "stealth_order_created",
                    "stealth_order_id": str(stealth_id),
                    "order": serialized_order
                }
                
                with state_lock:
                    engine_state["stealth_orders"][str(stealth_id)] = serialized_order
                
                add_log_entry("INFO", f"Stealth order created: {order['product_id']} {order['side']} {order['total_size']}")
                logger.info(f"Stealth order created: {stealth_id}")
                
                # Broadcast to all clients
                await broadcast_stealth_order_update(response)
                
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Failed to create stealth order: {e}\n{error_trace}")
                response = {
                    "type": "error",
                    "message": f"Failed to create order: {str(e)}"
                }
                response.update(_exception_context_payload(e))
                add_log_entry("ERROR", f"Stealth order creation failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "cancel_stealth_order":
            # Cancel a stealth order
            stealth_order_id = data.get("stealth_order_id")
            if not stealth_order_id or not stealth_order_bridge:
                response = {
                    "type": "error",
                    "message": "Invalid order ID or system not initialized"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                stealth_order_bridge.cancel_stealth_order(stealth_order_id, "user_cancelled")
                
                # Update state
                with state_lock:
                    if stealth_order_id in engine_state["stealth_orders"]:
                        engine_state["stealth_orders"][stealth_order_id]["status"] = "CANCELLED"
                
                response = {
                    "type": "stealth_order_cancelled",
                    "stealth_order_id": stealth_order_id
                }
                
                add_log_entry("INFO", f"Stealth order cancelled: {stealth_order_id}")
                logger.info(f"Stealth order cancelled: {stealth_order_id}")
                
                # Broadcast to all clients
                await broadcast_stealth_order_update(response)
                
            except Exception as e:
                logger.error(f"Failed to cancel stealth order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to cancel order: {str(e)}"
                }
                await websocket.send(json.dumps(response))
        
        elif msg_type == "update_stealth_target_movement":
            # Update target movement for a stealth order
            stealth_order_id = data.get("stealth_order_id")
            target_movement = data.get("target_movement")
            target_movement_type = data.get("target_movement_type", "P")
            
            if not stealth_order_id:
                response = {
                    "type": "error",
                    "message": "Missing stealth_order_id"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                from database.order import update_parent_order_target_movement, get_stealth_order_by_id

                # CANONICAL: target_movement lives on the ``order_parent`` row.
                # The engine's ``_resolve_target_movement_for_plan`` reads from
                # there. Writing to ``stealth_orders`` (the previous behaviour)
                # was silently ignored by every reveal/profit-validation path
                # so UI edits had no runtime effect. See 2026-04-30 audit.
                success = update_parent_order_target_movement(
                    parent_order_id=stealth_order_id,
                    target_movement=target_movement,
                    target_movement_type=target_movement_type
                )
                
                if success:
                    # Sync to in-memory cache for fast access
                    if stealth_order_bridge:
                        stealth_order_bridge.stealth_manager.sync_target_movement_to_cache(
                            stealth_order_id,
                            target_movement,
                            target_movement_type
                        )
                    
                    # Update in-memory state if available
                    with state_lock:
                        if stealth_order_id in engine_state["stealth_orders"]:
                            engine_state["stealth_orders"][stealth_order_id]["target_movement"] = target_movement
                            engine_state["stealth_orders"][stealth_order_id]["target_movement_type"] = target_movement_type
                    
                    response = {
                        "type": "stealth_order_updated",
                        "stealth_order_id": stealth_order_id,
                        "order": {
                            "stealth_order_id": stealth_order_id,
                            "target_movement": target_movement,
                            "target_movement_type": target_movement_type
                        }
                    }
                    
                    add_log_entry("INFO", f"Stealth order target_movement updated: {stealth_order_id} = {target_movement}{target_movement_type}")
                    logger.info(f"Stealth order target_movement updated: {stealth_order_id} = {target_movement}{target_movement_type}")
                    
                    # Broadcast to all clients
                    message = json.dumps(response)
                    for client in connected_clients.copy():
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            connected_clients.discard(client)
                    
                    await websocket.send(json.dumps({"type": "update_success", "message": "Target movement updated"}))
                else:
                    response = {
                        "type": "error",
                        "message": f"Failed to update stealth order: {stealth_order_id}"
                    }
                    add_log_entry("ERROR", f"Failed to update stealth target_movement: {stealth_order_id}")
                    await websocket.send(json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to update stealth target_movement: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update target movement: {str(e)}"
                }
                add_log_entry("ERROR", f"Stealth target_movement update failed: {str(e)}")
                await websocket.send(json.dumps(response))

        elif msg_type == "reprice_now_stealth_order":
            # Immediately trigger anchor repricing for a single stealth order,
            # bypassing the next_reprice_at cooldown.
            stealth_order_id = data.get("stealth_order_id")
            if not stealth_order_id or not stealth_order_bridge:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Missing stealth_order_id or system not initialised"
                }))
                return

            try:
                mgr = stealth_order_bridge.stealth_manager
                order = mgr.in_memory_orders.get(stealth_order_id)
                if not order:
                    await websocket.send(json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": "Order not found"
                    }))
                    return

                policy = RepricingPolicy.from_anchor_repricing_policy_dict(
                    order.get("anchor_repricing_policy_json")
                )
                capability = evaluate_product_capability(
                    product_id=order.get("product_id", ""),
                    capability=ProductCapability.REPRICE_REVEALED,
                )
                if not capability.allowed:
                    await websocket.send(json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": capability.reason,
                        "capability": capability.to_dict(),
                    }))
                    return

                if not policy.enabled:
                    await websocket.send(json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": "Anchor repricing not enabled for this order"
                    }))
                    return

                active_statuses = {"HIDDEN", "PENDING", "TRIGGERED", "REVEALED"}
                if order.get("status") not in active_statuses:
                    await websocket.send(json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": f"Order status {order.get('status')} is not repriceable"
                    }))
                    return

                # Clear the cooldown so process_anchor_repricing_for_product won't skip it
                state = mgr._normalize_anchor_repricing_state(order.get("anchor_repricing_state_json"))
                state.pop("next_reprice_at", None)
                order["anchor_repricing_state_json"] = state

                product_id = order.get("product_id", "")
                processed = mgr.process_anchor_repricing_for_product(product_id)

                add_log_entry("INFO", f"Manual reprice triggered for {stealth_order_id}: processed={processed}")
                logger.info(f"[REPRICE-NOW] {stealth_order_id} processed={processed}")

                await websocket.send(json.dumps({
                    "type": "reprice_now_result",
                    "stealth_order_id": stealth_order_id,
                    "processed": processed
                }))

            except Exception as e:
                logger.error(f"reprice_now_stealth_order failed: {e}")
                await websocket.send(json.dumps({
                    "type": "reprice_now_result",
                    "stealth_order_id": stealth_order_id,
                    "processed": 0,
                    "error": str(e)
                }))

        elif msg_type == "move_revealed_stealth_order":
            # Move a REVEALED stealth order to a new limit price by
            # cancelling the existing exchange placement and re-placing
            # at the new price. Mutually exclusive with anchor repricing
            # for the same sid (enforced by StealthMutationKind claim).
            #
            # Inbound shape:
            #   {
            #     "type": "move_revealed_stealth_order",
            #     "stealth_order_id": "sid_xyz",
            #     "new_limit_price": 101.5,
            #     "reason":  "manual_user_move" | "operator_reprice",  # optional
            #     "notes":   "...",                                    # optional
            #     "new_target_movement": 0.2,                          # optional
            #     "new_target_movement_type": "P" | "$"                # optional
            #   }
            stealth_order_id = data.get("stealth_order_id")
            new_limit_price = data.get("new_limit_price")
            reason_raw = data.get("reason")
            notes = data.get("notes")
            new_target_movement = data.get("new_target_movement")
            new_target_movement_type = data.get("new_target_movement_type")

            if not stealth_order_id or new_limit_price is None or not stealth_order_bridge:
                await websocket.send(json.dumps({
                    "type": "stealth_order_moved",
                    "stealth_order_id": stealth_order_id,
                    "success": False,
                    "error": "Missing stealth_order_id / new_limit_price or system not initialised",
                    "stage": "validate",
                }))
                return

            try:
                from core.enums import StealthMoveReason
                from core.exceptions import StealthMoveError

                # Resolve reason enum at the boundary (P2 rule #5: enums, not magic strings).
                reason_enum = None
                if reason_raw:
                    try:
                        reason_enum = StealthMoveReason(reason_raw)
                    except ValueError:
                        await websocket.send(json.dumps({
                            "type": "stealth_order_moved",
                            "stealth_order_id": stealth_order_id,
                            "success": False,
                            "error": (
                                f"unknown reason {reason_raw!r}; "
                                f"expected one of: "
                                f"{[r.value for r in StealthMoveReason]}"
                            ),
                            "stage": "validate",
                        }))
                        return

                mgr = stealth_order_bridge.stealth_manager
                plan = mgr.build_stealth_move_plan(
                    stealth_order_id,
                    safe_float(new_limit_price, default=0.0),
                    new_target_movement=(
                        safe_float(new_target_movement, default=None)
                        if new_target_movement is not None else None
                    ),
                    new_target_movement_type=new_target_movement_type,
                    reason=reason_enum,
                    notes=notes,
                )
                # execute_stealth_move returns a StealthMoveResult with
                # both the internal client_order_id (used for tracking,
                # per AGENTS.md) and the exchange order_id (shown to the
                # operator so they can cross-reference on Coinbase).
                result = mgr.execute_stealth_move(plan)

                add_log_entry(
                    "INFO",
                    f"Stealth order moved: {stealth_order_id} "
                    f"@ {plan.new_configured_limit_price} "
                    f"(new placement_client_order_id: "
                    f"{result.new_placement_client_order_id}, "
                    f"new exchange_order_id: {result.new_exchange_order_id})",
                )
                logger.info(
                    f"[STEALTH-MOVE] {stealth_order_id} "
                    f"old_ex={plan.old_exchange_order_id} "
                    f"new_placement_client_order_id={result.new_placement_client_order_id} "
                    f"new_exchange_order_id={result.new_exchange_order_id} "
                    f"price={plan.new_configured_limit_price}"
                )

                response = {
                    "type": "stealth_order_moved",
                    "stealth_order_id": stealth_order_id,
                    "success": True,
                    "old_exchange_order_id": plan.old_exchange_order_id,
                    "new_placement_client_order_id": result.new_placement_client_order_id,
                    "new_exchange_order_id": result.new_exchange_order_id,
                    "new_submitted_price": result.new_submitted_price,
                }
                # Broadcast so any other connected dashboards refresh too.
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)

            except StealthMoveError as e:
                # Stage tells the UI which phase failed: validate / claim /
                # cancel / place / persist. "place" after a successful
                # cancel is the operator-action-required case (the stealth
                # order is now CANCELLED and there is no replacement on
                # the exchange — see audit table stealth_order_moves).
                logger.warning(
                    f"move_revealed_stealth_order rejected: "
                    f"sid={stealth_order_id} stage={e.stage} err={e}"
                )
                add_log_entry(
                    "WARN" if e.stage in ("validate", "claim") else "ERROR",
                    f"Stealth move {stealth_order_id} failed at {e.stage}: {e}",
                )
                await websocket.send(json.dumps({
                    "type": "stealth_order_moved",
                    "stealth_order_id": stealth_order_id,
                    "success": False,
                    "error": str(e),
                    "stage": e.stage,
                }))
            except Exception as e:
                logger.exception(f"move_revealed_stealth_order crashed: {e}")
                add_log_entry(
                    "ERROR",
                    f"Stealth move {stealth_order_id} crashed: {e}",
                )
                await websocket.send(json.dumps({
                    "type": "stealth_order_moved",
                    "stealth_order_id": stealth_order_id,
                    "success": False,
                    "error": str(e),
                    "stage": "unknown",
                }))

        elif msg_type == "update_stealth_price_threshold":
            # Update price threshold for a price-based stealth order
            stealth_order_id = data.get("stealth_order_id")
            price_threshold = data.get("price_threshold")
            hold_duration_seconds = data.get("hold_duration_seconds")  # optional

            if not stealth_order_id:
                response = {
                    "type": "error",
                    "message": "Missing stealth_order_id"
                }
                await websocket.send(json.dumps(response))
                return

            if price_threshold is None:
                response = {
                    "type": "error",
                    "message": "Missing price_threshold"
                }
                await websocket.send(json.dumps(response))
                return

            try:
                threshold = float(price_threshold)
            except (TypeError, ValueError):
                response = {
                    "type": "error",
                    "message": "price_threshold must be numeric"
                }
                await websocket.send(json.dumps(response))
                return

            if threshold <= 0:
                response = {
                    "type": "error",
                    "message": "price_threshold must be greater than 0"
                }
                await websocket.send(json.dumps(response))
                return

            # Validate optional hold_duration_seconds
            hold_secs = None
            if hold_duration_seconds is not None:
                try:
                    hold_secs = int(hold_duration_seconds)
                    if hold_secs < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    response = {
                        "type": "error",
                        "message": "hold_duration_seconds must be a non-negative integer"
                    }
                    await websocket.send(json.dumps(response))
                    return

            try:
                from database.order import get_stealth_order_by_id, update_stealth_order_price_threshold

                existing = get_stealth_order_by_id(stealth_order_id)
                if not existing:
                    response = {
                        "type": "error",
                        "message": f"Stealth order not found: {stealth_order_id}"
                    }
                    await websocket.send(json.dumps(response))
                    return

                if str(existing.get("reveal_condition_type", "")).lower() != "price":
                    response = {
                        "type": "error",
                        "message": "Threshold updates are only supported for price reveal conditions"
                    }
                    await websocket.send(json.dumps(response))
                    return

                hold_duration_persisted = hold_secs is None
                try:
                    if hold_secs is None:
                        success = update_stealth_order_price_threshold(
                            stealth_order_id=stealth_order_id,
                            price_threshold=threshold,
                        )
                    else:
                        success = update_stealth_order_price_threshold(
                            stealth_order_id=stealth_order_id,
                            price_threshold=threshold,
                            hold_duration_seconds=hold_secs,
                        )
                        hold_duration_persisted = True
                except TypeError as type_err:
                    # Backward compatibility for stale/legacy runtime where the helper
                    # still accepts only (stealth_order_id, price_threshold).
                    if "unexpected keyword argument 'hold_duration_seconds'" not in str(type_err):
                        raise

                    logger.warning(
                        "update_stealth_order_price_threshold loaded without hold_duration_seconds support; retrying threshold-only update"
                    )
                    success = update_stealth_order_price_threshold(
                        stealth_order_id=stealth_order_id,
                        price_threshold=threshold,
                    )
                    hold_duration_persisted = False

                if not success:
                    response = {
                        "type": "error",
                        "message": f"Failed to update threshold for stealth order: {stealth_order_id}"
                    }
                    await websocket.send(json.dumps(response))
                    return

                # Sync in-memory cache
                if stealth_order_bridge:
                    in_mem = stealth_order_bridge.stealth_manager.in_memory_orders.get(stealth_order_id)
                    if in_mem is not None:
                        reveal_json = in_mem.get("reveal_condition_json") or {}
                        reveal_json["price_threshold"] = threshold
                        if hold_secs is not None and hold_duration_persisted:
                            reveal_json["hold_duration_seconds"] = hold_secs
                        in_mem["reveal_condition_json"] = reveal_json

                # Sync state payload cache
                with state_lock:
                    if stealth_order_id in engine_state["stealth_orders"]:
                        state_order = engine_state["stealth_orders"][stealth_order_id]
                        reveal_json = state_order.get("reveal_condition_json") or {}
                        reveal_json["price_threshold"] = threshold
                        if hold_secs is not None and hold_duration_persisted:
                            reveal_json["hold_duration_seconds"] = hold_secs
                        state_order["reveal_condition_json"] = reveal_json

                response = {
                    "type": "stealth_threshold_updated",
                    "stealth_order_id": stealth_order_id,
                    "price_threshold": threshold,
                    "hold_duration_seconds": hold_secs if hold_duration_persisted else None,
                }

                add_log_entry("INFO", f"Stealth threshold updated: {stealth_order_id} -> {threshold}" + (f", hold={hold_secs}s" if hold_secs is not None else ""))
                logger.info(f"Stealth threshold updated: {stealth_order_id} -> {threshold}" + (f", hold={hold_secs}s" if hold_secs is not None else ""))

                message = json.dumps(response, cls=CustomJSONEncoder)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)

                await websocket.send(json.dumps({"type": "update_success", "message": "Threshold updated"}))

            except Exception as e:
                logger.error(f"Failed to update stealth threshold: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update threshold: {str(e)}"
                }
                add_log_entry("ERROR", f"Stealth threshold update failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "update_parent_target_movement":
            # Update target movement for a parent order
            parent_order_id = data.get("parent_order_id")
            target_movement = data.get("target_movement")
            target_movement_type = data.get("target_movement_type", "P")
            
            if not parent_order_id:
                response = {
                    "type": "error",
                    "message": "Missing parent_order_id"
                }
                await websocket.send(json.dumps(response))
                return
            
            try:
                from database.order import update_parent_order_target_movement, get_parent_order
                
                # Update in database (order_parent table is source of truth for target_movement)
                success = update_parent_order_target_movement(
                    parent_order_id=parent_order_id,
                    target_movement=target_movement,
                    target_movement_type=target_movement_type
                )
                
                if success:
                    # Sync to in-memory cache for fast access
                    if stealth_order_bridge:
                        stealth_order_bridge.stealth_manager.sync_target_movement_to_cache(
                            parent_order_id,
                            target_movement,
                            target_movement_type
                        )
                    
                    response = {
                        "type": "parent_target_movement_updated",
                        "parent_order_id": parent_order_id,
                        "target_movement": target_movement,
                        "target_movement_type": target_movement_type
                    }
                    
                    add_log_entry("INFO", f"Parent order target_movement updated: {parent_order_id} = {target_movement}{target_movement_type}")
                    logger.info(f"Parent order target_movement updated: {parent_order_id} = {target_movement}{target_movement_type}")
                    
                    # Broadcast to all clients
                    message = json.dumps(response, cls=CustomJSONEncoder)
                    for client in connected_clients.copy():
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            connected_clients.discard(client)
                    
                    await websocket.send(json.dumps({"type": "update_success", "message": "Parent target movement updated"}))
                else:
                    response = {
                        "type": "error",
                        "message": f"Failed to update parent order: {parent_order_id}"
                    }
                    add_log_entry("ERROR", f"Failed to update parent target_movement: {parent_order_id}")
                    await websocket.send(json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to update parent target_movement: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update parent target movement: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent target_movement update failed: {str(e)}")
                await websocket.send(json.dumps(response))

        elif msg_type == "request_hotpoint_state":
            # Hotpoint Auto-Replicate: full UI snapshot.
            # Returns kill switch + config + active buckets + recent
            # auto-placements. Polled by the hotpoint manager UI.
            try:
                engine = (
                    stealth_order_bridge.order_engine
                    if stealth_order_bridge
                    and getattr(stealth_order_bridge, "order_engine", None)
                    else None
                )
                if engine is None:
                    await websocket.send(json.dumps({
                        "type": "hotpoint_state",
                        "available": False,
                        "error": "engine_not_initialized",
                    }))
                else:
                    snap = engine.get_hotpoint_state_snapshot()
                    await websocket.send(json.dumps({
                        "type": "hotpoint_state",
                        "available": True,
                        "state": snap,
                    }))
            except Exception as e:
                logger.error(f"hotpoint_state request failed: {e}")
                await websocket.send(json.dumps({
                    "type": "hotpoint_state",
                    "available": False,
                    "error": str(e),
                }))

        elif msg_type == "set_hotpoint_kill_switch":
            # Flip the runtime kill switch. {enabled: bool}
            requested = bool(data.get("enabled", False))
            try:
                engine = (
                    stealth_order_bridge.order_engine
                    if stealth_order_bridge
                    and getattr(stealth_order_bridge, "order_engine", None)
                    else None
                )
                if engine is None:
                    await websocket.send(json.dumps({
                        "type": "hotpoint_kill_switch_response",
                        "success": False,
                        "error": "engine_not_initialized",
                    }))
                else:
                    engine.set_hotpoint_auto_place_enabled(requested)
                    add_log_entry(
                        "INFO",
                        f"Hotpoint auto-place {'ENABLED' if requested else 'DISABLED'} via UI",
                    )
                    await websocket.send(json.dumps({
                        "type": "hotpoint_kill_switch_response",
                        "success": True,
                        "enabled": engine.is_hotpoint_auto_place_enabled(),
                    }))
            except Exception as e:
                logger.error(f"set_hotpoint_kill_switch failed: {e}")
                await websocket.send(json.dumps({
                    "type": "hotpoint_kill_switch_response",
                    "success": False,
                    "error": str(e),
                }))

        elif msg_type == "place_hotpoint_test_order":
            # Place a normal limit order with enable_hotpoint_replication=True.
            # Used to seed the detector for live testing. Payload:
            #   {product_id, side, price, size}
            payload = data.get("order") or {}
            product_id = str(payload.get("product_id") or "").strip()
            try:
                side = OrderSide(str(payload.get("side") or "").upper()).value
            except ValueError:
                side = ""
            try:
                price = float(payload.get("price"))
                size = float(payload.get("size"))
            except (TypeError, ValueError):
                price = size = 0.0

            if not (product_id and side and price > 0 and size > 0):
                await websocket.send(json.dumps({
                    "type": "place_hotpoint_test_order_response",
                    "success": False,
                    "error": "invalid_payload",
                }))
                return

            if not REST_CLIENT_AVAILABLE:
                await websocket.send(json.dumps({
                    "type": "place_hotpoint_test_order_response",
                    "success": False,
                    "error": "rest_client_unavailable",
                }))
                return

            client_order_id = None
            parent_row_inserted = False
            update_parent_status = None
            try:
                from calculation.size_validation import validate_and_quantize_size
                from database.order import insert_order_parent, update_order_parent_status
                from core.enums import OrderStatus
                import uuid as _uuid

                update_parent_status = update_order_parent_status
                client_order_id = str(_uuid.uuid4())
                capability = evaluate_product_capability(
                    product_id=product_id,
                    capability=ProductCapability.HOTPOINT_AUTO_PLACEMENT,
                )
                if not capability.allowed:
                    message = (
                        "Hotpoint test order rejected by product capability policy: "
                        f"{capability.reason}"
                    )
                    add_log_entry("WARNING", message)
                    await websocket.send(json.dumps({
                        "type": "place_hotpoint_test_order_response",
                        "success": False,
                        "error": "product_capability_blocked",
                        "message": message,
                        "capability": capability.to_dict(),
                    }))
                    return

                size_check = validate_and_quantize_size(
                    size,
                    product_id=product_id,
                    price=price,
                )
                if not size_check:
                    message = (
                        "Hotpoint test order rejected at boundary: "
                        f"{size_check.reason}"
                    )
                    add_log_entry("WARNING", message)
                    await websocket.send(json.dumps({
                        "type": "place_hotpoint_test_order_response",
                        "success": False,
                        "error": "size_validation_failed",
                        "message": message,
                    }))
                    return
                approved_size = size_check.size

                guard_ok, guard_failure = ActionConditionGuard(
                    planned_budget_fetcher=(
                        _get_dashboard_spot_planned_budget_commitments
                    ),
                    lot_authority_evaluator=(
                        _get_dashboard_spot_lot_authority_evaluator()
                    ),
                ).evaluate(
                    phase=ActionGuardPhase.PLANNING,
                    product_id=product_id,
                    side=side,
                    size=approved_size,
                    limit_price=price,
                    client_order_id=client_order_id,
                )
                if not guard_ok:
                    reason = (guard_failure or {}).get("reason", "blocked")
                    message = (
                        "Hotpoint test order rejected by action-condition guard: "
                        f"{reason}"
                    )
                    add_log_entry("WARNING", message)
                    await websocket.send(json.dumps({
                        "type": "place_hotpoint_test_order_response",
                        "success": False,
                        "error": "action_condition_guard_blocked",
                        "message": message,
                        "guard": guard_failure,
                    }))
                    return

                # Pre-insert order_parent row with the opt-in flag set.
                # Auto-placed children of this order will spawn from the
                # engine's hotpoint dispatcher when fills accumulate.
                parent_id = insert_order_parent(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    size=approved_size,
                    price=price,
                    target_movement=0.0,
                    target_movement_type="P",
                    max_order_replacement=0,
                    current_order_replacement=0,
                    status=OrderStatus.PENDING.value,
                    parent_order_id=None,
                    allow_partial_fills=False,
                    enable_hotpoint_replication=True,
                    auto_placed_by_hotpoint=False,
                )
                if parent_id is None:
                    raise OrderCreationError(
                        "failed to pre-insert hotpoint test parent order",
                        client_order_id=client_order_id,
                    )
                parent_row_inserted = True

                order_configuration = {
                    "limit_limit_gtc": {
                        "base_size": str(approved_size),
                        "limit_price": str(price),
                        "post_only": False,
                    },
                }
                # Submit GTC limit on the exchange.
                with controller.track_inflight(INFLIGHT_REST_PLACE):
                    result = REST_CLIENT.limit_order_gtc(
                        product_id=product_id,
                        side=side,
                        base_size=str(approved_size),
                        limit_price=str(price),
                        client_order_id=client_order_id,
                        post_only=False,
                    )

                result_dict = _coinbase_order_response_to_dict(result)
                response_success = _coinbase_order_response_success(
                    result,
                    result_dict,
                )
                if response_success is False:
                    error_msg = _coinbase_order_response_error_message(
                        result,
                        result_dict,
                    )
                    raise CoinbaseAPIError(
                        f"Hotpoint test order creation failed: {error_msg}",
                        api_error_code="hotpoint_test_order_creation_failed",
                    )
                order_id = _coinbase_order_response_order_id(result, result_dict)
                submission_event_recorded = _publish_direct_order_submission_event(
                    client_order_id=client_order_id,
                    order_id=order_id,
                    order_params={"product_id": product_id, "side": side},
                    order_configuration=order_configuration,
                )
                add_log_entry(
                    "INFO",
                    f"Hotpoint test order placed: {client_order_id} {product_id} "
                    f"{side} {approved_size}@{price}",
                )
                await websocket.send(json.dumps({
                    "type": "place_hotpoint_test_order_response",
                    "success": True,
                    "client_order_id": client_order_id,
                    "order_id": order_id,
                    "submission_event_recorded": submission_event_recorded,
                }))
            except Exception as e:
                if parent_row_inserted and update_parent_status and client_order_id:
                    try:
                        update_parent_status(
                            client_order_id,
                            OrderStatus.FAILED.value,
                        )
                    except Exception as update_exc:
                        logger.error(
                            "failed to mark hotpoint test order parent FAILED: "
                            f"{update_exc}"
                        )
                logger.error(f"place_hotpoint_test_order failed: {e}")
                await websocket.send(json.dumps({
                    "type": "place_hotpoint_test_order_response",
                    "success": False,
                    "error": str(e),
                }))

        elif msg_type == "clear_all_stealth_orders":
            # Clear all stealth orders from BOTH the live engine (memory) and
            # the database. Without the in-memory step the reveal evaluator
            # in stealth_order_bridge keeps polling _get_active_stealth_orders()
            # and continues firing reveals on the exchange even after the DB
            # rows are gone. Route every order through the same cancel path
            # used for single-order cancel so the lifecycle (status flip,
            # DB sync, lifecycle event dispatch) stays single-sourced.
            try:
                from database.order import clear_all_stealth_orders

                cancelled_in_memory = 0
                cancel_failures = 0
                if stealth_order_bridge is not None:
                    mgr = stealth_order_bridge.stealth_manager
                    # Snapshot ids first; cancel mutates in_memory_orders state.
                    active_ids = list(mgr.in_memory_orders.keys())
                    for sid in active_ids:
                        try:
                            if stealth_order_bridge.cancel_stealth_order(
                                sid, reason="Clear All Orders (dashboard)"
                            ):
                                cancelled_in_memory += 1
                        except Exception as cancel_exc:
                            cancel_failures += 1
                            logger.error(
                                f"Clear All: failed to cancel stealth order {sid}: {cancel_exc}"
                            )
                    # Defensive: drop any cached entries (including terminal-status
                    # rows the cancel path skipped) so the engine can no longer
                    # touch them after the DB wipe below.
                    mgr.in_memory_orders.clear()
                    mgr._placed_order_index.clear()

                result = clear_all_stealth_orders()

                if result["success"]:
                    # Clear dashboard's view-copy as well
                    with state_lock:
                        engine_state["stealth_orders"] = {}

                    response = {
                        "type": "stealth_orders_cleared",
                        "rows_deleted": result["rows_deleted"],
                        "in_memory_cancelled": cancelled_in_memory,
                        "in_memory_cancel_failures": cancel_failures,
                        "message": result["message"]
                    }

                    add_log_entry(
                        "INFO",
                        f"All stealth orders cleared - {result['rows_deleted']} DB rows, "
                        f"{cancelled_in_memory} in-memory cancelled, "
                        f"{cancel_failures} cancel failures"
                    )
                    logger.info(
                        f"All stealth orders cleared - {result['rows_deleted']} DB rows, "
                        f"{cancelled_in_memory} in-memory cancelled, "
                        f"{cancel_failures} cancel failures"
                    )
                    
                    # Broadcast to all clients
                    message = json.dumps(response)
                    for client in connected_clients.copy():
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            connected_clients.discard(client)
                else:
                    response = {
                        "type": "error",
                        "message": f"Failed to clear orders: {result.get('error', 'Unknown error')}"
                    }
                    add_log_entry("ERROR", f"Failed to clear stealth orders: {result.get('error')}")
                    await websocket.send(json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to clear stealth orders: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to clear orders: {str(e)}"
                }
                add_log_entry("ERROR", f"Clear stealth orders failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "request_parent_orders":
            # Send parent orders list
            try:
                from database.order_dashboard_helpers import get_all_parent_orders
                orders = get_all_parent_orders()
                
                # Convert to dict keyed by client_order_id
                orders_dict = {o['client_order_id']: o for o in orders}
                
                response = {
                    "type": "parent_orders_list",
                    "orders": orders_dict
                }
                await websocket.send(json.dumps(response))
                logger.info(f"Sent {len(orders)} parent orders to client")
                
            except Exception as e:
                logger.error(f"Failed to fetch parent orders: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to fetch orders: {str(e)}"
                }
                await websocket.send(json.dumps(response))
        
        elif msg_type == "create_parent_order":
            # Create new parent order
            try:
                from database.order_dashboard_helpers import insert_parent_order, get_parent_order_by_client_id
                order = data.get("order", {})
                
                client_order_id = str(uuid.uuid4())
                
                result = insert_parent_order(
                    client_order_id=client_order_id,
                    product_id=order.get('product_id'),
                    side=order.get('side'),
                    size=float(order.get('size', 0)),
                    price=float(order.get('price', 0)),
                    target_movement=float(order.get('target_movement')) if order.get('target_movement') else None,
                    max_order_replacement=int(order.get('max_order_replacement', 0)),
                    status=order.get('status', 'OPEN')
                )
                
                # Fetch the created order
                created_order = get_parent_order_by_client_id(client_order_id)
                
                response = {
                    "type": "parent_order_created",
                    "order": created_order
                }
                
                add_log_entry("INFO", f"Parent order created: {order.get('product_id')} {order.get('side')} {order.get('size')}")
                logger.info(f"Parent order created: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to create parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to create order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order creation failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "update_parent_order":
            # Update existing parent order
            try:
                from database.order_dashboard_helpers import update_parent_order, get_parent_order_by_client_id
                order = data.get("order", {})
                
                client_order_id = order.get('client_order_id')
                update_data = {
                    'size': float(order.get('size', 0)),
                    'price': float(order.get('price', 0)),
                    'target_movement': float(order.get('target_movement')) if order.get('target_movement') else None,
                    'max_order_replacement': int(order.get('max_order_replacement', 0)),
                    'status': order.get('status', 'OPEN')
                }
                
                update_parent_order(client_order_id, update_data)
                
                # Fetch the updated order
                updated_order = get_parent_order_by_client_id(client_order_id)
                
                response = {
                    "type": "parent_order_updated",
                    "order": updated_order
                }
                
                add_log_entry("INFO", f"Parent order updated: {client_order_id}")
                logger.info(f"Parent order updated: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to update parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order update failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "delete_parent_order":
            # Delete parent order
            try:
                from database.order_dashboard_helpers import delete_parent_order
                client_order_id = data.get('client_order_id')
                
                delete_parent_order(client_order_id)
                
                response = {
                    "type": "parent_order_deleted",
                    "client_order_id": client_order_id
                }
                
                add_log_entry("INFO", f"Parent order deleted: {client_order_id}")
                logger.info(f"Parent order deleted: {client_order_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to delete parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to delete order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order deletion failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "request_products":
            # Send products list to client
            try:
                products_file = Path(__file__).parent / "products.json"
                if products_file.exists():
                    with open(products_file, 'r') as f:
                        products_data = json.load(f)
                        response = {
                            "type": "products_list",
                            "derivatives": products_data.get("derivatives", []),
                            "spot": products_data.get("spot", []),
                        }
                        await websocket.send(json.dumps(response))
                else:
                    logger.warning("products.json not found")
                    response = {
                        "type": "products_list",
                        "derivatives": [],
                        "spot": [],
                    }
                    await websocket.send(json.dumps(response))
            except Exception as e:
                logger.error(f"Failed to send products: {e}")
                response = {"type": "error", "message": f"Failed to load products: {str(e)}"}
                await websocket.send(json.dumps(response))
        
        elif msg_type == "request_move_history":
            # Send move history list
            try:
                from database.order import get_order_moves_by_original_parent
                # Get all moves from database (fetch all to show complete history)
                # For now, we'll fetch from database directly
                from database.database import PostgresDB
                from database.order_dashboard_helpers import _serialize_for_json
                db = PostgresDB()
                result = db.execute_query("SELECT * FROM order_moves ORDER BY created_at DESC LIMIT 100")
                
                moves_dict = {move['id']: move for move in result} if result else {}
                
                response = {
                    "type": "move_history_list",
                    "moves": _serialize_for_json(moves_dict)
                }
                await websocket.send(json.dumps(response))
                logger.info(f"Sent {len(result or [])} move records to client")

            except Exception as e:
                logger.error(f"Failed to fetch move history: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to fetch move history: {str(e)}"
                }
                await websocket.send(json.dumps(response))
        
        elif msg_type == "move_order":
            # Execute a manual move (immediate)
            try:
                from business.move_manager import MoveManager
                from configuration import OrderBook
                
                move_data = data.get("move", {})
                original_parent_id = move_data.get('original_parent_client_order_id')
                new_order_details = move_data.get('new_order_details', {})
                reason = move_data.get('reason', 'user_move')
                notes = move_data.get('notes')
                
                # Create move manager and execute move
                move_manager = MoveManager(OrderBook())
                result = move_manager.move_order(
                    original_parent_client_order_id=original_parent_id,
                    new_order_details=new_order_details,
                    reason=reason,
                    notes=notes
                )
                
                if result['success']:
                    # The new parent order was already created by move_order()
                    # Just fetch it to send back to client
                    from database.order_dashboard_helpers import get_parent_order_by_client_id
                    new_parent_id = result['new_parent_client_order_id']
                    new_parent_order = get_parent_order_by_client_id(new_parent_id)
                    
                    response = {
                        "type": "order_moved",
                        "success": True,
                        "original_parent_client_order_id": original_parent_id,
                        "new_parent_client_order_id": new_parent_id,
                        "new_parent_order": new_parent_order,
                        "message": f"Order moved successfully"
                    }
                    
                    add_log_entry("INFO", f"Order moved: {original_parent_id} -> {new_parent_id}")
                    logger.info(f"Order moved: {original_parent_id} -> {new_parent_id}")
                else:
                    response = {
                        "type": "error",
                        "message": f"Move failed: {result.get('message', 'Unknown error')}"
                    }
                    add_log_entry("ERROR", f"Move failed: {result.get('message')}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to move order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to move order: {str(e)}"
                }
                add_log_entry("ERROR", f"Order move failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "premark_move":
            # Pre-mark an order for automatic move (when cancelled)
            try:
                from database.order import create_pending_move
                
                move_data = data.get("move", {})
                parent_id = move_data.get('parent_client_order_id')
                new_order_details = move_data.get('new_order_details', {})
                notes = move_data.get('notes')
                
                # Create pending move record in database
                move_id = create_pending_move(
                    parent_client_order_id=parent_id,
                    new_order_config=new_order_details,
                    reason='premarked_auto_move',
                    notes=notes
                )
                
                response = {
                    "type": "order_premarked",
                    "success": True,
                    "parent_client_order_id": parent_id,
                    "move_id": move_id,
                    "message": f"Order pre-marked for automatic move on cancellation"
                }
                
                add_log_entry("INFO", f"Order pre-marked for move: {parent_id}")
                logger.info(f"Order pre-marked for move: {parent_id}")
                
                # Broadcast to all clients
                message = json.dumps(response)
                for client in connected_clients.copy():
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        connected_clients.discard(client)
                
            except Exception as e:
                logger.error(f"Failed to pre-mark order for move: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to pre-mark order: {str(e)}"
                }
                add_log_entry("ERROR", f"Pre-mark failed: {str(e)}")
                await websocket.send(json.dumps(response))
        
        elif msg_type == "ping":
            response = {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
            await websocket.send(json.dumps(response))
        
        elif msg_type == "update_products_list":
            # Update products.json with latest data from REST API
            logger.info("Products list update requested")
            
            try:
                result = update_products_json_from_api()
                
                if result["success"]:
                    response = {
                        "type": "products_list_updated",
                        "status": "success",
                        "message": result["message"],
                        "derivatives_count": result["derivatives_count"],
                        "spot_count": result["spot_count"],
                        "metadata_count": result["metadata_count"],
                    }
                    add_log_entry("INFO", f"Products list updated: {result['derivatives_count']} derivatives, {result['spot_count']} spot products")
                    logger.info(f"Products updated successfully: {result['derivatives_count']} derivatives, {result['spot_count']} spot")
                else:
                    response = {
                        "type": "products_list_updated",
                        "status": "error",
                        "message": result["message"],
                        "derivatives_count": 0,
                        "spot_count": 0,
                        "metadata_count": 0,
                    }
                    add_log_entry("ERROR", f"Products list update failed: {result['message']}")
                
                # Send response to requesting client
                await websocket.send(json.dumps(response))
                
                # If successful, broadcast updated products to all clients
                if result["success"]:
                    try:
                        products_file = Path(__file__).parent / "products.json"
                        if products_file.exists():
                            with open(products_file, 'r') as f:
                                products_data = json.load(f)
                                broadcast_payload = {
                                    "type": "products_list",
                                    "derivatives": products_data.get("derivatives", []),
                                    "spot": products_data.get("spot", []),
                                    "metadata": products_data.get("metadata", {}),
                                }
                                
                                # Broadcast to all connected clients
                                message = json.dumps(broadcast_payload)
                                for client in connected_clients.copy():
                                    try:
                                        await client.send(message)
                                    except websockets.exceptions.ConnectionClosed:
                                        connected_clients.discard(client)
                    except Exception as e:
                        logger.error(f"Failed to broadcast updated products: {e}")
                
            except Exception as e:
                logger.error(f"Products list update failed: {str(e)}")
                response = {
                    "type": "products_list_updated",
                    "status": "error",
                    "message": f"Failed to update products: {str(e)}",
                    "derivatives_count": 0,
                    "spot_count": 0,
                    "metadata_count": 0,
                }
                add_log_entry("ERROR", f"Products update exception: {str(e)}")
                await websocket.send(json.dumps(response))
            
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON received: {message}")


async def handler(websocket: WebSocketServerProtocol, path: str):
    """Main WebSocket connection handler."""
    await register_client(websocket)
    
    try:
        async for message in websocket:
            await handle_client_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        await unregister_client(websocket)


def update_order(order_id: str, order_data: Dict[str, Any]):
    """Update order in dashboard state."""
    with state_lock:
        engine_state["orders"][order_id] = {
            **order_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
    _trigger_broadcast()


def update_position(product_id: str, position_data: Dict[str, Any]):
    """Update position in dashboard state."""
    with state_lock:
        engine_state["positions"][product_id] = {
            **position_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
    _trigger_broadcast()


def update_engine_status(status_data: Dict[str, Any]):
    """Update engine status in dashboard state."""
    with state_lock:
        engine_state["engine_status"].update(status_data)
        engine_state["engine_status"]["last_update"] = datetime.utcnow().isoformat()
    _trigger_broadcast()


def add_log_entry(level: str, message: str, context: Dict[str, Any] = None):
    """Add log entry to dashboard for UI display and storage.
    
    Note: Console output is handled by Python's logging module, not here.
    This function only stores the log entry in engine_state for the dashboard UI.
    """
    # Store in engine state for UI
    with state_lock:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        engine_state["logs"].append(entry)
        # Keep only recent logs
        if len(engine_state["logs"]) > max_logs:
            engine_state["logs"] = engine_state["logs"][-max_logs:]
    _trigger_broadcast()


def update_products_json_from_api() -> Dict[str, Any]:
    """Update products.json with the latest data from Coinbase REST API.
    
    Fetches current product metadata for derivatives and spot products,
    organizes them by type, and updates the products.json file while
    preserving the ticker_to_trading mapping if it exists.
    
    Returns:
        Dictionary with status information:
        {
            "success": bool,
            "message": str,
            "derivatives_count": int,
            "spot_count": int,
            "metadata_count": int
        }
    
    Raises:
        Exception: If REST API call fails
    """
    try:
        # Fetch all products from REST API
        api_products = rest_get_products()
        logger.info(f"Fetched {len(api_products)} products from REST API")
        
        # Separate derivatives and spot products
        derivatives = []
        spot = []
        metadata = {}
        
        for product_id, product_data in api_products.items():
            # Determine product type
            product_type = product_data.get("product_type", "").upper()
            
            if product_type == "PERPETUAL_FUTURE" or product_type == "FUTURE":
                derivatives.append(product_id)
            else:
                # Default to SPOT for any other type
                spot.append(product_id)
            
            # Extract metadata for this product
            metadata[product_id] = {
                "type": product_type if product_type in ["SPOT", "FUTURE", "PERPETUAL_FUTURE"] else "UNKNOWN",
                "base_currency": product_data.get("base_currency"),
                "quote_currency": product_data.get("quote_currency"),
                "base_increment": str(product_data.get("base_increment", "")),
                "quote_increment": str(product_data.get("quote_increment", "")),
                "price_increment": str(product_data.get("price_increment", "")),
                # Min order sizes from the API. Persisted so the size-validation
                # path (calculation/size_validation.py) can reject too-small
                # orders before they hit the exchange. If the API returns
                # nothing the field is preserved as an empty string and
                # validators treat it as "no minimum advertised".
                "base_min_size": str(product_data.get("base_min_size", "")),
                "quote_min_size": str(product_data.get("quote_min_size", "")),
                "display_name": product_data.get("display_name"),
                "status": product_data.get("status"),
                "mid_price": product_data.get("mid_price"),
                "trading_disabled": product_data.get("trading_disabled", False),
                "contract_size": str(product_data.get("contract_size", "")) if "contract_size" in product_data else None,
                "expiry": product_data.get("expiry"),
            }
        
        # Load existing products.json to preserve ticker_to_trading mapping
        products_file = Path(__file__).parent / "products.json"
        existing_data = {}
        
        if products_file.exists():
            try:
                with open(products_file, 'r') as f:
                    existing_data = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read existing products.json: {e}")
        
        # Build the updated products data with desired key order
        # Put spot and derivatives at the top (human-managed), then metadata
        updated_data = {}
        updated_data["spot"] = sorted(spot)
        updated_data["derivatives"] = sorted(derivatives)
        
        # Preserve ticker_to_trading mapping if it exists
        if "ticker_to_trading" in existing_data:
            updated_data["ticker_to_trading"] = existing_data["ticker_to_trading"]
        
        # Add metadata last
        updated_data["metadata"] = metadata
        
        # Write updated data to products.json (preserve key order, don't sort)
        with open(products_file, 'w') as f:
            json.dump(updated_data, f, indent=2)
        
        logger.info(f"Updated products.json: {len(derivatives)} derivatives, {len(spot)} spot, {len(metadata)} metadata entries")
        
        return {
            "success": True,
            "message": f"Successfully updated products.json with {len(api_products)} products",
            "derivatives_count": len(derivatives),
            "spot_count": len(spot),
            "metadata_count": len(metadata),
        }
        
    except Exception as e:
        error_msg = f"Failed to update products.json: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "derivatives_count": 0,
            "spot_count": 0,
            "metadata_count": 0,
        }



async def _async_broadcast_ticker(ticker_data: Dict[str, Any]):
    """Async version of broadcast_ticker for scheduling from event loop."""
    payload = {
        "type": "ticker",
        "data": ticker_data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    message = json.dumps(payload)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def broadcast_ticker(
    product_id: str,
    price: float,
    price_24h: float = None,
    cb_time: Any = None,
):
    """Broadcast ticker/price update to all connected chart clients.

    Args:
        product_id: The product ID (e.g., 'BTC-USDC')
        price: Current price
        price_24h: Price 24 hours ago (optional, for % change calculation)
        cb_time: Coinbase upstream ticker time (ISO-8601 string from the
            Coinbase WS payload, e.g. ``"2026-05-01T16:07:21.234567Z"``,
            or a numeric epoch). Optional. When provided, the broadcast
            payload carries an extra ``cb_time_ms`` field so chart
            consumers can detect clock skew between this host and the
            authoritative Coinbase tick time. Silently dropped on parse
            failure — telemetry must never block a price broadcast.

    Example:
        >>> broadcast_ticker('BTC-USDC', 42500.50, 41200.00,
        ...                  cb_time='2026-05-01T16:07:21.234567Z')
    """
    global server_event_loop
    
    if not server_event_loop:
        # Server not started yet or stopping, silently skip
        return
    
    if not connected_clients:
        # No clients connected, nothing to broadcast
        return
    
    try:
        # NOTE: ``time`` field below is the legacy server-relay clock.
        # It is computed from ``datetime.utcnow().timestamp()`` which is
        # bugged on non-UTC hosts (naive UTC datetime gets reinterpreted
        # as local time before epoch conversion). We keep emitting it
        # for back-compat with the 8 dashboards that compensate for
        # that bug client-side via ``getTimezoneOffset()``.
        # ``server_time_ms`` (added below) is the honest tz-aware
        # equivalent — chart consumers should prefer it.
        ticker_data = {
            "product_id": product_id,
            "price": float(price),
            "time": datetime.utcnow().timestamp(),
            # New (additive) fields for clock-skew detection. Both are
            # epoch milliseconds, both true UTC.
            "server_time_ms": int(
                datetime.now(timezone.utc).timestamp() * 1000
            ),
        }

        if price_24h is not None:
            ticker_data["price_24h"] = float(price_24h)

        # Best-effort parse of the upstream Coinbase tick time. Chart
        # uses this to compute (server_time_ms − cb_time_ms), which is
        # the host↔Coinbase-feed skew the operator actually cares about.
        if cb_time is not None:
            cb_ms = _coerce_cb_time_to_epoch_ms(cb_time)
            if cb_ms is not None:
                ticker_data["cb_time_ms"] = cb_ms

        # Schedule on the event loop without blocking
        asyncio.run_coroutine_threadsafe(
            _async_broadcast_ticker(ticker_data),
            server_event_loop
        )
    except Exception as e:
        logger.debug(f"Failed to broadcast ticker: {e}")


def _coerce_cb_time_to_epoch_ms(value: Any) -> Optional[int]:
    """Best-effort parse of a Coinbase tick ``time`` value to epoch ms.

    Accepts:
      * ISO-8601 with trailing ``Z`` or numeric offset
        (e.g. ``"2026-05-01T16:07:21.234567Z"``)
      * float / int seconds since epoch (already true UTC)
      * float / int milliseconds since epoch

    Returns ``None`` on any parse failure — telemetry is best-effort.
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            # Heuristic: anything past 1e12 is already milliseconds
            # (year 2001 in seconds, year 33658 in ms — unambiguous).
            return int(v if v > 1e12 else v * 1000)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            # ``fromisoformat`` accepts ``Z`` suffix from Python 3.11+;
            # handle older inputs by normalising.
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                # Naive ISO string — assume UTC (Coinbase's contract).
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return None
    return None


# Spread monitoring for arbitrage detection
spread_data = {}  # product_id -> { bids: [prices], asks: [prices], last_window: timestamp }
spread_lock = Lock()


def record_spread_tick(product_id: str, bid: float, ask: float):
    """Record a bid/ask tick for spread monitoring.
    
    Args:
        product_id: The product ID (e.g., 'BTC-USDC')
        bid: Best bid price
        ask: Best ask price
    
    Example:
        >>> record_spread_tick('BTC-USDC', 42500.00, 42501.50)
    """
    global spread_data
    
    with spread_lock:
        if product_id not in spread_data:
            spread_data[product_id] = {
                'bids': [],
                'asks': [],
                'last_window': datetime.utcnow().timestamp(),
            }
        
        spread_data[product_id]['bids'].append(float(bid))
        spread_data[product_id]['asks'].append(float(ask))


async def _async_broadcast_spread(spread_snapshot: list):
    """Async version of broadcast_spread for scheduling from event loop."""
    payload = {
        "type": "spread_snapshot",
        "data": spread_snapshot,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    message = json.dumps(payload)
    
    for client in connected_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.discard(client)


def broadcast_spread():
    """Aggregate and broadcast 1-second spread averages to all connected clients.
    
    Calculates average bid/ask for each product over the last second and sends
    to all connected spread monitor clients.
    """
    global server_event_loop, spread_data
    
    if not server_event_loop or not connected_clients:
        return
    
    try:
        snapshot = []
        
        with spread_lock:
            for product_id, data in spread_data.items():
                if not data['bids'] or not data['asks']:
                    continue
                
                avg_bid = sum(data['bids']) / len(data['bids'])
                avg_ask = sum(data['asks']) / len(data['asks'])
                mid = (avg_bid + avg_ask) / 2
                
                snapshot.append({
                    'product_id': product_id,
                    'bid': round(avg_bid, 8),
                    'ask': round(avg_ask, 8),
                    'mid': round(mid, 8),
                })
                
                # Reset for next window
                data['bids'] = []
                data['asks'] = []
                data['last_window'] = datetime.utcnow().timestamp()
        
        if snapshot:
            asyncio.run_coroutine_threadsafe(
                _async_broadcast_spread(snapshot),
                server_event_loop
            )
    except Exception as e:
        logger.debug(f"Failed to broadcast spread: {e}")


async def send_stealth_orders_snapshot(websocket: WebSocketServerProtocol):
    """Send current stealth orders to a client."""
    try:
        with state_lock:
            # Enrich stealth orders with parent target_movement
            enriched_orders = _enrich_stealth_orders_with_parent_data(engine_state["stealth_orders"])
            
            # Phase 3: Calculate repricing statistics
            repricing_stats = _calculate_repricing_statistics(enriched_orders)
            
            payload = {
                "type": "stealth_orders_snapshot",
                "orders": enriched_orders,
                "repricing_stats": repricing_stats,
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        await websocket.send(json.dumps(payload, cls=CustomJSONEncoder))
    except Exception as e:
        logger.error(f"Failed to send stealth orders snapshot: {e}")


def _calculate_repricing_statistics(orders: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate repricing statistics from stealth orders.
    
    Returns:
        {
            "active_repricing_count": int,
            "total_reprices_executed": int,
            "breakdown_by_source": {
                <RepricingReferenceSource value>: int,
                ...
            },
        }
    """
    active_count = 0
    total_executed = 0
    breakdown: Dict[str, int] = {s.value: 0 for s in RepricingReferenceSource}

    for order_data in orders.values():
        if not isinstance(order_data, dict):
            continue

        # Build typed view of the policy. Disabled policies short-circuit
        # without touching any field except ``enabled``.
        policy = RepricingPolicy.from_anchor_repricing_policy_dict(
            order_data.get("anchor_repricing_policy_json")
        )
        if not policy.enabled:
            continue

        active_count += 1

        # Count reprices executed from state
        state = order_data.get("anchor_repricing_state_json") or {}
        history = state.get("reprice_history") or []
        total_executed += len(history)

        # Breakdown by reference source
        breakdown[policy.reference_price_source.value] += 1
    
    return {
        "active_repricing_count": active_count,
        "total_reprices_executed": total_executed,
        "breakdown_by_source": breakdown,
    }


def _enrich_stealth_orders_with_parent_data(orders: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich stealth orders with parent-related data.
    
    Args:
        orders: Dictionary of stealth_order_id -> order_data
    
    Returns:
        Same dictionary enriched with:
        - For child orders: parent_target_movement, parent_target_movement_type, parent_max_order_replacements
        - For parent orders: max_order_replacements from order_parent table
    """
    from database.order import get_parent_order
    
    enriched = {}
    for order_id, order_data in orders.items():
        enriched_order = order_data.copy() if isinstance(order_data, dict) else dict(order_data)
        
        # Check if this is a parent or child order
        parent_order_id = enriched_order.get("parent_order_id")
        
        if parent_order_id:
            # Child order: get parent's data by parent_order_id
            try:
                parent_data = get_parent_order(parent_order_id)
                if parent_data:
                    enriched_order["parent_target_movement"] = parent_data.get("target_movement")
                    enriched_order["parent_target_movement_type"] = parent_data.get("target_movement_type", "P")
                    enriched_order["parent_max_order_replacements"] = parent_data.get("max_order_replacement", 0)
            except Exception as e:
                logger.debug(f"Failed to enrich order {order_id} with parent data: {e}")
        else:
            # Parent order: look it up in order_parent using stealth_order_id as client_order_id
            # to get max_order_replacements (target_movement is already in stealth_order)
            try:
                parent_data = get_parent_order(order_id)
                if parent_data:
                    enriched_order["max_order_replacements"] = parent_data.get("max_order_replacement", 0)
                    # Also ensure we have the parent's target movement for consistent UI display
                    if not enriched_order.get("target_movement"):
                        enriched_order["target_movement"] = parent_data.get("target_movement")
                    if not enriched_order.get("target_movement_type"):
                        enriched_order["target_movement_type"] = parent_data.get("target_movement_type", "P")
            except Exception as e:
                logger.debug(f"Failed to enrich parent order {order_id}: {e}")
        
        enriched[order_id] = enriched_order
    
    return enriched


async def broadcast_stealth_order_update(update: Dict[str, Any]):
    """Broadcast stealth order update to all connected clients."""
    global server_event_loop
    
    if not server_event_loop or not connected_clients:
        return
    
    try:
        message = json.dumps(update, cls=CustomJSONEncoder)
        
        for client in connected_clients.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                connected_clients.discard(client)
    except Exception as e:
        logger.debug(f"Failed to broadcast stealth order update: {e}")


async def _stealth_orders_refresh_loop():
    """Background task to refresh stealth orders from database every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(30)
            
            # Reload active stealth orders from database
            if stealth_order_bridge:
                try:
                    # Get fresh orders from manager in JSON-serializable format
                    serialized_orders = stealth_order_bridge.stealth_manager.get_serializable_orders()
                    
                    # Enrich with parent target_movement data
                    enriched_orders = _enrich_stealth_orders_with_parent_data(serialized_orders)
                    
                    with state_lock:
                        # Update with enriched orders
                        engine_state["stealth_orders"] = enriched_orders
                    
                    # Broadcast updated snapshot
                    payload = {
                        "type": "stealth_orders_snapshot",
                        "orders": enriched_orders,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    
                    message = json.dumps(payload, cls=CustomJSONEncoder)
                    for client in connected_clients.copy():
                        try:
                            await client.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            connected_clients.discard(client)
                except Exception as e:
                    logger.debug(f"Error refreshing stealth orders: {e}")
        
        except Exception as e:
            logger.debug(f"Stealth orders refresh loop error: {e}")


async def _spread_broadcast_loop():
    """Background task to broadcast spread snapshots every second."""
    while True:
        try:
            await asyncio.sleep(1)
            broadcast_spread()
        except Exception as e:
            logger.debug(f"Spread broadcast loop error: {e}")


async def run_websocket_server(host: str = "localhost", port: int = 8765):
    """Start the WebSocket server."""
    global server_event_loop
    server_event_loop = asyncio.get_event_loop()
    
    logger.info(f"Starting WebSocket server on ws://{host}:{port}")
    
    # Update products from REST API on startup
    logger.info("Updating products list from REST API on startup...")
    update_result = update_products_json_from_api()
    if update_result["success"]:
        logger.info(f"Initial products update: {update_result['derivatives_count']} derivatives, {update_result['spot_count']} spot products loaded")
        add_log_entry("INFO", f"Products loaded: {update_result['derivatives_count']} derivatives, {update_result['spot_count']} spot")
    else:
        logger.warning(f"Initial products update failed: {update_result['message']}")
        add_log_entry("WARNING", f"Products update failed: {update_result['message']}")
    
    # Start spread broadcast loop as background task
    asyncio.create_task(_spread_broadcast_loop())
    
    # Start stealth orders refresh loop as background task
    asyncio.create_task(_stealth_orders_refresh_loop())
    
    async with websockets.serve(handler, host, port):
        logger.info("WebSocket server running. Connect dashboard.html to ws://localhost:8765")
        await asyncio.Event().wait()  # Run forever


def start_dashboard_server(host: str = "localhost", port: int = 8765):
    """Start dashboard server in background thread."""
    
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_websocket_server(host, port))
    
    thread = Thread(target=run, daemon=True)
    thread.start()
    logger.info("Dashboard server thread started")
    return thread


def set_stealth_order_bridge(bridge):
    """Set the stealth order bridge reference for WebSocket handlers and order placement.
    
    Call this from main.py after initializing the stealth order bridge:
    
    Example:
        >>> from dashboard_server import set_stealth_order_bridge
        >>> stealth_manager = StealthOrderManager(DB_CLIENT)
        >>> stealth_bridge = StealthOrderBridge(stealth_manager, None)
        >>> set_stealth_order_bridge(stealth_bridge)
    """
    global stealth_order_bridge
    stealth_order_bridge = bridge
    logger.info("Stealth order bridge registered with dashboard server")
    
    # Also register with order.py so create_limit_order_span can use it
    try:
        from order import set_stealth_order_bridge as order_set_stealth_bridge
        order_set_stealth_bridge(bridge)
        logger.info("Stealth order bridge registered with order.py")
    except ImportError:
        logger.warning("Could not register stealth bridge with order.py")


# Demo/testing
if __name__ == "__main__":
    import time
    
    start_dashboard_server()
    
    # Simulate some data
    update_engine_status({
        "running": True,
        "threads_active": 5,
        "event_queue_depth": 3,
    })
    
    add_log_entry("INFO", "Trading engine started")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard server")
