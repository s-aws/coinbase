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
from datetime import datetime, timezone
from threading import Thread, Lock
from typing import Any, Dict, Optional, Set
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
    OrderStatus,
    RepricingReferenceSource,
    StealthOrderStatus,
    StealthSpanResultStatus,
)
from core.models import RepricingPolicy
from core.exceptions import WebSocketMessageError, OrderCreationError
from core.runtime_controller import (
    get_runtime_controller,
    validate_drain_timeout_seconds,
)
from calculation.formatter import safe_float

# Message types that *originate* new work and are gated on EngineState.RUNNING.
# Cancellations, queries, and admin commands are intentionally excluded so the
# engine remains controllable and existing positions can be wound down while
# paused or draining.
_ORIGINATING_MSG_TYPES = frozenset({
    "create_stealth_order",
    "create_stealth_order_span",
    "reprice_now_stealth_order",
    "rehide_stealth_order",
    "move_revealed_stealth_order",
    "import_stealth_orders",
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
)

logger = get_logger("DashboardServer")

# Global state
connected_clients: Set[WebSocketServerProtocol] = set()
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


def configure_runtime_dependencies(
    *,
    orderbook: Any,
    state_publish_interval_seconds: float,
) -> None:
    """Install the live adapters owned and constructed by ``main.py``."""

    if orderbook is None:
        raise ValueError("orderbook is required")
    interval = max(0.01, float(state_publish_interval_seconds))

    global ORDERBOOK
    global DASHBOARD_STATE_PUBLISH_INTERVAL_SECONDS
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
                await _send_dashboard_message(websocket, json_lib.dumps(products_payload))
    except Exception as e:
        logger.error(f"Failed to send products list: {e}")
    
    # Send current state to newly connected client
    await broadcast_state(websocket)


async def unregister_client(websocket: WebSocketServerProtocol):
    """Unregister a disconnected client."""
    connected_clients.discard(websocket)
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
        connected_clients.discard(client)
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
        connected_clients.discard(client)
        raise
    except Exception as exc:
        connected_clients.discard(client)
        logger.debug(f"Dashboard client broadcast failed: {exc}")
        raise


async def _broadcast_dashboard_message(message: str) -> None:
    """Fan one serialized message out through the bounded send path."""

    for client in connected_clients.copy():
        try:
            await _send_dashboard_message(client, message)
        except Exception:
            # One dead or lagging browser must not block other clients.
            pass


def _build_state_update_message() -> str:
    """Capture and serialize one internally consistent dashboard snapshot."""

    market_metrics = _build_market_metrics_payload()
    with state_lock:
        engine_state["market_metrics"] = market_metrics
        state_snapshot = deepcopy(engine_state)
    payload = {
        "type": "state_update",
        "data": state_snapshot,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return json.dumps(payload, cls=CustomJSONEncoder)


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
        await _send_dashboard_message(
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


def _cancel_managed_stealth_order(stealth_order_id: str, reason: str) -> Dict[str, Any]:
    """Return committed local truth, never treating REST acceptance as final."""
    if not isinstance(stealth_order_id, str) or not stealth_order_id.strip():
        raise ValueError("A non-empty stealth_order_id is required")
    if stealth_order_bridge is None:
        raise RuntimeError("Stealth order system not initialized")
    with stealth_order_bridge._get_order_action_lock(stealth_order_id):
        accepted = stealth_order_bridge.cancel_stealth_order(stealth_order_id, reason)
        current = stealth_order_bridge.stealth_manager._get_stealth_order(stealth_order_id)
        order = deepcopy(current) if current is not None else None
    pending = _stealth_exchange_cancel_pending(order) if order is not None else False
    response = {
        "stealth_order_id": stealth_order_id,
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
            engine_state["stealth_orders"][stealth_order_id] = deepcopy(order)
    return response


async def handle_client_message(websocket: WebSocketServerProtocol, message: str):
    """Handle incoming messages from client.
    
    Raises:
        WebSocketMessageError: If message parsing fails or required fields missing
        OrderCreationError: If order placement fails
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
        # not RUNNING (starting / paused / draining / stopped). Cancels, queries, and
        # admin messages pass through so operators can still control the
        # system and wind down existing positions.
        controller = get_runtime_controller()
        if msg_type in _ORIGINATING_MSG_TYPES and not controller.is_admitting():
            if controller.state is EngineState.STARTING:
                rejection_message = (
                    "Engine startup is still completing; new orders are not "
                    "being accepted yet."
                )
            else:
                rejection_message = (
                    f"Engine is {controller.state.value}; new orders are not "
                    f"being accepted. Resume the engine to place new orders."
                )
            response = {
                "type": "admission_rejected",
                "rejected_type": msg_type,
                "engine_state": controller.state.value,
                "message": rejection_message,
            }
            await _send_dashboard_message(websocket, json.dumps(response))
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
                "startup_pause_pending": controller.startup_pause_pending(),
                "inflight": controller.inflight_snapshot(),
                "total_inflight": controller.total_inflight(),
                "timestamp": datetime.utcnow().isoformat(),
            }
            await _send_dashboard_message(websocket, json.dumps(response))
            return

        if msg_type == "admin_pause":
            changed = controller.request_pause()
            response = {
                "type": "admin_pause_response",
                "changed": changed,
                "engine_state": controller.state.value,
                "startup_pause_pending": controller.startup_pause_pending(),
            }
            if changed:
                if controller.state is EngineState.STARTING:
                    add_log_entry(
                        "WARNING",
                        "Engine pause requested during startup via admin_pause",
                    )
                else:
                    add_log_entry("WARNING", "Engine paused via admin_pause")
            await _send_dashboard_message(websocket, json.dumps(response))
            return

        if msg_type == "admin_resume":
            changed = controller.resume()
            response = {
                "type": "admin_resume_response",
                "changed": changed,
                "engine_state": controller.state.value,
                "startup_pause_pending": controller.startup_pause_pending(),
            }
            if changed:
                add_log_entry("INFO", "Engine resumed via admin_resume")
            await _send_dashboard_message(websocket, json.dumps(response))
            return

        if msg_type == "admin_shutdown":
            # Close admission synchronously, then acknowledge and run the
            # bounded drain in a worker so the asyncio loop stays responsive.
            # This prevents startup readiness from winning after the operator
            # has already requested shutdown.
            try:
                timeout = validate_drain_timeout_seconds(
                    data.get("timeout_seconds", 30.0)
                )
            except ValueError as exc:
                await _send_dashboard_message(websocket, json.dumps({
                    "type": "admin_shutdown_response",
                    "accepted": False,
                    "engine_state_before": controller.state.value,
                    "message": str(exc),
                }))
                return
            state_before = controller.state
            controller.request_shutdown()
            response = {
                "type": "admin_shutdown_response",
                "accepted": True,
                "timeout_seconds": timeout,
                "engine_state_before": state_before.value,
            }

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
                # Admission is already closed. If the worker cannot be
                # created, complete the same single-owner drain here instead
                # of leaving the runtime stranded in DRAINING.
                logger.exception(
                    "Could not start admin drain worker; draining synchronously"
                )
                controller.drain_and_stop(timeout_seconds=timeout)
            await _send_dashboard_message(websocket, json.dumps(response))
            add_log_entry(
                "WARNING",
                f"Engine shutdown requested (timeout={timeout}s)",
            )
            return
        
        if msg_type == "request_stealth_orders":
            # Send current stealth orders snapshot
            await send_stealth_orders_snapshot(websocket)

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
                await _send_dashboard_message(websocket, json.dumps(response))
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
                await _send_dashboard_message(websocket, json.dumps(response))
            except Exception as e:
                logger.exception("Failed to export active stealth orders")
                response = {
                    "type": "export_active_stealth_orders_response",
                    "status": "error",
                    "message": f"Export failed: {e}",
                }
                await _send_dashboard_message(websocket, json.dumps(response))

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
                await _send_dashboard_message(websocket, json.dumps(response))
                return

            if not stealth_order_bridge:
                response = {
                    "type": "import_stealth_orders_response",
                    "status": "error",
                    "message": "Stealth order system not initialized",
                }
                await _send_dashboard_message(websocket, json.dumps(response))
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
            await _send_dashboard_message(websocket, json.dumps(response))
            # Push fresh state to all clients so the new orders show up.
            await broadcast_stealth_order_update({
                "type": "stealth_orders_imported",
                "imported": success_count,
                "total": len(orders_to_import),
            })

        elif msg_type == "create_stealth_order_span":
            span = data.get("span")
            span_id = span.get("span_id") if isinstance(span, dict) else None
            if not isinstance(span, dict):
                await _send_dashboard_message(websocket, json.dumps({
                    "type": "stealth_order_span_result",
                    "span_id": span_id,
                    "status": "error",
                    "requested_count": 0,
                    "created_count": 0,
                    "existing_count": 0,
                    "failed_count": 1,
                    "orders": [],
                    "error": "Missing or invalid span data",
                }))
                return
            if not stealth_order_bridge:
                await _send_dashboard_message(websocket, json.dumps({
                    "type": "stealth_order_span_result",
                    "span_id": span_id,
                    "status": "error",
                    "requested_count": span.get("order_count", 0),
                    "created_count": 0,
                    "existing_count": 0,
                    "failed_count": 1,
                    "orders": [],
                    "error": "Stealth order system not initialized",
                }))
                return

            try:
                result = stealth_order_bridge.create_stealth_order_span(span)
                response = {
                    "type": "stealth_order_span_result",
                    **result,
                }
                with state_lock:
                    for order_result in result.get("orders", []):
                        client_order_id = order_result.get("client_order_id")
                        if not client_order_id:
                            continue
                        current = stealth_order_bridge.stealth_manager.in_memory_orders.get(
                            client_order_id
                        )
                        if current is not None:
                            engine_state["stealth_orders"][client_order_id] = (
                                stealth_order_bridge.stealth_manager._serialize_order_for_json(
                                    current
                                )
                            )
                add_log_entry(
                    "INFO"
                    if result.get("status") == StealthSpanResultStatus.SUCCESS.value
                    else "WARNING",
                    "Stealth order span "
                    f"{result.get('status')}: {result.get('created_count', 0)} created, "
                    f"{result.get('existing_count', 0)} existing, "
                    f"{result.get('failed_count', 0)} failed",
                )
            except Exception as exc:
                logger.exception("Failed to create stealth order span")
                response = {
                    "type": "stealth_order_span_result",
                    "span_id": span_id,
                    "status": StealthSpanResultStatus.ERROR.value,
                    "requested_count": span.get("order_count", 0),
                    "created_count": 0,
                    "existing_count": 0,
                    "failed_count": 1,
                    "orders": [],
                    "error": str(exc),
                }
                add_log_entry("ERROR", f"Stealth order span creation failed: {exc}")

            await _send_dashboard_message(
                websocket,
                json.dumps(response, cls=CustomJSONEncoder),
            )
            # The request receives one aggregate result; all clients then get
            # one authoritative state refresh instead of N per-rung success
            # broadcasts from the browser loop.
            await broadcast_state()

        elif msg_type == "create_stealth_order":
            # Create new stealth order
            logger.info("[HANDLER] create_stealth_order message received")
            order = data.get("order")
            
            if not order:
                response = {
                    "type": "error",
                    "message": "Missing order data"
                }
                await _send_dashboard_message(websocket, json.dumps(response))
                return
            
            if not stealth_order_bridge:
                response = {
                    "type": "error",
                    "message": "Stealth order system not initialized"
                }
                await _send_dashboard_message(websocket, json.dumps(response))
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
                add_log_entry("ERROR", f"Stealth order creation failed: {str(e)}")
                await _send_dashboard_message(websocket, json.dumps(response))
        
        elif msg_type == "cancel_stealth_order":
            stealth_order_id = data.get("stealth_order_id")
            try:
                response = _cancel_managed_stealth_order(stealth_order_id, "user_cancelled")
            except Exception as exc:
                response = {
                    "stealth_order_id": stealth_order_id, "accepted": False,
                    "exchange_cancel_pending": False, "error": str(exc), "message": str(exc),
                }
            response["type"] = "stealth_order_cancel_result"
            await _send_dashboard_message(websocket, json.dumps(response, cls=CustomJSONEncoder))
        
        elif msg_type == "rehide_stealth_order":
            stealth_order_id = data.get("stealth_order_id")
            response = {
                "type": "stealth_order_rehide_result",
                "stealth_order_id": stealth_order_id,
                "accepted": False,
            }
            try:
                if not isinstance(stealth_order_id, str) or not stealth_order_id.strip():
                    raise ValueError("Missing or invalid stealth_order_id")
                if not stealth_order_bridge:
                    raise RuntimeError("Stealth order system is not initialized")
                # The bridge owns readiness, atomic admission, and same-order
                # serialization. Acceptance is not confirmation of cancellation.
                if not stealth_order_bridge.rehide_stealth_order(stealth_order_id):
                    raise ValueError("Rehide request was not accepted; refresh the order and retry")
            except Exception as exc:
                response["error"] = str(exc)
                response["message"] = f"Rehide not accepted: {exc}"
                logger.warning("Rehide not accepted for %s: %s", stealth_order_id, exc)
            else:
                response["accepted"] = True
                response["message"] = (
                    "Rehide requested; exchange withdrawal confirmation is pending. "
                    "The same order may reveal again when its condition is satisfied."
                )
                add_log_entry("INFO", f"Stealth order rehide requested: {stealth_order_id}")
            # Never infer HIDDEN from an accepted request or overwrite the cache.
            await _send_dashboard_message(websocket, json.dumps(response))

        elif msg_type == "reprice_now_stealth_order":
            # Immediately trigger anchor repricing for a single stealth order,
            # bypassing the next_reprice_at cooldown.
            stealth_order_id = data.get("stealth_order_id")
            if not stealth_order_id or not stealth_order_bridge:
                await _send_dashboard_message(websocket, json.dumps({
                    "type": "error",
                    "message": "Missing stealth_order_id or system not initialised"
                }))
                return

            try:
                mgr = stealth_order_bridge.stealth_manager
                order = mgr.in_memory_orders.get(stealth_order_id)
                if not order:
                    await _send_dashboard_message(websocket, json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": "Order not found"
                    }))
                    return

                policy = RepricingPolicy.from_dict(order.get("anchor_repricing_policy_json"))
                if not policy.enabled:
                    await _send_dashboard_message(websocket, json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": "Anchor repricing not enabled for this order"
                    }))
                    return

                active_statuses = {"HIDDEN", "PENDING", "TRIGGERED", "REVEALED"}
                if order.get("status") not in active_statuses:
                    await _send_dashboard_message(websocket, json.dumps({
                        "type": "reprice_now_result",
                        "stealth_order_id": stealth_order_id,
                        "processed": 0,
                        "error": f"Order status {order.get('status')} is not repriceable"
                    }))
                    return

                # The bridge owns manual anchor scheduling so the persisted
                # next_reprice_at and disposable heap deadline cannot diverge.
                processed = stealth_order_bridge.reprice_stealth_order_now(
                    stealth_order_id
                )

                add_log_entry("INFO", f"Manual reprice triggered for {stealth_order_id}: processed={processed}")
                logger.info(f"[REPRICE-NOW] {stealth_order_id} processed={processed}")

                await _send_dashboard_message(websocket, json.dumps({
                    "type": "reprice_now_result",
                    "stealth_order_id": stealth_order_id,
                    "processed": processed
                }))

            except Exception as e:
                logger.error(f"reprice_now_stealth_order failed: {e}")
                await _send_dashboard_message(websocket, json.dumps({
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
                await _send_dashboard_message(websocket, json.dumps({
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
                        await _send_dashboard_message(websocket, json.dumps({
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
                await _broadcast_dashboard_message(message)

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
                await _send_dashboard_message(websocket, json.dumps({
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
                await _send_dashboard_message(websocket, json.dumps({
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
                await _send_dashboard_message(websocket, json.dumps(response))
                return

            if price_threshold is None:
                response = {
                    "type": "error",
                    "message": "Missing price_threshold"
                }
                await _send_dashboard_message(websocket, json.dumps(response))
                return

            try:
                threshold = float(price_threshold)
            except (TypeError, ValueError):
                response = {
                    "type": "error",
                    "message": "price_threshold must be numeric"
                }
                await _send_dashboard_message(websocket, json.dumps(response))
                return

            if threshold <= 0:
                response = {
                    "type": "error",
                    "message": "price_threshold must be greater than 0"
                }
                await _send_dashboard_message(websocket, json.dumps(response))
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
                    await _send_dashboard_message(websocket, json.dumps(response))
                    return

            try:
                from database.order import get_stealth_order_by_id

                existing = get_stealth_order_by_id(stealth_order_id)
                if not existing:
                    response = {
                        "type": "error",
                        "message": f"Stealth order not found: {stealth_order_id}"
                    }
                    await _send_dashboard_message(websocket, json.dumps(response))
                    return

                if str(existing.get("reveal_condition_type", "")).lower() != "price":
                    response = {
                        "type": "error",
                        "message": "Threshold updates are only supported for price reveal conditions"
                    }
                    await _send_dashboard_message(websocket, json.dumps(response))
                    return

                if not stealth_order_bridge:
                    response = {
                        "type": "error",
                        "message": "Stealth order bridge is not available",
                    }
                    await _send_dashboard_message(websocket, json.dumps(response))
                    return

                try:
                    stealth_order_bridge.update_price_condition(
                        stealth_order_id,
                        price_threshold=threshold,
                        hold_duration_seconds=hold_secs,
                    )
                except Exception as update_error:
                    logger.exception(
                        "Failed to update stealth price condition for %s",
                        stealth_order_id,
                    )
                    response = {
                        "type": "error",
                        "message": str(update_error),
                    }
                    await _send_dashboard_message(websocket, json.dumps(response))
                    return

                hold_duration_persisted = hold_secs is not None

                affected_conditions = {}
                manager = stealth_order_bridge.stealth_manager
                affected_snapshot = getattr(
                    manager,
                    "strategy_condition_order_ids",
                    None,
                )
                affected_ids = (
                    affected_snapshot(stealth_order_id)
                    if callable(affected_snapshot)
                    else (stealth_order_id,)
                )
                if not isinstance(affected_ids, (list, tuple, set)):
                    affected_ids = (stealth_order_id,)
                for affected_id in affected_ids:
                    affected_order = manager.in_memory_orders.get(affected_id)
                    if not isinstance(affected_order, dict):
                        continue
                    affected_conditions[affected_id] = deepcopy(
                        affected_order.get("reveal_condition_json") or {}
                    )

                # Sync state payload cache
                with state_lock:
                    for affected_id, reveal_json in affected_conditions.items():
                        if affected_id in engine_state["stealth_orders"]:
                            engine_state["stealth_orders"][affected_id][
                                "reveal_condition_json"
                            ] = deepcopy(reveal_json)

                response = {
                    "type": "stealth_threshold_updated",
                    "stealth_order_id": stealth_order_id,
                    "price_threshold": threshold,
                    "hold_duration_seconds": hold_secs if hold_duration_persisted else None,
                    "affected_conditions": affected_conditions,
                }

                add_log_entry("INFO", f"Stealth threshold updated: {stealth_order_id} -> {threshold}" + (f", hold={hold_secs}s" if hold_secs is not None else ""))
                logger.info(f"Stealth threshold updated: {stealth_order_id} -> {threshold}" + (f", hold={hold_secs}s" if hold_secs is not None else ""))

                message = json.dumps(response, cls=CustomJSONEncoder)
                await _broadcast_dashboard_message(message)

                await _send_dashboard_message(websocket, json.dumps({"type": "update_success", "message": "Threshold updated"}))

            except Exception as e:
                logger.error(f"Failed to update stealth threshold: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update threshold: {str(e)}"
                }
                add_log_entry("ERROR", f"Stealth threshold update failed: {str(e)}")
                await _send_dashboard_message(websocket, json.dumps(response))
        
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
                await _send_dashboard_message(websocket, json.dumps(response))
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
                    await _broadcast_dashboard_message(message)
                    
                    await _send_dashboard_message(websocket, json.dumps({"type": "update_success", "message": "Parent target movement updated"}))
                else:
                    response = {
                        "type": "error",
                        "message": f"Failed to update parent order: {parent_order_id}"
                    }
                    add_log_entry("ERROR", f"Failed to update parent target_movement: {parent_order_id}")
                    await _send_dashboard_message(websocket, json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to update parent target_movement: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update parent target movement: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent target_movement update failed: {str(e)}")
                await _send_dashboard_message(websocket, json.dumps(response))

        elif msg_type == "clear_all_stealth_orders":
            # Stop through the canonical path, but preserve recovery evidence
            # until every cancellation is settled. The operator can retry Clear
            # All afterwards; there is no deferred deletion job.
            try:
                from database.order import clear_all_stealth_orders

                cancelled_in_memory = 0
                cancel_failures = 0
                mgr = None
                if stealth_order_bridge is not None:
                    mgr = stealth_order_bridge.stealth_manager
                    orders = stealth_order_bridge.get_stealth_orders()
                    for sid, order in orders.items():
                        if (
                            order.get("status") in _TERMINAL_STEALTH_STATUSES
                            and not _stealth_exchange_cancel_pending(order)
                        ):
                            continue
                        try:
                            outcome = _cancel_managed_stealth_order(
                                sid, "Clear All Orders (dashboard)"
                            )
                            if outcome["accepted"]:
                                cancelled_in_memory += 1
                            else:
                                cancel_failures += 1
                        except Exception as cancel_exc:
                            cancel_failures += 1
                            logger.error(
                                f"Clear All: failed to cancel stealth order {sid}: {cancel_exc}"
                            )
                # Do not acquire a SID action lock while holding the creation
                # lock: creation takes them in the opposite order.
                with mgr._creation_lock if mgr is not None else nullcontext():
                    current = stealth_order_bridge.get_stealth_orders() if mgr is not None else {}
                    pending = any(_stealth_exchange_cancel_pending(row) for row in current.values())
                    active = any(row.get("status") not in _TERMINAL_STEALTH_STATUSES for row in current.values())
                    blocked = bool(cancel_failures or pending or active)
                    if not blocked:
                        result = clear_all_stealth_orders()
                        if result["success"] and mgr is not None:
                            mgr.clear_in_memory_orders()
                            mgr._placed_order_index.clear()
                if blocked:
                    await _send_dashboard_message(websocket, json.dumps({
                        "type": "stealth_orders_clear_result", "cleared": False,
                        "exchange_cancel_pending": pending,
                        "in_memory_cancelled": cancelled_in_memory,
                        "in_memory_cancel_failures": cancel_failures,
                        "message": "No records deleted. Resolve outstanding cancellations, then retry Clear All.",
                    }))
                    return

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
                    await _broadcast_dashboard_message(message)
                else:
                    response = {
                        "type": "error",
                        "message": f"Failed to clear orders: {result.get('error', 'Unknown error')}"
                    }
                    add_log_entry("ERROR", f"Failed to clear stealth orders: {result.get('error')}")
                    await _send_dashboard_message(websocket, json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to clear stealth orders: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to clear orders: {str(e)}"
                }
                add_log_entry("ERROR", f"Clear stealth orders failed: {str(e)}")
                await _send_dashboard_message(websocket, json.dumps(response))
        
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
                
                if not update_parent_order(
                    client_order_id,
                    update_data,
                    metadata_reader=_product_metadata_reader,
                ):
                    raise OrderCreationError(
                        "Parent order update failed boundary or persistence validation",
                        client_order_id=client_order_id,
                    )
                
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
                await _broadcast_dashboard_message(message)
                
            except Exception as e:
                logger.error(f"Failed to update parent order: {e}")
                response = {
                    "type": "error",
                    "message": f"Failed to update order: {str(e)}"
                }
                add_log_entry("ERROR", f"Parent order update failed: {str(e)}")
                await _send_dashboard_message(websocket, json.dumps(response))
        
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
    payload = {
        "type": "ticker",
        "data": ticker_data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    message = json.dumps(payload)
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
    payload = {
        "type": "spread_snapshot",
        "data": spread_snapshot,
        "timestamp": datetime.utcnow().isoformat(),
    }
    message = json.dumps(payload)
    await _broadcast_dashboard_message(message)


async def send_stealth_orders_snapshot(websocket: WebSocketServerProtocol):
    """Send current stealth orders to a client."""
    try:
        with state_lock:
            orders_snapshot = deepcopy(engine_state["stealth_orders"])

        # Parent enrichment performs database I/O. Never hold state_lock while
        # waiting for it, and fetch all relevant parents in one query.
        enriched_orders = _enrich_stealth_orders_with_parent_data(orders_snapshot)
        repricing_stats = _calculate_repricing_statistics(enriched_orders)
        payload = {
            "type": "stealth_orders_snapshot",
            "orders": enriched_orders,
            "repricing_stats": repricing_stats,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        await _send_dashboard_message(websocket, json.dumps(payload, cls=CustomJSONEncoder))
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


async def broadcast_stealth_order_update(update: Dict[str, Any]):
    """Broadcast stealth order update to all connected clients."""
    global server_event_loop
    
    if not server_event_loop or not connected_clients:
        return
    
    try:
        message = json.dumps(update, cls=CustomJSONEncoder)
        
        await _broadcast_dashboard_message(message)
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
                    await _broadcast_dashboard_message(message)
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
