"""Lightweight WebSocket server for trading engine dashboard.

Provides real-time order updates, engine status, and manual order placement.
Runs as a separate thread alongside the main trading engine.

Runtime resources are installed by ``main.py``. Importing this transport does
not read environment variables, create exchange clients, or start a partial
trading runtime. Browser endpoints remain documented in
``genai_data/CONFIGURATION.md``.
"""
import asyncio
import json
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread, Lock
from typing import Any, Awaitable, Callable, Dict, Optional, Set
import websockets
from websockets.server import WebSocketServerProtocol

DASHBOARD_SERVER_HOST = "localhost"
DASHBOARD_SERVER_PORT = 8765
DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS = 0.25

# Transitional transport adapters installed explicitly by the process
# composition root. Item 7 will replace these globals with an application
# command/query facade; they must never construct their own runtime resources.
ORDERBOOK = None

# Use custom logging service
from logging_service import get_logger
from core.enums import (
    EngineState,
    FollowUpRevealDirection,
    OperatorErrorReason,
    OperatorNotificationMethod,
    OperatorOutcome,
    OperatorRpcErrorCode,
    OperatorRpcMethod,
    OrderSide,
    OrderStatus,
    RevealPricingPolicy,
    RepricingReferenceSource,
    StealthMoveReason,
    StealthOrderStatus,
    StealthSpanResultStatus,
    TargetMovementType,
)
from core.execution_core import (
    CreateStealthOrderRequest,
    CreateStealthOrderSpanRequest,
    ExecutionCore,
    ImportStealthOrdersRequest,
    MoveRevealedStealthOrderRequest,
    OriginatingCommandResult,
    RehideStealthOrderRequest,
    RepriceStealthOrderRequest,
)
from core.models import RepricingPolicy
from core.exceptions import OrderCreationError
from core.runtime_controller import (
    get_runtime_controller,
    validate_drain_timeout_seconds,
)
from calculation.formatter import safe_float
from operator_api.protocol import (
    STEALTH_EXPORT_SCHEMA,
    STEALTH_EXPORT_VERSION,
    OperatorRpcError,
    OperatorRpcRequest,
    decode_request,
    encode_error,
    encode_notification,
    encode_success,
)

# RPC methods that *originate* new work and therefore must route through an
# explicit ``ExecutionCore`` command. Cancellations, queries, and admin commands
# are intentionally excluded so the engine remains controllable and existing
# positions can be wound down while paused or draining.
_ORIGINATING_METHODS = frozenset({
    OperatorRpcMethod.STEALTH_CREATE,
    OperatorRpcMethod.STEALTH_CREATE_SPAN,
    OperatorRpcMethod.STEALTH_REPRICE_NOW,
    OperatorRpcMethod.STEALTH_REHIDE,
    OperatorRpcMethod.STEALTH_MOVE_REVEALED,
    OperatorRpcMethod.STEALTH_IMPORT,
})

# Stealth-order statuses considered "active" for export. Derived from the
# canonical StealthOrderStatus enum by excluding terminal states (EXECUTED,
# CANCELLED) — anything else represents a live order whose configuration we
# want to be able to back up and replay. REVEALED is included: the root is
# placed on the exchange but not yet filled, so re-importing after a wipe
# must recreate it. Use enum values so export tracks the lifecycle contract.
_TERMINAL_STEALTH_STATUSES = frozenset({
    StealthOrderStatus.EXECUTED.value,
    StealthOrderStatus.CANCELLED.value,
    StealthOrderStatus.ERROR.value,
})
_ACTIVE_STEALTH_STATUSES = frozenset(
    s.value for s in StealthOrderStatus if s.value not in _TERMINAL_STEALTH_STATUSES
)

# Fields on the in-memory stealth order that map back to the canonical create
# request. Listing them explicitly avoids leaking runtime-only state
# (revealed_orders, executed_size, anchor state, etc.) into the export payload.
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
    "enable_hotpoint_replication",
)

logger = get_logger("DashboardServer")

# Global state
connected_clients: Set[WebSocketServerProtocol] = set()
_bootstrap_pending_clients: Set[WebSocketServerProtocol] = set()
state_lock = Lock()
engine_state = {
    "orders": {},  # order_id -> order_data
    "positions": {},  # product_id -> position_data
    "stealth_orders": {},  # stealth_order_id -> order_data
    "engine_status": {
        "running": False,
        "engine_state": EngineState.STARTING.value,
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

# Dashboard delivery is a lossy latest-state view. Trading state remains
# authoritative in the engine/database, so queuing one full snapshot per
# mutation only creates stale work during bursts. Keep one state publisher
# active, retain one dirty bit for a follow-up snapshot, and bound every
# client send so a stalled browser cannot retain messages indefinitely.
_DASHBOARD_CLIENT_SEND_TIMEOUT_SECONDS = 2.0
_DASHBOARD_CLIENT_CLOSE_TIMEOUT_SECONDS = 0.5
_MAX_TERMINAL_DASHBOARD_ORDERS = 1_000
_TERMINAL_DASHBOARD_ORDER_STATUSES = frozenset({
    OrderStatus.FILLED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.EXPIRED.value,
    OrderStatus.FAILED.value,
})

_state_publish_lock = Lock()
_state_publish_scheduled = False
_state_publish_dirty = False

# Ticker consumers need the newest price for each product, not every stale
# relay attempt. The pending map therefore has a fixed upper bound equal to
# the configured product count even when a client is slower than Coinbase.
_ticker_publish_lock = Lock()
_ticker_publish_scheduled = False
_pending_ticker_updates: Dict[str, Dict[str, Any]] = {}

# Event loop reference (set when server starts)
server_event_loop = None

# Stealth order bridge reference (set during integration)
stealth_order_bridge = None
EXECUTION_CORE: Optional[ExecutionCore] = None


def configure_runtime_dependencies(
    *,
    orderbook: Any,
    execution_core: ExecutionCore,
    state_publish_interval_seconds: float,
) -> None:
    """Install the live adapters owned and constructed by ``main.py``."""

    if orderbook is None:
        raise ValueError("orderbook is required")
    if execution_core is None:
        raise ValueError("execution_core is required")
    interval = max(0.01, float(state_publish_interval_seconds))

    global ORDERBOOK
    global DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS
    global EXECUTION_CORE
    EXECUTION_CORE = execution_core
    ORDERBOOK = orderbook
    DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS = interval


def _product_metadata_reader(product_id: str) -> Dict[str, Any]:
    """Read metadata through the explicitly installed runtime orderbook."""

    if ORDERBOOK is None:
        return {}
    return ORDERBOOK.get_product_metadata(product_id)


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


def _discard_dashboard_client(
    websocket: WebSocketServerProtocol,
) -> None:
    """Remove one socket from transport and notification eligibility."""

    connected_clients.discard(websocket)
    _bootstrap_pending_clients.discard(websocket)


async def register_client(websocket: WebSocketServerProtocol):
    """Register a socket behind the initial-bootstrap notification barrier."""

    connected_clients.add(websocket)
    _bootstrap_pending_clients.add(websocket)
    logger.info(f"Client connected. Total clients: {len(connected_clients)}")


def _load_products_payload() -> Dict[str, Any]:
    """Return the static product catalog used by operator clients."""

    products_file = Path(__file__).parent / "products.json"
    if not products_file.exists():
        return {"derivatives": [], "spot": [], "metadata": {}}
    try:
        with products_file.open("r", encoding="utf-8-sig") as products_stream:
            products_data = json.load(products_stream)
    except Exception as exc:
        logger.error(f"Failed to load products list: {exc}")
        raise OperatorRpcError(
            OperatorRpcErrorCode.APPLICATION_FAILED,
            "Product catalog is unavailable",
            reason=OperatorErrorReason.UNAVAILABLE,
            data={"retryable": True},
        ) from exc
    return {
        "derivatives": products_data.get("derivatives", []),
        "spot": products_data.get("spot", []),
        "metadata": products_data.get("metadata", {}),
    }


def _runtime_status_payload() -> Dict[str, Any]:
    """Return the authoritative RuntimeController status projection."""

    controller = get_runtime_controller()
    return {
        "engine_state": controller.state.value,
        "is_admitting": controller.is_admitting(),
        "is_stopping": controller.is_stopping(),
        "startup_pause_pending": controller.startup_pause_pending(),
        "inflight": controller.inflight_snapshot(),
        "total_inflight": controller.total_inflight(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def unregister_client(websocket: WebSocketServerProtocol):
    """Unregister a disconnected client."""
    _discard_dashboard_client(websocket)
    logger.info(f"Client disconnected. Total clients: {len(connected_clients)}")


async def _send_dashboard_message(
    client: WebSocketServerProtocol,
    message: str,
) -> None:
    """Send one dashboard message without allowing an unbounded stall."""

    try:
        await asyncio.wait_for(
            client.send(message),
            timeout=_DASHBOARD_CLIENT_SEND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _discard_dashboard_client(client)
        logger.warning("Dropping dashboard client after send timeout")
        try:
            await asyncio.wait_for(
                client.close(
                    code=1013,
                    reason="Dashboard client could not keep up",
                ),
                timeout=_DASHBOARD_CLIENT_CLOSE_TIMEOUT_SECONDS,
            )
        except Exception:
            pass
        raise
    except websockets.exceptions.ConnectionClosed:
        _discard_dashboard_client(client)
        raise
    except Exception as exc:
        _discard_dashboard_client(client)
        logger.debug(f"Dashboard client broadcast failed: {exc}")
        raise


async def _send_dashboard_notification(
    client: WebSocketServerProtocol,
    message: str,
) -> bool:
    """Send a notification only after this socket completes bootstrap."""

    if (
        client not in connected_clients
        or client in _bootstrap_pending_clients
    ):
        return False
    await _send_dashboard_message(client, message)
    return True


async def _broadcast_dashboard_message(message: str) -> None:
    """Fan one serialized message out through the bounded send path."""

    for client in connected_clients.copy():
        try:
            await _send_dashboard_notification(client, message)
        except Exception:
            # One dead or lagging browser must not block other clients.
            pass


def _normalize_stealth_orders_for_operator(
    orders: Dict[str, Any],
) -> Dict[str, Any]:
    """Translate legacy manager identity fields into the wire contract."""

    normalized: Dict[str, Any] = {}
    for map_client_order_id, raw_order in orders.items():
        if not isinstance(raw_order, dict):
            normalized[map_client_order_id] = raw_order
            continue
        order = deepcopy(raw_order)
        client_order_id = order.pop(
            "stealth_order_id",
            order.get("client_order_id") or map_client_order_id,
        )
        order["client_order_id"] = client_order_id
        if "parent_order_id" in order:
            order["parent_client_order_id"] = order.pop(
                "parent_order_id"
            )
        revealed_orders = order.get("revealed_orders")
        if isinstance(revealed_orders, list):
            for reveal_event in revealed_orders:
                if not isinstance(reveal_event, dict):
                    continue
                if "placed_order_id" in reveal_event:
                    placement_client_order_id = reveal_event.pop(
                        "placed_order_id"
                    )
                    if "placement_client_order_id" not in reveal_event:
                        reveal_event["placement_client_order_id"] = (
                            placement_client_order_id
                        )
        normalized[str(client_order_id)] = order
    return normalized


def _build_state_update_message() -> str:
    """Capture one internally consistent runtime projection notification."""

    market_metrics = _build_market_metrics_payload()
    runtime_status = _runtime_status_payload()
    with state_lock:
        engine_state["market_metrics"] = market_metrics
        state_snapshot = deepcopy(engine_state)
    state_snapshot["engine_status"].update(runtime_status)
    state_snapshot["stealth_orders"] = (
        _normalize_stealth_orders_for_operator(
            state_snapshot["stealth_orders"]
        )
    )
    return encode_notification(
        OperatorNotificationMethod.RUNTIME_PROJECTION,
        {
            "state": state_snapshot,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _async_broadcast_state():
    """Broadcast one full latest-state snapshot to every current client."""

    message = _build_state_update_message()
    await _broadcast_dashboard_message(message)


async def _drain_state_broadcasts() -> None:
    """Publish rate-limited latest state while coalescing burst mutations."""

    global _state_publish_dirty, _state_publish_scheduled

    while True:
        # The authenticated feed may deliver hundreds of distinct order
        # transitions per second. Waiting for one short UI frame batches those
        # transitions into a single latest-state snapshot instead of repeatedly
        # serializing and transmitting the same bounded order history.
        await asyncio.sleep(DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS)

        # Mutations received before this point are represented by the snapshot
        # we are about to build. A mutation during serialization or send sets
        # the bit again and earns exactly one follow-up snapshot.
        with _state_publish_lock:
            _state_publish_dirty = False

        try:
            await _async_broadcast_state()
        except Exception:
            logger.exception("Dashboard state broadcast failed")

        with _state_publish_lock:
            if _state_publish_dirty:
                continue
            _state_publish_scheduled = False
            return


def _trigger_broadcast():
    """Mark state dirty and schedule at most one publisher coroutine."""

    global _state_publish_dirty, _state_publish_scheduled

    loop = server_event_loop
    if not loop or not connected_clients:
        return

    with _state_publish_lock:
        _state_publish_dirty = True
        if _state_publish_scheduled:
            return
        _state_publish_scheduled = True

    coroutine = _drain_state_broadcasts()
    try:
        asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception as exc:
        coroutine.close()
        with _state_publish_lock:
            _state_publish_scheduled = False
        logger.error(f"Failed to trigger dashboard state broadcast: {exc}")


async def broadcast_state(websocket: WebSocketServerProtocol = None):
    """Broadcast current engine state to all connected clients."""
    if websocket:
        await _send_dashboard_notification(
            websocket,
            _build_state_update_message(),
        )
    else:
        await _async_broadcast_state()


def _stealth_exchange_cancel_pending(order: Dict[str, Any]) -> bool:
    """Exposure remains unresolved even when local automation has stopped."""
    state = order.get("anchor_repricing_state_json") or {}
    return bool(
        isinstance(state.get("pending_rearm"), dict)
        or state.get("active_placement_client_order_id")
        or state.get("active_exchange_order_id")
        or safe_float(order.get("revealed_size"), default=0.0)
        > safe_float(order.get("executed_size"), default=0.0)
    )


def _cancel_managed_stealth_order(client_order_id: str, reason: str) -> Dict[str, Any]:
    """Return committed local truth, never treating REST acceptance as final."""
    if not isinstance(client_order_id, str) or not client_order_id.strip():
        raise ValueError("A non-empty client_order_id is required")
    if stealth_order_bridge is None:
        raise RuntimeError("Stealth order system not initialized")
    with stealth_order_bridge._get_order_action_lock(client_order_id):
        accepted = stealth_order_bridge.cancel_stealth_order(client_order_id, reason)
        current = stealth_order_bridge.stealth_manager._get_stealth_order(client_order_id)
        order = deepcopy(current) if current is not None else None
    pending = _stealth_exchange_cancel_pending(order) if order is not None else False
    response = {
        "client_order_id": client_order_id,
        "accepted": bool(accepted),
        "exchange_cancel_pending": pending,
        "order": order,
        "message": (
            "Automation stopped; exchange cancellation pending confirmation."
            if accepted and pending else
            "Order cancelled; automation stopped." if accepted else
            "Cancellation could not be completed; review the order's current state."
        ),
    }
    if not accepted:
        response["error"] = (order or {}).get("failure_reason") or response["message"]
    if order is not None:
        with state_lock:
            engine_state["stealth_orders"][client_order_id] = deepcopy(order)
    return response


def _create_stealth_order_request(
    order: Dict[str, Any],
    *,
    force_root: bool = False,
) -> CreateStealthOrderRequest:
    """Parse one dashboard payload into the typed application contract."""

    reveal_policy = order.get("reveal_pricing_policy")
    target_type = order.get(
        "target_movement_type",
        TargetMovementType.PERCENTAGE.value,
    )
    follow_up_direction = order.get(
        "follow_up_reveal_direction",
        FollowUpRevealDirection.OPPOSITE.value,
    )
    return CreateStealthOrderRequest(
        client_order_id=order["client_order_id"],
        product_id=str(order["product_id"]),
        side=OrderSide(str(order["side"]).upper()),
        total_size=float(order["total_size"]),
        limit_price=float(order["limit_price"]),
        reveal_condition=order["reveal_condition"],
        reveal_pricing_policy=(
            RevealPricingPolicy(reveal_policy)
            if reveal_policy is not None
            else None
        ),
        sizing_strategy=order.get("sizing_strategy", {}),
        parent_client_order_id=(
            None if force_root else order.get("parent_client_order_id")
        ),
        follow_up_reveal_direction=FollowUpRevealDirection(
            follow_up_direction
        ),
        notes=str(order.get("notes", "")),
        max_order_replacements=order.get("max_order_replacements"),
        target_movement=float(order.get("target_movement", 0.002)),
        target_movement_type=TargetMovementType(target_type),
        allow_partial_fills=bool(order.get("allow_partial_fills", True)),
        anchor_repricing_policy=order.get("anchor_repricing_policy"),
        enable_hotpoint_replication=bool(
            order.get("enable_hotpoint_replication", False)
        ),
    )


def _admitted_value(outcome: OriginatingCommandResult[Any]) -> Any:
    """Return an admitted value or raise a structured application error."""

    rejection = outcome.rejection
    if rejection is None:
        return outcome.value

    if rejection.state is EngineState.STARTING:
        rejection_message = (
            "Engine startup is still completing; new orders are not "
            "being accepted yet."
        )
    else:
        rejection_message = (
            f"Engine is {rejection.state.value}; new orders are not "
            f"being accepted. Resume the engine to place new orders."
        )
    add_log_entry(
        "WARNING",
        "Rejected operator command: engine state "
        f"{rejection.state.value}",
    )
    raise OperatorRpcError(
        OperatorRpcErrorCode.ENGINE_NOT_ADMITTING,
        rejection_message,
        reason=OperatorErrorReason.ENGINE_NOT_ADMITTING,
        data={
            "engine_state": rejection.state.value,
            "category": rejection.category,
            "retryable": rejection.state is EngineState.PAUSED,
        },
    )


@dataclass(frozen=True)
class _RpcDispatchResult:
    payload: Dict[str, Any]
    broadcast_runtime: bool = False
    broadcast_stealth_orders: bool = False


_RpcHandler = Callable[
    [Dict[str, Any]],
    Awaitable[_RpcDispatchResult],
]


def _encode_rpc_error_response(
    request_id: Optional[str],
    error: OperatorRpcError,
) -> str:
    """Encode an error, falling back if application evidence is not JSON-safe."""

    try:
        return encode_error(request_id, error)
    except Exception:
        logger.exception("Operator RPC error evidence was not serializable")
        fallback = OperatorRpcError(
            OperatorRpcErrorCode.INTERNAL_ERROR,
            "Internal operator RPC error",
            reason=OperatorErrorReason.INDETERMINATE,
            data={"retryable": False},
        )
        return encode_error(request_id, fallback)


def _rpc_result(
    payload: Optional[Dict[str, Any]] = None,
    *,
    outcome: OperatorOutcome = OperatorOutcome.SUCCEEDED,
    broadcast_runtime: bool = False,
    broadcast_stealth_orders: bool = False,
) -> _RpcDispatchResult:
    result = dict(payload or {})
    result["outcome"] = outcome.value
    return _RpcDispatchResult(
        payload=result,
        broadcast_runtime=broadcast_runtime,
        broadcast_stealth_orders=broadcast_stealth_orders,
    )


async def _publish_requested_rpc_projections(
    dispatch_result: _RpcDispatchResult,
) -> None:
    """Best-effort each projection requested by a completed RPC handler."""

    if dispatch_result.broadcast_runtime:
        try:
            await broadcast_state()
        except Exception:
            logger.exception(
                "Operator RPC runtime projection publication failed"
            )

    if dispatch_result.broadcast_stealth_orders:
        try:
            await _broadcast_stealth_orders_projection()
        except Exception:
            logger.exception(
                "Operator RPC stealth-order projection publication failed"
            )


def _rpc_application_error(
    message: str,
    *,
    reason: OperatorErrorReason,
    code: Optional[OperatorRpcErrorCode] = None,
    data: Optional[Dict[str, Any]] = None,
) -> OperatorRpcError:
    resolved_code = code
    if resolved_code is None:
        resolved_code = (
            OperatorRpcErrorCode.INVALID_PARAMS
            if reason is OperatorErrorReason.INVALID_PARAMS
            else OperatorRpcErrorCode.APPLICATION_REJECTED
        )
    return OperatorRpcError(
        resolved_code,
        message,
        reason=reason,
        data=data,
    )


def _require_execution_core() -> ExecutionCore:
    if EXECUTION_CORE is None:
        raise _rpc_application_error(
            "Execution core is not initialized",
            reason=OperatorErrorReason.UNAVAILABLE,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"retryable": True},
        )
    return EXECUTION_CORE


def _require_stealth_bridge():
    if stealth_order_bridge is None:
        raise _rpc_application_error(
            "Stealth order system is not initialized",
            reason=OperatorErrorReason.UNAVAILABLE,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"retryable": True},
        )
    return stealth_order_bridge


async def _rpc_session_bootstrap(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    market_metrics = _build_market_metrics_payload()
    with state_lock:
        engine_state["market_metrics"] = market_metrics
        dashboard_state = deepcopy(engine_state)
    runtime_status = _runtime_status_payload()
    dashboard_state["engine_status"].update(runtime_status)
    dashboard_state["stealth_orders"] = (
        _normalize_stealth_orders_for_operator(
            dashboard_state["stealth_orders"]
        )
    )
    return _rpc_result({
        "protocol_version": 1,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "capabilities": {
            "methods": [method.value for method in OperatorRpcMethod],
            "notifications": [
                method.value for method in OperatorNotificationMethod
            ],
            "client_notifications": False,
            "batch_requests": False,
            "generic_idempotent_replay": False,
        },
        "runtime": runtime_status,
        "products": _load_products_payload(),
        "stealth_orders": _stealth_orders_snapshot_payload(),
        "dashboard_state": dashboard_state,
    })


async def _rpc_runtime_status(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    return _rpc_result(_runtime_status_payload())


async def _rpc_runtime_pause(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    controller = get_runtime_controller()
    changed = controller.request_pause()
    if changed:
        if controller.state is EngineState.STARTING:
            add_log_entry(
                "WARNING",
                "Engine pause requested during startup via operator RPC",
            )
        else:
            add_log_entry("WARNING", "Engine paused via operator RPC")
    return _rpc_result(
        {
            "changed": changed,
            "engine_state": controller.state.value,
            "startup_pause_pending": controller.startup_pause_pending(),
        },
        broadcast_runtime=True,
    )


async def _rpc_runtime_resume(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    controller = get_runtime_controller()
    changed = controller.resume()
    if changed:
        add_log_entry("INFO", "Engine resumed via operator RPC")
    return _rpc_result(
        {
            "changed": changed,
            "engine_state": controller.state.value,
            "startup_pause_pending": controller.startup_pause_pending(),
        },
        broadcast_runtime=True,
    )


async def _rpc_runtime_shutdown(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    controller = get_runtime_controller()
    try:
        timeout = validate_drain_timeout_seconds(
            params.get("timeout_seconds", 30.0)
        )
    except ValueError as exc:
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.INVALID_PARAMS,
            data={
                "fields": [{
                    "path": "timeout_seconds",
                    "message": str(exc),
                    "rule": "runtime_validation",
                }],
                "retryable": False,
            },
        ) from exc

    state_before = controller.state
    controller.request_shutdown()

    def _drain_worker() -> None:
        try:
            controller.drain_and_stop(timeout_seconds=timeout)
        except Exception:
            logger.exception("Drain worker raised")

    try:
        drain_thread = Thread(
            target=_drain_worker,
            daemon=False,
            name="admin-shutdown-drain",
        )
        drain_thread.start()
    except Exception:
        logger.exception(
            "Could not start admin drain worker; draining synchronously"
        )
        controller.drain_and_stop(timeout_seconds=timeout)

    add_log_entry(
        "WARNING",
        f"Engine shutdown requested (timeout={timeout}s)",
    )
    return _rpc_result(
        {
            "accepted": True,
            "timeout_seconds": timeout,
            "engine_state_before": state_before.value,
        },
        outcome=OperatorOutcome.ACCEPTED_PENDING,
        broadcast_runtime=True,
    )


async def _rpc_stealth_list(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    return _rpc_result(_stealth_orders_snapshot_payload())


async def _rpc_stealth_export(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    bridge = _require_stealth_bridge()

    try:
        from database.order import get_parent_order

        manager = bridge.stealth_manager
        exported: list[dict[str, Any]] = []
        for client_order_id, order in list(manager.in_memory_orders.items()):
            if not isinstance(order, dict):
                continue
            if order.get("parent_order_id"):
                continue
            status = str(order.get("status") or "").upper()
            if status not in _ACTIVE_STEALTH_STATUSES:
                continue

            serialized = manager._serialize_order_for_json(order)
            try:
                parent_row = get_parent_order(client_order_id) or {}
            except Exception as exc:
                logger.warning(
                    "export: get_parent_order failed for %s: %s",
                    client_order_id,
                    exc,
                )
                parent_row = {}

            target_movement = parent_row.get("target_movement")
            if (
                target_movement is not None
                and "target_movement" not in serialized
            ):
                serialized["target_movement"] = safe_float(
                    target_movement,
                    default=0.0,
                )
            if (
                parent_row.get("target_movement_type")
                and "target_movement_type" not in serialized
            ):
                serialized["target_movement_type"] = (
                    parent_row["target_movement_type"]
                )
            if parent_row.get("max_order_replacement") is not None:
                serialized["max_order_replacements"] = int(
                    parent_row["max_order_replacement"]
                )
            if parent_row.get("allow_partial_fills") is not None:
                serialized["allow_partial_fills"] = bool(
                    parent_row["allow_partial_fills"]
                )
            if parent_row.get("enable_hotpoint_replication") is not None:
                serialized["enable_hotpoint_replication"] = bool(
                    parent_row["enable_hotpoint_replication"]
                )

            payload: dict[str, Any] = {
                "client_order_id": client_order_id,
            }
            for source_key in _EXPORT_FIELDS:
                if source_key not in serialized:
                    continue
                if source_key == "reveal_condition_json":
                    destination_key = "reveal_condition"
                elif source_key == "sizing_strategy_json":
                    destination_key = "sizing_strategy"
                elif source_key == "anchor_repricing_policy_json":
                    destination_key = "anchor_repricing_policy"
                else:
                    destination_key = source_key
                payload[destination_key] = serialized[source_key]
            exported.append(payload)

        document = {
            "schema": STEALTH_EXPORT_SCHEMA,
            "version": STEALTH_EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(exported),
            "orders": exported,
        }
        add_log_entry(
            "INFO",
            f"Exported {len(exported)} active stealth orders for backup",
        )
        return _rpc_result({"document": document})
    except OperatorRpcError:
        raise
    except Exception as exc:
        logger.exception("Failed to export active stealth orders")
        raise _rpc_application_error(
            f"Export failed: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"retryable": False},
        ) from exc


def _normalize_import_order(
    entry: Dict[str, Any],
    *,
    document_version: int,
) -> Dict[str, Any]:
    normalized = dict(entry)
    if document_version == 1:
        if "client_order_id" not in normalized:
            normalized["client_order_id"] = normalized.pop(
                "stealth_order_id",
                None,
            )
        normalized.pop("parent_order_id", None)
        normalized["enable_hotpoint_replication"] = False
    return normalized


async def _rpc_stealth_import(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    core = _require_execution_core()
    document = params["document"]
    document_version = int(document.get("version", 1))
    if document_version == STEALTH_EXPORT_VERSION:
        if document.get("schema") != STEALTH_EXPORT_SCHEMA:
            raise _rpc_application_error(
                "Version 2 import requires the canonical stealth export schema",
                reason=OperatorErrorReason.INVALID_PARAMS,
                data={
                    "fields": [{
                        "path": "document.schema",
                        "message": (
                            f"expected {STEALTH_EXPORT_SCHEMA!r}"
                        ),
                        "rule": "const",
                    }],
                    "retryable": False,
                },
            )
    elif document_version != 1:
        raise _rpc_application_error(
            f"Unsupported stealth export version: {document_version}",
            reason=OperatorErrorReason.INVALID_PARAMS,
            data={"retryable": False},
        )

    orders_to_import = document["orders"]
    declared_count = document.get("count")
    if (
        declared_count is not None
        and int(declared_count) != len(orders_to_import)
    ):
        raise _rpc_application_error(
            "Import document count does not match orders length",
            reason=OperatorErrorReason.INVALID_PARAMS,
            data={
                "fields": [{
                    "path": "document.count",
                    "message": "must equal len(document.orders)",
                    "rule": "consistency",
                }],
                "retryable": False,
            },
        )

    warnings: list[str] = []
    if document_version == 1:
        warnings.append(
            "Version 1 backup imported with "
            "enable_hotpoint_replication=false because that field was not "
            "preserved by the old export format."
        )

    parsed_orders: list[CreateStealthOrderRequest] = []
    parsed_indexes: list[int] = []
    preflight_errors: dict[int, dict[str, Any]] = {}
    for index, entry in enumerate(orders_to_import):
        if not isinstance(entry, dict):
            preflight_errors[index] = {
                "succeeded": False,
                "error": "entry is not an object",
            }
            continue
        normalized = _normalize_import_order(
            entry,
            document_version=document_version,
        )
        try:
            if not normalized.get("client_order_id"):
                raise ValueError("client_order_id is required")
            parsed_orders.append(
                _create_stealth_order_request(
                    normalized,
                    force_root=True,
                )
            )
            parsed_indexes.append(index)
        except Exception as exc:
            preflight_errors[index] = {
                "succeeded": False,
                "requested_client_order_id": normalized.get(
                    "client_order_id"
                ),
                "product_id": normalized.get("product_id"),
                "side": normalized.get("side"),
                "error": str(exc),
            }

    import_result = _admitted_value(
        core.import_stealth_orders(
            ImportStealthOrdersRequest(orders=tuple(parsed_orders))
        )
    )
    results_by_index = dict(preflight_errors)
    for index, result in zip(parsed_indexes, import_result.orders):
        results_by_index[index] = {
            "succeeded": result.succeeded,
            "requested_client_order_id": (
                result.requested_client_order_id
            ),
            "client_order_id": result.client_order_id,
            "product_id": result.product_id,
            "side": result.side.value,
            "error": result.error,
        }

    results = [
        results_by_index[index]
        for index in range(len(orders_to_import))
    ]
    success_count = import_result.imported_count
    total = len(orders_to_import)
    add_log_entry(
        "INFO",
        f"Imported {success_count}/{total} stealth orders",
    )
    return _rpc_result(
        {
            "imported": success_count,
            "total": total,
            "results": results,
            "warnings": warnings,
        },
        outcome=(
            OperatorOutcome.SUCCEEDED
            if success_count == total
            else OperatorOutcome.PARTIAL
        ),
        broadcast_stealth_orders=success_count > 0,
    )


async def _rpc_stealth_create_span(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    core = _require_execution_core()
    bridge = _require_stealth_bridge()
    span_id = params.get("span_id")
    try:
        result = _admitted_value(
            core.create_stealth_order_span(
                CreateStealthOrderSpanRequest(span=params)
            )
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        logger.exception("Failed to create stealth order span")
        raise _rpc_application_error(
            f"Stealth order span creation failed: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"span_id": span_id, "retryable": False},
        ) from exc

    with state_lock:
        for order_result in result.get("orders", []):
            client_order_id = order_result.get("client_order_id")
            if not client_order_id:
                continue
            current = bridge.stealth_manager.in_memory_orders.get(
                client_order_id
            )
            if current is not None:
                engine_state["stealth_orders"][client_order_id] = (
                    bridge.stealth_manager._serialize_order_for_json(
                        current
                    )
                )

    status = result.get("status")
    if status == StealthSpanResultStatus.ERROR.value:
        raise _rpc_application_error(
            result.get("error") or "Stealth span creation failed",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"span_result": result, "retryable": False},
        )
    outcome = (
        OperatorOutcome.PARTIAL
        if status == StealthSpanResultStatus.PARTIAL.value
        else OperatorOutcome.SUCCEEDED
    )
    add_log_entry(
        "INFO" if outcome is OperatorOutcome.SUCCEEDED else "WARNING",
        "Stealth order span "
        f"{status}: {result.get('created_count', 0)} created, "
        f"{result.get('existing_count', 0)} existing, "
        f"{result.get('failed_count', 0)} failed",
    )
    return _rpc_result(
        {"span": result},
        outcome=outcome,
        broadcast_stealth_orders=True,
    )


async def _rpc_stealth_create(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    core = _require_execution_core()
    bridge = _require_stealth_bridge()
    try:
        client_order_id = _admitted_value(
            core.create_stealth_order(
                _create_stealth_order_request(params)
            )
        )
        client_order_id = str(client_order_id)
        order_data = bridge.stealth_manager.in_memory_orders.get(
            client_order_id
        )
        serialized_order = (
            bridge.stealth_manager._serialize_order_for_json(order_data)
            if order_data
            else None
        )
        with state_lock:
            engine_state["stealth_orders"][client_order_id] = (
                serialized_order
            )
        add_log_entry(
            "INFO",
            "Stealth order created: "
            f"{params['product_id']} {params['side']} "
            f"{params['total_size']}",
        )
        projected_order = _normalize_stealth_orders_for_operator({
            client_order_id: serialized_order,
        }).get(client_order_id)
        return _rpc_result(
            {
                "client_order_id": client_order_id,
                "order": projected_order,
            },
            broadcast_stealth_orders=True,
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        logger.exception("Failed to create stealth order")
        raise _rpc_application_error(
            f"Failed to create order: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": params.get("client_order_id"),
                "retryable": False,
            },
        ) from exc


async def _rpc_stealth_cancel(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    client_order_id = params["client_order_id"]
    try:
        response = _cancel_managed_stealth_order(
            client_order_id,
            "user_cancelled",
        )
    except Exception as exc:
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        ) from exc

    order = response.get("order")
    if isinstance(order, dict):
        response["order"] = _normalize_stealth_orders_for_operator({
            client_order_id: order,
        })[client_order_id]
    if not response["accepted"]:
        raise _rpc_application_error(
            response.get("error") or response["message"],
            reason=OperatorErrorReason.PRECONDITION_FAILED,
            data={
                **response,
                "retryable": False,
            },
        )
    return _rpc_result(
        response,
        outcome=(
            OperatorOutcome.ACCEPTED_PENDING
            if response["exchange_cancel_pending"]
            else OperatorOutcome.SUCCEEDED
        ),
        broadcast_stealth_orders=True,
    )


async def _rpc_stealth_rehide(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    client_order_id = params["client_order_id"]
    core = _require_execution_core()
    try:
        accepted = _admitted_value(
            core.rehide_stealth_order(
                RehideStealthOrderRequest(
                    client_order_id=client_order_id
                )
            )
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        raise _rpc_application_error(
            f"Rehide not accepted: {exc}",
            reason=OperatorErrorReason.PRECONDITION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        ) from exc
    if not accepted:
        raise _rpc_application_error(
            "Rehide request was not accepted; refresh the order and retry",
            reason=OperatorErrorReason.PRECONDITION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        )

    message = (
        "Rehide requested; exchange withdrawal confirmation is pending. "
        "The same order may reveal again when its condition is satisfied."
    )
    add_log_entry(
        "INFO",
        f"Stealth order rehide requested: {client_order_id}",
    )
    return _rpc_result(
        {
            "client_order_id": client_order_id,
            "accepted": True,
            "message": message,
        },
        outcome=OperatorOutcome.ACCEPTED_PENDING,
        broadcast_stealth_orders=True,
    )


async def _rpc_stealth_reprice_now(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    client_order_id = params["client_order_id"]
    core = _require_execution_core()
    bridge = _require_stealth_bridge()
    manager = bridge.stealth_manager
    order = manager.in_memory_orders.get(client_order_id)
    if not order:
        raise _rpc_application_error(
            "Order not found",
            reason=OperatorErrorReason.NOT_FOUND,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        )

    policy = RepricingPolicy.from_dict(
        order.get("anchor_repricing_policy_json")
    )
    if not policy.enabled:
        raise _rpc_application_error(
            "Anchor repricing is not enabled for this order",
            reason=OperatorErrorReason.PRECONDITION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        )

    active_statuses = {
        StealthOrderStatus.HIDDEN.value,
        StealthOrderStatus.PENDING.value,
        StealthOrderStatus.TRIGGERED.value,
        StealthOrderStatus.REVEALED.value,
    }
    if order.get("status") not in active_statuses:
        raise _rpc_application_error(
            f"Order status {order.get('status')} is not repriceable",
            reason=OperatorErrorReason.PRECONDITION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        )

    try:
        processed = _admitted_value(
            core.reprice_stealth_order_now(
                RepriceStealthOrderRequest(
                    client_order_id=client_order_id
                )
            )
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        ) from exc

    add_log_entry(
        "INFO",
        "Manual reprice triggered for "
        f"{client_order_id}: processed={processed}",
    )
    return _rpc_result(
        {
            "client_order_id": client_order_id,
            "processed": processed,
        },
        broadcast_stealth_orders=True,
    )


async def _rpc_stealth_move_revealed(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    from core.exceptions import StealthMoveError

    client_order_id = params["client_order_id"]
    core = _require_execution_core()
    reason = (
        StealthMoveReason(params["reason"])
        if params.get("reason")
        else None
    )
    movement_type = (
        TargetMovementType(params["new_target_movement_type"])
        if params.get("new_target_movement_type") is not None
        else None
    )

    try:
        move_result = _admitted_value(
            core.move_revealed_stealth_order(
                MoveRevealedStealthOrderRequest(
                    client_order_id=client_order_id,
                    new_limit_price=float(params["new_limit_price"]),
                    new_target_movement=params.get(
                        "new_target_movement"
                    ),
                    new_target_movement_type=movement_type,
                    reason=reason,
                    notes=params.get("notes"),
                )
            )
        )
        plan = move_result.plan
        result = move_result.result
    except OperatorRpcError:
        raise
    except StealthMoveError as exc:
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": client_order_id,
                "stage": exc.stage,
                "retryable": False,
            },
        ) from exc
    except Exception as exc:
        logger.exception("move_revealed_stealth_order crashed")
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.INDETERMINATE,
            code=OperatorRpcErrorCode.APPLICATION_INDETERMINATE,
            data={
                "client_order_id": client_order_id,
                "stage": "unknown",
                "retryable": False,
            },
        ) from exc

    add_log_entry(
        "INFO",
        f"Stealth order moved: {client_order_id} "
        f"@ {plan.new_configured_limit_price} "
        f"(new placement_client_order_id: "
        f"{result.new_placement_client_order_id}, "
        f"new exchange_order_id: {result.new_exchange_order_id})",
    )
    return _rpc_result(
        {
            "client_order_id": client_order_id,
            "old_exchange_order_id": plan.old_exchange_order_id,
            "new_placement_client_order_id": (
                result.new_placement_client_order_id
            ),
            "new_exchange_order_id": result.new_exchange_order_id,
            "new_submitted_price": result.new_submitted_price,
        },
        broadcast_stealth_orders=True,
    )


async def _rpc_stealth_update_price_condition(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    client_order_id = params["client_order_id"]
    threshold = float(params["price_threshold"])
    hold_seconds = params.get("hold_duration_seconds")
    bridge = _require_stealth_bridge()

    try:
        from database.order import get_stealth_order_by_id

        existing = get_stealth_order_by_id(client_order_id)
        if not existing:
            raise _rpc_application_error(
                f"Stealth order not found: {client_order_id}",
                reason=OperatorErrorReason.NOT_FOUND,
                data={
                    "client_order_id": client_order_id,
                    "retryable": False,
                },
            )
        if (
            str(existing.get("reveal_condition_type", "")).lower()
            != "price"
        ):
            raise _rpc_application_error(
                "Threshold updates are only supported for price "
                "reveal conditions",
                reason=OperatorErrorReason.PRECONDITION_FAILED,
                data={
                    "client_order_id": client_order_id,
                    "retryable": False,
                },
            )

        bridge.update_price_condition(
            client_order_id,
            price_threshold=threshold,
            hold_duration_seconds=hold_seconds,
        )

        manager = bridge.stealth_manager
        affected_ids = manager.strategy_condition_order_ids(
            client_order_id
        )
        if not isinstance(affected_ids, (list, tuple, set)):
            affected_ids = (client_order_id,)

        affected_conditions: dict[str, Any] = {}
        for affected_id in affected_ids:
            affected_order = manager.in_memory_orders.get(affected_id)
            if not isinstance(affected_order, dict):
                continue
            affected_conditions[affected_id] = deepcopy(
                affected_order.get("reveal_condition_json") or {}
            )

        with state_lock:
            for affected_id, reveal_json in affected_conditions.items():
                if affected_id in engine_state["stealth_orders"]:
                    engine_state["stealth_orders"][affected_id][
                        "reveal_condition_json"
                    ] = deepcopy(reveal_json)

        add_log_entry(
            "INFO",
            f"Stealth threshold updated: {client_order_id} -> "
            f"{threshold}"
            + (
                f", hold={hold_seconds}s"
                if hold_seconds is not None
                else ""
            ),
        )
        return _rpc_result(
            {
                "client_order_id": client_order_id,
                "price_threshold": threshold,
                "hold_duration_seconds": hold_seconds,
                "affected_conditions": affected_conditions,
            },
            broadcast_stealth_orders=True,
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to update stealth price condition for %s",
            client_order_id,
        )
        raise _rpc_application_error(
            str(exc),
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": client_order_id,
                "retryable": False,
            },
        ) from exc


async def _rpc_strategy_update_target(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    from database.order import update_parent_order_target_movement

    parent_client_order_id = params["parent_client_order_id"]
    target_movement = float(params["target_movement"])
    target_movement_type = TargetMovementType(
        params["target_movement_type"]
    )
    try:
        success = update_parent_order_target_movement(
            parent_order_id=parent_client_order_id,
            target_movement=target_movement,
            target_movement_type=target_movement_type.value,
        )
        if not success:
            raise _rpc_application_error(
                f"Failed to update parent order: "
                f"{parent_client_order_id}",
                reason=OperatorErrorReason.OPERATION_FAILED,
                code=OperatorRpcErrorCode.APPLICATION_FAILED,
                data={
                    "parent_client_order_id": parent_client_order_id,
                    "retryable": False,
                },
            )
        if stealth_order_bridge:
            stealth_order_bridge.stealth_manager.sync_target_movement_to_cache(
                parent_client_order_id,
                target_movement,
                target_movement_type.value,
            )
        add_log_entry(
            "INFO",
            "Parent order target_movement updated: "
            f"{parent_client_order_id} = {target_movement}"
            f"{target_movement_type.value}",
        )
        return _rpc_result(
            {
                "parent_client_order_id": parent_client_order_id,
                "target_movement": target_movement,
                "target_movement_type": target_movement_type.value,
            },
            broadcast_stealth_orders=True,
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        raise _rpc_application_error(
            f"Failed to update parent target movement: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "parent_client_order_id": parent_client_order_id,
                "retryable": False,
            },
        ) from exc


async def _rpc_stealth_clear_all(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    del params
    try:
        from database.order import clear_all_stealth_orders

        cancelled_in_memory = 0
        cancel_failures = 0
        manager = None
        if stealth_order_bridge is not None:
            manager = stealth_order_bridge.stealth_manager
            orders = stealth_order_bridge.get_stealth_orders()
            for client_order_id, order in orders.items():
                if (
                    order.get("status") in _TERMINAL_STEALTH_STATUSES
                    and not _stealth_exchange_cancel_pending(order)
                ):
                    continue
                try:
                    outcome = _cancel_managed_stealth_order(
                        client_order_id,
                        "Clear All Orders (operator RPC)",
                    )
                    if outcome["accepted"]:
                        cancelled_in_memory += 1
                    else:
                        cancel_failures += 1
                except Exception:
                    cancel_failures += 1
                    logger.exception(
                        "Clear All failed to cancel %s",
                        client_order_id,
                    )

        creation_context = (
            manager._creation_lock
            if manager is not None
            else nullcontext()
        )
        with creation_context:
            current = (
                stealth_order_bridge.get_stealth_orders()
                if manager is not None
                else {}
            )
            pending = any(
                _stealth_exchange_cancel_pending(row)
                for row in current.values()
            )
            active = any(
                row.get("status") not in _TERMINAL_STEALTH_STATUSES
                for row in current.values()
            )
            blocked = bool(cancel_failures or pending or active)
            if blocked:
                raise _rpc_application_error(
                    "No records deleted. Resolve outstanding "
                    "cancellations, then retry Clear All.",
                    reason=OperatorErrorReason.PRECONDITION_FAILED,
                    data={
                        "cleared": False,
                        "exchange_cancel_pending": pending,
                        "in_memory_cancelled": cancelled_in_memory,
                        "in_memory_cancel_failures": cancel_failures,
                        "retryable": True,
                    },
                )
            result = clear_all_stealth_orders()
            if not result["success"]:
                raise _rpc_application_error(
                    "Failed to clear orders: "
                    f"{result.get('error', 'Unknown error')}",
                    reason=OperatorErrorReason.OPERATION_FAILED,
                    code=OperatorRpcErrorCode.APPLICATION_FAILED,
                    data={"retryable": False},
                )
            if manager is not None:
                manager.clear_in_memory_orders()
                manager._placed_order_index.clear()

        with state_lock:
            engine_state["stealth_orders"] = {}
        add_log_entry(
            "INFO",
            f"All stealth orders cleared - {result['rows_deleted']} "
            f"DB rows, {cancelled_in_memory} in-memory cancelled, "
            f"{cancel_failures} cancel failures",
        )
        return _rpc_result(
            {
                "rows_deleted": result["rows_deleted"],
                "in_memory_cancelled": cancelled_in_memory,
                "in_memory_cancel_failures": cancel_failures,
                "message": result["message"],
            },
            broadcast_stealth_orders=True,
        )
    except OperatorRpcError:
        raise
    except Exception as exc:
        logger.exception("Failed to clear stealth orders")
        raise _rpc_application_error(
            f"Failed to clear orders: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={"retryable": False},
        ) from exc


async def _rpc_strategy_update_parent(
    params: Dict[str, Any],
) -> _RpcDispatchResult:
    try:
        from database.order_dashboard_helpers import (
            get_parent_order_by_client_id,
            update_parent_order,
        )

        client_order_id = params["client_order_id"]
        update_data = {
            "size": float(params["size"]),
            "price": float(params["price"]),
            "target_movement": params.get("target_movement"),
            "max_order_replacement": int(
                params["max_order_replacement"]
            ),
            "status": params["status"],
        }
        if not update_parent_order(
            client_order_id,
            update_data,
            metadata_reader=_product_metadata_reader,
        ):
            raise OrderCreationError(
                "Parent order update failed boundary or persistence "
                "validation",
                client_order_id=client_order_id,
            )
        updated_order = get_parent_order_by_client_id(client_order_id)
        if isinstance(updated_order, dict):
            updated_order = _normalize_stealth_orders_for_operator({
                client_order_id: updated_order,
            })[client_order_id]
        add_log_entry(
            "INFO",
            f"Parent order updated: {client_order_id}",
        )
        return _rpc_result(
            {
                "client_order_id": client_order_id,
                "order": updated_order,
            },
            broadcast_stealth_orders=True,
        )
    except Exception as exc:
        raise _rpc_application_error(
            f"Failed to update order: {exc}",
            reason=OperatorErrorReason.OPERATION_FAILED,
            code=OperatorRpcErrorCode.APPLICATION_FAILED,
            data={
                "client_order_id": params.get("client_order_id"),
                "retryable": False,
            },
        ) from exc


_RPC_HANDLERS: Dict[OperatorRpcMethod, _RpcHandler] = {
    OperatorRpcMethod.SESSION_BOOTSTRAP: _rpc_session_bootstrap,
    OperatorRpcMethod.RUNTIME_STATUS: _rpc_runtime_status,
    OperatorRpcMethod.RUNTIME_PAUSE: _rpc_runtime_pause,
    OperatorRpcMethod.RUNTIME_RESUME: _rpc_runtime_resume,
    OperatorRpcMethod.RUNTIME_SHUTDOWN: _rpc_runtime_shutdown,
    OperatorRpcMethod.STEALTH_LIST: _rpc_stealth_list,
    OperatorRpcMethod.STEALTH_EXPORT: _rpc_stealth_export,
    OperatorRpcMethod.STEALTH_IMPORT: _rpc_stealth_import,
    OperatorRpcMethod.STEALTH_CREATE: _rpc_stealth_create,
    OperatorRpcMethod.STEALTH_CREATE_SPAN: _rpc_stealth_create_span,
    OperatorRpcMethod.STEALTH_CANCEL: _rpc_stealth_cancel,
    OperatorRpcMethod.STEALTH_REHIDE: _rpc_stealth_rehide,
    OperatorRpcMethod.STEALTH_REPRICE_NOW: _rpc_stealth_reprice_now,
    OperatorRpcMethod.STEALTH_MOVE_REVEALED: (
        _rpc_stealth_move_revealed
    ),
    OperatorRpcMethod.STEALTH_UPDATE_PRICE_CONDITION: (
        _rpc_stealth_update_price_condition
    ),
    OperatorRpcMethod.STEALTH_CLEAR_ALL: _rpc_stealth_clear_all,
    OperatorRpcMethod.STRATEGY_UPDATE_TARGET: (
        _rpc_strategy_update_target
    ),
    OperatorRpcMethod.STRATEGY_UPDATE_PARENT: (
        _rpc_strategy_update_parent
    ),
}


async def _activate_bootstrapped_client(
    websocket: WebSocketServerProtocol,
) -> None:
    """Send fresh catch-up, then open live notifications after bootstrap."""

    if websocket not in connected_clients:
        return

    catch_up_notifications = (
        (
            "runtime",
            _build_state_update_message,
        ),
        (
            "stealth-order",
            lambda: encode_notification(
                OperatorNotificationMethod.STEALTH_ORDERS_PROJECTION,
                _stealth_orders_snapshot_payload(),
            ),
        ),
    )
    for projection_name, build_message in catch_up_notifications:
        if websocket not in connected_clients:
            return
        try:
            await _send_dashboard_message(
                websocket,
                build_message(),
            )
        except Exception:
            logger.exception(
                "Bootstrap succeeded but %s catch-up publication failed",
                projection_name,
            )

    if websocket in connected_clients:
        _bootstrap_pending_clients.discard(websocket)


async def handle_client_message(
    websocket: WebSocketServerProtocol,
    message: str,
) -> None:
    """Decode, dispatch, and answer one correlated operator request."""

    request: OperatorRpcRequest | None = None
    try:
        request = decode_request(message)
        handler_function = _RPC_HANDLERS[request.method]
        dispatch_result = await handler_function(request.params)
    except OperatorRpcError as exc:
        request_id = (
            request.request_id
            if request is not None
            else exc.request_id
        )
        await _send_dashboard_message(
            websocket,
            _encode_rpc_error_response(request_id, exc),
        )
        return
    except Exception as exc:
        logger.exception("Unhandled operator RPC failure")
        error = OperatorRpcError(
            OperatorRpcErrorCode.INTERNAL_ERROR,
            "Internal operator RPC error",
            reason=OperatorErrorReason.INDETERMINATE,
            data={"retryable": False},
        )
        await _send_dashboard_message(
            websocket,
            _encode_rpc_error_response(
                request.request_id if request is not None else None,
                error,
            ),
        )
        return

    try:
        response_message = encode_success(
            request.request_id,
            request.method,
            dispatch_result.payload,
        )
    except Exception:
        # A mutating handler may already have completed. Treat a producer-side
        # contract or serialization defect as indeterminate and never retry it
        # automatically.
        logger.exception(
            "Operator RPC result violated its contract or was not serializable"
        )
        error = OperatorRpcError(
            OperatorRpcErrorCode.INTERNAL_ERROR,
            "Internal operator RPC error",
            reason=OperatorErrorReason.INDETERMINATE,
            data={"retryable": False},
        )
        await _send_dashboard_message(
            websocket,
            _encode_rpc_error_response(request.request_id, error),
        )
        await _publish_requested_rpc_projections(dispatch_result)
        return

    await _send_dashboard_message(
        websocket,
        response_message,
    )

    if request.method is OperatorRpcMethod.SESSION_BOOTSTRAP:
        await _activate_bootstrapped_client(websocket)

    await _publish_requested_rpc_projections(dispatch_result)


async def handler(websocket: WebSocketServerProtocol, path: str):
    """Main WebSocket connection handler."""
    await register_client(websocket)
    
    try:
        async for message in websocket:
            await handle_client_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister_client(websocket)


def update_order(order_id: str, order_data: Dict[str, Any]):
    """Update order in dashboard state."""
    status = getattr(order_data.get("status"), "value", order_data.get("status"))
    with state_lock:
        if status in _TERMINAL_DASHBOARD_ORDER_STATUSES:
            # Reinsert terminal transitions at the end so dict order is also
            # terminal-recency order for the bounded-history eviction below.
            engine_state["orders"].pop(order_id, None)
        engine_state["orders"][order_id] = {
            **order_data,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if status in _TERMINAL_DASHBOARD_ORDER_STATUSES:
            terminal_order_ids = [
                existing_order_id
                for existing_order_id, existing_order in engine_state["orders"].items()
                if getattr(
                    existing_order.get("status"),
                    "value",
                    existing_order.get("status"),
                )
                in _TERMINAL_DASHBOARD_ORDER_STATUSES
            ]
            excess = len(terminal_order_ids) - _MAX_TERMINAL_DASHBOARD_ORDERS
            for expired_order_id in terminal_order_ids[:max(0, excess)]:
                engine_state["orders"].pop(expired_order_id, None)
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


async def _async_broadcast_ticker(ticker_data: Dict[str, Any]):
    """Broadcast one latest-per-product ticker update."""
    message = encode_notification(
        OperatorNotificationMethod.MARKET_TICKER,
        {
            "ticker": ticker_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    await _broadcast_dashboard_message(message)


async def _drain_ticker_broadcasts() -> None:
    """Drain bounded latest-per-product ticker updates."""

    global _ticker_publish_scheduled

    while True:
        with _ticker_publish_lock:
            updates = tuple(_pending_ticker_updates.values())
            _pending_ticker_updates.clear()

        for ticker_data in updates:
            await _async_broadcast_ticker(ticker_data)

        with _ticker_publish_lock:
            if _pending_ticker_updates:
                continue
            _ticker_publish_scheduled = False
            return


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
    global _ticker_publish_scheduled
    
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

        with _ticker_publish_lock:
            _pending_ticker_updates[product_id] = ticker_data
            if _ticker_publish_scheduled:
                return
            _ticker_publish_scheduled = True

        coroutine = _drain_ticker_broadcasts()
        try:
            asyncio.run_coroutine_threadsafe(coroutine, server_event_loop)
        except Exception:
            coroutine.close()
            with _ticker_publish_lock:
                _ticker_publish_scheduled = False
            raise
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


# Spread monitoring for arbitrage detection. Keep aggregates rather than raw
# per-tick lists so memory remains O(products) if the dashboard has no clients
# or its event loop is delayed.
spread_data = {}
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
                'bid_total': 0.0,
                'ask_total': 0.0,
                'sample_count': 0,
                'last_window': datetime.utcnow().timestamp(),
            }

        data = spread_data[product_id]
        data['bid_total'] += float(bid)
        data['ask_total'] += float(ask)
        data['sample_count'] += 1


class DashboardExecutionProjectionSink:
    """Execution projection adapter over the existing dashboard publishers.

    Every method stays synchronous and bounded: state publishers mutate the
    existing protected projection and ticker delivery only schedules work on
    the dashboard event loop.  ``OrderEngine`` may call these methods while
    holding its own short lifecycle or ticker locks.
    """

    def publish_order_update(
        self,
        client_order_id: str,
        order_data: Dict[str, Any],
    ) -> None:
        update_order(client_order_id, order_data)

    def publish_position_update(
        self,
        product_id: str,
        position_data: Dict[str, Any],
    ) -> None:
        update_position(product_id, position_data)

    def publish_engine_status(self, status_data: Dict[str, Any]) -> None:
        update_engine_status(status_data)

    def publish_log_entry(
        self,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        add_log_entry(level, message, context)

    def publish_ticker(
        self,
        product_id: str,
        price: float,
        price_24h: Optional[float] = None,
        cb_time: Any = None,
    ) -> None:
        broadcast_ticker(
            product_id,
            price,
            price_24h=price_24h,
            cb_time=cb_time,
        )

    def record_spread(
        self,
        product_id: str,
        bid: float,
        ask: float,
    ) -> None:
        record_spread_tick(product_id, bid, ask)


def _take_spread_snapshot() -> list:
    """Return and reset the current spread window in bounded memory."""

    snapshot = []
    with spread_lock:
        for product_id, data in spread_data.items():
            sample_count = int(data['sample_count'])
            if sample_count <= 0:
                continue

            avg_bid = data['bid_total'] / sample_count
            avg_ask = data['ask_total'] / sample_count
            snapshot.append({
                'product_id': product_id,
                'bid': round(avg_bid, 8),
                'ask': round(avg_ask, 8),
                'mid': round((avg_bid + avg_ask) / 2, 8),
            })

            data['bid_total'] = 0.0
            data['ask_total'] = 0.0
            data['sample_count'] = 0
            data['last_window'] = datetime.utcnow().timestamp()
    return snapshot


async def _async_broadcast_spread(spread_snapshot: list):
    """Async version of broadcast_spread for scheduling from event loop."""
    message = encode_notification(
        OperatorNotificationMethod.MARKET_SPREAD_SNAPSHOT,
        {
            "spreads": spread_snapshot,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    await _broadcast_dashboard_message(message)


def _stealth_orders_snapshot_payload() -> Dict[str, Any]:
    """Build the current enriched stealth-order projection."""

    with state_lock:
        orders_snapshot = deepcopy(engine_state["stealth_orders"])

    # Parent enrichment performs database I/O. Never hold state_lock while
    # waiting for it, and fetch all relevant parents in one query.
    enriched_orders = _enrich_stealth_orders_with_parent_data(
        orders_snapshot
    )
    return {
        "orders": _normalize_stealth_orders_for_operator(
            enriched_orders
        ),
        "repricing_stats": _calculate_repricing_statistics(
            enriched_orders
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def send_stealth_orders_snapshot(websocket: WebSocketServerProtocol):
    """Send the current canonical stealth-order projection notification."""
    try:
        await _send_dashboard_notification(
            websocket,
            encode_notification(
                OperatorNotificationMethod.STEALTH_ORDERS_PROJECTION,
                _stealth_orders_snapshot_payload(),
            ),
        )
    except Exception as e:
        logger.error(f"Failed to send stealth orders snapshot: {e}")


async def _broadcast_stealth_orders_projection() -> None:
    """Broadcast the current canonical stealth-order projection."""

    await _broadcast_dashboard_message(
        encode_notification(
            OperatorNotificationMethod.STEALTH_ORDERS_PROJECTION,
            _stealth_orders_snapshot_payload(),
        )
    )


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
        policy = RepricingPolicy.from_dict(order_data.get("anchor_repricing_policy_json"))
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
    from database.order import get_parent_orders_by_client_ids

    parent_ids = {
        order_data.get("parent_order_id") or order_id
        for order_id, order_data in orders.items()
        if isinstance(order_data, dict)
    }
    try:
        parent_rows = get_parent_orders_by_client_ids(tuple(parent_ids))
    except Exception as exc:
        logger.debug(f"Failed to load parent data for dashboard enrichment: {exc}")
        parent_rows = []
    parents_by_client_order_id = {
        row.get("client_order_id"): row
        for row in parent_rows
        if isinstance(row, dict) and row.get("client_order_id")
    }

    enriched = {}
    for order_id, order_data in orders.items():
        enriched_order = order_data.copy() if isinstance(order_data, dict) else dict(order_data)
        
        # Check if this is a parent or child order
        parent_order_id = enriched_order.get("parent_order_id")
        
        if parent_order_id:
            parent_data = parents_by_client_order_id.get(parent_order_id)
            if parent_data:
                enriched_order["parent_target_movement"] = parent_data.get("target_movement")
                enriched_order["parent_target_movement_type"] = parent_data.get("target_movement_type", "P")
                enriched_order["parent_max_order_replacements"] = parent_data.get("max_order_replacement", 0)
        else:
            parent_data = parents_by_client_order_id.get(order_id)
            if parent_data:
                enriched_order["max_order_replacements"] = parent_data.get("max_order_replacement", 0)
                # Also ensure we have the parent's target movement for consistent UI display
                if not enriched_order.get("target_movement"):
                    enriched_order["target_movement"] = parent_data.get("target_movement")
                if not enriched_order.get("target_movement_type"):
                    enriched_order["target_movement_type"] = parent_data.get("target_movement_type", "P")
        
        enriched[order_id] = enriched_order
    
    return enriched


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
                    
                    await _broadcast_stealth_orders_projection()
                except Exception as e:
                    logger.debug(f"Error refreshing stealth orders: {e}")
        
        except Exception as e:
            logger.debug(f"Stealth orders refresh loop error: {e}")


async def _spread_broadcast_loop():
    """Background task to broadcast spread snapshots every second."""
    while True:
        try:
            await asyncio.sleep(1)
            snapshot = _take_spread_snapshot()
            if snapshot and connected_clients:
                await _async_broadcast_spread(snapshot)
        except Exception as e:
            logger.debug(f"Spread broadcast loop error: {e}")


async def run_websocket_server(host: str = "localhost", port: int = 8765):
    """Start configured WebSocket transport on ``host`` and ``port``."""
    global server_event_loop
    server_event_loop = asyncio.get_event_loop()
    
    logger.info(f"Starting WebSocket server on ws://{host}:{port}")
    
    # Start spread broadcast loop as background task
    asyncio.create_task(_spread_broadcast_loop())
    
    # Start stealth orders refresh loop as background task
    asyncio.create_task(_stealth_orders_refresh_loop())
    
    async with websockets.serve(handler, host, port):
        logger.info(f"WebSocket server running. Connect dashboard.html to ws://{host}:{port}")
        await asyncio.Event().wait()  # Run forever


def start_dashboard_server(host: str = DASHBOARD_SERVER_HOST, port: int = DASHBOARD_SERVER_PORT):
    """Start the configured transport in a daemon thread."""
    
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

    The :mod:`main` composition root calls this after constructing the fully
    wired bridge.  ``dashboard_server.py`` is not a supported standalone
    runtime entrypoint.
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


if __name__ == "__main__":
    raise SystemExit(
        "dashboard_server.py is an embedded transport. Start the trading "
        "runtime with: python -m main"
    )
