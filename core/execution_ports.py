"""Typed outbound capabilities consumed by execution lifecycle owners.

The concrete dashboard and hook registries live outside ``core``.  These
structural protocols let ``main.py`` compose those adapters without making
``OrderEngine`` or ``StealthOrderManager`` import operator/integration modules.
The no-op implementations support isolated tests and unsupported embedded
construction; the canonical runtime always installs the real adapters.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol

from core.enums import OrderStatus, StealthLifecycleEvent


OrderPayload = Dict[str, Any]
OrderCallback = Callable[[OrderPayload], None]
FillCallback = Callable[[OrderPayload, str], None]
PlacementCallback = Callable[[OrderPayload, Any], None]
LifecycleCallback = Callable[
    [str, StealthLifecycleEvent, Dict[str, Any]],
    None,
]


class ExecutionProjectionSink(Protocol):
    """Bounded, synchronous projection capability used by ``OrderEngine``."""

    def publish_order_update(
        self,
        client_order_id: str,
        order_data: Dict[str, Any],
    ) -> None: ...

    def publish_position_update(
        self,
        product_id: str,
        position_data: Dict[str, Any],
    ) -> None: ...

    def publish_engine_status(self, status_data: Dict[str, Any]) -> None: ...

    def publish_log_entry(
        self,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    def publish_ticker(
        self,
        product_id: str,
        price: float,
        price_24h: Optional[float] = None,
        cb_time: Any = None,
    ) -> None: ...

    def record_spread(
        self,
        product_id: str,
        bid: float,
        ask: float,
    ) -> None: ...


class WebSocketHooks(Protocol):
    """Ordered WebSocket normalization and status-observer capability."""

    def register_post_order_status(
        self,
        status: str | OrderStatus,
        callback: OrderCallback,
    ) -> None: ...

    def call_pre_snapshot(self, snapshot: Dict[str, Any]) -> None: ...

    def call_snapshot_normalizers(self, snapshot: Dict[str, Any]) -> None: ...

    def call_post_snapshot(self, snapshot: Dict[str, Any]) -> None: ...

    def call_pre_order_status(
        self,
        status: str | OrderStatus,
        order: OrderPayload,
    ) -> None: ...

    def call_order_normalizers(self, order: OrderPayload) -> None: ...

    def call_post_order_status(
        self,
        status: str | OrderStatus,
        order: OrderPayload,
    ) -> None: ...


class FillEventHooks(Protocol):
    """Ordered pre/post fill-ledger callback capability."""

    def register_post_fill(self, callback: FillCallback) -> None: ...

    def call_pre_fill_hooks(self, fill_data: OrderPayload) -> None: ...

    def call_post_fill_hooks(
        self,
        fill_data: OrderPayload,
        trade_id: str,
    ) -> None: ...


class OrderPlacementHooks(Protocol):
    """Ordered pre/post exchange-submission callback capability."""

    def register_pre_submission(self, callback: OrderCallback) -> None: ...

    def register_post_submission(
        self,
        callback: PlacementCallback,
    ) -> None: ...

    def call_pre_submission_hooks(self, order: OrderPayload) -> None: ...

    def call_post_submission_hooks(
        self,
        order: OrderPayload,
        result: Any,
    ) -> list[Exception]: ...


class StealthLifecycleHooks(Protocol):
    """Best-effort ordered stealth-transition observer capability."""

    def register_on_transition(self, callback: LifecycleCallback) -> None: ...

    def call_on_transition(
        self,
        stealth_order_id: str,
        event: StealthLifecycleEvent,
        context: Dict[str, Any],
    ) -> None: ...


class NoOpExecutionProjectionSink:
    """Discard projections for deliberately headless construction."""

    def publish_order_update(
        self,
        client_order_id: str,
        order_data: Dict[str, Any],
    ) -> None:
        del client_order_id, order_data

    def publish_position_update(
        self,
        product_id: str,
        position_data: Dict[str, Any],
    ) -> None:
        del product_id, position_data

    def publish_engine_status(self, status_data: Dict[str, Any]) -> None:
        del status_data

    def publish_log_entry(
        self,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        del level, message, context

    def publish_ticker(
        self,
        product_id: str,
        price: float,
        price_24h: Optional[float] = None,
        cb_time: Any = None,
    ) -> None:
        del product_id, price, price_24h, cb_time

    def record_spread(
        self,
        product_id: str,
        bid: float,
        ask: float,
    ) -> None:
        del product_id, bid, ask


class NoOpWebSocketHooks:
    """Discard WebSocket hook registration and dispatch."""

    def register_post_order_status(
        self,
        status: str | OrderStatus,
        callback: OrderCallback,
    ) -> None:
        del status, callback

    def call_pre_snapshot(self, snapshot: Dict[str, Any]) -> None:
        del snapshot

    def call_snapshot_normalizers(self, snapshot: Dict[str, Any]) -> None:
        del snapshot

    def call_post_snapshot(self, snapshot: Dict[str, Any]) -> None:
        del snapshot

    def call_pre_order_status(
        self,
        status: str | OrderStatus,
        order: OrderPayload,
    ) -> None:
        del status, order

    def call_order_normalizers(self, order: OrderPayload) -> None:
        del order

    def call_post_order_status(
        self,
        status: str | OrderStatus,
        order: OrderPayload,
    ) -> None:
        del status, order


class NoOpFillEventHooks:
    """Discard fill-hook registration and dispatch."""

    def register_post_fill(self, callback: FillCallback) -> None:
        del callback

    def call_pre_fill_hooks(self, fill_data: OrderPayload) -> None:
        del fill_data

    def call_post_fill_hooks(
        self,
        fill_data: OrderPayload,
        trade_id: str,
    ) -> None:
        del fill_data, trade_id


class NoOpOrderPlacementHooks:
    """Allow placement while discarding extension registration and dispatch."""

    def register_pre_submission(self, callback: OrderCallback) -> None:
        del callback

    def register_post_submission(
        self,
        callback: PlacementCallback,
    ) -> None:
        del callback

    def call_pre_submission_hooks(self, order: OrderPayload) -> None:
        del order

    def call_post_submission_hooks(
        self,
        order: OrderPayload,
        result: Any,
    ) -> list[Exception]:
        del order, result
        return []


class NoOpStealthLifecycleHooks:
    """Discard best-effort lifecycle observer registration and dispatch."""

    def register_on_transition(self, callback: LifecycleCallback) -> None:
        del callback

    def call_on_transition(
        self,
        stealth_order_id: str,
        event: StealthLifecycleEvent,
        context: Dict[str, Any],
    ) -> None:
        del stealth_order_id, event, context


NO_OP_EXECUTION_PROJECTION_SINK = NoOpExecutionProjectionSink()
NO_OP_WEBSOCKET_HOOKS = NoOpWebSocketHooks()
NO_OP_FILL_EVENT_HOOKS = NoOpFillEventHooks()
NO_OP_ORDER_PLACEMENT_HOOKS = NoOpOrderPlacementHooks()
NO_OP_STEALTH_LIFECYCLE_HOOKS = NoOpStealthLifecycleHooks()
