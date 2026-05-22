"""OrderEngine - multithreaded event-driven order lifecycle engine.

This module coordinates Coinbase WebSocket events, thread-safe in-memory state,
and persistent order/position tracking.

Current feature set:
- Real-time user/ticker ingestion and channel queue fan-out.
- Event deduplication via rolling hash buckets (EventBridge).
- RLock-protected orderbook mutations.
- Parent-child lifecycle management with flat hierarchy semantics.
- Follow-up generation for FILLED/CANCELLED flows using target movement rules.
- Stealth order integration via StealthOrderBridge and reveal-linked fills.
- Optional lot tracking via post-fill hooks.
- Optional dashboard broadcasting for orders, positions, ticker, and logs.

Critical ID semantics:
- Use client_order_id for all internal tracking and parent-child linkage.
- Use order_id only for exchange-facing operations and external references.

Extension points:
- websocket_hooks: add custom WebSocket message handlers without forking core loops.
- fill_event_hooks: add post-fill business integrations (risk, analytics, persistence).
- logging_flags + structured payload builders: increase observability safely.

Example: initialize and run
    >>> from core.order_engine import OrderEngine
    >>> engine = OrderEngine(
    ...     orderbook=ORDERBOOK,
    ...     db_module=DB_MODULE,
    ...     subscription=Subscription,
    ...     api_key=API_KEY,
    ...     api_secret=API_SECRET,
    ...     order_post_only=ORDER_POST_ONLY,
    ...     websocket_thread_maximum=2,
    ...     max_workers=8,
    ... )
    >>> engine.logging_flags['order'] = True
    >>> engine.run_forever()

Example: register a custom fill hook
    >>> def my_fill_hook(fill_context: dict) -> None:
    ...     return
    >>> if engine.fill_event_hooks:
    ...     engine.fill_event_hooks.register('my_fill_hook', my_fill_hook)

Example: resolve parent linkage
    >>> is_parent, parent_id = engine.resolve_parent_client_order_id(
    ...     client_order_id='550e8400-e29b-41d4-a716-446655440000'
    ... )
    >>> isinstance(is_parent, bool)
    True
"""

import json
import threading
import uuid
from time import sleep
from queue import Queue, Full, Empty
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any, Dict, List, Optional
from coinbase.websocket import WSClient, WSClientConnectionClosedException

from external import CoinbaseWebSocketClient

from configuration import (
    DEFAULT_MAX_ORDER_REPLACEMENT,
    calculate_new_order_move_from_snapshot,
    apply_calculated_position_update,
    get_futures_positions,
    get_trading_product_id,
)

from core.constants import get_local_now
from core.enums import OrderStatus, OrderSide, ProductType, FollowUpRevealDirection, Direction, TargetMovementType, ChannelType, StealthOrderStatus, EventStreamType, EventSourceChannel
from core.stealth_order_manager import resolve_stealth_chain_root
from core.exceptions import (
    OrderProcessingError,
    OrderCalculationError,
    OrderCreationError,
    FollowUpOrderError,
    WebSocketMessageError,
    CoinbaseAPIError,
)
from calculation.resolver import (
    resolve_order_size,
    resolve_order_side,
    resolve_cumulative_filled,
    resolve_remaining_size,
    resolve_partial_fill_delta,
)
from calculation.formatter import safe_float
from bridges.event_bridge import EventBridge
from business.order_progress import OrderProgressTracker, OrderSnapshotDelta
from integration.websocket_hooks import WebSocketHookRegistry, get_global_hook_registry
from integration.order_placement_hooks import get_global_placement_hook_registry

# Dashboard integration (optional - will fail gracefully if dashboard_server not available)
try:
    from dashboard_server import update_order, update_position, add_log_entry, update_engine_status, broadcast_ticker, record_spread_tick
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    def update_order(*args, **kwargs): pass
    def update_position(*args, **kwargs): pass
    def add_log_entry(*args, **kwargs): pass
    def update_engine_status(*args, **kwargs): pass
    def broadcast_ticker(*args, **kwargs): pass
    def record_spread_tick(*args, **kwargs): pass

# Market-tick persistence (optional - degrades to no-op if module fails to
# import, e.g. in DB-less smoke tests). Used by the slide-calibration view
# to draw the market-mid reference line. See business/market_tick_recorder.py.
try:
    from business.market_tick_recorder import (
        get_recorder as _get_market_tick_recorder,
        init_recorder as _init_market_tick_recorder,
    )
    MARKET_TICK_RECORDER_AVAILABLE = True
except ImportError:
    MARKET_TICK_RECORDER_AVAILABLE = False
    def _get_market_tick_recorder(): return None
    def _init_market_tick_recorder(*args, **kwargs): return None

# In-memory Fibonacci-window market metrics. Read by the dashboard (and
# console UI) at broadcast time; written here on every ticker tick. No DB,
# no I/O, bounded memory. Keep this hook in lock-step with
# ``business/market_metrics.py::FIBONACCI_WINDOWS_MINUTES``.
try:
    from business.market_metrics import (
        get_market_metrics_tracker as _get_market_metrics_tracker,
    )
    MARKET_METRICS_AVAILABLE = True
except ImportError:
    MARKET_METRICS_AVAILABLE = False
    def _get_market_metrics_tracker(): return None

# Lot tracking integration (optional - will fail gracefully if not available).
# Note: production fills flow through OrderProgressTracker ->
# FillLedgerRepository.append_derived_fill(delta); the legacy
# post_fill_hook.on_order_filled helper is retained only for offline
# backfill scripts and is no longer imported here.
try:
    from integration.fill_event_hooks import get_global_fill_event_hook_registry
    LOT_TRACKING_AVAILABLE = True
except ImportError:
    LOT_TRACKING_AVAILABLE = False
    def get_global_fill_event_hook_registry(): return None


class OrderEngine:
    """Multithreaded trading engine for Coinbase Advanced API order management.
    
    Orchestrates realtime event processing, parent-child tracking, follow-up
    creation, and optional business integrations (dashboard, lot tracking, hooks).
    
    Attributes:
        orderbook: OrderBook instance (source-of-truth for orders/positions).
        db_module: Database client for persisting parent/child orders.
        subscription: Subscription config (products, channels).
        api_key: Coinbase API key for websocket authentication.
        api_secret: Coinbase API secret for websocket authentication.
        order_post_only: Dict mapping side ('BUY'/'SELL') to post_only flag.
        websocket_thread_maximum: Number of websocket connection threads.
        max_workers: Thread pool size for event processing.
        max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval (seconds).
        max_seen_event_buckets: Number of rolling dedup hash buckets.
        ticker: Dict mapping product_id to last ticker data.
        ticker_lock: Thread lock for ticker updates.
        orderbook_lock: Thread lock for orderbook mutations.
        event_executor: ThreadPoolExecutor for user event processing.
        event_queue: Dict mapping channel name to Queue.
        logging_flags: Dict controlling which log types are emitted.
        debug_logging_enabled: Whether to include debug fields in logs.
        evt_bridge: EventBridge instance for event deduplication and bucket rotation.
        websocket_events: Event type schemas (internal reference).
        websocket_hooks: Registry for WebSocket extension hooks.
        fill_event_hooks: Registry for post-fill extension hooks.
    
    Example:
        >>> from core.order_engine import OrderEngine
        >>> engine = OrderEngine(
        ...     orderbook=ORDERBOOK,
        ...     db_module=DB_MODULE,
        ...     subscription=Subscription,
        ...     api_key=API_KEY,
        ...     api_secret=API_SECRET,
        ...     order_post_only=ORDER_POST_ONLY,
        ...     websocket_thread_maximum=2,
        ...     max_workers=8
        ... )
        >>> engine.logging_flags['order'] = True
        >>> engine.run_forever()
    """

    def __init__(
        self,
        orderbook,
        db_module: ModuleType,
        subscription,
        api_key,
        api_secret,
        order_post_only,
        websocket_thread_maximum=3,
        max_workers=16,
        max_rotate_seen_events_bucket_seconds=60,
        max_seen_event_buckets=3,
        queue_maxsize=10000,
        stealth_order_bridge=None,
        websocket_hooks=None,
    ) -> None:
        """Initialize the OrderEngine with configuration and state.
        
        Args:
            orderbook: OrderBook instance for state tracking.
            db_module: Database client module.
            subscription: Subscription config object.
            api_key: Coinbase API key.
            api_secret: Coinbase API secret.
            order_post_only: Dict mapping order side to post_only flag.
            websocket_thread_maximum: Number of parallel websocket threads (default 3).
            max_workers: Thread pool size (default 16).
            max_rotate_seen_events_bucket_seconds: Dedup bucket rotation interval (default 60).
            max_seen_event_buckets: Number of dedup buckets (default 3).
            queue_maxsize: Max size for event queues (default 10000).
            stealth_order_bridge: Optional StealthOrderBridge for market data updates.
            websocket_hooks: Optional WebSocketHookRegistry for extensibility (default: global registry).
        """
        self.orderbook = orderbook
        self.db_module = db_module
        self.subscription = subscription
        self.api_key = api_key
        self.api_secret = api_secret
        self.order_post_only = order_post_only
        self.stealth_order_bridge = stealth_order_bridge
        
        # WebSocket hook registry for extensible message handling
        self.websocket_hooks = websocket_hooks or get_global_hook_registry()

        self.websocket_thread_maximum = websocket_thread_maximum
        self.max_rotate_seen_events_bucket_seconds = max_rotate_seen_events_bucket_seconds
        self.max_seen_event_buckets = max_seen_event_buckets
        self.queue_maxsize = queue_maxsize

        self.ticker = {}
        self.ticker_lock = threading.RLock()
        self.orderbook_lock = threading.RLock()

        # Per-parent counter of replacement slots that have been atomically
        # claimed by a follow-up creator but whose child has not yet been
        # registered via ``register_child_order``. Together with the parent's
        # in-memory ``current_order_replacement`` it forms the gating budget
        # used by ``claim_replacement_slots``: ``current + pending < max``.
        # Without this, multiple WS-event threads each observe the same
        # stale ``current_order_replacement`` snapshot, all pass the gate
        # check, and breach ``max_order_replacement`` (see 2026-04-29
        # incident: max=1, observed current=4 with 4 BUY follow-ups
        # spawned). All access protected by ``orderbook_lock``.
        self._pending_replacement_claims: Dict[str, int] = {}

        # Diagnostic throttle for the parent/child reconciler drift
        # diagnostic. Stores monotonic seconds of the last emit so we
        # only fire one diff log per ~1h even if drift is observed
        # every reconciler tick (the typical symptom). ``None`` means
        # never emitted yet â€” the first drift detection always fires.
        self._reconcile_diff_last_emit_monotonic: Optional[float] = None

        # Suppress the periodic ``parent_child_reconciled`` success line
        # when nothing has actually changed since the last emit. The
        # reconciler runs every ~30s; emitting a 73/230 status line every
        # tick produces ~2880 identical log entries per day. We re-emit
        # only when (parent_count, child_count) differs, when force_log
        # is set (operator-initiated), or when the drift diagnostic
        # fires. ``None`` means never emitted â€” the first call always logs.
        self._last_reconciled_counts: Optional[tuple] = None

        # Dedup gate for snapshot_drift_detected. Each WS user-event
        # worker thread (we run ~6) processes the SNAPSHOT frame
        # independently and previously emitted its own drift report,
        # producing NÃ— duplicated WARNING lines for the same drift state.
        # Track the last-emitted signature per source under a lock and
        # skip re-emission when the signature is unchanged.
        self._snapshot_drift_last_signature: Dict[str, tuple] = {}
        self._snapshot_drift_emit_lock = threading.Lock()

        # Per-COID serialisation for the WS user-channel handler.
        # ``process_user_order`` runs on a ThreadPoolExecutor, so two
        # threads can race for the same brand-new external COID:
        #   T_A: cache miss â†’ resolve_parent_client_order_id populates
        #        ``orderbook.parent_order_ids`` BEFORE the DB INSERT
        #        commits.
        #   T_B: cache check passes (T_A's in-memory write) â†’ skips
        #        ensure â†’ calls _process_ws_order_delta â†’
        #        upsert_partial_fill_progress fails with FK violation
        #        because T_A's INSERT hasn't committed yet.
        # Per-COID lock makes the ensureâ†’delta pair atomic per order.
        # Different COIDs still process in parallel.
        self._coid_handler_locks: Dict[str, threading.Lock] = {}
        self._coid_handler_locks_guard = threading.Lock()

        # Cooperative shutdown signal for all background loops/threads owned
        # by this engine. Set by ``stop()`` (registered as a runtime stop
        # hook in main.py); checked by every ``while`` loop below in lieu of
        # ``while True``. Threads use ``Event.wait`` instead of ``time.sleep``
        # so they wake immediately on shutdown rather than after the next
        # interval expires.
        self._shutdown_event = threading.Event()
        # Short blocking timeout used by event-worker queue.get() calls so
        # workers can periodically observe the shutdown event between events.
        self._worker_queue_poll_seconds = 0.5

        self.event_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="user_event_thread",
        )

        self.event_queue = {
            channel: Queue(maxsize=self.queue_maxsize)
            for channel in self.subscription.channels
        }

        self.logging_flags = {
            "snapshot": False,
            "open": True,
            "filled": True,
            "cancelled": True,
            "update": True,
            "user": False,
            "ticker": False,
            "connection": True,
            "event": True,
            "order": True,
            "database": True,
            "warning": True,
            "error": True,
            "reconcile": True,
        }
        self.debug_logging_enabled = False
        
        # WebSocket event deduplication bridge
        self.evt_bridge = EventBridge(
            max_dedup_buckets=max_seen_event_buckets,
            dedup_bucket_duration_secs=max_rotate_seen_events_bucket_seconds,
        )
        
        # Profit Tracking: FeeManager and ProfitValidator for profitable order validation
        from configuration import REST_CLIENT
        from calculation.fee_manager import FeeManager
        from calculation.profit_validator import ProfitValidator
        
        self.fee_manager = FeeManager(
            REST_CLIENT,
            log_callback=self.log_message,
            orderbook=self.orderbook,
        )
        self.profit_validator = ProfitValidator(
            fee_manager=self.fee_manager,
            orderbook=self.orderbook,
        )

        # Lot Tracking Integration: Initialize fill ledger and hook registry
        self.fill_repo = None
        self.fill_event_hooks = None
        self.event_stream_publisher = None
        if LOT_TRACKING_AVAILABLE:
            try:
                from business.post_fill_hook import initialize_fill_ledger
                self.fill_repo = initialize_fill_ledger(self.db_module.DB_CLIENT)
                # Initialize fill event hook registry
                self.fill_event_hooks = get_global_fill_event_hook_registry()
                # Register default post-fill hook for recording fills
                self._register_default_fill_hook()
            except Exception as e:
                # Log but don't fail - lot tracking is optional
                self.log_message("warning", f"Failed to initialize fill ledger: {e}")

        # Single source of truth for all per-order WS-derived progress.
        # Replaces the previous parallel ``_partial_fill_state`` and
        # ``_fill_recording_state`` dicts. The tracker owns:
        #   * the cumulative-counter watermark used to derive per-match fill
        #     ledger rows, and
        #   * the carry/min-size watermark used to spawn partial-fill
        #     follow-up orders.
        # Hydrated at startup via ``_hydrate_order_progress_tracker_from_db``.
        self.order_progress_tracker = OrderProgressTracker(
            min_order_size_resolver=self._resolve_min_order_size,
            parent_resolver=lambda coid: self.get_parent_of_child(coid) or coid,
        )

        # Reconstructive timeline event stream integration via existing hooks.
        self._initialize_event_stream_integration()

        # Hotpoint Auto-Replicate subsystem. See `business/hotpoint_*.py` and
        # the 2026-05-03 design conversation. Detector + rate limiter live
        # entirely in memory (rate limiter is restart-rebuilt from
        # `order_parent` rows in `start_background_threads`). Sweeper is
        # daemon-thread, also started in `start_background_threads`.
        self._initialize_hotpoint_subsystem()

        self.websocket_events = {
            "SNAPSHOT": {
                "type": "snapshot",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
            "OPEN": {"type": "open", "orders": []},
            "FILLED": {"type": "filled", "orders": []},
            "CANCELLED": {"type": "cancelled", "orders": []},
            "UPDATE": {
                "type": "update",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
        }

        self.orderbook.db_module = self.db_module

    def _initialize_event_stream_integration(self) -> None:
        """Initialize order event stream and wire it into existing hook registries."""
        try:
            from business.order_event_stream import OrderEventStreamPublisher
            from integration.stealth_lifecycle_hooks import (
                get_global_stealth_lifecycle_hook_registry,
            )

            self.event_stream_publisher = OrderEventStreamPublisher(self.db_module)
            self.event_stream_publisher.set_fee_info_provider(
                self.fee_manager.get_fee_info if self.fee_manager else None
            )
            order_placement_hooks = get_global_placement_hook_registry()
            self.event_stream_publisher.register_hook_integrations(
                websocket_hooks=self.websocket_hooks,
                fill_event_hooks=self.fill_event_hooks,
                order_placement_hooks=order_placement_hooks,
                stealth_lifecycle_hooks=get_global_stealth_lifecycle_hook_registry(),
            )
            if self.event_stream_publisher.enabled:
                self.log_message("info", "[EVENT-STREAM] Hook integration enabled")
            else:
                self.log_message("warning", "[EVENT-STREAM] Integration disabled (table init failed)")
        except Exception as e:
            self.log_message("warning", f"[EVENT-STREAM] Integration init failed: {e}")

    def _initialize_hotpoint_subsystem(self) -> None:
        """Construct the hotpoint detector + rate limiter (in-memory).

        Sweeper start + rate-limiter restart-rebuild happen in
        :meth:`start_background_threads` once DB and REST are reachable.

        Failures are logged and the subsystem is marked disabled rather
        than aborting engine startup. The kill switch remains queryable
        either way.
        """
        from core import constants as _constants

        # Start with constants-defined runtime kill switch. Operator can
        # flip via ``set_hotpoint_auto_place_enabled(bool)`` without a
        # restart.
        self._hotpoint_auto_place_enabled = bool(
            getattr(_constants, "HOTPOINT_AUTO_PLACE_ENABLED", False)
        )
        self._hotpoint_detector = None
        self._hotpoint_rate_limiter = None
        self._hotpoint_decay_sweeper = None
        self._hotpoint_policy = None
        self._hotpoint_width_pct = float(
            getattr(_constants, "HOTPOINT_WIDTH_PCT", 0.005)
        )
        self._hotpoint_rate_window_seconds = float(
            getattr(_constants, "HOTPOINT_RATE_LIMIT_WINDOW_SECONDS", 300)
        )

        try:
            from business.hotpoint_detector import HotpointDetector
            from business.hotpoint_rate_limiter import HotpointRateLimiter
            from core.enums import HotpointPlacementPolicy

            self._hotpoint_detector = HotpointDetector(
                width_pct=self._hotpoint_width_pct,
                trigger_n=int(getattr(_constants, "HOTPOINT_TRIGGER_N", 3)),
                trigger_window_seconds=float(
                    getattr(_constants, "HOTPOINT_TRIGGER_WINDOW_SECONDS", 60)
                ),
            )
            self._hotpoint_rate_limiter = HotpointRateLimiter(
                cap_n=int(getattr(_constants, "HOTPOINT_RATE_LIMIT_N", 5)),
                window_seconds=self._hotpoint_rate_window_seconds,
            )
            policy_name = str(
                getattr(_constants, "HOTPOINT_DEFAULT_POLICY", "WINDOW_CENTER")
            )
            try:
                self._hotpoint_policy = HotpointPlacementPolicy(policy_name)
            except ValueError:
                self.log_message(
                    "warning",
                    f"[HOTPOINT] Unknown policy {policy_name!r}, falling back to WINDOW_CENTER",
                )
                self._hotpoint_policy = HotpointPlacementPolicy.WINDOW_CENTER
            self.log_message(
                "info",
                f"[HOTPOINT] Subsystem initialized: enabled={self._hotpoint_auto_place_enabled}, "
                f"width_pct={self._hotpoint_width_pct}, policy={self._hotpoint_policy.value}",
            )
        except Exception as e:
            self.log_message(
                "warning",
                f"[HOTPOINT] Subsystem init failed (feature disabled): {type(e).__name__}: {e}",
            )

    # ------------------------------------------------------------------
    # Hotpoint Auto-Replicate â€” runtime API
    # ------------------------------------------------------------------

    def set_hotpoint_auto_place_enabled(self, enabled: bool) -> None:
        """Runtime kill-switch toggle. Effective immediately for new triggers.

        Detector continues to record fills regardless (so when re-enabled,
        the recent history is intact). Only the placer gates on this flag.
        """
        self._hotpoint_auto_place_enabled = bool(enabled)
        self.log_message(
            "info",
            f"[HOTPOINT] Auto-place {'ENABLED' if enabled else 'DISABLED'} via runtime toggle",
        )

    def is_hotpoint_auto_place_enabled(self) -> bool:
        """Return current runtime kill-switch state."""
        return bool(getattr(self, "_hotpoint_auto_place_enabled", False))

    def get_hotpoint_state_snapshot(self) -> dict:
        """Return a UI-friendly snapshot of the hotpoint subsystem.

        Used by the dashboard's hotpoint manager page. All values are
        plain JSON-safe types (dict / list / str / int / float / bool).

        Returned shape:
            {
              "enabled": bool,                 # runtime kill switch
              "subsystem_initialized": bool,   # detector + limiter exist
              "config": {
                "width_pct": float,
                "trigger_n": int,
                "trigger_window_seconds": float,
                "rate_limit_n": int,
                "rate_limit_window_seconds": float,
                "decay_sweep_interval_seconds": float,
                "default_policy": str,
              },
              "active_buckets": [
                {
                  "product_id", "side", "bucket_id",
                  "bucket_center", "fills_in_window",
                },
                ...
              ],
              "recent_auto_placements": [
                {
                  "client_order_id", "product_id", "side",
                  "price", "epoch_seconds",
                },
                ...
              ],
            }

        Active-bucket enumeration walks the detector's internal state
        under its lock; the cost is O(n_buckets), which is bounded by
        the number of product/side/bucket triples ever seen since
        startup. Practical bounds are tiny (single-digit triples per
        active product).
        """
        from core import constants as _constants

        out = {
            "enabled": self.is_hotpoint_auto_place_enabled(),
            "subsystem_initialized": bool(
                getattr(self, "_hotpoint_detector", None)
                and getattr(self, "_hotpoint_rate_limiter", None)
            ),
            "config": {
                "width_pct": float(getattr(self, "_hotpoint_width_pct", 0.0)),
                "trigger_n": int(getattr(_constants, "HOTPOINT_TRIGGER_N", 0)),
                "trigger_window_seconds": float(
                    getattr(_constants, "HOTPOINT_TRIGGER_WINDOW_SECONDS", 0)
                ),
                "rate_limit_n": int(
                    getattr(_constants, "HOTPOINT_RATE_LIMIT_N", 0)
                ),
                "rate_limit_window_seconds": float(
                    getattr(self, "_hotpoint_rate_window_seconds", 0.0)
                ),
                "decay_sweep_interval_seconds": float(
                    getattr(_constants, "HOTPOINT_DECAY_SWEEP_INTERVAL_SECONDS", 0)
                ),
                "default_policy": getattr(
                    self._hotpoint_policy, "value", "WINDOW_CENTER",
                ) if getattr(self, "_hotpoint_policy", None) else "WINDOW_CENTER",
            },
            "active_buckets": [],
            "recent_auto_placements": [],
        }

        # Snapshot active buckets from the detector.
        det = getattr(self, "_hotpoint_detector", None)
        if det is not None:
            try:
                from business.hotpoint_detector import bucket_center_price
                width = float(self._hotpoint_width_pct)
                # Reach into the detector under its lock for a consistent view.
                with det._lock:  # noqa: SLF001 - intentional internal access
                    keys = list(det._buckets.keys())  # noqa: SLF001
                for product_id, side, bucket_id in keys:
                    n = det.fills_in_window(
                        product_id=product_id, side=side, bucket_id=bucket_id,
                    )
                    if n <= 0:
                        continue
                    out["active_buckets"].append({
                        "product_id": product_id,
                        "side": side,
                        "bucket_id": bucket_id,
                        "bucket_center": bucket_center_price(bucket_id, width),
                        "fills_in_window": n,
                    })
            except Exception as e:
                self.log_message(
                    "warning",
                    f"[HOTPOINT] active-bucket snapshot failed: {type(e).__name__}: {e}",
                )

        # Recent auto-placements from DB.
        try:
            from database.order import get_recent_auto_placed_hotpoint_rows
            window = int(out["config"]["rate_limit_window_seconds"]) or 300
            rows = get_recent_auto_placed_hotpoint_rows(window)
            for r in rows:
                out["recent_auto_placements"].append({
                    "client_order_id": r.get("client_order_id"),
                    "product_id": r.get("product_id"),
                    "side": r.get("side"),
                    "price": float(r.get("price") or 0.0),
                    "epoch_seconds": float(r.get("epoch_seconds") or 0.0),
                })
        except Exception as e:
            self.log_message(
                "warning",
                f"[HOTPOINT] recent-placements snapshot failed: {type(e).__name__}: {e}",
            )

        return out

    def _start_hotpoint_background(self) -> None:
        """Restart-rebuild the rate limiter and start the decay sweeper.

        Called from :meth:`start_background_threads` after market-tick
        recorder init. All steps are wrapped in try/except â€” a hotpoint
        background failure must never block engine startup.
        """
        try:
            from configuration import REST_CLIENT
            from core import constants as _constants
            from business.hotpoint_decay_sweeper import HotpointDecaySweeper
            from business.hotpoint_detector import compute_bucket_id
            from database.order import (
                get_open_auto_placed_hotpoint_rows,
                get_recent_auto_placed_hotpoint_rows,
            )

            # 1. Restart-rebuild rate limiter from persisted rows.
            if self._hotpoint_rate_limiter is not None:
                try:
                    rows = get_recent_auto_placed_hotpoint_rows(
                        int(self._hotpoint_rate_window_seconds)
                    )
                    hydrated = []
                    for row in rows:
                        try:
                            price = float(row["price"])
                            if price <= 0:
                                continue
                            bid = compute_bucket_id(price, self._hotpoint_width_pct)
                            hydrated.append((
                                row["product_id"],
                                row["side"],
                                bid,
                                float(row["epoch_seconds"]),
                            ))
                        except Exception:
                            continue
                    n = self._hotpoint_rate_limiter.hydrate(hydrated)
                    self.log_message(
                        "info",
                        f"[HOTPOINT] Rate limiter rebuilt from DB: {n} placement(s)",
                    )
                except Exception as e:
                    self.log_message(
                        "warning",
                        f"[HOTPOINT] Rate limiter rebuild failed: {type(e).__name__}: {e}",
                    )

            # 2. Start decay sweeper daemon.
            if self._hotpoint_detector is not None:
                try:
                    self._hotpoint_decay_sweeper = HotpointDecaySweeper(
                        detector=self._hotpoint_detector,
                        width_pct=self._hotpoint_width_pct,
                        interval_seconds=float(getattr(
                            _constants,
                            "HOTPOINT_DECAY_SWEEP_INTERVAL_SECONDS",
                            30,
                        )),
                        list_open_fn=get_open_auto_placed_hotpoint_rows,
                        rest_client=REST_CLIENT,
                        shutdown_event=self._shutdown_event,
                        log_callback=self.log_message,
                    )
                    self._hotpoint_decay_sweeper.start()
                    self.log_message("info", "[HOTPOINT] Decay sweeper started")
                except Exception as e:
                    self.log_message(
                        "warning",
                        f"[HOTPOINT] Decay sweeper start failed: {type(e).__name__}: {e}",
                    )
        except Exception as e:
            self.log_message(
                "warning",
                f"[HOTPOINT] Background init failed: {type(e).__name__}: {e}",
            )

    def _maybe_dispatch_hotpoint(self, delta) -> None:
        """Feed a fresh fill into the hotpoint detector and place if triggered.

        Called from :meth:`_process_ws_order_delta` AFTER the per-match fill
        ledger row has been recorded. Silently no-ops if:

          * The hotpoint subsystem failed to initialise.
          * The fill came from an order whose parent does NOT have
            ``enable_hotpoint_replication=TRUE`` (lookup via the orderbook
            cache, falling back to a single DB read).
          * ``delta.derived_price`` is non-positive.

        All errors are caught and logged. This method MUST NEVER raise into
        the WS pipeline.
        """
        try:
            detector = self._hotpoint_detector
            rate_limiter = self._hotpoint_rate_limiter
            policy = self._hotpoint_policy
            if not (detector and rate_limiter and policy):
                return
            if not delta.is_new_match:
                return
            if delta.derived_price is None or delta.derived_price <= 0.0:
                return

            # Opt-in gate: only fills from parents flagged
            # ``enable_hotpoint_replication=TRUE`` count toward triggers.
            parent_root = self.get_parent_of_child(delta.client_order_id) or delta.client_order_id
            if not self._get_parent_enable_hotpoint_replication(parent_root):
                return

            event = detector.record_fill(
                product_id=delta.product_id,
                side=delta.side,
                fill_price=float(delta.derived_price),
            )
            if event is None:
                return

            from business.hotpoint_placer import place_hotpoint_order
            from configuration import REST_CLIENT
            from database.order import insert_order_parent

            product_meta = self.orderbook.product.get(delta.product_id, {})
            place_hotpoint_order(
                event=event,
                rate_limiter=rate_limiter,
                product_meta=product_meta,
                policy=policy,
                rest_client=REST_CLIENT,
                insert_order_parent_fn=insert_order_parent,
                kill_switch_enabled=self.is_hotpoint_auto_place_enabled(),
                log_callback=self.log_message,
            )
        except Exception as e:
            self.log_message(
                "warning",
                f"[HOTPOINT] dispatch failed for {getattr(delta, 'client_order_id', '?')}: "
                f"{type(e).__name__}: {e}",
            )

    def _get_parent_enable_hotpoint_replication(self, parent_id: str) -> bool:
        """Return whether ``enable_hotpoint_replication`` is set for a parent.

        Mirrors :meth:`_get_parent_allow_partial_fills`: orderbook cache first,
        single DB lookup on miss.
        """
        if not parent_id:
            return False
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_id, {})
            if "enable_hotpoint_replication" in parent:
                return bool(parent["enable_hotpoint_replication"])
        try:
            row = self.db_module.get_parent_order(parent_id)
            if row:
                return bool(row.get("enable_hotpoint_replication", False))
        except Exception as e:
            self.log_message(
                "warning",
                f"[HOTPOINT] enable_hotpoint_replication lookup failed for {parent_id}: {e}",
            )
        return False

    # ------------------------------------------------------------------
    # Partial-fill persistence helpers
    # ------------------------------------------------------------------

    def _hydrate_order_progress_tracker_from_db(self) -> None:
        """Load ACTIVE ``partial_fill_progress`` rows into the tracker.

        Called once at engine startup (inside ``start_background_threads``) so
        that in-flight partial-fill watermarks survive restarts. Delegates the
        actual record construction to ``OrderProgressTracker.hydrate``.
        """
        try:
            from database.order import get_all_active_partial_fill_progress
            rows = get_all_active_partial_fill_progress()
        except Exception as e:
            self.log_message("warning", f"[PARTIAL-FILL] Hydration failed: {e}")
            return

        self.order_progress_tracker.hydrate(rows)

        self.log_message(
            "order",
            self.build_event_log_payload(
                "partial_fill_state_hydrated",
                active_rows=len(rows),
            ),
        )

    def _persist_progress_from_record(
        self,
        client_order_id: str,
        record,
        cumulative_qty: float,
        number_of_fills: int,
        completion_pct: float,
    ) -> None:
        """Persist the tracker's per-order watermark to ``partial_fill_progress``.

        The :class:`OrderProgressTracker` is the single source of truth for
        in-memory state; this helper writes that state through to the database
        and emits an immutable audit row to ``order_event_stream``.

        Args:
            client_order_id:    Order whose watermark to persist.
            record:             Snapshot of the tracker's ``_WatermarkRecord``
                                (already a copy returned by
                                ``OrderProgressTracker.get_record``).
            cumulative_qty:     Cumulative quantity from the latest snapshot.
            number_of_fills:    ``number_of_fills`` from the latest snapshot.
            completion_pct:     ``completion_percentage`` from the latest snapshot.
        """
        try:
            from database.order import upsert_partial_fill_progress
            upsert_partial_fill_progress(
                client_order_id=client_order_id,
                parent_client_order_id=record.parent_client_order_id,
                product_id=record.product_id,
                side=record.side,
                original_order_size=record.original_order_size,
                min_order_size=record.min_order_size,
                last_cumulative_qty_processed=cumulative_qty,
                carry_remainder_qty=record.carry_remainder_qty,
                last_number_of_fills_seen=number_of_fills,
                last_completion_pct_seen=completion_pct,
                partial_follow_ups_created=record.partial_follow_ups_created,
            )
        except Exception as e:
            self.log_message(
                "error",
                f"[PARTIAL-FILL] DB upsert failed for {client_order_id}: {e}",
            )

        # Emit immutable audit row to order_event_stream.
        if self.event_stream_publisher and self.event_stream_publisher.enabled:
            audit_payload = {
                "client_order_id": client_order_id,
                "parent_order_id": record.parent_client_order_id,
                "product_id": record.product_id,
                "side": record.side,
                "cumulative_quantity": cumulative_qty,
                "carry_remainder": record.carry_remainder_qty,
                "number_of_fills": number_of_fills,
                "completion_percentage": completion_pct,
                "partial_follow_ups_created": record.partial_follow_ups_created,
                "original_order_size": record.original_order_size,
                "min_order_size": record.min_order_size,
            }
            idempotency_key = (
                f"partial_fill_progress:{client_order_id}:{cumulative_qty}:{number_of_fills}"
            )
            self.event_stream_publisher.publish_event(
                event_type=EventStreamType.PARTIAL_FILL_PROGRESS_UPDATED.value,
                source_channel=EventSourceChannel.ORDER_ENGINE_OPEN.value,
                payload=audit_payload,
                idempotency_key=idempotency_key,
                status_to=OrderStatus.OPEN.value,
            )

    def _process_ws_order_delta(self, normalized_order: dict) -> Optional[OrderSnapshotDelta]:
        """Single ingestion point for one WS order snapshot.

        Replaces the previous parallel ``_record_incremental_fills`` and
        ``_handle_partial_fill_if_enabled`` paths. Routes the resulting
        :class:`OrderSnapshotDelta` to:
          * fill-ledger row generation (always, when there is a real per-match
            advance and lot-tracking is enabled),
          * partial-fill follow-up creation (only when the parent has
            ``allow_partial_fills=True``),
          * watermark persistence to ``partial_fill_progress``,
          * append-only audit insertion to ``order_match_audit``.

        Args:
            normalized_order: Normalised WS order dict produced by the
                processor bridge for any status.

        Returns:
            The :class:`OrderSnapshotDelta` produced by the tracker, or
            ``None`` when the snapshot carried no advance.
        """
        delta = self.order_progress_tracker.ingest(normalized_order)
        if delta is None:
            return None

        client_order_id = delta.client_order_id

        # 1. Per-match fill-ledger row + post/pre fill hooks.
        if delta.is_new_match and self.fill_repo and LOT_TRACKING_AVAILABLE:
            self._append_derived_fill_with_hooks(delta)

            # 1b. Hotpoint Auto-Replicate dispatch. Silent no-op for orders
            #     not flagged ``enable_hotpoint_replication=TRUE``. Failures
            #     never propagate back into the WS pipeline.
            self._maybe_dispatch_hotpoint(delta)

        # 2. Append-only audit row covering EVERY accepted snapshot.
        self._append_order_match_audit(delta, normalized_order)

        # 3. Persist watermark + emit progress audit event.
        record = self.order_progress_tracker.get_record(client_order_id)
        if record is not None:
            self._persist_progress_from_record(
                client_order_id=client_order_id,
                record=record,
                cumulative_qty=delta.cumulative_quantity,
                number_of_fills=delta.number_of_fills,
                completion_pct=delta.completion_percentage,
            )

            # 4. Conditionally create partial-fill follow-up(s).
            #    Opt-in is parent-side; carry-vs-min check is delta-side.
            if delta.is_new_match and not delta.is_terminal:
                self._maybe_create_partial_fill_follow_up(delta, record)

        return delta

    def _append_derived_fill_with_hooks(self, delta: OrderSnapshotDelta) -> None:
        """Run pre-fill hooks, append the derived fill row, then post-fill hooks."""
        fill_data = {
            "instrument": delta.product_id,
            "side": delta.side,
            "quantity": delta.size_delta,
            "price": delta.derived_price,
            "fees": delta.fee_delta,
            "client_order_id": delta.client_order_id,
            "timestamp": delta.observed_at,
            "commission_percentage": 0.0,
            "trade_id": delta.derived_trade_key,
            "derived_trade_key": delta.derived_trade_key,
        }

        try:
            if self.fill_event_hooks:
                self.fill_event_hooks.call_pre_fill_hooks(fill_data)
        except Exception as hook_error:
            self.log_message(
                "warning",
                f"[LOT-TRACK] Pre-fill hook blocked recording: {hook_error}",
            )
            return

        record_success = self.fill_repo.append_derived_fill(delta)

        if record_success and self.fill_event_hooks:
            try:
                self.fill_event_hooks.call_post_fill_hooks(
                    fill_data, delta.derived_trade_key
                )
            except Exception as hook_error:
                self.log_message(
                    "warning",
                    f"[LOT-TRACK] Post-fill hook exception: {hook_error}",
                )

    def _append_order_match_audit(
        self, delta: OrderSnapshotDelta, normalized_order: dict
    ) -> None:
        """Best-effort append of one row to ``order_match_audit``.

        Failures are logged but do not block the WS pipeline â€” the audit table
        is for forensic reconstruction, not transactional correctness.
        """
        try:
            from database.order import insert_order_match_audit
            insert_order_match_audit(
                client_order_id=delta.client_order_id,
                snapshot_seq=delta.snapshot_seq,
                cumulative_quantity=delta.cumulative_quantity,
                filled_value=delta.filled_value,
                total_fees=delta.total_fees,
                number_of_fills=delta.number_of_fills,
                leaves_quantity=delta.leaves_quantity,
                outstanding_hold_amount=delta.outstanding_hold_amount,
                status=delta.status,
                derived_size_delta=delta.size_delta,
                derived_value_delta=delta.value_delta,
                derived_fee_delta=delta.fee_delta,
                derived_price=delta.derived_price if delta.is_new_match else None,
                derived_trade_key=delta.derived_trade_key if delta.is_new_match else None,
                emitted_fill_ledger_row=bool(
                    delta.is_new_match and self.fill_repo and LOT_TRACKING_AVAILABLE
                ),
                raw_payload_json=json.dumps(normalized_order, default=str),
            )
        except Exception as e:
            self.log_message(
                "warning",
                f"[ORDER-MATCH-AUDIT] Insert failed for {delta.client_order_id} "
                f"seq={delta.snapshot_seq}: {e}",
            )

    def _finalize_partial_fill_progress(self, client_order_id: str, terminal_status: str) -> None:
        """Drop the order's tracker watermark and mark its DB row terminal.

        Called when an order reaches FILLED, CANCELLED, or FAILED status so
        that the partial-fill progress row is no longer surfaced on restart
        hydration. The tracker owns the in-memory state; this method handles
        the DB finalize and audit emission.

        Args:
            client_order_id:  The child order's client_order_id.
            terminal_status:  'FINALIZED' (filled) or 'CANCELLED'.
        """
        self.order_progress_tracker.finalize(client_order_id, terminal_status)

        try:
            from database.order import finalize_partial_fill_progress
            finalize_partial_fill_progress(client_order_id, terminal_status)
        except Exception as e:
            self.log_message("warning", f"[PARTIAL-FILL] Finalize failed for {client_order_id}: {e}")

        # Emit terminal audit row to order_event_stream.
        if self.event_stream_publisher and self.event_stream_publisher.enabled:
            audit_payload = {
                "client_order_id": client_order_id,
                "terminal_status": terminal_status,
            }
            idempotency_key = f"partial_fill_finalized:{client_order_id}:{terminal_status}"
            self.event_stream_publisher.publish_event(
                event_type=EventStreamType.PARTIAL_FILL_FINALIZED.value,
                source_channel=EventSourceChannel.ORDER_ENGINE_TERMINAL.value,
                payload=audit_payload,
                idempotency_key=idempotency_key,
                status_to=terminal_status,
            )

    def _resolve_filled_follow_up_size_after_partials(
        self,
        client_order_id: str,
        proposed_follow_up_size: float,
    ) -> tuple[float, dict | None]:
        """Adjust FILLED follow-up size by subtracting already-created partial follow-up units.

        Partial fills can spawn follow-up size in advance (tracked in partial_fill_progress).
        When the same order later reaches FILLED, creating another full-size follow-up would
        over-allocate total follow-up size. This helper caps FILLED follow-up size to the
        remaining unallocated size.

        Returns:
            Tuple of (adjusted_size, details_dict_or_none).
        """
        if proposed_follow_up_size <= 0.0:
            return 0.0, None

        try:
            from database.order import get_partial_fill_progress
        except Exception:
            return proposed_follow_up_size, None

        progress = get_partial_fill_progress(client_order_id)
        if not progress:
            return proposed_follow_up_size, None

        original_order_size = safe_float(progress.get("original_order_size"), default=0.0)
        min_order_size = safe_float(progress.get("min_order_size"), default=0.0)
        partial_follow_ups_created = int(progress.get("partial_follow_ups_created") or 0)

        if original_order_size <= 0.0 or min_order_size <= 0.0 or partial_follow_ups_created <= 0:
            return proposed_follow_up_size, None

        allocated_by_partial_follow_ups = partial_follow_ups_created * min_order_size
        remaining_follow_up_size = max(0.0, original_order_size - allocated_by_partial_follow_ups)
        adjusted_size = min(proposed_follow_up_size, remaining_follow_up_size)

        details = {
            "original_order_size": original_order_size,
            "min_order_size": min_order_size,
            "partial_follow_ups_created": partial_follow_ups_created,
            "allocated_by_partial_follow_ups": allocated_by_partial_follow_ups,
            "remaining_follow_up_size": remaining_follow_up_size,
            "proposed_follow_up_size": proposed_follow_up_size,
            "adjusted_follow_up_size": adjusted_size,
        }
        return adjusted_size, details

    def _resolve_min_order_size(self, product_id: str) -> float:
        """Return the base_increment (minimum tradeable quantity) for a product.

        Reads from the in-memory ``orderbook.product`` cache populated at startup.

        Args:
            product_id: Exchange product ID (e.g. 'BTC-USDC').

        Returns:
            Minimum order size as float, or 0.0 if product metadata is unavailable.
        """
        if not product_id:
            return 0.0
        from core.models import Product as _Product
        product_meta = self.orderbook.product.get(product_id, {})
        if isinstance(product_meta, _Product):
            return safe_float(product_meta.base_increment, default=0.0)
        return safe_float(product_meta.get("base_increment"), default=0.0)

    def _get_parent_allow_partial_fills(self, parent_id: str) -> bool:
        """Return whether partial-fill follow-ups are enabled for a parent order.

        Reads from the in-memory ``orderbook.parent_order_ids`` cache first.  On
        a cache miss (order not yet in memory) falls back to a single DB lookup,
        which only happens once per new order lifecycle.

        Args:
            parent_id: The root parent ``client_order_id``.

        Returns:
            True if the parent was created with ``allow_partial_fills=True``.
        """
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_id, {})
            if "allow_partial_fills" in parent:
                return bool(parent["allow_partial_fills"])

        # Cache miss: one-time DB lookup
        try:
            row = self.db_module.get_parent_order(parent_id)
            if row:
                return bool(row.get("allow_partial_fills", False))
        except Exception as e:
            self.log_message("warning", f"[PARTIAL-FILL] allow_partial_fills DB lookup failed for {parent_id}: {e}")
        return False

    def _create_partial_fill_follow_up(
        self,
        client_order_id: str,
        parent_client_order_id: str,
        min_order_size: float,
        follow_ups_due: int,
    ) -> int:
        """Create a stealth follow-up order for accumulated partial fills.

        Returns how many minimum-size follow-up units were actually created.
        """
        if follow_ups_due <= 0 or min_order_size <= 0.0:
            return 0
        if not self.stealth_order_bridge:
            return 0

        try:
            stealth_manager = self.stealth_order_bridge.stealth_manager
            original_stealth_order = stealth_manager.find_stealth_order_by_placed_order_id(
                client_order_id
            )
            if not original_stealth_order:
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "partial_fill_follow_up_skipped_no_stealth_parent",
                        client_order_id=client_order_id,
                        parent_client_order_id=parent_client_order_id,
                    ),
                )
                return 0

            # NOTE: partial-fill follow-ups intentionally bypass
            # ``max_order_replacement``. The cap exists to limit how many
            # times the parent gets re-anchored when a placement
            # cancels/fully-fills (see ``handle_filled_order`` path). A
            # partial-fill follow-up is COMPLETING the existing placement
            # â€” the original child counted as one replacement, and the
            # follow-ups are just refilling the unfilled slice. Letting
            # the cap gate them strands the operator with un-hedged
            # exposure equal to the carry remainder when ``cap=1`` and
            # the placement partial-fills (2026-04-30 incident: 10-unit
            # SELL filled-in-full but only 1 of 9 BUY follow-ups
            # spawned). The carry budget alone (``claim_follow_up_units``)
            # bounds the spawn rate; the cap is conceptually a different
            # budget and is enforced separately on the cancel/full-fill
            # follow-up path.

            # CRITICAL: atomically reserve carry units BEFORE the slow REST
            # place call. Without this claim, concurrent WS-delta threads each
            # observe the same stale ``carry_remainder_qty`` snapshot and each
            # spawn a duplicate full-size follow-up. See 2026-04-29
            # over-buy incident: a 100-unit SELL filled in 6 partial matches
            # produced 5 BUY follow-ups @ 100 units each (500 total instead
            # of 100). The atomic claim under the per-order lock causes the
            # second concurrent thread to observe the already-reduced carry
            # and back off.
            units_to_create = self.order_progress_tracker.claim_follow_up_units(
                client_order_id, max_units=follow_ups_due
            )
            if units_to_create <= 0:
                # Another concurrent thread already drained the carry; nothing
                # left for us to spawn.
                return 0

            # From here on, any failure must refund the carry claim so a
            # future delta can re-attempt the follow-up.
            try:
                target_movement = self.resolve_parent_target_movement(parent_client_order_id)
                order_template = self.compute_partial_fill_order_template(
                    client_order_id,
                    target_movement=target_movement,
                )
                if not order_template:
                    self.log_message(
                        "warning",
                        self.build_event_log_payload(
                            "partial_fill_follow_up_template_compute_failed",
                            client_order_id=client_order_id,
                            parent_client_order_id=parent_client_order_id,
                        ),
                    )
                    self.order_progress_tracker.release_follow_up_units(
                        client_order_id, units_to_create
                    )
                    return 0

                follow_up_price = float(order_template["start_price"])
                follow_up_size = float(units_to_create * min_order_size)

                follow_up_reveal_condition = dict(original_stealth_order.get("reveal_condition_json", {}))
                direction_choice = original_stealth_order.get(
                    "follow_up_reveal_direction",
                    FollowUpRevealDirection.OPPOSITE.value,
                )

                if follow_up_reveal_condition.get("type") == "price":
                    follow_up_reveal_condition["price_threshold"] = float(follow_up_price)
                    if direction_choice == FollowUpRevealDirection.OPPOSITE.value:
                        if "direction" in follow_up_reveal_condition:
                            follow_up_reveal_condition["direction"] = (
                                Direction.ABOVE.value
                                if follow_up_reveal_condition.get("direction") == Direction.BELOW.value
                                else Direction.BELOW.value
                            )

                parent_order_data = self.db_module.get_parent_order(parent_client_order_id)
                parent_target_movement = parent_order_data.get("target_movement") if parent_order_data else None
                parent_target_movement_type = (
                    parent_order_data.get("target_movement_type", TargetMovementType.PERCENTAGE.value)
                    if parent_order_data
                    else TargetMovementType.PERCENTAGE.value
                )

                stealth_follow_up_id = stealth_manager.create_follow_up_stealth_order(
                    original_stealth_order_id=original_stealth_order["stealth_order_id"],
                    side=order_template["side"],
                    total_size=follow_up_size,
                    limit_price=follow_up_price,
                    reveal_condition=follow_up_reveal_condition,
                    follow_up_reveal_direction=direction_choice,
                    reveal_pricing_policy=None,
                    notes=(
                        f"Auto partial-fill follow-up ({units_to_create} x {min_order_size})"
                    ),
                    target_movement=parent_target_movement,
                    target_movement_type=parent_target_movement_type,
                )

                # Flat hierarchy: register the follow-up against the chain ROOT,
                # never against the placement uuid that just settled (which is
                # itself a child). Single canonical resolver lives in
                # stealth_order_manager.
                root_parent_client_order_id = resolve_stealth_chain_root(original_stealth_order)
                self.register_child_order(
                    stealth_follow_up_id,
                    root_parent_client_order_id,
                    bypass_replacement_cap=True,
                )
                self.log_message(
                    "order",
                    self.build_event_log_payload(
                        "partial_fill_follow_up_created",
                        client_order_id=client_order_id,
                        parent_client_order_id=parent_client_order_id,
                        stealth_follow_up_id=stealth_follow_up_id,
                        follow_up_units=units_to_create,
                        follow_up_size=follow_up_size,
                        follow_up_price=follow_up_price,
                    ),
                )
                return units_to_create
            except Exception:
                # Refund the carry claim so a subsequent WS delta may retry.
                self.order_progress_tracker.release_follow_up_units(
                    client_order_id, units_to_create
                )
                raise
        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "partial_fill_follow_up_creation_failed",
                    client_order_id=client_order_id,
                    parent_client_order_id=parent_client_order_id,
                    error=str(e),
                ),
            )
            return 0

    def _maybe_create_partial_fill_follow_up(
        self,
        delta: OrderSnapshotDelta,
        record,
    ) -> None:
        """Create partial-fill follow-up order(s) when carry has crossed min-size.

        Called from :meth:`_process_ws_order_delta` for every accepted snapshot
        with a positive size advance. The opt-in check is parent-scoped; when
        the parent has ``allow_partial_fills=False`` we still record the
        watermark/audit but do not spawn a follow-up.

        Carry-arithmetic invariants:
          * ``record.carry_remainder_qty`` already includes ``delta.size_delta``
            (the tracker accumulates it during ``ingest``).
          * After we place ``created_units`` follow-ups, we hand the consumed
            amount back to the tracker via ``consume_carry_units`` so the
            in-memory and persisted state agree on what is left.

        Args:
            delta:  Snapshot delta from :class:`OrderProgressTracker`.
            record: Read-only snapshot of the per-order watermark from the
                tracker (already a copy â€” safe to read but do not mutate).
        """
        from logging_service import get_logger

        logger = get_logger("OrderEngine")
        client_order_id = delta.client_order_id

        if not self._get_parent_allow_partial_fills(record.parent_client_order_id):
            logger.debug(
                "[PARTIAL-FILL] Skipped (opt-out): client_order_id=%s parent_client_order_id=%s",
                client_order_id,
                record.parent_client_order_id,
            )
            return

        product_id = delta.product_id
        side = delta.side
        cumulative = delta.cumulative_quantity
        min_size = record.min_order_size
        carry = record.carry_remainder_qty
        size_delta = delta.size_delta

        # First-event audit emission so dashboards can show "first partial fill"
        # for an opted-in order.
        if (
            record.partial_follow_ups_created == 0
            and record.last_cumulative_qty_processed > 0
            and self.event_stream_publisher
            and self.event_stream_publisher.enabled
        ):
            # ``last_cumulative_qty_processed`` was already advanced by ingest
            # so the first time we get here the previous value (pre-advance)
            # would have been 0; we can't easily reach back for it. Emit on
            # the first delta seen â€” gate by snapshot_seq == 1.
            pass
        if delta.snapshot_seq == 1 and self.event_stream_publisher and self.event_stream_publisher.enabled:
            self.event_stream_publisher.publish_event(
                event_type=EventStreamType.PARTIAL_FILL_DETECTED.value,
                source_channel=EventSourceChannel.ORDER_ENGINE_OPEN.value,
                payload={
                    "client_order_id": client_order_id,
                    "parent_order_id": record.parent_client_order_id,
                    "product_id": product_id,
                    "side": side,
                    "cumulative_quantity": cumulative,
                },
                idempotency_key=f"partial_fill_detected:{client_order_id}:{cumulative}",
                status_to=OrderStatus.OPEN.value,
            )

        if min_size <= 0.0:
            logger.debug(
                "[PARTIAL-FILL] Skipped (min size unavailable): client_order_id=%s product_id=%s",
                client_order_id,
                product_id,
            )
            return

        if size_delta <= 0.0 and carry < min_size:
            logger.debug(
                "[PARTIAL-FILL] Skipped (no new delta and below min): client_order_id=%s "
                "cumulative=%s carry=%s min_size=%s",
                client_order_id,
                cumulative,
                carry,
                min_size,
            )
            return

        follow_ups_due = int(carry / min_size)
        created_units = 0
        if follow_ups_due > 0:
            created_units = self._create_partial_fill_follow_up(
                client_order_id=client_order_id,
                parent_client_order_id=record.parent_client_order_id,
                min_order_size=min_size,
                follow_ups_due=follow_ups_due,
            )

            logger.debug(
                "[PARTIAL-FILL] Follow-up evaluation: client_order_id=%s follow_ups_due=%s "
                "follow_ups_created=%s carry_before=%s min_size=%s",
                client_order_id,
                follow_ups_due,
                created_units,
                carry,
                min_size,
            )

            if self.event_stream_publisher and self.event_stream_publisher.enabled:
                self.event_stream_publisher.publish_event(
                    event_type=EventStreamType.PARTIAL_FILL_FOLLOW_UP_QUEUED.value,
                    source_channel=EventSourceChannel.ORDER_ENGINE_OPEN.value,
                    payload={
                        "client_order_id": client_order_id,
                        "parent_order_id": record.parent_client_order_id,
                        "product_id": product_id,
                        "side": side,
                        "cumulative_quantity": cumulative,
                        "follow_ups_due": follow_ups_due,
                        "follow_ups_created": created_units,
                        "min_order_size": min_size,
                    },
                    idempotency_key=(
                        f"partial_fill_follow_up_queued:{client_order_id}:{cumulative}:"
                        f"{follow_ups_due}:{created_units}"
                    ),
                    status_to=OrderStatus.OPEN.value,
                )

        if follow_ups_due <= 0 and self.event_stream_publisher and self.event_stream_publisher.enabled:
            self.event_stream_publisher.publish_event(
                event_type=EventStreamType.PARTIAL_FILL_BELOW_MIN.value,
                source_channel=EventSourceChannel.ORDER_ENGINE_OPEN.value,
                payload={
                    "client_order_id": client_order_id,
                    "parent_order_id": record.parent_client_order_id,
                    "product_id": product_id,
                    "side": side,
                    "cumulative_quantity": cumulative,
                    "delta": size_delta,
                    "carry_quantity": carry,
                    "min_order_size": min_size,
                },
                idempotency_key=f"partial_fill_below_min:{client_order_id}:{cumulative}:{carry}",
                status_to=OrderStatus.OPEN.value,
            )

        if created_units > 0:
            # Carry was already decremented atomically by
            # ``claim_follow_up_units`` inside ``_create_partial_fill_follow_up``
            # BEFORE the REST place call (2026-04-29 race fix). Just persist
            # the updated tracker state so the database reflects the new
            # ``carry_remainder_qty`` and ``partial_follow_ups_created``.
            updated_record = self.order_progress_tracker.get_record(client_order_id)
            if updated_record is not None:
                self._persist_progress_from_record(
                    client_order_id=client_order_id,
                    record=updated_record,
                    cumulative_qty=cumulative,
                    number_of_fills=delta.number_of_fills,
                    completion_pct=delta.completion_percentage,
                )

        # Single INFO summary for each processed partial-fill event.
        new_carry = max(0.0, carry - (created_units * min_size))
        new_follow_ups_created = record.partial_follow_ups_created + created_units
        self.log_message(
            "order",
            self.build_event_log_payload(
                "partial_fill_summary",
                client_order_id=client_order_id,
                parent_client_order_id=record.parent_client_order_id,
                product_id=product_id,
                side=side,
                cumulative_quantity=cumulative,
                delta=size_delta,
                min_order_size=min_size,
                carry_before=carry,
                carry_after=new_carry,
                follow_ups_due=follow_ups_due,
                follow_ups_created=created_units,
                total_follow_ups_created=new_follow_ups_created,
                number_of_fills=delta.number_of_fills,
                completion_percentage=delta.completion_percentage,
            ),
        )

    def log_message(self, log_type: str, message) -> None:
        """Log a message if the log type is enabled.
        
        Formats message with timestamp and thread name. Converts dicts/lists to JSON.
        
        Args:
            log_type: Log category (enabled via logging_flags dict).
            message: Message text or dict/list to log.
        
        Returns:
            None
        
        Example:
            >>> engine.log_message("order", {"event": "order_placed", "id": "123"})
        """
        if not self.logging_flags.get(log_type, False):
            return

        if isinstance(message, (dict, list)):
            message = json.dumps(message, sort_keys=True, default=str)

        from logging_service import get_logger
        logger = get_logger("OrderEngine")
        logger.info(f"{threading.current_thread().name} [{log_type.upper()}] {message}")

    @staticmethod
    def _is_uuid_like(value: Any) -> bool:
        """Return True when value can be used against a PostgreSQL UUID column."""
        if value is None:
            return False
        try:
            uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def order_limit_price_or_avg_price(order: dict) -> float:
        """Extract the price from an order, preferring limit_price over avg_price.
        
        Args:
            order: Order dict with optional 'limit_price' and 'avg_price' fields.
        
        Returns:
            The price as a float (limit_price if present and > 0, else avg_price).
        
        Example:
            >>> price = OrderEngine.order_limit_price_or_avg_price(
            ...     {'limit_price': '100.50', 'avg_price': '100.00'})
            >>> price
            100.5
        """
        if order.get("limit_price") and float(order["limit_price"]) > 0:
            return float(order["limit_price"])
        return float(order["avg_price"])

    def build_order_log_context(self, order: dict) -> dict:
        """Build a concise log dict from order data.
        
        Extracts key fields for logging without dumping entire order.
        
        Args:
            order: Order dict.
        
        Returns:
            Dict with client_order_id, order_id, product_type, product_id, side, status, price.
        
        Example:
            >>> ctx = engine.build_order_log_context({'client_order_id': 'id123', ...})
            >>> ctx['product_id']
            'BTC-USDC'
        """
        if not order:
            return {}

        price = None
        try:
            price = self.order_limit_price_or_avg_price(order)
        except Exception:
            price = None

        return {
            "client_order_id": order.get("client_order_id"),
            "order_id": order.get("order_id"),
            "product_type": self.normalize_product_type(order),
            "product_id": order.get("product_id"),
            "side": order.get("order_side") or order.get("side"),
            "status": order.get("status"),
            "price": price,
        }

    def build_event_log_payload(self, event: str, **kwargs) -> dict:
        """Build a structured log payload with event name and kwargs.
        
        Args:
            event: Event name.
            **kwargs: Additional fields to include.
        
        Returns:
            Dict with 'event' key plus all kwargs.
        
        Example:
            >>> payload = engine.build_event_log_payload(
            ...     'order_placed', product_id='BTC-USDC', side='BUY')
            >>> payload['event']
            'order_placed'
        """
        payload = {"event": event}
        payload.update(kwargs)
        return payload

    def include_debug_fields(self, **kwargs) -> dict:
        """Return kwargs dict only if debug_logging_enabled is True.
        
        Used to conditionally include verbose fields in logs.
        
        Args:
            **kwargs: Fields to include if debugging.
        
        Returns:
            kwargs if debug enabled, else {}.
        
        Example:
            >>> debug_ctx = engine.include_debug_fields(raw_order={...})
            >>> len(debug_ctx)  # 0 if debug disabled, 1 if enabled
        """
        if not self.debug_logging_enabled:
            return {}
        return {
            key: value for key, value in kwargs.items()
            if value is not None
        }

    def normalize_product_type(self, order: dict) -> str:
        """Determine if order is SPOT or FUTURE.
        
        Checks order field, product metadata, and product_id suffix.
        Thread-safe access to orderbook.
        
        Args:
            order: Order dict.
        
        Returns:
            'SPOT' or 'FUTURE'.
        
        Example:
            >>> ptype = engine.normalize_product_type({'product_id': 'BTC-USDC'})
            >>> ptype
            'SPOT'
        """
        product_type = str(order.get("product_type") or "").upper()
        if product_type in {"SPOT", "FUTURE"}:
            return product_type

        product_id = order.get("product_id")
        with self.orderbook_lock:
            product = self.orderbook.product.get(product_id, {})

        configured_product_type = str(product.get("product_type") or "").upper()
        if configured_product_type in {"SPOT", "FUTURE"}:
            return configured_product_type

        if product_id and product_id.endswith("-CDE"):
            return "FUTURE"
        return "SPOT"

    # Note: resolve_order_size is now imported from calculation.resolver

    def resolve_profit_target(self, order: dict) -> float:
        """Get configured profit target % for an order.
        
        Args:
            order: Order dict with product_id and order_side.
        
        Returns:
            Profit % (e.g., 0.004 for 0.4%).
        
        Example:
            >>> profit = engine.resolve_profit_target({'product_id': 'BTC-USDC', 'order_side': 'BUY'})
            >>> profit
            0.004
        """
        product_type = self.normalize_product_type(order)
        product_id = order.get("product_id")
        order_side = order.get("order_side")

        product_profit = self.orderbook.profit.get(product_id)
        if isinstance(product_profit, dict) and order_side in product_profit:
            return product_profit[order_side]

        type_profit = self.orderbook.profit.get(product_type, {})
        return type_profit[order_side]

    def get_orderbook_snapshot(self) -> dict:
        """Get thread-safe snapshot of orderbook state.
        
        Deep copies mutable state to prevent concurrent modification issues.
        
        Returns:
            Dict with order, positions, product, profit, mandatory_fee_per_contract,
            parent_order_ids, child_order_ids keys.
        
        Example:
            >>> snap = engine.get_orderbook_snapshot()
            >>> orders = snap['order']
        """
        # Single-lock snapshot via the v2 OrderBook implementation â€” replaces
        # the previous block of seven sequential ``deepcopy(...)`` reads which
        # required holding ``orderbook_lock`` across multiple attribute
        # accesses.  Shape is byte-for-byte identical.
        return self.orderbook.diagnostic_snapshot()

    def refresh_positions_if_needed(self, product_id: str) -> None:
        """Refresh futures positions from API if product_id not in cache.
        
        Args:
            product_id: Product ID to check/refresh.
        
        Returns:
            None
        
        Example:
            >>> engine.refresh_positions_if_needed('BIP-20DEC30-CDE')
        """
        with self.orderbook_lock:
            future_positions = self.orderbook.positions.setdefault("FUTURE", {})
            if product_id in future_positions:
                return

        try:
            refreshed_positions = get_futures_positions()
        except Exception as e:
            self.log_message("error", f"Failed to refresh futures positions for {product_id}: {e}")
            return

        with self.orderbook_lock:
            self.orderbook.positions["FUTURE"] = refreshed_positions

    def resolve_parent_client_order_id(self, client_order_id: str, order: dict = None, create_parent: bool = False, status: str = None, stealth_order: dict = None, allow_partial_fills: bool = False) -> tuple:
        """Resolve if an order is a parent or find its parent.
        
        Returns (is_parent: bool, parent_client_order_id: str).
        Optionally creates a new parent entry if create_parent=True.
        
        Args:
            client_order_id: The order to resolve.
            order: Order data (required if create_parent=True).
            create_parent: Whether to create parent entry if not found.
            status: Order status (for parent creation).
            stealth_order: Optional stealth order dict with target_movement/target_movement_type
                          to use instead of defaults. Used when revealing stealth orders.
        
        Returns:
            Tuple (is_parent, parent_client_order_id).
        
        Example:
            >>> is_parent, parent_id = engine.resolve_parent_client_order_id('order_123')
            >>> if is_parent:
            ...     print(f"This is a parent order")
        """
        is_parent = False
        parent_client_order_id = None

        if self.is_parent_order(client_order_id):
            is_parent = True
            parent_client_order_id = client_order_id

        elif self.is_child_order(client_order_id):
            parent_client_order_id = self.get_parent_of_child(client_order_id)

        elif create_parent and order is not None:
            max_order_replacement = getattr(
                self.orderbook,
                "default_max_order_replacement",
                DEFAULT_MAX_ORDER_REPLACEMENT,
            )

            # âœ… FIX: Use stealth order's target_movement if available (for revealed orders)
            # This preserves the target_movement configured when the stealth order was created
            if stealth_order and stealth_order.get("target_movement"):
                target_movement_value = stealth_order["target_movement"]
                target_movement_type = stealth_order.get("target_movement_type", "P")
            else:
                target_movement_value = self.resolve_profit_target(order)
                target_movement_type = "P"

            self.orderbook.parent_order_ids[client_order_id] = {
                "orders": [],
                "target_movement": {
                    "movement": target_movement_value,
                    "type": target_movement_type,
                },
                "max_order_replacement": max_order_replacement,
                "current_order_replacement": 0,
                "allow_partial_fills": allow_partial_fills,
            }

            self.log_message(
                "order",
                self.build_event_log_payload(
                    "parent_order_entry_created",
                    source=self.build_order_log_context(order),
                ),
            )

            parent_id = self.db_module.insert_order_parent(
                client_order_id=client_order_id,
                product_id=order["product_id"],
                side=order["order_side"],
                size=float(resolve_order_size(order)),
                price=float(self.order_limit_price_or_avg_price(order)),
                target_movement=float(
                    self.orderbook.parent_order_ids[client_order_id]["target_movement"]["movement"]
                ),
                target_movement_type=self.orderbook.parent_order_ids[client_order_id]["target_movement"]["type"],
                status=status or order.get("status"),
                max_order_replacement=self.orderbook.parent_order_ids[client_order_id]["max_order_replacement"],
                current_order_replacement=self.orderbook.parent_order_ids[client_order_id]["current_order_replacement"],
                allow_partial_fills=allow_partial_fills,
            )

            self.orderbook.parent_order_ids[client_order_id]["parent_id"] = parent_id
            is_parent = True
            parent_client_order_id = client_order_id

        return is_parent, parent_client_order_id

    def is_parent_order(self, client_order_id: str) -> bool:
        """Check if a client_order_id is a parent order.
        
        Args:
            client_order_id: Order ID to check.
        
        Returns:
            True if parent, False if child or not found.
        """
        with self.orderbook_lock:
            return client_order_id in self.orderbook.parent_order_ids

    def _is_parent_order_unlocked(self, client_order_id: str) -> bool:
        """Internal: Check if order is parent (assumes lock already held)."""
        return client_order_id in self.orderbook.parent_order_ids

    def is_child_order(self, client_order_id: str) -> bool:
        """Check if a client_order_id is a child order.
        
        Args:
            client_order_id: Order ID to check.
        
        Returns:
            True if child, False if parent or not found.
        """
        with self.orderbook_lock:
            return client_order_id in self.orderbook.child_order_ids

    def _is_child_order_unlocked(self, client_order_id: str) -> bool:
        """Internal: Check if order is child (assumes lock already held)."""
        return client_order_id in self.orderbook.child_order_ids

    def get_parent_of_child(self, child_client_order_id: str) -> str | None:
        """Get the parent ID of a child order.
        
        Args:
            child_client_order_id: Child order ID to resolve.
        
        Returns:
            Parent order ID if child exists, None otherwise.
        """
        with self.orderbook_lock:
            return self.orderbook.child_order_ids.get(child_client_order_id)

    def _get_parent_of_child_unlocked(self, child_client_order_id: str) -> str | None:
        """Internal: Get parent of child (assumes lock already held)."""
        return self.orderbook.child_order_ids.get(child_client_order_id)

    def _register_stealth_placement_under_root(
        self,
        client_order_id: str,
        original_stealth_order: dict,
    ) -> None:
        """Register a stealth placement uuid as a child of its root parent.

        Flat hierarchy (see ``agent.md``): every child links to the original root,
        never to an intermediate slice. When a stealth order reveals with
        ``anchor_repricing.allow_revealed_reprice=True`` the placement uuid sent to
        the exchange differs from ``stealth_order_id`` and represents a slice that
        must be linked to the chain's root, not become its own parent.

        Root resolution:
          * stealth has ``parent_order_id``  â†’ root is that parent_order_id
          * stealth has no ``parent_order_id`` â†’ stealth itself is the root

        No-ops when ``client_order_id == stealth_order_id`` (same logical order)
        or when the placement is already registered as a child.

        Safety net: stealth follow-ups created by our engine are already
        registered at creation time; this catches orphaned/recovered placements.
        """
        stealth_order_id = original_stealth_order.get("stealth_order_id")
        if not stealth_order_id or client_order_id == stealth_order_id:
            return
        if self.is_child_order(client_order_id):
            return

        root_parent = resolve_stealth_chain_root(original_stealth_order)
        if not root_parent:
            return

        # Seed the root parent's in-memory metadata BEFORE registering, so
        # downstream resolve_parent_target_movement / resolve_parent_replacement_state
        # see the real configured values instead of an empty cache. Without this,
        # follow-ups computed off the placement uuid's parent fall back to system
        # defaults for target_movement, producing prices that erode the user's
        # profit margin (root cause of follow_up_order_skipped_unprofitable).
        self._seed_parent_order_cache_from_db(root_parent)

        self.register_child_order(client_order_id, root_parent)

    def claim_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> bool:
        """Atomically claim processing rights for a follow-up order.

        Prevents duplicate follow-up creation by acquiring a per-(kind,
        client_order_id) token in the OrderBook's typed claim ledger.
        Returns False if already claimed or done.

        Args:
            processed_flag_name: Kind name ('filled' or 'cancelled') â€” accepted
                as a plain string for backward compatibility, but validated
                against :class:`FollowUpKind` at the boundary.
            client_order_id: Order to claim.

        Returns:
            True if claimed, False if already in progress/done.

        Example:
            >>> if engine.claim_follow_up_processing('filled', 'order_123'):
            ...     # Do follow-up work

        Note:
            History (2026-04-27): this previously fetched ``self.orderbook
            .filled`` and ``.cancelled`` via ``getattr`` on the legacy shim.
            When those dict attributes were removed during the OrderBook v2
            cleanup, every call here returned ``False`` â€” silently disabling
            all FILLED and CANCELLED follow-up creation across production.
            The API is now backed by :meth:`core.orderbook.OrderBook
            .try_claim_follow_up`, which validates the kind against the
            :class:`FollowUpKind` enum at the boundary so a future rename of
            either side cannot fail silently again.
        """
        return self.orderbook.try_claim_follow_up(processed_flag_name, client_order_id)

    def release_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> None:
        """Release a processing claim (on error, before retry).

        Args:
            processed_flag_name: Kind name ('filled' or 'cancelled').
            client_order_id: Order to release.

        Returns:
            None
        """
        self.orderbook.release_follow_up(processed_flag_name, client_order_id)

    def complete_follow_up_processing(self, processed_flag_name: str, client_order_id: str) -> None:
        """Mark follow-up processing as complete (prevents future retries).

        Args:
            processed_flag_name: Kind name ('filled' or 'cancelled').
            client_order_id: Order to complete.

        Returns:
            None
        """
        self.orderbook.complete_follow_up(processed_flag_name, client_order_id)

    def register_child_order(
        self,
        child_client_order_id: str,
        parent_client_order_id: str,
        bypass_replacement_cap: bool = False,
    ) -> None:
        """Register a child order under a parent in the orderbook.
        
        Maintains bidirectional mappings and increments replacement count:
        - parent_order_ids[parent][orders] list contains child
        - child_order_ids[child] points to parent
        - Increments parent's current_order_replacement counter
        
        Args:
            child_client_order_id: The child order to register.
            parent_client_order_id: The parent order to register under.
            bypass_replacement_cap: When True, link the child to the parent
                without consuming a replacement slot. Used for partial-fill
                follow-ups, which complete an existing placement rather
                than adding a new one and therefore must not be gated by
                ``max_order_replacement``.
        
        Returns:
            None
        
        Example:
            >>> engine.register_child_order('child_123', 'parent_123')
            >>> # Now child_123 is tracked as child of parent_123 and count is incremented
        """
        # Contract guard: never register a phantom child. Passing None
        # here previously consumed a replacement slot on the parent and
        # appended `None` into the orders list, stranding exposure (see
        # incident 2026-05-04, cancel-path follow-up returning None).
        if child_client_order_id is None:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "register_child_order_rejected_null_child",
                    parent_client_order_id=parent_client_order_id,
                    child_client_order_id=None,
                ),
            )
            return

        # Flag to track if this is a new registration
        is_new_child = False
        registered_now = False
        
        with self.orderbook_lock:
            # Ensure parent entry exists
            if parent_client_order_id not in self.orderbook.parent_order_ids:
                self.orderbook.parent_order_ids[parent_client_order_id] = {
                    "orders": [],
                    "target_movement": {"movement": 0, "type": "P"},
                    "max_order_replacement": getattr(
                        self.orderbook,
                        "default_max_order_replacement",
                        DEFAULT_MAX_ORDER_REPLACEMENT,
                    ),
                    "current_order_replacement": 0,
                }
            
            # Add child to parent's orders list if not already there
            if child_client_order_id not in self.orderbook.parent_order_ids[parent_client_order_id]["orders"]:
                self.orderbook.parent_order_ids[parent_client_order_id]["orders"].append(child_client_order_id)
                registered_now = True

                if not bypass_replacement_cap:
                    # Consume one pre-claimed pending slot if any. Pre-claim
                    # already counted this slot toward the cap (via
                    # claim_replacement_slots), so we still bump
                    # current_order_replacement here but net out the pending
                    # counter so the gate doesn't double-count. If the caller
                    # didn't pre-claim, pending stays 0 and the bump alone
                    # accounts for the new child (legacy un-pre-claimed sites
                    # remain correct, just unprotected against the race).
                    pending = int(
                        self._pending_replacement_claims.get(parent_client_order_id, 0)
                    )
                    if pending > 0:
                        new_pending = pending - 1
                        if new_pending == 0:
                            self._pending_replacement_claims.pop(
                                parent_client_order_id, None
                            )
                        else:
                            self._pending_replacement_claims[
                                parent_client_order_id
                            ] = new_pending

                    # âœ… INCREMENT replacement count when adding a new child
                    self.orderbook.parent_order_ids[parent_client_order_id]["current_order_replacement"] += 1
                    is_new_child = True
            
            # Map child to parent
            self.orderbook.child_order_ids[child_client_order_id] = parent_client_order_id
        
        # âœ… ONLY increment in database if this is actually a new child registration
        # CRITICAL: Do not increment if child was already registered - prevents duplicate counts
        if is_new_child:
            from database.order import increment_order_parent_replacement_count
            new_count = increment_order_parent_replacement_count(parent_client_order_id)
            
            if new_count is not None:
                self.log_message(
                "order",
                self.build_event_log_payload(
                    "child_order_registered",
                    parent_client_order_id=parent_client_order_id,
                    child_client_order_id=child_client_order_id,
                    new_replacement_count=new_count,
                ),
            )
        else:
            if registered_now:
                # New child linked but cap was bypassed (partial-fill
                # follow-up). No DB replacement-count bump expected; this
                # is the documented bypass path, not a duplicate-call bug.
                self.log_message(
                    "order",
                    self.build_event_log_payload(
                        "child_order_registered_cap_bypass",
                        parent_client_order_id=parent_client_order_id,
                        child_client_order_id=child_client_order_id,
                        details={"reason": "partial_fill_follow_up"},
                    ),
                )
            else:
                # âš ï¸ REGRESSION DETECTOR: register_child_order() was called for a (child, parent) pair
                # that was already registered. This is almost always a bug â€” most likely a duplicate
                # call site in the event handling path. The DB increment is correctly skipped here,
                # but surface the duplicate so the offending caller can be fixed.
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "child_order_register_duplicate_skipped",
                        parent_client_order_id=parent_client_order_id,
                        child_client_order_id=child_client_order_id,
                        details={
                            "reason": "child_already_registered_under_parent",
                            "action": "db_increment_skipped",
                        },
                    ),
                )

    def _update_dashboard_order_status(self, client_order_id: str, order: dict, status: str) -> None:
        """Update dashboard with current order status.
        
        Extracts order details and pushes to dashboard, plus logs the update.
        
        Args:
            client_order_id: The order's client order ID.
            order: Order data dict.
            status: Order status (OPEN, CANCELLED, FILLED, FAILED, etc.).
        
        Returns:
            None
        
        Example:
            >>> self._update_dashboard_order_status('order_123', order_data, 'FILLED')
        """
        order_side = resolve_order_side(order)
        order_size = resolve_order_size(order)
        filled_size = safe_float(order.get("filled_size"), default=0.0)
        
        # Push to dashboard
        update_order(client_order_id, {
            "order_id": order.get("id", client_order_id),
            "client_order_id": client_order_id,
            "product_id": order.get("product_id"),
            "side": order_side,
            "size": order_size,
            "price": order.get("limit_price"),
            "filled_size": filled_size,
            "status": status,
        })
        
        # Log the update
        product_id = order.get("product_id", "UNKNOWN")
        if status == OrderStatus.FAILED:
            add_log_entry("ERROR", f"Order FAILED: {product_id} {order_side} - Check account balance/margin")
        elif status == OrderStatus.OPEN:
            add_log_entry("INFO", f"Order OPEN: {product_id} {order_side} {order_size}")
        elif status == OrderStatus.CANCELLED:
            add_log_entry("INFO", f"Order CANCELLED: {product_id} {order_side} {order_size}")
        elif status == OrderStatus.FILLED:
            add_log_entry("INFO", f"Order FILLED: {product_id} {order_side} {order_size}")

    def _is_external_order(self, client_order_id: str) -> bool:
        """Check if an order is external (not created by our engine).
        
        External orders are ones placed directly via Coinbase UI or API,
        not by our automated order engine.

        Resolution order:
            1. If the cached parent entry carries ``externally_created=True``
               (set by :meth:`_ensure_order_parent_row_exists`) â†’ external.
            2. Otherwise, an order we have no record of (neither parent nor
               child in the in-memory orderbook) is external. This is the
               legacy path retained for callers that look up COIDs we have
               not yet hoisted into the cache.
        
        Args:
            client_order_id: The order's client order ID.
        
        Returns:
            True if order is external (not in our orderbook), False if it's ours.
        
        Example:
            >>> if self._is_external_order('order_123'):
            ...     # Just track it, don't create follow-ups
        """
        with self.orderbook_lock:
            cached = self.orderbook.parent_order_ids.get(client_order_id)
            if cached is not None:
                return bool(cached.get("externally_created", False))
            in_child_cache = client_order_id in self.orderbook.child_order_ids
        return not in_child_cache

    def _handle_external_order_tracking(
        self,
        client_order_id: str,
        order: dict,
        event_type: str,
        processed_flag_name: str = None,
    ) -> bool:
        """Track external orders (for record-keeping, no follow-ups).
        
        For external orders that we didn't create:
        - Creates a parent entry for tracking purposes
        - Logs the event with appropriate context
        - Completes follow-up processing to prevent retries
        
        Args:
            client_order_id: The order's client order ID.
            order: Order data dict.
            event_type: Type of event ('cancelled' or 'filled').
            processed_flag_name: Flag dict name for completion ('cancelled' or 'filled').
        
        Returns:
            True (indicating we handled this external order and should return early).
        
        Example:
            >>> if self._handle_external_order_tracking('order_123', order, 'cancelled', 'cancelled'):
            ...     return  # Already handled
        """
        # Create a parent entry for tracking purposes only
        with self.orderbook_lock:
            is_parent, parent_client_order_id = self.resolve_parent_client_order_id(
                client_order_id,
                order=order,
                create_parent=True,
                status=event_type.upper(),
            )
        
        # Log the external order event
        event_name = f"external_order_{event_type}"
        self.log_message(
            "order",
            self.build_follow_up_log_payload(
                event_name,
                source_order=order,
                parent_client_order_id=parent_client_order_id,
                details={"reason": "external_order_no_follow_up"},
            ),
        )
        
        # Complete processing to prevent follow-up retries
        if processed_flag_name:
            self.complete_follow_up_processing(processed_flag_name, client_order_id)
        
        return True

    def build_follow_up_log_payload(
        self,
        event: str,
        source_order: dict = None,
        parent_client_order_id: str = None,
        parent_target_movement = None,
        new_order: dict = None,
        attempted_new_order: dict = None,
        details: dict = None,
    ) -> dict:
        """Build structured log payload for follow-up order events.
        
        Args:
            event: Event name.
            source_order: Original order that triggered follow-up.
            parent_client_order_id: Parent order ID.
            parent_target_movement: Parent order's target movement percentage.
            new_order: Newly placed order data.
            attempted_new_order: Order data if placement failed.
            details: Additional details dict.
        
        Returns:
            Structured log payload dict.
        
        Example:
            >>> payload = engine.build_follow_up_log_payload(
            ...     'follow_up_order_placed',
            ...     source_order=order,
            ...     new_order={'client_order_id': 'new_123'}
            ... )
        """
        payload = {"event": event}

        if parent_client_order_id is not None:
            payload["parent_client_order_id"] = parent_client_order_id

        if parent_target_movement is not None:
            payload["parent_target_movement"] = parent_target_movement

        if source_order is not None:
            payload["source"] = self.build_order_log_context(source_order)

        if new_order is not None:
            payload["new"] = new_order

        if attempted_new_order is not None:
            payload["attempted_new"] = attempted_new_order

        if details:
            payload["details"] = details

        return payload

    def on_open(self) -> None:
        """Callback when websocket connection opens.
        
        Returns:
            None
        """
        self.log_message("connection", "Connection Opened!")

    def on_message(self, msg: str) -> None:
        """Process incoming websocket message.
        
        Parses JSON, deduplicates events using EventBridge, and enqueues for processing.
        
        Args:
            msg: Raw websocket message (JSON string).
        
        Returns:
            None
        """
        try:
            json_msg = json.loads(msg)
            channel = json_msg.get("channel")

            if any((
                "events" not in json_msg,
                channel == ChannelType.SUBSCRIPTIONS.value,
                not channel,
                channel not in self.event_queue,
            )):
                return

            for event in json_msg["events"]:
                # Atomic claim: under EventProcessor's dedup lock, check all
                # buckets and add to the current bucket in one step. This
                # prevents the fan-out race where N WSClient threads all
                # observe "new" for the same payload and all enqueue it.
                # The legacy is_duplicate_event/mark_event_seen pair was
                # racy across threads â€” do not reintroduce it here.
                if not self.evt_bridge.claim_event(event):
                    continue

                try:
                    self.event_queue[channel].put(deepcopy(event), timeout=0.01)

                except Full:
                    self.log_message(
                        "warning",
                        self.build_event_log_payload(
                            "event_queue_full",
                            channel=channel,
                            **self.include_debug_fields(dropped_event=event),
                        ),
                    )

        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "websocket_message_processing_exception",
                    error=str(e),
                    raw_message=msg,
                ),
            )

    def process_user_event(self, event: dict) -> None:
        """Process user-channel event (orders or positions).
        
        Dispatches to process_user_order or process_user_snapshot.
        
        Args:
            event: Event dict with 'type' and 'orders'/'positions' keys.
        
        Returns:
            None
        """
        try:
            if event["type"].upper() not in self.websocket_events:
                self.log_message(
                    "event",
                    self.build_event_log_payload(
                        "user_event_ignored",
                        **self.include_debug_fields(received_event=event),
                    ),
                )
                return

            if "orders" in event and event["type"].upper() in ["OPEN", "FILLED", "CANCELLED", "UPDATE"]:
                for order in event["orders"]:
                    if "client_order_id" not in order:
                        self.log_message(
                            "warning",
                            self.build_event_log_payload(
                                "missing_client_order_id_in_order_event",
                                source=self.build_order_log_context(order),
                                **self.include_debug_fields(raw_order=order),
                            ),
                        )
                        continue
                    self.process_user_order(order)

            # WS user-channel SNAPSHOT events (sent on connect / reconnect)
            # carry the venue's view of every open order. We don't mutate
            # state from them â€” the live update path owns that â€” but we do
            # use them as a continuous self-check against in-memory state.
            # Any drift is logged for operator review and is the cheapest
            # available signal that a delta was missed.
            elif "orders" in event and event["type"].upper() == "SNAPSHOT":
                snapshot_orders = [
                    o for o in event.get("orders", [])
                    if o.get("client_order_id")
                ]
                ws_client_order_ids = {
                    o["client_order_id"] for o in snapshot_orders
                }
                # Drift check FIRST (compares venue snapshot against what we
                # *believed*), then heal in-memory state from the snapshot.
                # Order matters: if we hydrated first, drift would always be
                # zero and we'd lose the signal that we missed a delta.
                self.snapshot_drift_check(
                    ws_client_order_ids,
                    source="ws_user_snapshot",
                )
                self._hydrate_orderbook_from_ws_snapshot(snapshot_orders)

            elif "positions" in event:
                self.process_user_snapshot(event)

        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "user_event_processing_error",
                    error=str(e),
                    **self.include_debug_fields(received_event=event),
                ),
            )

    def process_futures_balance_summary_event(self, event: dict) -> None:
        """Process futures balance summary event and update fee regime state."""
        if not self.fee_manager:
            return

        if not isinstance(event, dict):
            return

        fcm_balance_summary = event.get("fcm_balance_summary")
        if isinstance(fcm_balance_summary, dict):
            self.fee_manager.update_margin_window_from_summary(fcm_balance_summary)

    def snapshot_drift_check(
        self,
        ws_client_order_ids,
        *,
        source: str = "ws_user_snapshot",
    ) -> dict:
        """Compare a venue-reported set of open ``client_order_id`` values
        against what is currently in the in-memory orderbook and log any
        drift.

        Read-only by design. The live update path remains the only writer
        to ``self.orderbook.order``; this method is a continuous self-check
        intended to surface dropped WebSocket frames or missed
        reconnect-snapshot deltas without mutating engine state.

        Logged drift cases:
          * ``ws_only`` â€” venue reports the order is open but our in-memory
            orderbook has no record of it. Most common cause: the WS
            connection dropped after the order was placed but before the
            OPEN delta arrived.
          * ``in_memory_only`` â€” we believe the order is open but the
            venue's snapshot does not include it. Most common cause: a
            FILLED or CANCELLED delta was dropped during a reconnect.

        Args:
            ws_client_order_ids: Iterable of ``client_order_id`` strings
                from the WS snapshot frame.
            source: Free-form label written into log records so multiple
                callers (e.g. WS snapshot, periodic auditor, manual
                operator probe) are distinguishable in audit queries.

        Returns:
            Dict with counts: ``{"ws_only": [...], "in_memory_only": [...],
            "in_sync_count": int, "source": source}``.
        """
        ws_ids = {coid for coid in ws_client_order_ids if coid}

        # Snapshot in-memory state under the lock, including each entry's
        # last-known status / product / cumulative_quantity so the drift
        # log can identify *what* the orphan actually is (leaked FILLED,
        # stuck OPEN, never-confirmed placement, etc.) instead of just
        # surfacing a bare client_order_id.
        #
        # Apples-to-apples principle: the venue's open-orders snapshot
        # only contains orders the exchange currently considers open
        # (status OPEN or UPDATE). Comparing it against every entry we
        # ever stored â€” including transient PENDING/CANCEL_QUEUED entries
        # mid-placement and terminal FILLED/CANCELLED/FAILED entries
        # awaiting bookkeeping cleanup â€” produces guaranteed false
        # positives. Filter the in-memory side to the same population
        # the WS snapshot is reporting on. Eviction (in process_user_order)
        # still bounds memory, but is no longer racing this check.
        _OPEN_ON_VENUE = {
            OrderStatus.OPEN.value,
            OrderStatus.UPDATE.value,
        }
        with self.orderbook_lock:
            all_state = {
                coid: dict(self.orderbook.order.get(coid) or {})
                for coid in self.orderbook.order.keys()
            }

        def _norm(s):
            return (s or "").upper() if isinstance(s, str) else s

        in_memory_state = {
            coid: {
                "status": data.get("status"),
                "product_id": data.get("product_id"),
                "cumulative_quantity": data.get("cumulative_quantity"),
                "leaves_quantity": data.get("leaves_quantity"),
                "creation_time": data.get("creation_time"),
            }
            for coid, data in all_state.items()
        }
        in_memory_ids = {
            coid
            for coid, data in all_state.items()
            if _norm(data.get("status")) in _OPEN_ON_VENUE
        }

        ws_only = sorted(ws_ids - in_memory_ids)
        in_memory_only = sorted(in_memory_ids - ws_ids)
        in_sync_count = len(ws_ids & in_memory_ids)

        report = {
            "source": source,
            "ws_only": ws_only,
            "in_memory_only": in_memory_only,
            "in_sync_count": in_sync_count,
            "ws_count": len(ws_ids),
            "in_memory_count": len(in_memory_ids),
        }

        if ws_only or in_memory_only:
            # Dedup gate: each WS user-event worker thread receives the
            # SNAPSHOT frame and would emit identical drift reports
            # (~6 worker threads â†’ 6Ã— duplicated WARNING blocks). Hash
            # the drift contents and skip emission when the signature
            # matches the previously-emitted one for this source. The
            # first observation of a new drift state always emits.
            signature = (
                "drift",
                tuple(ws_only),
                tuple(in_memory_only),
            )
            with self._snapshot_drift_emit_lock:
                if self._snapshot_drift_last_signature.get(source) == signature:
                    return report
                self._snapshot_drift_last_signature[source] = signature

            self.log_message(
                "warning",
                self.build_event_log_payload(
                    "snapshot_drift_detected",
                    source=source,
                    ws_only_count=len(ws_only),
                    in_memory_only_count=len(in_memory_only),
                    in_sync_count=in_sync_count,
                ),
            )
            for coid in ws_only:
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "snapshot_drift_ws_only",
                        source=source,
                        client_order_id=coid,
                    ),
                )
            for coid in in_memory_only:
                detail = in_memory_state.get(coid, {})
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "snapshot_drift_in_memory_only",
                        source=source,
                        client_order_id=coid,
                        in_memory_status=detail.get("status"),
                        product_id=detail.get("product_id"),
                        cumulative_quantity=detail.get("cumulative_quantity"),
                        leaves_quantity=detail.get("leaves_quantity"),
                        creation_time=detail.get("creation_time"),
                    ),
                )
        else:
            # Same dedup approach for the clean case: only emit when
            # the source transitions out of a drifted state (or on
            # first ever observation).
            signature = ("clean",)
            with self._snapshot_drift_emit_lock:
                if self._snapshot_drift_last_signature.get(source) == signature:
                    return report
                self._snapshot_drift_last_signature[source] = signature

            self.log_message(
                "info",
                self.build_event_log_payload(
                    "snapshot_drift_clean",
                    source=source,
                    in_sync_count=in_sync_count,
                ),
            )

        return report

    def _hydrate_orderbook_from_ws_snapshot(self, snapshot_orders) -> None:
        """Reconcile in-memory ``orderbook.order`` with a venue WS snapshot.

        The venue's user-channel SNAPSHOT frame is the authoritative view of
        every open order at the exchange. Without this hydration step the
        in-memory orderbook starts empty at engine boot and is only ever
        populated by live deltas, so:

        * cold start: the first SNAPSHOT trips ``snapshot_drift_detected``
          for every currently-open order at the venue (guaranteed noise).
        * reconnect: any delta missed during the disconnect window stays
          missed — we never observe the corrective state.

        Strategy: snapshot is canonical. For each snapshot order:
          - not in memory → insert minimal record.
          - in memory with same status → no-op.
          - in memory with different status → overwrite + emit
            ``snapshot_overrode_in_memory_status`` for audit.

        Only the small set of fields the drift check and downstream readers
        care about is written. Snapshot rows are NOT routed through
        ``process_user_order`` because that path mutates DB state (FK
        creation, fill ledger, partial-fill follow-ups) and would
        double-process orders the engine has already persisted.
        """
        if not snapshot_orders:
            return

        _MINIMAL_FIELDS = (
            "client_order_id",
            "order_id",
            "status",
            "product_id",
            "product_type",
            "side",
            "cumulative_quantity",
            "leaves_quantity",
            "filled_size",
            "creation_time",
            "outstanding_hold_amount",
        )

        inserted = 0
        overwritten = 0
        with self.orderbook_lock:
            for order in snapshot_orders:
                coid = order.get("client_order_id")
                if not coid:
                    continue
                existing = self.orderbook.order.get(coid)
                minimal = {k: order.get(k) for k in _MINIMAL_FIELDS if k in order}

                if existing is None:
                    self.orderbook.order[coid] = minimal
                    inserted += 1
                    continue

                existing_status = existing.get("status")
                snapshot_status = order.get("status")
                if existing_status == snapshot_status:
                    continue

                # Status disagreement: venue wins, but record the override
                # so an operator can investigate why our in-memory belief
                # diverged.
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "snapshot_overrode_in_memory_status",
                        client_order_id=coid,
                        in_memory_status=existing_status,
                        snapshot_status=snapshot_status,
                        product_id=order.get("product_id"),
                    ),
                )
                # Merge minimal fields over the existing record to preserve
                # any additional bookkeeping fields populated by other code
                # paths (e.g. internal flags) while letting the venue's
                # status / qty win.
                merged = dict(existing)
                merged.update(minimal)
                self.orderbook.order[coid] = merged
                overwritten += 1

        if inserted or overwritten:
            self.log_message(
                "info",
                self.build_event_log_payload(
                    "orderbook_hydrated_from_ws_snapshot",
                    inserted_count=inserted,
                    overwritten_count=overwritten,
                    snapshot_size=len(snapshot_orders),
                ),
            )

    def process_user_snapshot(self, snapshot: dict) -> None:
        """Process position snapshot from websocket.
        
        Updates in-memory futures positions.
        
        Flow:
        1. Call PRE-hooks on RAW snapshot
        2. Call normalizers (can enrich with computed fields)
        3. Process positions and update orderbook
        4. Call POST-hooks on NORMALIZED snapshot
        
        Args:
            snapshot: Event dict with 'positions' key.
        
        Returns:
            None
        """
        # Step 1: Call pre-processor hooks for snapshot (on raw data)
        self.websocket_hooks.call_pre_snapshot(snapshot)
        
        # Step 2: Call normalizers to transform/enrich snapshot
        self.websocket_hooks.call_snapshot_normalizers(snapshot)
        
        # Step 3: Process positions
        for _, items in snapshot["positions"].items():
            if not items:
                continue

            for item in items:
                with self.orderbook_lock:
                    self.orderbook.positions["FUTURE"][item["product_id"]] = {
                        "side": item["side"].upper(),
                        "number_of_contracts": item["number_of_contracts"],
                        "realized_pnl": item["realized_pnl"],
                        "unrealized_pnl": item["unrealized_pnl"],
                        "entry_price": item["entry_price"],
                    }

                self.log_message(
                    "snapshot",
                    self.build_event_log_payload(
                        "futures_position_snapshot_updated",
                        product_id=item["product_id"],
                        position=self.orderbook.positions["FUTURE"][item["product_id"]],
                    ),
                )
        
        # Step 4: Call post-processor hooks for snapshot
        self.websocket_hooks.call_post_snapshot(snapshot)

    def process_user_order(self, order: dict) -> None:
        """Process order event (state transitions).
        
        Updates orderbook, dispatches to fill/cancel handlers, persists to DB.
        
        Flow:
        1. Call PRE-hooks on RAW order (Coinbase fields as-is)
        2. Normalize order (handle field variations, add computed fields)
        3. Store normalized order in orderbook
        4. Process status transitions
        5. Call POST-hooks on NORMALIZED order
        
        Args:
            order: Order event dict.
        
        Returns:
            None
        """
        client_order_id = order.get("client_order_id")
        status = order.get("status")

        # Step 1: Call PRE-hooks on RAW order (before any normalization)
        # This allows extensions to see Coinbase fields as-is
        self.websocket_hooks.call_pre_order_status(status, order)

        # Step 2: Normalize order
        normalized_order = deepcopy(order)
        normalized_order["product_type"] = self.normalize_product_type(normalized_order)
        
        # Call extensible order normalizers (can modify fields, add computed values, etc.)
        self.websocket_hooks.call_order_normalizers(normalized_order)
        self._sync_stealth_exchange_order_id(normalized_order)
        
        outstanding_hold_amount = safe_float(
            normalized_order.get("outstanding_hold_amount"),
            default=0.0,
        )

        # Step 3: Store normalized order in orderbook
        with self.orderbook_lock:
            self.orderbook.order[client_order_id] = normalized_order

        # Per-COID serialisation: prevents two WS workers from racing on
        # the same external COID where T_A populates the in-memory cache
        # before its INSERT commits and T_B then trips the FK violation
        # on partial_fill_progress. See lock-init comment in __init__.
        coid_lock = self._get_coid_handler_lock(client_order_id)
        with coid_lock:
            # Step 3a: Ensure the order_parent row exists before any FK-dependent
            # write. partial_fill_progress.client_order_id_fkey requires a parent
            # row, so for genuinely-unknown (external) orders we must create one
            # NOW â€” before _process_ws_order_delta runs the watermark upsert.
            # See genai_tools/TODO_2026_04_28_partial_fill_root_causes.md (#1).
            self._ensure_order_parent_row_exists(normalized_order)

            # Step 3b: Single ingestion point for WS-derived progress.
            # Routes to fill ledger, audit table, watermark persistence and
            # partial-fill follow-up creation in one place â€” see
            # _process_ws_order_delta. Idempotent (deterministic
            # derived_trade_key); safe on every event regardless of status. Must
            # run before _finalize_partial_fill_progress wipes state on terminal
            # status.
            self._process_ws_order_delta(normalized_order)

        if status == OrderStatus.FILLED and outstanding_hold_amount > 0:
            self.log_message(
                "order",
                self.build_event_log_payload(
                    "filled_order_waiting_for_hold_clear",
                    source=self.build_order_log_context(normalized_order),
                    outstanding_hold_amount=normalized_order.get("outstanding_hold_amount"),
                ),
            )
            return

        # Step 4: Process status transitions
        try:
            # In the flat hierarchy, both root parents and reveal-placement
            # children live in the order_parent table. The placement row is
            # the truth-of-record for what happened on the exchange, so its
            # status MUST be updated regardless of parent/child classification.
            # When the COID is a child of a chain root (stealth-managed
            # placement) we also propagate the status to the root, since the
            # root row is what dashboards / reports read for the logical order.
            if self.is_parent_order(client_order_id):
                self.db_module.update_order_parent_status(
                    client_order_id=client_order_id,
                    status=status,
                )
            elif self.is_child_order(client_order_id):
                # Update the placement row itself.
                self.db_module.update_order_parent_status(
                    client_order_id=client_order_id,
                    status=status,
                )
                # Propagate to the chain root so the logical order's status
                # (read by dashboards) reflects the placement's lifecycle.
                root_client_order_id = self.get_parent_of_child(client_order_id)
                if root_client_order_id and root_client_order_id != client_order_id:
                    self.db_module.update_order_parent_status(
                        client_order_id=root_client_order_id,
                        status=status,
                    )
        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "database_order_status_update_failed",
                    error=str(e),
                    source=self.build_order_log_context(normalized_order),
                    **self.include_debug_fields(raw_order=normalized_order),
                ),
            )

        if status == OrderStatus.SNAPSHOT:
            return
        if status == OrderStatus.CANCEL_QUEUED:
            return
        if status == OrderStatus.PENDING:
            return
        if status == OrderStatus.FAILED:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "order_failed",
                    source=self.build_order_log_context(normalized_order),
                    **self.include_debug_fields(raw_order=normalized_order),
                ),
            )
            self._finalize_partial_fill_progress(client_order_id, "CANCELLED")
            self._update_dashboard_order_status(client_order_id, normalized_order, status)
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            self.websocket_hooks.call_post_order_status(status, normalized_order)
            return
        if status == OrderStatus.OPEN:
            # Partial-fill follow-up creation already happened inside
            # _process_ws_order_delta above; nothing more to do for OPEN here.
            self._update_dashboard_order_status(client_order_id, normalized_order, status)
            self.websocket_hooks.call_post_order_status(status, normalized_order)
            return
        if status == OrderStatus.UPDATE:
            # Same as OPEN: tracker has already routed any partial-fill
            # follow-up. Just refresh dashboard + downstream hooks.
            self._update_dashboard_order_status(client_order_id, normalized_order, status)
            self.websocket_hooks.call_post_order_status(status, normalized_order)
            return
        if status == OrderStatus.CANCELLED:
            self._finalize_partial_fill_progress(client_order_id, "CANCELLED")
            self.handle_cancelled_order(normalized_order)
            self._update_dashboard_order_status(client_order_id, normalized_order, status)

            # Evict the terminal entry from the in-memory orderbook so the
            # WS snapshot drift checker doesn't keep flagging it as
            # "in_memory_only" forever. Must run after handle_*_order so
            # downstream lookups (follow-up creation, external-order
            # tracking) still see the row, and after dashboard update so
            # the final terminal state is rendered.
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            self.websocket_hooks.call_post_order_status(status, normalized_order)
            return
        if status == OrderStatus.FILLED:
            self._finalize_partial_fill_progress(client_order_id, "FINALIZED")
            self.handle_filled_order(normalized_order)
            self._update_dashboard_order_status(client_order_id, normalized_order, status)

            # Same eviction reason as the CANCELLED branch above.
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            self.websocket_hooks.call_post_order_status(status, normalized_order)
            return

        self.log_message(
            "warning",
            self.build_event_log_payload(
                "unrecognized_order_status",
                status=status,
                source=self.build_order_log_context(normalized_order),
            ),
        )

    def _sync_stealth_exchange_order_id(self, order: dict) -> None:
        """Backfill exchange_order_id for stealth audit rows when websocket data arrives."""
        if not self.stealth_order_bridge:
            return

        client_order_id = order.get("client_order_id")
        exchange_order_id = order.get("order_id")
        if not client_order_id or not exchange_order_id:
            return

        stealth_manager = getattr(self.stealth_order_bridge, "stealth_manager", None)
        if not stealth_manager:
            return

        try:
            stealth_manager.sync_exchange_order_id_for_placed_order(
                client_order_id,
                exchange_order_id,
            )
        except Exception as exc:
            self.log_message(
                "warning",
                self.build_event_log_payload(
                    "stealth_exchange_order_id_sync_failed",
                    source=self.build_order_log_context(order),
                    error=str(exc),
                ),
            )

    def _seed_parent_order_cache_from_db(self, client_order_id: str) -> bool:
        """Hydrate in-memory parent metadata for stealth orders already persisted at creation."""
        if self.is_parent_order(client_order_id) or self.is_child_order(client_order_id):
            return True
        if not self.db_module or not hasattr(self.db_module, "get_parent_order"):
            return False

        parent_order = self.db_module.get_parent_order(client_order_id)
        if not parent_order:
            return False

        # If the persisted row is itself a child (parent_order_id set), hydrate
        # the chain root first and register this COID as a child under it.
        # Otherwise downstream lookups (is_parent_order / status routing)
        # mis-classify it as a root and update the wrong order_parent row â€”
        # source of the 2026-04-29 stealth-status-stuck-at-PENDING bug where
        # status writes targeted the placement uuid (row 62) instead of the
        # stealth root (row 61).
        db_parent_link = parent_order.get("parent_order_id")
        if db_parent_link:
            root_client_order_id = str(db_parent_link)
            # Recursively seed root metadata (flat hierarchy means one hop,
            # but the recursion is safe and bounded by is_parent_order short-circuit).
            if root_client_order_id != client_order_id:
                self._seed_parent_order_cache_from_db(root_client_order_id)

            # Register the in-memory child link WITHOUT touching the DB
            # replacement counter â€” the row already reflects its persisted
            # state and re-incrementing here would double-count on every
            # restart / reconcile pass.
            with self.orderbook_lock:
                root_entry = self.orderbook.parent_order_ids.get(root_client_order_id)
                if root_entry is not None:
                    if client_order_id not in root_entry.setdefault("orders", []):
                        root_entry["orders"].append(client_order_id)
                self.orderbook.child_order_ids[client_order_id] = root_client_order_id
            return True

        with self.orderbook_lock:
            self.orderbook.parent_order_ids[client_order_id] = {
                "orders": list(self.orderbook.parent_order_ids.get(client_order_id, {}).get("orders", [])),
                "target_movement": {
                    "movement": safe_float(parent_order.get("target_movement"), default=0.0),
                    "type": parent_order.get("target_movement_type", "P"),
                },
                "max_order_replacement": int(parent_order.get("max_order_replacement") or DEFAULT_MAX_ORDER_REPLACEMENT),
                "current_order_replacement": int(parent_order.get("current_order_replacement") or 0),
                "parent_id": parent_order.get("id"),
                "allow_partial_fills": bool(parent_order.get("allow_partial_fills", False)),
            }
        return True

    def _get_coid_handler_lock(self, client_order_id: str) -> threading.Lock:
        """Return the per-COID handler lock, creating it on first access.

        The map of locks is itself protected by a small guard lock so that
        the get-or-create sequence is atomic. Locks are never evicted â€”
        the working set is bounded by the number of distinct active COIDs
        and entries are tiny (a single threading.Lock each).
        """
        with self._coid_handler_locks_guard:
            lock = self._coid_handler_locks.get(client_order_id)
            if lock is None:
                lock = threading.Lock()
                self._coid_handler_locks[client_order_id] = lock
            return lock

    def _ensure_order_parent_row_exists(self, normalized_order: dict) -> None:
        """Idempotently guarantee an ``order_parent`` row exists for this COID.

        Why this exists:
            ``partial_fill_progress.client_order_id_fkey`` requires that an
            ``order_parent`` row already be present before any watermark
            upsert. Prior to 2026-04-28 the WS handler called
            :meth:`_process_ws_order_delta` (which writes that watermark)
            *before* the FILLED/CANCELLED routing that would have created
            the parent row for externally-placed orders. Result: every
            brand-new external order produced a ``ForeignKeyViolation``
            and at least one parent insert was lost when the error
            handler itself crashed (separate exception-signature bug).

        Behaviour:
            - Already tracked (parent or child in memory) â†’ no-op.
            - Persisted in DB but not yet cached â†’ hydrate cache, no-op.
            - Genuinely unknown â†’ insert via
              :meth:`resolve_parent_client_order_id` and tag the cache
              entry ``externally_created=True`` so :meth:`_is_external_order`
              still routes the order to the external-tracking path
              downstream.

        Args:
            normalized_order: Normalised WS order dict; must contain
                ``client_order_id``. May lack a ``status`` (e.g. snapshot)
                in which case the parent is inserted with whatever status
                the payload reports, defaulting to ``OPEN``.
        """
        client_order_id = normalized_order.get("client_order_id")
        if not client_order_id:
            return

        if self.is_parent_order(client_order_id) or self.is_child_order(client_order_id):
            return  # Already tracked in memory â€” FK precondition satisfied.

        if self._seed_parent_order_cache_from_db(client_order_id):
            return  # Persisted in DB but not yet cached â€” hydrate and done.

        # Genuinely unknown order. Insert the parent row idempotently so
        # the watermark upsert that follows can satisfy the FK.
        self.resolve_parent_client_order_id(
            client_order_id,
            order=normalized_order,
            create_parent=True,
            status=normalized_order.get("status"),
        )
        with self.orderbook_lock:
            cached = self.orderbook.parent_order_ids.get(client_order_id)
            if cached is not None:
                cached["externally_created"] = True

    def apply_position_update(self, order_template: dict) -> None:
        """Apply position update from order template to orderbook.
        
        Args:
            order_template: Template dict (may have 'position_update' key).
        
        Returns:
            None
        """
        position_update = order_template.get("position_update")
        if not position_update:
            return
        with self.orderbook_lock:
            apply_calculated_position_update(self.orderbook.positions, position_update)
            
            # Push position updates to dashboard
            for product_id, position_data in self.orderbook.positions.items():
                update_position(product_id, {
                    "product_id": product_id,
                    "type": position_data.get("type", "UNKNOWN"),
                    "amount": position_data.get("amount", 0),
                    "entry_price": position_data.get("entry_price", 0),
                    "current_value": position_data.get("current_value", 0),
                    "entry_cost": position_data.get("entry_cost", 0),
                })

    def compute_order_template(self, client_order_id: str, target_movement: dict = None) -> dict:
        """Compute follow-up order template for a given order.
        
        Args:
            client_order_id: Order to compute template for.
            target_movement: Optional override for profit target.
        
        Returns:
            Order template dict or {} if computation fails.
        
        Example:
            >>> template = engine.compute_order_template('order_123')
            >>> print(template['start_price'])
        """
        snapshot = self.get_orderbook_snapshot()
        order = snapshot["order"].get(client_order_id)
        if not order:
            return {}

        if self.normalize_product_type(order) == ProductType.FUTURE:
            product_id = order.get("product_id")
            if product_id not in snapshot.get("positions", {}).get("FUTURE", {}):
                self.refresh_positions_if_needed(product_id)
                snapshot = self.get_orderbook_snapshot()

        return calculate_new_order_move_from_snapshot(
            snapshot,
            order_id=client_order_id,
            target_movement=target_movement,
        )

    def compute_partial_fill_order_template(self, client_order_id: str, target_movement: dict = None) -> dict:
        """Compute partial-fill follow-up template as the EXIT trade for the just-filled portion.

        A partial fill means N units actually filled at the parent's price. The follow-up
        for those units is the profit-taking exit, so it must be **opposite-side** at a
        target-adjusted price (BUY parent â†’ SELL exit; SELL parent â†’ BUY exit).

        We force ``status=FILLED`` in the snapshot copy so
        ``calculate_new_order_move_from_snapshot`` flips the side and applies the
        profit-target price move. The caller supplies its own ``follow_up_size``
        (the partial quantity), so the template's size is unused and the FILLED-branch
        position adjustment is harmless (caller does not apply ``position_update``).
        """
        snapshot = self.get_orderbook_snapshot()
        order = snapshot["order"].get(client_order_id)
        if not order:
            return {}

        if self.normalize_product_type(order) == ProductType.FUTURE:
            product_id = order.get("product_id")
            if product_id not in snapshot.get("positions", {}).get("FUTURE", {}):
                self.refresh_positions_if_needed(product_id)
                snapshot = self.get_orderbook_snapshot()
                order = snapshot["order"].get(client_order_id)
                if not order:
                    return {}

        # Force FILLED semantics so the side flips to the exit trade and the
        # profit-target price move is applied â€” same math as the post-FILLED follow-up.
        order_copy = deepcopy(order)
        order_copy["status"] = OrderStatus.FILLED.value
        snapshot["order"][client_order_id] = order_copy

        return calculate_new_order_move_from_snapshot(
            snapshot,
            order_id=client_order_id,
            target_movement=target_movement,
        )

    def child_order_already_exists(self, parent_client_order_id: str, order_template: dict) -> bool:
        """Check if a child order matching the template already exists.
        
        Queries database to prevent duplicate child orders.
        
        Args:
            parent_client_order_id: Parent order ID.
            order_template: New order template to check.
        
        Returns:
            True if child order already exists, False otherwise.
        
        Example:
            >>> exists = engine.child_order_already_exists('parent_123', template)
            >>> if not exists:
            ...     # Safe to place new order
        """
        if not parent_client_order_id:
            self.log_message(
                "warning",
                f"Order {parent_client_order_id} not found in parent or child order book."
            )
            return False

        if hasattr(self.db_module, "child_order_exists"):
            try:
                return bool(self.db_module.child_order_exists(
                    parent_client_order_id=parent_client_order_id,
                    product_id=order_template["product_id"],
                    side=order_template["side"],
                    size=float(order_template["order_base_size"]),
                    price=float(order_template["start_price"]),
                ))
            except TypeError:
                try:
                    return bool(self.db_module.child_order_exists(parent_client_order_id, order_template))
                except Exception as e:
                    self.log_message(
                        "warning",
                        self.build_event_log_payload(
                            "child_order_exists_check_failed",
                            parent_client_order_id=parent_client_order_id,
                            attempted_new_order=order_template,
                            error=str(e),
                        ),
                    )
            except Exception as e:
                self.log_message(
                    "warning",
                    self.build_event_log_payload(
                        "child_order_exists_check_failed",
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order=order_template,
                        error=str(e),
                    ),
                )

        return False

    def resolve_parent_target_movement(self, parent_client_order_id: str) -> dict:
        """Get configured profit target for a parent order.
        
        Args:
            parent_client_order_id: Parent order ID.
        
        Returns:
            Dict with 'type' and 'movement' keys, or None if parent not found.
        """
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_client_order_id, {})
            target_movement = deepcopy(parent.get("target_movement"))

        if not target_movement:
            return target_movement

        if target_movement.get("type") != TargetMovementType.PERCENTAGE.value:
            return target_movement

        product_id = None
        with self.orderbook_lock:
            parent_order = self.orderbook.order.get(parent_client_order_id, {})
            if isinstance(parent_order, dict):
                product_id = parent_order.get("product_id")

        if self.fee_manager:
            movement_value = safe_float(target_movement.get("movement"), default=0.0)
            adaptive_multiplier = self.fee_manager.get_target_movement_multiplier(product_id)
            target_movement["movement"] = movement_value * adaptive_multiplier

        return target_movement

    def resolve_parent_replacement_state(self, parent_client_order_id: str) -> dict:
        """Get current and max replacement counts for a parent order.
        
        Args:
            parent_client_order_id: Parent order ID (or child ID, will be resolved).
        
        Returns:
            Dict with 'max_order_replacement' and 'current_order_replacement' keys.
        """
        with self.orderbook_lock:
            # If this is a child ID, resolve to the actual parent
            actual_parent_id = parent_client_order_id
            if self._is_child_order_unlocked(parent_client_order_id):
                actual_parent_id = self._get_parent_of_child_unlocked(parent_client_order_id)
            
            parent = self.orderbook.parent_order_ids.get(actual_parent_id, {})

            return {
                "max_order_replacement": int(parent.get("max_order_replacement", 0)),
                "current_order_replacement": int(parent.get("current_order_replacement", 0)),
            }

    def can_create_follow_up_order(self, parent_client_order_id: str) -> tuple:
        """Check if a follow-up order can be created for a parent.
        
        Compares current replacement count vs max allowed.
        
        Args:
            parent_client_order_id: Parent order ID.
        
        Returns:
            Tuple (can_create: bool, details: dict).
        
        Example:
            >>> can_create, details = engine.can_create_follow_up_order('parent_123')
            >>> if can_create:
            ...     # Place follow-up order
        """
        replacement_state = self.resolve_parent_replacement_state(parent_client_order_id)
        max_order_replacement = replacement_state["max_order_replacement"]
        current_order_replacement = replacement_state["current_order_replacement"]

        details = {
            "current_order_replacement": current_order_replacement,
            "max_order_replacement": max_order_replacement,
        }
        return current_order_replacement < max_order_replacement, details

    def claim_replacement_slots(
        self, parent_client_order_id: str, requested: int
    ) -> int:
        """Atomically reserve up to ``requested`` follow-up replacement slots.

        Returns the number of slots actually granted (``0`` when the parent's
        ``max_order_replacement`` cap is already met or when ``requested`` is
        non-positive). The grant is recorded in ``_pending_replacement_claims``
        and is released either by ``register_child_order`` (success path â€”
        decrements pending and increments ``current_order_replacement`` so the
        net is one consumed slot) or by ``release_replacement_slots`` (failure
        path â€” decrements pending only).

        This method is the **single gate** for replacement-cap enforcement.
        Callers must NOT do their own ``can_create_follow_up_order`` +
        compute-remaining-then-create pattern: that pattern lets concurrent
        threads each observe the same stale snapshot and breach the cap (see
        2026-04-29 incident â€” ``max_order_replacement=1`` with four
        concurrent BUY follow-ups created on the same parent).

        Args:
            parent_client_order_id: Parent order id (or child id; resolved).
            requested: Maximum number of slots to claim.

        Returns:
            Number of slots actually granted in ``[0, requested]``.
        """
        if requested <= 0:
            return 0
        with self.orderbook_lock:
            actual_parent_id = parent_client_order_id
            if self._is_child_order_unlocked(parent_client_order_id):
                actual_parent_id = self._get_parent_of_child_unlocked(
                    parent_client_order_id
                )
            parent = self.orderbook.parent_order_ids.get(actual_parent_id, {})
            max_repl = int(parent.get("max_order_replacement", 0))
            current = int(parent.get("current_order_replacement", 0))
            pending = int(self._pending_replacement_claims.get(actual_parent_id, 0))
            available = max(0, max_repl - current - pending)
            granted = min(requested, available)
            if granted > 0:
                self._pending_replacement_claims[actual_parent_id] = pending + granted
            return granted

    def release_replacement_slots(
        self, parent_client_order_id: str, n: int
    ) -> None:
        """Release ``n`` replacement slots previously claimed via
        ``claim_replacement_slots`` whose child was never registered (e.g.
        follow-up creation failed). Safe to call with ``n <= 0``.
        """
        if n <= 0:
            return
        with self.orderbook_lock:
            actual_parent_id = parent_client_order_id
            if self._is_child_order_unlocked(parent_client_order_id):
                actual_parent_id = self._get_parent_of_child_unlocked(
                    parent_client_order_id
                )
            current_pending = int(
                self._pending_replacement_claims.get(actual_parent_id, 0)
            )
            new_pending = max(0, current_pending - n)
            if new_pending == 0:
                self._pending_replacement_claims.pop(actual_parent_id, None)
            else:
                self._pending_replacement_claims[actual_parent_id] = new_pending

    def handle_cancelled_order(self, order: dict) -> None:
        """Handle a cancelled order by potentially creating a follow-up.
        
        If the order is pre-marked for automatic move (move_on_cancel=True),
        executes the pending move instead of creating a child order.
        
        NOTE: External orders (created in Coinbase UI, not by our engine) are
        tracked for record-keeping but do NOT trigger follow-up orders.
        
        Args:
            order: Cancelled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        # CRITICAL: Claim follow-up processing FIRST to prevent race conditions
        # Must happen BEFORE any other processing (including registration) to ensure
        # atomicity and prevent duplicate follow-up creation in concurrent scenarios
        if not self.claim_follow_up_processing("cancelled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=None,
                    details={"reason": "cancelled_order_follow_up_already_claimed"},
                ),
            )
            return

        # CRITICAL: Check for stealth order BEFORE marking as external
        # Stealth-revealed slices won't be in orderbook yet, but they're not external orders
        original_stealth_order = None
        if self.stealth_order_bridge:
            original_stealth_order = self.stealth_order_bridge.stealth_manager.find_stealth_order_by_placed_order_id(
                client_order_id
            )

        # If this is a stealth-revealed order, register the placement uuid under the
        # stealth chain's root (flat hierarchy â€” see agent.md). No-op when the
        # placement uuid equals stealth_order_id (same logical order).
        if original_stealth_order:
            self._register_stealth_placement_under_root(client_order_id, original_stealth_order)
            policy_cancelled = self.stealth_order_bridge.stealth_manager.is_policy_cancelled_placement(
                original_stealth_order,
                client_order_id,
            )
            if policy_cancelled is True:
                self.log_message(
                    "order",
                    {
                        "event": "cancel_reentry_policy_cancel_confirmed",
                        "client_order_id": client_order_id,
                        "stealth_order_id": original_stealth_order.get("stealth_order_id"),
                    },
                )
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

        # Check if this is an external order (not created by our engine)
        # External orders are ones we didn't place, so we shouldn't create follow-ups
        is_external_order = self._is_external_order(client_order_id)

        # For external orders, just track them but don't create follow-ups
        if is_external_order:
            self._handle_external_order_tracking(
                client_order_id,
                order,
                "cancelled",
                processed_flag_name="cancelled",
            )
            return

        with self.orderbook_lock:
            should_replace_cancelled = self.orderbook.should_replace["CANCELLED"] is True

        if not should_replace_cancelled:
            self.release_follow_up_processing("cancelled", client_order_id)
            return

        _, parent_client_order_id = self.resolve_parent_client_order_id(client_order_id)

        # Check for pending move (automation) - executes instead of normal follow-up
        from database.order import has_pending_move
        if has_pending_move(parent_client_order_id):
            try:
                from business.move_manager import MoveManager
                move_manager = MoveManager(self.orderbook)
                move_result = move_manager.execute_pending_move_for_order(parent_client_order_id)
                
                if move_result["success"]:
                    self.log_message(
                        "order",
                        {
                            "event": "pending_move_auto_executed",
                            "original_parent_client_order_id": parent_client_order_id,
                            "new_parent_client_order_id": move_result["new_parent_client_order_id"],
                            "trigger": "cancelled_order"
                        }
                    )
                    # Successfully handled via pending move, don't do normal follow-up
                    self.complete_follow_up_processing("cancelled", client_order_id)
                    return
                else:
                    self.log_message(
                        "warning",
                        {
                            "event": "pending_move_execution_failed",
                            "original_parent_client_order_id": parent_client_order_id,
                            "error": move_result.get("error"),
                            "message": move_result.get("message")
                        }
                    )
                    # IMPORTANT: Don't fall through to normal follow-up
                    # If a pending move failed, don't create a child order as fallback
                    # Complete the processing to mark as handled
                    self.complete_follow_up_processing("cancelled", client_order_id)
                    return
            except Exception as e:
                self.log_message(
                    "error",
                    {
                        "event": "pending_move_execution_exception",
                        "original_parent_client_order_id": parent_client_order_id,
                        "error": str(e)
                    }
                )
                # IMPORTANT: Don't fall through to normal follow-up
                # If a pending move exception occurs, don't create a child order as fallback
                # Complete the processing to mark as handled
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

        try:
            order_template = self.compute_order_template(client_order_id)
            if not order_template:
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_template_compute_failed",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details={"reason": "cancelled_order_follow_up_template_compute_failed"},
                    ),
                )
                self.release_follow_up_processing("cancelled", client_order_id)
                return

            if self.child_order_already_exists(parent_client_order_id, order_template):
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_duplicate_child_skipped",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order={
                            "product_id": order_template["product_id"],
                            "side": order_template["side"],
                            "price": float(order_template["start_price"]),
                        },
                    ),
                )
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

            # All orders are stealth orders - create stealth follow-up on cancel
            try:
                # Update the original stealth order status to CANCELLED
                if original_stealth_order:
                    self.stealth_order_bridge.stealth_manager.update_execution(
                        stealth_order_id=original_stealth_order["stealth_order_id"],
                        executed_size=0.0,
                        order_status=StealthOrderStatus.CANCELLED.value
                    )
                
                follow_up_price = float(order_template["start_price"])
                
                # Build reveal condition for the follow-up (use same as filled orders)
                reveal_condition = {
                    "type": "time_delay",
                    "delay_seconds": 0  # Immediate reveal on cancel follow-up
                }
                
                # Get target_movement from parent order (source of truth)
                from database.order import get_parent_order
                try:
                    if getattr(self, "db_module", None) and hasattr(self.db_module, "get_parent_order"):
                        parent_order_data = self.db_module.get_parent_order(parent_client_order_id)
                    else:
                        parent_order_data = get_parent_order(parent_client_order_id)
                except Exception as lookup_exc:
                    self.log_message(
                        "warning",
                        {
                            "event": "cancel_follow_up_parent_lookup_failed",
                            "parent_client_order_id": parent_client_order_id,
                            "error": str(lookup_exc),
                        },
                    )
                    parent_order_data = None
                parent_target_movement = parent_order_data.get("target_movement") if parent_order_data else None
                parent_target_movement_type = parent_order_data.get("target_movement_type", TargetMovementType.PERCENTAGE.value) if parent_order_data else TargetMovementType.PERCENTAGE.value
                
                # Pure-cancel of a non-stealth-tracked placement should not
                # land here under current flow (all orders are stealth).
                # Fail closed rather than feed `None` into the lookup, which
                # would silently return None below and burn a replacement
                # slot on a phantom child (see incident 2026-05-04).
                if not original_stealth_order:
                    self.log_message(
                        "warning",
                        self.build_follow_up_log_payload(
                            "stealth_follow_up_skipped_no_stealth_record",
                            source_order=order,
                            parent_client_order_id=parent_client_order_id,
                            details={"reason": "no_stealth_order_for_cancelled_placement"},
                        ),
                    )
                    self.complete_follow_up_processing("cancelled", client_order_id)
                    return

                stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(
                    original_stealth_order_id=original_stealth_order["stealth_order_id"],
                    side=order_template["side"],
                    total_size=order_template["order_base_size"],
                    limit_price=follow_up_price,
                    reveal_condition=reveal_condition,
                    follow_up_reveal_direction="same",
                    reveal_pricing_policy=None,  # Inherit from original
                    notes=f"Auto follow-up from cancelled order",
                    target_movement=parent_target_movement,
                    target_movement_type=parent_target_movement_type
                )

                # Defensive: if the follow-up creator returned None the
                # follow-up was NOT persisted. Do NOT register a phantom
                # child (would burn a replacement slot on `None` and
                # strand exposure). Release the processing flag so a
                # later retry path stays open.
                if stealth_follow_up_id is None:
                    self.log_message(
                        "error",
                        {
                            "event": "stealth_follow_up_creation_returned_none_on_cancel",
                            "parent_id": parent_client_order_id,
                            "client_order_id": client_order_id,
                            "original_stealth_order_id": original_stealth_order["stealth_order_id"],
                        },
                    )
                    self.release_follow_up_processing("cancelled", client_order_id)
                    return

                # Register stealth follow-up as child of the chain ROOT.
                # Single canonical resolver â€” see resolve_stealth_chain_root.
                root_parent_client_order_id = resolve_stealth_chain_root(original_stealth_order)
                self.register_child_order(stealth_follow_up_id, root_parent_client_order_id)

                self.log_message(
                    "order",
                    {
                        "event": "stealth_follow_up_created_on_cancel",
                        "stealth_follow_up_id": stealth_follow_up_id,
                        "parent_id": parent_client_order_id,
                        "product_id": order_template["product_id"],
                        "side": order_template["side"],
                    }
                )

                self.complete_follow_up_processing("cancelled", client_order_id)
                return
            except Exception as e:
                self.log_message(
                    "error",
                    {
                        "event": "stealth_follow_up_creation_failed_on_cancel",
                        "error": str(e),
                        "parent_id": parent_client_order_id,
                        "client_order_id": client_order_id
                    }
                )
                # All orders are stealth orders - no fallback to regular orders
                self.complete_follow_up_processing("cancelled", client_order_id)
                return

        except Exception:
            self.release_follow_up_processing("cancelled", client_order_id)
            raise

    def move_cancelled_order(
        self,
        original_parent_client_order_id: str,
        new_order_details: dict,
        reason: str = "cancelled_move",
        notes: str = None
    ) -> dict:
        """Move a cancelled parent order to a new parent order.
        
        Instead of creating a child order, this replaces the parent/child relationship
        by creating a completely new parent order. The original parent remains in the
        database for audit purposes, and the move is recorded in order_moves table.
        
        Args:
            original_parent_client_order_id: The client_order_id of the parent to move.
            new_order_details: Dict with new parent configuration (product_id, side, size,
                             price, target_movement, target_movement_type, max_order_replacement).
            reason: Reason for the move (default 'cancelled_move').
            notes: Optional additional context.
        
        Returns:
            Dict with move result:
            {
                "success": bool,
                "message": str,
                "new_parent_client_order_id": str or None,
                "error": str or None
            }
            
        Example:
            >>> result = engine.move_cancelled_order(
            ...     original_parent_client_order_id="old_parent_uuid",
            ...     new_order_details={
            ...         "product_id": "BTC-USDC",
            ...         "side": "BUY",
            ...         "size": 1.0,
            ...         "price": 42500.0,
            ...         "target_movement": 0.005
            ...     },
            ...     reason="user_cancelled_and_moved"
            ... )
        """
        from business.move_manager import MoveManager
        
        try:
            move_manager = MoveManager(self.orderbook)
            result = move_manager.move_order(
                original_parent_client_order_id=original_parent_client_order_id,
                new_order_details=new_order_details,
                reason=reason,
                notes=notes
            )
            
            if result["success"]:
                self.log_message(
                    "order",
                    {
                        "event": "order_moved",
                        "original_parent_client_order_id": original_parent_client_order_id,
                        "new_parent_client_order_id": result["new_parent_client_order_id"],
                        "move_id": result["move_id"],
                        "reason": reason,
                        "product_id": new_order_details.get("product_id"),
                        "side": new_order_details.get("side"),
                        "price": new_order_details.get("price"),
                        "notes": notes
                    }
                )
            else:
                self.log_message(
                    "warning",
                    {
                        "event": "order_move_failed",
                        "original_parent_client_order_id": original_parent_client_order_id,
                        "reason": reason,
                        "error": result.get("error"),
                        "message": result.get("message")
                    }
                )
            
            return result
            
        except Exception as e:
            error_msg = f"Exception during order move: {str(e)}"
            self.log_message(
                "error",
                {
                    "event": "order_move_exception",
                    "original_parent_client_order_id": original_parent_client_order_id,
                    "error": error_msg
                }
            )
            return {
                "success": False,
                "message": error_msg,
                "new_parent_client_order_id": None,
                "error": error_msg
            }

    def _register_default_fill_hook(self) -> None:
        """Register the default post-fill hook for recording fills to ledger.
        
        This hook is called after a fill is recorded and logs the fill event.
        It's registered as a non-blocking post-fill hook.
        
        Returns:
            None
        """
        def default_post_fill_hook(fill_data: dict, trade_id: str) -> None:
            """Default post-fill hook: log the recorded fill."""
            try:
                self.log_message(
                    "info",
                    f"[LOT-TRACK] Fill hook recorded: {trade_id} {fill_data.get('side')} {fill_data.get('quantity')} {fill_data.get('instrument')} @ {fill_data.get('price')}, fees={fill_data.get('fees')}, client_order={fill_data.get('client_order_id')}"
                )
            except Exception as e:
                # Log but don't fail - this is non-blocking
                self.log_message("warning", f"[LOT-TRACK] Failed to log fill: {e}")
        
        if self.fill_event_hooks:
            self.fill_event_hooks.register_post_fill(default_post_fill_hook)

    def handle_filled_order(self, order: dict) -> None:
        """Handle a filled order by creating a follow-up if allowed.
        
        NOTE: External orders (created in Coinbase UI, not by our engine) are
        tracked for record-keeping but do NOT trigger follow-up orders.
        
        Args:
            order: Filled order dict.
        
        Returns:
            None
        """
        client_order_id = order["client_order_id"]

        # CRITICAL: Claim follow-up processing FIRST to prevent race conditions
        # Must happen BEFORE any other processing (including registration, fill recording) 
        # to ensure atomicity and prevent duplicate follow-up creation in concurrent scenarios
        #
        # Note: We claim BEFORE fill recording (even though fill recording is idempotent
        # via trade_id constraint), because we want to prevent concurrent threads from both
        # creating follow-ups while fill recording can safely happen multiple times
        if not self.claim_follow_up_processing("filled", client_order_id):
            self.log_message(
                "warning",
                self.build_follow_up_log_payload(
                    "follow_up_already_claimed",
                    source_order=order,
                    parent_client_order_id=None,
                    details={"reason": "filled_order_follow_up_already_claimed"},
                ),
            )
            return

        # CRITICAL: Check for stealth order BEFORE marking as external
        # Stealth-revealed slices won't be in orderbook yet, but they're not external orders
        original_stealth_order = None
        if self.stealth_order_bridge:
            original_stealth_order = self.stealth_order_bridge.stealth_manager.find_stealth_order_by_placed_order_id(
                client_order_id
            )

        # If this is a stealth-revealed order, register the placement uuid under the
        # stealth chain's root (flat hierarchy â€” see agent.md). No-op when the
        # placement uuid equals stealth_order_id (same logical order).
        if original_stealth_order:
            self._register_stealth_placement_under_root(client_order_id, original_stealth_order)

        # Check if this is an external order (not created by our engine)
        # External orders are ones we didn't place, so we shouldn't create follow-ups
        is_external_order = self._is_external_order(client_order_id)

        # NOTE: Per-match fill recording happens in process_user_order via
        # _process_ws_order_delta, which derives one ledger row per real exchange
        # match from cumulative-counter deltas. Do NOT add bulk single-row recording
        # here â€” that collapsed N matches into 1 and corrupted lot accounting.

        with self.orderbook_lock:
            should_replace_filled = self.orderbook.should_replace["FILLED"] is True

        if not should_replace_filled:
            return

        # âœ… FIX: For stealth-revealed orders, get target_movement from the stealth order's entry
        stealth_target_movement = None
        if original_stealth_order:
            # The stealth order's target_movement is stored in order_parent with client_order_id=stealth_order_id
            parent_order_data = self.db_module.get_parent_order(
                original_stealth_order["stealth_order_id"]
            )
            if parent_order_data:
                # âœ… Use safe_float to handle Decimal type from database (imported at module level)
                target_mv = safe_float(parent_order_data.get("target_movement"))
                stealth_target_movement = {
                    "target_movement": target_mv if target_mv > 0 else None,
                    "target_movement_type": parent_order_data.get("target_movement_type", "P")
                }

            self._seed_parent_order_cache_from_db(client_order_id)

        # Resolve allow_partial_fills for parent creation:
        # 1. Check in-memory cache (populated by startup rebuild or prior seeding)
        # 2. Fall back to False
        _cached_parent = self.orderbook.parent_order_ids.get(client_order_id, {})
        _allow_partial_fills = bool(_cached_parent.get("allow_partial_fills", False))

        _, parent_client_order_id = self.resolve_parent_client_order_id(
            client_order_id,
            order=order,
            create_parent=True,
            status=OrderStatus.FILLED.value,
            stealth_order=stealth_target_movement,
            allow_partial_fills=_allow_partial_fills,
        )
        
        # ðŸ”§ CRITICAL FIX: If a new parent was created (order became its own parent),
        # but this stealth order has an explicit parent_order_id, use that instead.
        # This ensures stealth follow-ups use the correct parent's replacement count.
        if original_stealth_order and parent_client_order_id == client_order_id:
            explicit_parent = original_stealth_order.get("parent_order_id")
            if explicit_parent and explicit_parent != client_order_id:
                parent_client_order_id = explicit_parent
                # NOTE: Child registration already happened at line 2528, so don't call again here
                # Calling twice would cause duplicate replacement count increments

        # For external orders, just track them but don't create follow-ups
        # EXCEPT: Stealth-revealed orders should create follow-ups (Child stealth orders)
        if is_external_order and not original_stealth_order:
            self._handle_external_order_tracking(
                client_order_id,
                order,
                "filled",
                processed_flag_name=None,  # Don't complete processing for filled orders
            )
            return

        # Handle stealth order fills - create a Child stealth order as follow-up
        # NOTE: This is handled in the later stealth order code path (around line 1663)
        # After normal follow-up processing claims the order. Kept here for reference only.

        # Note: We already claimed processing at the start of handle_filled_order
        # No need to claim again here
        
        try:
            # Post-fill profit-taking follow-up bypasses ``max_order_replacement``.
            # The cap is meant to gate pre-fill cancel/reprice (anchor track) cycles,
            # not the closing leg that completes the round-trip after a fill.
            # Conflating the two strands the operator with un-hedged exposure when
            # earlier reprices have already exhausted the slot (incident 2026-05-04,
            # parent 514563cc-607b-446f-b92f-c3714594fc44). See
            # /memories/budget-vs-completion-cap.md and the partial-fill bypass
            # precedent in _create_partial_fill_follow_up.
            can_replace, replacement_details = self.can_create_follow_up_order(parent_client_order_id)
            if not can_replace:
                self.log_message(
                    "order",
                    self.build_follow_up_log_payload(
                        "follow_up_replacement_cap_bypassed_post_fill",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details={
                            **replacement_details,
                            "reason": "post_fill_profit_taking_bypasses_cap",
                        },
                    ),
                )

            target_movement = self.resolve_parent_target_movement(parent_client_order_id)
            order_template = self.compute_order_template(
                client_order_id,
                target_movement=target_movement,
            )
            if not order_template:
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_template_compute_failed",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details={"reason": "filled_order_follow_up_template_compute_failed"},
                    ),
                )
                self.release_follow_up_processing("filled", client_order_id)
                return

            if self.child_order_already_exists(parent_client_order_id, order_template):
                self.log_message(
                    "warning",
                    self.build_follow_up_log_payload(
                        "follow_up_duplicate_child_skipped",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        attempted_new_order={
                            "product_id": order_template["product_id"],
                            "side": order_template["side"],
                            "price": float(order_template["start_price"]),
                        },
                        details=replacement_details,
                    ),
                )
                self.complete_follow_up_processing("filled", client_order_id)
                return

            proposed_follow_up_size = safe_float(order_template.get("order_base_size"), default=0.0)
            adjusted_follow_up_size, partial_adjustment_details = self._resolve_filled_follow_up_size_after_partials(
                client_order_id=client_order_id,
                proposed_follow_up_size=proposed_follow_up_size,
            )

            if partial_adjustment_details:
                self.log_message(
                    "order",
                    self.build_event_log_payload(
                        "filled_follow_up_size_adjusted_by_partial_progress",
                        client_order_id=client_order_id,
                        parent_client_order_id=parent_client_order_id,
                        **partial_adjustment_details,
                    ),
                )

            if adjusted_follow_up_size <= 0.0:
                self.log_message(
                    "order",
                    self.build_follow_up_log_payload(
                        "follow_up_skipped_already_covered_by_partial_follow_ups",
                        source_order=order,
                        parent_client_order_id=parent_client_order_id,
                        details=partial_adjustment_details or {
                            "reason": "adjusted_follow_up_size_non_positive",
                            "proposed_follow_up_size": proposed_follow_up_size,
                        },
                    ),
                )
                self.complete_follow_up_processing("filled", client_order_id)
                return

            order_template["order_base_size"] = adjusted_follow_up_size

            # Use the stealth order already found at the start of this function
            # If this is a stealth order follow-up, create a stealth order instead of a regular order
            if original_stealth_order:
                try:
                    # Check profitability BEFORE creating follow-up order
                    filled_price = float(order.get("price", order.get("avg_price", 0)))
                    follow_up_price = float(order_template["start_price"])
                    # âœ… FIX: Use helper to resolve order_side (checks "order_side" then "side")
                    order_side = resolve_order_side(order) or "BUY"
                    order_size = float(order_template["order_base_size"])
                    product_id = order.get("product_id")
                    try:
                        self.stealth_order_bridge.stealth_manager.apply_same_side_post_fill_retreat(
                            original_stealth_order,
                            filled_placement_client_order_id=client_order_id,
                            filled_price=filled_price,
                        )
                    except Exception as retreat_error:
                        self.log_message(
                            "warning",
                            {
                                "event": "same_side_post_fill_retreat_failed",
                                "client_order_id": client_order_id,
                                "stealth_order_id": original_stealth_order.get("stealth_order_id"),
                                "error": str(retreat_error),
                            },
                        )

                    # Debug: Log what we're about to validate (product context auto-resolved by validator)
                    self.log_message(
                        "info",
                        {
                            "event": "profitability_check_debug",
                            "filled_price": filled_price,
                            "follow_up_price": follow_up_price,
                            "parent_side": order_side,
                            "product_id": product_id,
                        }
                    )
                    
                    # Validate profitability â€” validator auto-resolves product_type,
                    # contract_size, and position_side from product_id via injected orderbook.
                    if self.profit_validator:
                        # Derive post_only from the parent stealth order's reveal
                        # pricing policy via the canonical helper. TOP_OF_BOOK /
                        # MIDPOINT follow-ups rest as makers; without this the
                        # check uses taker rate and over-rejects profitable
                        # follow-ups (the production ROI killer on TOP_OF_BOOK).
                        try:
                            will_be_post_only = (
                                self.stealth_order_bridge.stealth_manager
                                ._resolve_post_only_from_policy(
                                    reveal_pricing_policy=original_stealth_order.get(
                                        "reveal_pricing_policy"
                                    ),
                                    reveal_condition=original_stealth_order.get(
                                        "reveal_condition_json"
                                    ),
                                )
                            )
                        except Exception:
                            will_be_post_only = False

                        profit_result = self.profit_validator.is_profitable(
                            filled_price=filled_price,
                            follow_up_price=follow_up_price,
                            side=order_side,
                            order_size=order_size,
                            product_id=product_id,
                            triggered_by_fill=True,
                            post_only=will_be_post_only,
                        )
                        
                        if not profit_result["is_profitable"]:
                            self.log_message(
                                "warning",
                                {
                                    "event": "follow_up_order_skipped_unprofitable",
                                    "parent_client_order_id": parent_client_order_id,
                                    "product_id": product_id,
                                    "filled_price": filled_price,
                                    "follow_up_price": follow_up_price,
                                    "gross_profit": profit_result.get("gross_profit", 0),
                                    "total_fees": profit_result.get("total_fees", 0),
                                    "net_profit": profit_result.get("net_profit", 0),
                                }
                            )
                            self.complete_follow_up_processing("filled", client_order_id)
                            return
                    
                    # Update the original stealth order status to EXECUTED
                    filled_size = float(order.get("filled_size", order_template["order_base_size"]))
                    self.stealth_order_bridge.stealth_manager.update_execution(
                        stealth_order_id=original_stealth_order["stealth_order_id"],
                        executed_size=filled_size,
                        order_status=StealthOrderStatus.EXECUTED.value
                    )
                    
                    # This is a stealth order fill - create a stealth follow-up instead of a regular order
                    follow_up_price = float(order_template["start_price"])
                    
                    # Seed the market cache with the fill price
                    product_id = order["product_id"]
                    fill_price = float(order.get("price", follow_up_price))
                    
                    self.stealth_order_bridge.stealth_manager._market_cache[product_id] = {
                        "product_id": product_id,
                        "price": fill_price,
                        "bid": fill_price,
                        "ask": fill_price,
                        "volume_1m": 0,
                        "time": get_local_now(),
                        "source": "synthetic_follow_up_seed",
                    }
                    
                    # Build the reveal condition for the follow-up using configurable direction
                    follow_up_reveal_condition = dict(original_stealth_order.get("reveal_condition_json", {}))
                    direction_choice = original_stealth_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value)
                    
                    if follow_up_reveal_condition.get("type") == "price":
                        # Set threshold to the ACTUAL price where we plan to place the new order
                        # Use float conversion to ensure numeric precision
                        follow_up_reveal_condition["price_threshold"] = float(follow_up_price)
                        
                        if direction_choice == FollowUpRevealDirection.OPPOSITE.value:
                            # Flip direction (below â†’ above, above â†’ below)
                            if "direction" in follow_up_reveal_condition:
                                follow_up_reveal_condition["direction"] = Direction.ABOVE.value if follow_up_reveal_condition.get("direction") == Direction.BELOW.value else Direction.BELOW.value
                        elif direction_choice == FollowUpRevealDirection.SAME.value:
                            # Keep original direction unchanged
                            pass
                        # else: Unknown direction choice, keep original
                    
                    # Use parent order's target_movement (source of truth)
                    from database.order import get_parent_order
                    parent_order_data = get_parent_order(parent_client_order_id)
                    parent_target_movement = parent_order_data.get("target_movement") if parent_order_data else None
                    parent_target_movement_type = parent_order_data.get("target_movement_type", TargetMovementType.PERCENTAGE.value) if parent_order_data else TargetMovementType.PERCENTAGE.value
                    
                    # Debug: Log the exact reveal condition being set
                    self.log_message(
                        "info",
                        {
                            "event": "stealth_follow_up_condition_set",
                            "follow_up_price": follow_up_price,
                            "fill_price": fill_price,
                            "threshold": follow_up_reveal_condition.get("price_threshold"),
                            "direction": follow_up_reveal_condition.get("direction"),
                            "hold_duration_seconds": follow_up_reveal_condition.get("hold_duration_seconds"),
                            "market_cache_price": self.stealth_order_bridge.stealth_manager._market_cache.get(product_id, {}).get("price"),
                        }
                    )
                    
                    stealth_follow_up_id = self.stealth_order_bridge.stealth_manager.create_follow_up_stealth_order(
                        original_stealth_order_id=original_stealth_order["stealth_order_id"],
                        side=order_template["side"],
                        total_size=adjusted_follow_up_size,
                        limit_price=follow_up_price,
                        reveal_condition=follow_up_reveal_condition,
                        follow_up_reveal_direction=direction_choice,
                        reveal_pricing_policy=None,  # Inherit from original
                        notes=f"Auto follow-up from stealth order reveal",
                        target_movement=parent_target_movement,
                        target_movement_type=parent_target_movement_type
                    )
                    
                    # Register stealth follow-up as child of the chain ROOT.
                    # Single canonical resolver â€” see resolve_stealth_chain_root.
                    # bypass_replacement_cap=True: matches the gate-bypass above.
                    # The post-fill closing leg must not consume a replacement slot,
                    # otherwise pre-fill anchor reprices can starve it (incident
                    # 2026-05-04). See /memories/budget-vs-completion-cap.md.
                    root_parent_client_order_id = resolve_stealth_chain_root(original_stealth_order)
                    self.register_child_order(
                        stealth_follow_up_id,
                        root_parent_client_order_id,
                        bypass_replacement_cap=True,
                    )
                    
                    self.log_message(
                        "order",
                        {
                            "event": "stealth_follow_up_created",
                            "stealth_follow_up_id": stealth_follow_up_id,
                            "parent_stealth_id": original_stealth_order["stealth_order_id"],
                            "parent_target_movement": {
                                "movement": parent_target_movement,
                                "type": parent_target_movement_type
                            } if parent_target_movement else None,
                            "product_id": product_id,
                            "side": order_template["side"],
                            "follow_up_size": adjusted_follow_up_size,
                            "reveal_condition": follow_up_reveal_condition,
                            "follow_up_reveal_direction": direction_choice,
                        }
                    )
                    
                    self.complete_follow_up_processing("filled", client_order_id)
                    return
                except Exception as e:
                    self.log_message(
                        "error",
                        {
                            "event": "stealth_follow_up_creation_failed",
                            "error": str(e),
                            "original_stealth_order_id": original_stealth_order.get("stealth_order_id"),
                            "client_order_id": client_order_id
                        }
                    )
                    # All orders are stealth orders - no fallback to regular orders
                    self.complete_follow_up_processing("filled", client_order_id)
                    return

        except Exception:
            self.release_follow_up_processing("filled", client_order_id)
            raise

    def build_parent_child_order_ids_snapshot(self) -> tuple:
        """Query database and build parent/child order mapping snapshot.
        
        Since all orders are stealth orders, all children are stealth children
        stored in the stealth_orders table with parent_order_id set.
        
        Returns:
            Tuple (parent_order_ids_dict, child_order_ids_dict).
        """
        from database.order import get_stealth_children_for_parent
        
        parent_order_ids = {}
        child_order_ids = {}

        parent_orders = self.db_module.get_parent_orders()

        for parent in parent_orders:
            parent_client_order_id = parent["client_order_id"]

            parent_order_ids[parent_client_order_id] = {
                "parent_id": parent["id"],
                "orders": [],
                "target_movement": {
                    "movement": float(parent["target_movement"]),
                    "type": parent.get("target_movement_type", TargetMovementType.PERCENTAGE.value),
                },
                "max_order_replacement": int(parent["max_order_replacement"]),
                "current_order_replacement": int(parent["current_order_replacement"]),
                "allow_partial_fills": bool(parent.get("allow_partial_fills", False)),
            }

            # All children are stealth children (stored in stealth_orders table)
            # ``stealth_orders.parent_order_id`` is UUID-typed. Old polluted
            # ``order_parent`` rows from pre-guard tests may contain values
            # like ``test_order_6``; querying with those would abort the whole
            # reconcile pass with InvalidTextRepresentation.
            if not self._is_uuid_like(parent_client_order_id):
                self.log_message(
                    "error",
                    self.build_event_log_payload(
                        "parent_child_snapshot_skipped_non_uuid_parent",
                        client_order_id=parent_client_order_id,
                    ),
                )
                continue

            stealth_children = get_stealth_children_for_parent(parent_client_order_id)
            for stealth_child in stealth_children:
                stealth_child_id = stealth_child["client_order_id"]  # This is stealth_order_id
                parent_order_ids[parent_client_order_id]["orders"].append(stealth_child_id)
                child_order_ids[stealth_child_id] = parent_client_order_id

        return parent_order_ids, child_order_ids

    def adopt_child_to_new_parent(
        self,
        child_client_order_id: str,
        new_parent_client_order_id: str,
        keep_adoption_history: bool = True
    ) -> bool:
        """
        Reassign a child order to a new parent order (adoption).
        
        Updates both in-memory orderbook structures and the database to reflect
        the new parent-child relationship. Optionally tracks the original parent
        for audit history.
        
        This is useful for strategies like:
        - Migrating orders to a new parent due to market conditions
        - Consolidating children from multiple parents to a single parent
        - Orphaning a child and making it the parent of other orders
        
        Args:
            child_client_order_id: The UUID of the child order to adopt.
            new_parent_client_order_id: The UUID of the new parent order.
            keep_adoption_history: If True, stores the old parent in the database
                                   for audit trail. If False, old parent link is lost.
        
        Returns:
            True if adoption was successful, False otherwise.
        
        Raises:
            None - errors are logged and False is returned.
        
        Examples:
            >>> # Adopt child to new parent, keeping history
            >>> result = engine.adopt_child_to_new_parent(
            ...     child_client_order_id="child-uuid-123",
            ...     new_parent_client_order_id="parent-uuid-456",
            ...     keep_adoption_history=True
            ... )
            >>> if result:
            ...     print("Adoption successful")
            
            >>> # Adopt without tracking history
            >>> result = engine.adopt_child_to_new_parent(
            ...     child_client_order_id="child-uuid-123",
            ...     new_parent_client_order_id="parent-uuid-456",
            ...     keep_adoption_history=False
            ... )
        
        Notes:
            - Both child and new parent must exist in the system
            - Validates existence before attempting adoption
            - Updates in-memory orderbook atomically with orderbook_lock
            - Persists changes to database immediately
            - Logs adoption event for audit trail
        """
        # First update database
        success = self.db_module.adopt_child_to_parent(
            child_client_order_id=child_client_order_id,
            new_parent_client_order_id=new_parent_client_order_id,
            keep_adoption_history=keep_adoption_history,
        )
        
        if not success:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "adopt_child_database_failed",
                    child_client_order_id=child_client_order_id,
                    new_parent_client_order_id=new_parent_client_order_id,
                ),
            )
            return False
        
        # Then update in-memory structures atomically
        with self.orderbook_lock:
            old_parent = self._get_parent_of_child_unlocked(child_client_order_id)
            
            # Remove from old parent's children list
            if old_parent and self._is_parent_order_unlocked(old_parent):
                children_list = self.orderbook.parent_order_ids[old_parent].get("orders", [])
                if child_client_order_id in children_list:
                    children_list.remove(child_client_order_id)
            
            # Update mapping to new parent
            self.orderbook.child_order_ids[child_client_order_id] = new_parent_client_order_id
            
            # Add to new parent's children list
            if new_parent_client_order_id in self.orderbook.parent_order_ids:
                children_list = self.orderbook.parent_order_ids[new_parent_client_order_id].get("orders", [])
                if child_client_order_id not in children_list:
                    children_list.append(child_client_order_id)
        
        # Log the adoption
        self.log_message(
            "order",
            self.build_event_log_payload(
                "child_order_adopted",
                child_client_order_id=child_client_order_id,
                old_parent_client_order_id=old_parent,
                new_parent_client_order_id=new_parent_client_order_id,
                kept_history=keep_adoption_history,
            ),
        )
        
        return True

    # Fields inside ``parent_order_ids[coid]`` whose value is a list whose
    # ORDER IS NOT SEMANTICALLY MEANINGFUL. The two writers — the
    # in-memory ``register_child_order`` path (WS arrival order) and the
    # DB-rehydrated ``build_parent_child_order_ids_snapshot`` path (SQL
    # order) — produce these lists in different orders for the same
    # underlying state. Comparing them as ordered lists produces phantom
    # drift on every reconciler tick. Compare as multisets instead.
    _PARENT_FIELDS_WITH_SET_SEMANTICS = frozenset({"orders"})

    @classmethod
    def _field_values_equivalent(cls, field: str, a: Any, b: Any) -> bool:
        """Compare two field values, treating set-semantics fields as multisets."""
        if (
            field in cls._PARENT_FIELDS_WITH_SET_SEMANTICS
            and isinstance(a, list)
            and isinstance(b, list)
        ):
            return sorted(a) == sorted(b)
        return a == b

    @classmethod
    def _parents_equivalent(cls, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        """Compare two parent dicts, normalizing set-semantics fields."""
        if a.keys() != b.keys():
            return False
        return all(cls._field_values_equivalent(k, a[k], b[k]) for k in a)

    @classmethod
    def _parent_maps_equivalent(
        cls,
        a: Dict[str, Dict[str, Any]],
        b: Dict[str, Dict[str, Any]],
    ) -> bool:
        """Compare two parent_order_ids maps, normalizing set-semantics fields."""
        if a.keys() != b.keys():
            return False
        return all(cls._parents_equivalent(a[k], b[k]) for k in a)

    def _build_reconcile_diff_diagnostic(
        self,
        old_parents: Dict[str, Any],
        new_parents: Dict[str, Any],
        old_children: Dict[str, Any],
        new_children: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Capture a one-shot, throttled diff of reconciler drift.

        Returns ``None`` when the diagnostic is suppressed (recently
        emitted). Otherwise returns a payload describing the FIRST 3
        differing parents (full field diff per parent) plus added/
        removed parent counts and child-mapping deltas. The intent is
        to identify whether persistent drift is field-shape mismatch
        (bootstrap vs DB-rehydrated entries) vs real state advancement.

        Throttle: 1 emit per ~1 hour. Drift seen every reconciler tick
        (~every 30s) would otherwise flood logs.
        """
        import time

        now = time.monotonic()
        if (
            self._reconcile_diff_last_emit_monotonic is not None
            and now - self._reconcile_diff_last_emit_monotonic < 3600.0
        ):
            return None

        old_keys = set(old_parents.keys())
        new_keys = set(new_parents.keys())
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        common = old_keys & new_keys

        # Bootstrap detection: an empty in-memory map being populated for
        # the first time is NOT drift â€” it's expected hydration. Don't
        # burn the throttle on it; we want the throttle to fire on the
        # first REAL drift event (parents_modified > 0 or post-bootstrap
        # additions/removals).
        is_bootstrap = (
            len(old_keys) == 0
            and len(new_keys) > 0
            and len(removed) == 0
        )
        if is_bootstrap:
            return None

        differing: List[Dict[str, Any]] = []
        for coid in sorted(common):
            old_v = old_parents[coid]
            new_v = new_parents[coid]
            if self._parents_equivalent(old_v, new_v):
                continue
            # Build per-field diff (limit to top-level keys; nested
            # dicts compared as opaque values for diagnostic clarity).
            field_diffs: Dict[str, Any] = {}
            all_fields = set(old_v.keys()) | set(new_v.keys())
            for f in sorted(all_fields):
                ov = old_v.get(f, "<MISSING>")
                nv = new_v.get(f, "<MISSING>")
                if self._field_values_equivalent(f, ov, nv):
                    continue
                field_diffs[f] = {
                    "in_memory": repr(ov),
                    "in_memory_type": type(ov).__name__,
                    "from_db": repr(nv),
                    "from_db_type": type(nv).__name__,
                }
            if not field_diffs:
                # All differences were order-only on set-semantics
                # fields; not real drift.
                continue
            differing.append({
                "client_order_id": coid,
                "field_diffs": field_diffs,
            })
            if len(differing) >= 3:
                break

        # Child-mapping delta (just counts; usually less interesting
        # than parent shape mismatch).
        child_added = len(set(new_children.keys()) - set(old_children.keys()))
        child_removed = len(set(old_children.keys()) - set(new_children.keys()))
        child_remapped = sum(
            1 for k, v in new_children.items()
            if k in old_children and old_children[k] != v
        )

        self._reconcile_diff_last_emit_monotonic = now

        return {
            "summary": {
                "parents_added": len(added),
                "parents_removed": len(removed),
                "parents_modified": sum(
                    1 for k in common
                    if not self._parents_equivalent(old_parents[k], new_parents[k])
                ),
                "child_mappings_added": child_added,
                "child_mappings_removed": child_removed,
                "child_mappings_remapped": child_remapped,
            },
            "added_parent_sample": added[:3],
            "removed_parent_sample": removed[:3],
            "differing_parents_sample": differing,
            "throttle": "1_emit_per_hour",
        }

    def load_parent_child_order_ids(self, force_log: bool = False) -> bool:
        """Load parent/child order mappings from database into orderbook.
        
        Args:
            force_log: Whether to log reconciliation event.
        
        Returns:
            True if state changed, False if already in sync.
        """
        if force_log:
            self.log_message(
                "reconcile",
                self.build_event_log_payload("parent_child_reconcile_started"),
            )

        try:
            new_parent_order_ids, new_child_order_ids = self.build_parent_child_order_ids_snapshot()
        except Exception as e:
            self.log_message(
                "error",
                self.build_event_log_payload(
                    "build_parent_child_snapshot_failed",
                    error=str(e),
                ),
            )
            return False

        loaded_parent_count = len(new_parent_order_ids)
        loaded_child_count = len(new_child_order_ids)

        with self.orderbook_lock:
            if all((
                self._parent_maps_equivalent(
                    self.orderbook.parent_order_ids, new_parent_order_ids
                ),
                self.orderbook.child_order_ids == new_child_order_ids,
            )):
                if force_log:
                    self.log_message(
                        "reconcile",
                        self.build_event_log_payload(
                            "parent_child_reconcile_in_sync",
                            parent_count=loaded_parent_count,
                            child_count=loaded_child_count,
                        ),
                    )
                return False

            # Atomic dual-replace via the v2 OrderBook â€” closes the TOCTOU
            # window where the previous code wrote ``parent_order_ids`` and
            # ``child_order_ids`` in two separate statements while another
            # thread could observe the half-replaced state.
            #
            # DIAGNOSTIC (2026-04-30): persistent drift was suspected to be
            # field-shape mismatch between the bootstrap path
            # (``register_child_order``) and the DB-rehydrated snapshot
            # (``build_parent_child_order_ids_snapshot``). Capture a
            # one-shot diff of the first few differing entries so the
            # cause is verifiable from logs rather than inferred. The
            # diagnostic suppresses itself for ~1 hour after each emit.
            diff_payload = self._build_reconcile_diff_diagnostic(
                self.orderbook.parent_order_ids,
                new_parent_order_ids,
                self.orderbook.child_order_ids,
                new_child_order_ids,
            )

            self.orderbook.atomic_replace_links(
                new_parent_order_ids,
                new_child_order_ids,
            )

        if diff_payload is not None:
            self.log_message(
                "reconcile",
                self.build_event_log_payload(
                    "parent_child_reconcile_drift_diagnostic",
                    **diff_payload,
                ),
            )

        # Suppress the per-cycle status line when counts are unchanged
        # (see ``_last_reconciled_counts`` init for rationale). Always
        # emit when the operator forced a log, when this is the first
        # ever emit, or when the drift diagnostic just fired (so the
        # success line provides context for the diagnostic).
        current_counts = (loaded_parent_count, loaded_child_count)
        should_emit_status = (
            force_log
            or diff_payload is not None
            or self._last_reconciled_counts != current_counts
        )
        if should_emit_status:
            self._last_reconciled_counts = current_counts
            self.log_message(
                "reconcile",
                self.build_event_log_payload(
                    "parent_child_reconciled",
                    parent_count=loaded_parent_count,
                    child_count=loaded_child_count,
                ),
            )
        return True

    def reconcile_parent_child_order_ids_periodically(self, interval_seconds: int = 30) -> None:
        """Periodically load parent/child orders from database.
        
        Runs in daemon thread. Loops until ``self._shutdown_event`` is set,
        using ``Event.wait`` for the inter-iteration delay so a shutdown
        request wakes the loop immediately rather than waiting out the full
        ``interval_seconds`` interval.
        
        Args:
            interval_seconds: Sleep duration between syncs (default 30).
        
        Returns:
            None
        """
        while not self._shutdown_event.is_set():
            try:
                self.load_parent_child_order_ids(force_log=False)
            except Exception as e:
                self.log_message(
                    "error",
                    self.build_event_log_payload(
                        "periodic_parent_child_reconcile_error",
                        error=str(e),
                    ),
                )
            if self._shutdown_event.wait(timeout=interval_seconds):
                return

    def rotate_seen_events_buckets(self) -> None:
        """Periodically rotate event deduplication hash buckets using EventBridge.
        
        Runs in daemon thread. Loops until ``self._shutdown_event`` is set,
        using ``Event.wait`` for the rotation interval so shutdown wakes the
        loop immediately.
        
        Returns:
            None
        """
        while not self._shutdown_event.is_set():
            # Use EventBridge to rotate dedup buckets
            self.evt_bridge.rotate_dedup_buckets()
            if self._shutdown_event.wait(timeout=self.max_rotate_seen_events_bucket_seconds):
                return

    def generate_process_event_worker(self, channel: str) -> callable:
        """Generate an event worker function for a specific channel.
        
        Returns a callable that processes events from the channel's queue
        in an infinite loop.
        
        Args:
            channel: Channel name ('ticker', 'user', 'heartbeats').
        
        Returns:
            Callable worker function.
        
        Example:
            >>> worker = engine.generate_process_event_worker('user')
            >>> thread = threading.Thread(target=worker, daemon=True)
            >>> thread.start()
        """
        def worker() -> None:
            while not self._shutdown_event.is_set():
                try:
                    event = self.event_queue[channel].get(
                        timeout=self._worker_queue_poll_seconds,
                    )
                except Empty:
                    # No event within the poll window: re-check the
                    # shutdown flag and continue polling.
                    continue
                try:
                    if channel == ChannelType.TICKER.value:
                        with self.ticker_lock:
                            self.log_message(
                                "ticker",
                                self.build_event_log_payload(
                                    "ticker_event_received",
                                    **self.include_debug_fields(received_event=event),
                                ),
                            )
                            for tickr in event["tickers"]:
                                self.ticker[tickr["product_id"]] = tickr
                                trading_product_id = get_trading_product_id(tickr.get("product_id"))
                                # Broadcast to price chart
                                price = float(tickr.get("price", 0))
                                product_id = tickr.get("product_id")
                                if price > 0 and product_id:
                                    # Pass the upstream Coinbase tick
                                    # ``time`` so dashboard consumers
                                    # can detect hostâ†”CB clock skew
                                    # (engine-host vs Coinbase feed).
                                    broadcast_ticker(
                                        product_id,
                                        price,
                                        cb_time=tickr.get("time"),
                                    )
                                # Record bid/ask for spread monitor
                                best_bid = float(tickr.get("best_bid", 0))
                                best_ask = float(tickr.get("best_ask", 0))
                                if best_bid > 0 and best_ask > 0 and product_id:
                                    record_spread_tick(product_id, best_bid, best_ask)

                                # Persist a downsampled copy for slide-calibration
                                # analytics. Best-effort: throttled to <=1 row/s/product
                                # by the recorder; any DB error is logged inside
                                # record() and never raised.
                                tick_recorder = _get_market_tick_recorder()
                                if tick_recorder is not None and product_id and price > 0:
                                    tick_recorder.record(
                                        product_id=product_id,
                                        price=price,
                                        best_bid=best_bid if best_bid > 0 else None,
                                        best_ask=best_ask if best_ask > 0 else None,
                                    )

                                # Fold into the in-memory Fibonacci-window
                                # tracker consumed by the dashboard / console
                                # UI. Pure in-process; no I/O.
                                if MARKET_METRICS_AVAILABLE and price > 0 and product_id:
                                    metrics_tracker = _get_market_metrics_tracker()
                                    if metrics_tracker is not None:
                                        metrics_tracker.record(
                                            product_id=trading_product_id or product_id,
                                            price=price,
                                        )

                                # Feed market data to stealth order evaluator
                                if self.stealth_order_bridge and product_id:
                                    self.stealth_order_bridge.process_ticker_update(product_id, tickr)

                                # Feed adaptive volume regime in FeeManager.
                                if self.fee_manager and trading_product_id:
                                    self.fee_manager.update_volume_signal(
                                        trading_product_id,
                                        safe_float(tickr.get("volume_24_h"), default=0.0),
                                    )

                    elif channel == ChannelType.USER.value:
                        self.log_message(
                            "user",
                            self.build_event_log_payload(
                                "user_event_received",
                                **self.include_debug_fields(received_event=event),
                            ),
                        )
                        self.event_executor.submit(self.process_user_event, event)

                    elif channel == ChannelType.FUTURES_BALANCE_SUMMARY.value:
                        self.process_futures_balance_summary_event(event)

                finally:
                    self.event_queue[channel].task_done()

        return worker

    def connect_to_websocket(self) -> None:
        """Establish and maintain websocket connection to Coinbase.
        
        Runs in daemon thread, loops forever. Reconnects on disconnect.
        
        Returns:
            None (infinite loop)
        """
        # Create SDK client and wrap with our abstraction
        sdk_client = WSClient(
            verbose=True,
            api_key=self.api_key,
            api_secret=self.api_secret,
            on_open=self.on_open,
            on_message=self.on_message,
        )
        ws_client = CoinbaseWebSocketClient(sdk_client)

        ws_client.connect()
        ws_client.subscribe(
            products=self.subscription.product_ids,
            channels=self.subscription.channels,
        )

        try:
            while not self._shutdown_event.is_set():
                if ws_client.sleep_with_exception_check(1):
                    break
        except WSClientConnectionClosedException as e:
            self.log_message(
                "connection",
                self.build_event_log_payload(
                    "websocket_connection_closed",
                    error=str(e),
                ),
            )

    def start_background_threads(self) -> None:
        """Start all background worker threads.
        
        Initializes parent/child order mappings, then launches:
        - Reconciliation thread
        - Deduplication rotation thread
        - Channel workers (ticker, user, heartbeats)
        - Websocket threads
        - Status monitoring thread
        
        Returns:
            None
        """
        self.load_parent_child_order_ids(force_log=True)
        self._hydrate_order_progress_tracker_from_db()

        # Update dashboard with initial engine status
        update_engine_status(self._build_engine_status_payload(event_queue_depth=0))
        add_log_entry("INFO", "Trading engine started")

        # Initialise the market-tick recorder + retention sweeper. Idempotent;
        # safe to call repeatedly. Tickers won't be persisted until this runs,
        # so it must happen before the channel workers start below.
        if MARKET_TICK_RECORDER_AVAILABLE:
            try:
                _init_market_tick_recorder()
            except Exception as e:
                self.log_message(
                    "warning",
                    f"market_tick recorder failed to initialise: {e}",
                )

        # Hotpoint Auto-Replicate: restart-rebuild the rate-limiter from
        # `order_parent` rows + start the decay sweeper. Both are best-effort;
        # failures degrade the feature, never abort engine startup.
        self._start_hotpoint_background()

        # Decision-support warm-up: replay persisted ticks into the
        # in-memory Fibonacci/standard-window tracker so the longer
        # windows (1d, 7d) have something to show from the first
        # broadcast. Runs in a daemon thread so a slow / large
        # market_tick query never delays engine startup. Safe even
        # before the first live tick because tracker.record() is
        # idempotent and order-tolerant.
        if MARKET_METRICS_AVAILABLE:
            def _warm_load_metrics() -> None:
                try:
                    from business.market_metrics import (
                        warm_load_from_market_tick,
                    )
                    n = warm_load_from_market_tick()
                    if n:
                        self.log_message(
                            "info",
                            f"market_metrics warm-load: replayed {n} rows",
                        )
                except Exception as e:
                    self.log_message(
                        "warning",
                        f"market_metrics warm-load failed: {e}",
                    )

            threading.Thread(
                target=_warm_load_metrics,
                name="market-metrics-warmload",
                daemon=True,
            ).start()

        threading.Thread(
            name="parent_child_reconcile_thread",
            target=self.reconcile_parent_child_order_ids_periodically,
            kwargs={"interval_seconds": 30},
            daemon=True,
        ).start()
        
        # Start status monitoring thread
        threading.Thread(
            name="dashboard_status_monitor",
            target=self._monitor_engine_status,
            daemon=True,
        ).start()

        threading.Thread(
            name="rotate_seen_events_buckets_thread",
            target=self.rotate_seen_events_buckets,
            daemon=True,
        ).start()

        for channel in self.subscription.channels:
            threading.Thread(
                name=f"{channel}_worker",
                target=self.generate_process_event_worker(channel),
                daemon=True,
            ).start()
        
        # Start fee manager (fetches taker fees from Coinbase API, refreshes hourly)
        self.fee_manager.start()

        for websocket in range(self.websocket_thread_maximum):
            threading.Thread(
                name=f"websocket_thread_{websocket}",
                target=self.connect_to_websocket,
                daemon=True,
            ).start()

    def _monitor_engine_status(self) -> None:
        """Monitor and broadcast engine status periodically to dashboard.
        
        Runs in background thread, updates event queue depth every 5 seconds.
        Exits when ``self._shutdown_event`` is set.
        
        Returns:
            None
        """
        while not self._shutdown_event.is_set():
            try:
                # Calculate total events in all queues
                total_queue_depth = sum(q.qsize() for q in self.event_queue.values())
                
                update_engine_status(self._build_engine_status_payload(event_queue_depth=total_queue_depth))
            except Exception as e:
                self.log_message("error", self.build_event_log_payload(
                    "dashboard_status_update_failed",
                    error=str(e),
                ))
            if self._shutdown_event.wait(timeout=5):
                return

    def _build_engine_status_payload(self, event_queue_depth: int) -> dict:
        """Build dashboard engine status payload with adaptive fee regime metrics."""
        payload = {
            "running": True,
            "threads_active": 2 + len(self.subscription.channels) + self.websocket_thread_maximum,
            "event_queue_depth": event_queue_depth,
        }

        if not self.fee_manager:
            return payload

        try:
            fee_info = self.fee_manager.get_fee_info()
            payload.update({
                "taker_fee_rate": fee_info.get("taker_fee_rate"),
                "effective_fee_rate": fee_info.get("profit_validation_fee_rate"),
                "target_movement_factor": fee_info.get("target_movement_factor"),
                "fee_regime_factor": fee_info.get("fee_regime_factor"),
                "volume_ratio": fee_info.get("volume_ratio"),
                "overnight_margin_active": fee_info.get("overnight_margin_active"),
                "margin_window_type": fee_info.get("margin_window_type"),
            })
        except Exception:
            # Keep status updates resilient if fee telemetry is temporarily unavailable.
            pass

        return payload

    def stop(self) -> None:
        """Signal cooperative shutdown to all engine background threads.
        
        Idempotent. Safe to call from a signal handler or from the runtime
        controller's drain orchestrator. Does NOT join threads itself â€” they
        are daemon threads, and joining is not needed because:
        
        - Periodic loops use ``self._shutdown_event.wait`` and return on the
          next iteration boundary (within their poll interval).
        - Event workers use ``Queue.get(timeout=...)`` and re-check the flag
          within ``self._worker_queue_poll_seconds``.
        - The websocket loop checks the flag every second.
        
        Caller should also gate any in-flight work via the runtime controller
        so the drain waits for outstanding fill processing / DB writes before
        the process exits.
        """
        self._shutdown_event.set()
        try:
            self.event_executor.shutdown(wait=False, cancel_futures=False)
        except Exception:
            pass
        try:
            if getattr(self, "fee_manager", None) is not None:
                stop = getattr(self.fee_manager, "stop", None)
                if callable(stop):
                    stop()
        except Exception:
            pass

    def run_forever(self) -> None:
        """Start all background threads and loop until shutdown is signalled.
        
        Call this to launch the trading engine. Blocks until
        ``self._shutdown_event`` is set (typically by ``stop()`` invoked from
        a signal handler or the runtime controller's drain orchestrator).
        
        Returns:
            None
        
        Example:
            >>> engine = OrderEngine(...)
            >>> engine.run_forever()  # Starts all threads, returns on shutdown
        """
        self.start_background_threads()
        # Block on the shutdown event instead of busy-sleeping. Returns
        # promptly when ``stop()`` is called.
        #
        # IMPORTANT: an unbounded ``Event.wait()`` is uninterruptible by
        # SIGINT on Windows (the underlying ``WaitForSingleObject`` call
        # is not waked by a console Ctrl+C), which prevents Python's
        # signal handler from running and makes the process appear
        # deadlocked. Polling with a short timeout lets the interpreter
        # service signals between waits without measurably wasting CPU.
        while not self._shutdown_event.wait(timeout=0.5):
            pass
