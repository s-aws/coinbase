"""Authenticated Coinbase user-feed sequencing and bounded dispatch.

The processor owns all connection-generation state and per-client-order FIFO
dispatch. Trading lifecycle behavior remains on its host ``OrderEngine`` and
is invoked through the narrow ``UserFeedHost`` protocol.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from queue import Full, Queue
from time import monotonic
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol, Tuple

from core.enums import ChannelType, OrderSide, OrderStatus, UserFeedPhase
from core.exceptions import OrderProcessingError


USER_SNAPSHOT_PAGE_SIZE = 50
USER_BOOTSTRAP_TIMEOUT_SECONDS = 10.0
PRIVATE_CHANNELS = frozenset({
    ChannelType.USER.value,
    ChannelType.FUTURES_BALANCE_SUMMARY.value,
})
LIVE_USER_ORDER_REQUIRED_FIELDS = frozenset({
    "client_order_id",
    "order_id",
    "product_id",
    "status",
    "order_side",
    "cumulative_quantity",
    "leaves_quantity",
    "filled_value",
    "total_fees",
    "number_of_fills",
    "completion_percentage",
})


@dataclass(frozen=True)
class UserStreamEnvelope:
    """One authenticated Coinbase envelope retained through its queue."""

    generation: int
    sequence_num: int
    timestamp: Optional[str]
    events: Tuple[dict, ...]
    channel: str = ChannelType.USER.value


class KeyedSerialDispatcher:
    """Run one FIFO per key while allowing unrelated keys in parallel."""

    def __init__(
        self,
        executor: ThreadPoolExecutor,
        *,
        max_pending: int,
    ) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self._executor = executor
        self._max_pending = max_pending
        self._lock = threading.Lock()
        self._queues: Dict[str, Deque[tuple]] = {}
        self._active_keys = set()
        self._pending_count = 0
        self._closed = False

    def submit(self, key: str, fn: Callable[..., Any], *args, **kwargs) -> Future:
        return self.submit_many(((key, fn, args, kwargs),))[0]

    def submit_many(
        self,
        requests: Tuple[
            Tuple[str, Callable[..., Any], tuple, dict],
            ...,
        ],
    ) -> List[Future]:
        """Atomically admit one validated envelope's lifecycle calls."""

        if not requests:
            return []
        with self._lock:
            if self._closed:
                raise RuntimeError("user order dispatcher is closed")
            if self._pending_count + len(requests) > self._max_pending:
                raise Full("user order dispatcher is full")

            admitted = []
            newly_active_keys = []
            futures = []
            for key, fn, args, kwargs in requests:
                future = Future()
                entry = (future, fn, args, kwargs)
                queue_for_key = self._queues.setdefault(key, deque())
                queue_for_key.append(entry)
                admitted.append((key, entry))
                futures.append(future)
                if key not in self._active_keys:
                    self._active_keys.add(key)
                    newly_active_keys.append(key)
            self._pending_count += len(admitted)

            try:
                for key in newly_active_keys:
                    self._executor.submit(self._drain_key, key)
            except Exception as exc:
                for admitted_key, entry in reversed(admitted):
                    queue_for_key = self._queues[admitted_key]
                    if queue_for_key[-1] is not entry:
                        raise RuntimeError(
                            "user order dispatcher rollback invariant failed"
                        ) from exc
                    queue_for_key.pop()
                    if not queue_for_key:
                        self._queues.pop(admitted_key, None)
                for key in newly_active_keys:
                    self._active_keys.discard(key)
                self._pending_count -= len(admitted)
                raise RuntimeError(
                    "user order dispatcher could not schedule work"
                ) from exc
        return futures

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _drain_key(self, key: str) -> None:
        while True:
            with self._lock:
                queue_for_key = self._queues.get(key)
                if not queue_for_key:
                    self._queues.pop(key, None)
                    self._active_keys.discard(key)
                    return
                future, fn, args, kwargs = queue_for_key.popleft()
            if not future.set_running_or_notify_cancel():
                with self._lock:
                    self._pending_count -= 1
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                with self._lock:
                    self._pending_count -= 1


# Backward-compatible private name imported by older tests and integrations.
_KeyedSerialDispatcher = KeyedSerialDispatcher


class UserFeedHost(Protocol):
    event_queue: Dict[str, Queue]
    websocket_events: Dict[str, dict]

    def _configured_private_channels(self) -> Tuple[str, ...]: ...
    def _private_reducer_queue_channel(self) -> Optional[str]: ...
    def build_event_log_payload(self, event: str, **details) -> dict: ...
    def include_debug_fields(self, **fields) -> dict: ...
    def log_message(self, log_type: str, message) -> None: ...
    def process_futures_balance_summary_event(self, event: dict) -> None: ...
    def process_user_event(self, event: dict, **kwargs) -> None: ...
    def process_user_order(self, order: dict) -> None: ...
    def process_user_snapshot(self, event: dict) -> None: ...


class UserFeedProcessor:
    """Own private-feed generation, reduction, dispatch, and metrics state."""

    def __init__(
        self,
        host: UserFeedHost,
        *,
        executor: Optional[ThreadPoolExecutor] = None,
        max_pending: int = 10_000,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._host = host
        self._clock = clock
        self._user_feed_lock = threading.RLock()
        self._user_reducer_lock = threading.RLock()
        self._user_generation_condition = threading.Condition(
            self._user_feed_lock
        )
        self._user_feed_phase = UserFeedPhase.AWAITING_SNAPSHOT
        self._user_stream_generation = 0
        self._user_last_sequence_num = None
        self._user_last_envelope_payload = None
        self._user_bootstrap_orders: Dict[str, dict] = {}
        self._user_bootstrap_deadline_monotonic = None
        self._user_stream_reconnect_event = None
        self._user_generation_inflight: Dict[int, int] = {}
        self._user_order_dispatcher = (
            KeyedSerialDispatcher(executor, max_pending=max_pending)
            if executor is not None
            else None
        )

    @property
    def dispatcher(self):
        return self._user_order_dispatcher

    @dispatcher.setter
    def dispatcher(self, value) -> None:
        self._user_order_dispatcher = value

    def snapshot_metrics(self) -> dict:
        """Return one coherent, bounded operational snapshot."""

        with self._user_feed_lock:
            generation = self._user_stream_generation
            phase = self._user_feed_phase.value
            bootstrap_orders = len(self._user_bootstrap_orders)
            generation_inflight = sum(self._user_generation_inflight.values())
        dispatcher = self._user_order_dispatcher
        if dispatcher is None:
            pending = queues = active_keys = 0
        else:
            with dispatcher._lock:
                pending = dispatcher._pending_count
                queues = len(dispatcher._queues)
                active_keys = len(dispatcher._active_keys)
        queue_channel = self._host._private_reducer_queue_channel()
        event_queues = getattr(self._host, "event_queue", {})
        queue_depth = (
            event_queues[queue_channel].qsize()
            if queue_channel in event_queues
            else 0
        )
        return {
            "generation": generation,
            "phase": phase,
            "bootstrap_orders": bootstrap_orders,
            "generation_inflight": generation_inflight,
            "queue_depth": queue_depth,
            "dispatcher_pending": pending,
            "dispatcher_queues": queues,
            "dispatcher_active_keys": active_keys,
        }

    def _begin_user_stream_generation(
        self,
        reconnect_event: Optional[threading.Event] = None,
    ) -> int:
        """Reset bootstrap ownership for one newly-opened private connection."""

        with self._user_reducer_lock:
            with self._user_generation_condition:
                previous_generation = self._user_stream_generation
                while self._user_generation_inflight.get(
                    previous_generation,
                    0,
                ):
                    self._user_generation_condition.wait()
                self._user_stream_generation += 1
                generation = self._user_stream_generation
                self._user_feed_phase = UserFeedPhase.AWAITING_SNAPSHOT
                self._user_last_sequence_num = None
                self._user_last_envelope_payload = None
                self._user_bootstrap_orders = {}
                self._user_bootstrap_deadline_monotonic = (
                    self._clock() + USER_BOOTSTRAP_TIMEOUT_SECONDS
                )
                self._user_stream_reconnect_event = reconnect_event
        try:
            self._host.log_message(
                "connection",
                self._host.build_event_log_payload(
                    "user_stream_generation_started",
                    generation=generation,
                ),
            )
        except Exception:
            pass
        return generation

    def _mark_user_stream_desynchronized(
        self,
        *,
        generation: Optional[int],
        reason: str,
        **details,
    ) -> bool:
        """Fail one current generation closed and request a clean reconnect."""

        with self._user_feed_lock:
            if (
                generation is not None
                and generation != self._user_stream_generation
            ):
                return False
            changed = self._user_feed_phase != UserFeedPhase.DESYNCHRONIZED
            self._user_feed_phase = UserFeedPhase.DESYNCHRONIZED
            self._user_bootstrap_orders = {}
            self._user_bootstrap_deadline_monotonic = None
            reconnect_event = self._user_stream_reconnect_event
            if reconnect_event is not None:
                reconnect_event.set()
            active_generation = self._user_stream_generation

        if changed:
            self._host.log_message(
                "error",
                self._host.build_event_log_payload(
                    "user_stream_desynchronized",
                    generation=active_generation,
                    reason=reason,
                    **details,
                ),
            )
        return changed

    def _check_user_bootstrap_timeout(self) -> bool:
        """Reconnect instead of guessing through an unterminated bootstrap."""

        with self._user_feed_lock:
            generation = self._user_stream_generation
            deadline = self._user_bootstrap_deadline_monotonic
            timed_out = (
                self._user_feed_phase
                in (
                    UserFeedPhase.AWAITING_SNAPSHOT,
                    UserFeedPhase.BOOTSTRAPPING,
                )
                and deadline is not None
                and self._clock() >= deadline
            )
            phase = self._user_feed_phase
        if not timed_out:
            return False
        self._mark_user_stream_desynchronized(
            generation=generation,
            reason=(
                "initial_snapshot_timeout"
                if phase == UserFeedPhase.AWAITING_SNAPSHOT
                else "bootstrap_timeout"
            ),
            timeout_seconds=USER_BOOTSTRAP_TIMEOUT_SECONDS,
        )
        return True

    def on_user_message(self, msg: str, *, generation: int) -> None:
        """Validate and enqueue one complete private Coinbase envelope.

        Unlike public market ingress, private message identity is the
        connection generation plus Coinbase's connection-global sequence.
        Payload hashing is intentionally not used for authenticated messages.
        """

        try:
            json_msg = json.loads(msg) if isinstance(msg, str) else deepcopy(msg)
            if not isinstance(json_msg, dict):
                raise ValueError("private websocket message must be an object")

            channel = json_msg.get("channel")
            if not isinstance(channel, str) or not channel:
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="invalid_private_channel",
                )
                return

            sequence_num = json_msg.get("sequence_num")
            if (
                not isinstance(sequence_num, int)
                or isinstance(sequence_num, bool)
            ):
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="invalid_sequence_number",
                )
                return

            events = json_msg.get("events")
            if (
                not isinstance(events, list)
                or not events
                or not all(isinstance(event, dict) for event in events)
            ):
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="invalid_events_payload",
                    sequence_num=sequence_num,
                )
                return

            configured_private_channels = self._host._configured_private_channels()
            if (
                channel != ChannelType.SUBSCRIPTIONS.value
                and channel not in configured_private_channels
            ):
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="unexpected_private_channel",
                    channel=channel,
                    sequence_num=sequence_num,
                )
                return

            # Retain the minimum wire evidence needed to distinguish a venue
            # delivery omission from a local reducer/dispatch omission.  Do
            # not log the full authenticated payload: order identity, terminal
            # progress, envelope sequence, and wire event type are sufficient
            # to reconstruct how this envelope should have been reduced.
            if channel == ChannelType.USER.value:
                try:
                    wire_events = []
                    for wire_event in events:
                        raw_orders = wire_event.get("orders")
                        order_rows = []
                        if isinstance(raw_orders, list):
                            for order_row in raw_orders:
                                if not isinstance(order_row, dict):
                                    continue
                                order_rows.append({
                                    "client_order_id": order_row.get(
                                        "client_order_id"
                                    ),
                                    "exchange_order_id": order_row.get(
                                        "order_id"
                                    ),
                                    "status": order_row.get("status"),
                                    "cumulative_quantity": order_row.get(
                                        "cumulative_quantity"
                                    ),
                                    "leaves_quantity": order_row.get(
                                        "leaves_quantity"
                                    ),
                                    "number_of_fills": order_row.get(
                                        "number_of_fills"
                                    ),
                                })
                        wire_events.append({
                            "type": wire_event.get("type"),
                            "order_count": (
                                len(raw_orders)
                                if isinstance(raw_orders, list)
                                else None
                            ),
                            "orders": order_rows,
                        })
                    self._host.log_message(
                        "event",
                        self._host.build_event_log_payload(
                            "user_envelope_ingress",
                            generation=generation,
                            channel=channel,
                            sequence_num=sequence_num,
                            exchange_timestamp=json_msg.get("timestamp"),
                            wire_events=wire_events,
                        ),
                    )
                except Exception:
                    # Diagnostic logging must never alter private-feed
                    # admission, sequencing, or lifecycle behavior.
                    pass

            with self._user_feed_lock:
                if generation != self._user_stream_generation:
                    return
                if self._user_feed_phase == UserFeedPhase.DESYNCHRONIZED:
                    return
                previous_sequence = self._user_last_sequence_num
                if previous_sequence is not None:
                    if sequence_num == previous_sequence:
                        if json_msg == self._user_last_envelope_payload:
                            self._host.log_message(
                                "event",
                                self._host.build_event_log_payload(
                                    "user_envelope_duplicate_ignored",
                                    generation=generation,
                                    channel=channel,
                                    sequence_num=sequence_num,
                                ),
                            )
                        else:
                            self._mark_user_stream_desynchronized(
                                generation=generation,
                                reason="conflicting_duplicate_sequence",
                                channel=channel,
                                sequence_num=sequence_num,
                            )
                        return
                    if sequence_num < previous_sequence:
                        sequence_failure = "sequence_regression"
                    elif sequence_num != previous_sequence + 1:
                        sequence_failure = "sequence_gap"
                    else:
                        sequence_failure = None
                    if sequence_failure is not None:
                        self._mark_user_stream_desynchronized(
                            generation=generation,
                            reason=sequence_failure,
                            channel=channel,
                            previous_sequence_num=previous_sequence,
                            sequence_num=sequence_num,
                        )
                        return

                if channel == ChannelType.SUBSCRIPTIONS.value:
                    self._user_last_sequence_num = sequence_num
                    self._user_last_envelope_payload = deepcopy(json_msg)
                    return
                reducer_queue_channel = self._host._private_reducer_queue_channel()
                if (
                    reducer_queue_channel is None
                    or reducer_queue_channel not in self._host.event_queue
                ):
                    self._mark_user_stream_desynchronized(
                        generation=generation,
                        reason="missing_private_event_queue",
                        channel=channel,
                        sequence_num=sequence_num,
                    )
                    return

                queued_item = UserStreamEnvelope(
                    generation=generation,
                    sequence_num=sequence_num,
                    timestamp=json_msg.get("timestamp"),
                    events=tuple(deepcopy(events)),
                    channel=channel,
                )

                try:
                    self._host.event_queue[reducer_queue_channel].put(
                        queued_item,
                        timeout=0.01,
                    )
                except Full:
                    self._mark_user_stream_desynchronized(
                        generation=generation,
                        reason="private_event_queue_full",
                        channel=channel,
                        reducer_queue_channel=reducer_queue_channel,
                        sequence_num=sequence_num,
                    )
                    return
                self._user_last_sequence_num = sequence_num
                self._user_last_envelope_payload = deepcopy(json_msg)

        except Exception as exc:
            self._mark_user_stream_desynchronized(
                generation=generation,
                reason="private_message_processing_exception",
                error=str(exc),
            )

    def process_user_envelope(self, envelope: UserStreamEnvelope) -> None:
        """Reduce one private envelope in sequence order on the user worker."""

        with self._user_reducer_lock:
            with self._user_feed_lock:
                if (
                    envelope.generation != self._user_stream_generation
                    or self._user_feed_phase == UserFeedPhase.DESYNCHRONIZED
                ):
                    return
                phase_before = self._user_feed_phase

            try:
                pending_live_orders = []
                for event in envelope.events:
                    self._host.process_user_event(
                        event,
                        dispatch_async=True,
                        generation=envelope.generation,
                        pending_live_orders=pending_live_orders,
                    )
                    with self._user_feed_lock:
                        if (
                            envelope.generation == self._user_stream_generation
                            and self._user_feed_phase
                            == UserFeedPhase.DESYNCHRONIZED
                        ):
                            return
                # Snapshot the reducer decision before async dispatch can run
                # hooks that mutate an order row or desynchronize the feed.
                with self._user_feed_lock:
                    phase_after = self._user_feed_phase
                lifecycle_orders = [{
                    "client_order_id": order.get("client_order_id"),
                    "exchange_order_id": order.get("order_id"),
                    "status": order.get("status"),
                } for order in pending_live_orders]
                dispatch_attempted = bool(pending_live_orders)
                dispatch_result = self._dispatch_validated_user_orders(
                    pending_live_orders,
                    dispatch_async=True,
                    generation=envelope.generation,
                )
                dispatch_accepted = (
                    dispatch_result if dispatch_attempted else None
                )
                try:
                    self._host.log_message(
                        "event",
                        self._host.build_event_log_payload(
                            "user_envelope_reduced",
                            generation=envelope.generation,
                            sequence_num=envelope.sequence_num,
                            wire_event_types=[
                                event.get("type")
                                for event in envelope.events
                            ],
                            phase_before=phase_before.value,
                            phase_after=phase_after.value,
                            lifecycle_order_count=len(pending_live_orders),
                            lifecycle_orders=lifecycle_orders,
                            dispatch_attempted=dispatch_attempted,
                            dispatch_accepted=dispatch_accepted,
                        ),
                    )
                except Exception:
                    # Evidence capture cannot affect lifecycle dispatch.
                    pass
            except Exception as exc:
                self._mark_user_stream_desynchronized(
                    generation=envelope.generation,
                    reason="user_envelope_processing_exception",
                    sequence_num=envelope.sequence_num,
                    error=str(exc),
                )

    def process_private_envelope(self, envelope: UserStreamEnvelope) -> None:
        """Generation-fence and route one complete private-channel envelope."""

        with self._user_reducer_lock:
            with self._user_feed_lock:
                if (
                    envelope.generation != self._user_stream_generation
                    or self._user_feed_phase == UserFeedPhase.DESYNCHRONIZED
                ):
                    return

            if envelope.channel == ChannelType.USER.value:
                self.process_user_envelope(envelope)
                return
            if envelope.channel == ChannelType.HEARTBEATS.value:
                return
            if envelope.channel == ChannelType.FUTURES_BALANCE_SUMMARY.value:
                for event in envelope.events:
                    try:
                        self._host.process_futures_balance_summary_event(event)
                    except Exception as exc:
                        self._host.log_message(
                            "error",
                            self._host.build_event_log_payload(
                                "futures_balance_summary_processing_error",
                                generation=envelope.generation,
                                sequence_num=envelope.sequence_num,
                                error=str(exc),
                            ),
                        )
                return

            self._mark_user_stream_desynchronized(
                generation=envelope.generation,
                reason="unexpected_private_envelope_channel",
                channel=envelope.channel,
            )

    def _process_user_positions_safely(self, event: dict) -> None:
        """Keep position-shape failures isolated from order lifecycle work."""

        if "positions" not in event:
            return
        try:
            self._host.process_user_snapshot(event)
        except Exception as exc:
            self._host.log_message(
                "error",
                self._host.build_event_log_payload(
                    "user_position_processing_error",
                    error=str(exc),
                    **self._host.include_debug_fields(received_event=event),
                ),
            )

    def _validate_complete_user_order(self, order: dict) -> List[str]:
        if not isinstance(order, dict):
            return sorted(LIVE_USER_ORDER_REQUIRED_FIELDS)
        missing = sorted(LIVE_USER_ORDER_REQUIRED_FIELDS - order.keys())
        if missing:
            return missing
        raw_status = order.get("status")
        if not isinstance(raw_status, str) or raw_status != raw_status.upper():
            return ["status(canonical_order_status)"]
        try:
            status = OrderStatus(raw_status)
        except ValueError:
            return ["status(valid_order_status)"]
        if status in (OrderStatus.UPDATE, OrderStatus.SNAPSHOT):
            return ["status(exchange_lifecycle_status)"]
        for field in ("client_order_id", "order_id", "product_id"):
            value = order.get(field)
            if not isinstance(value, str) or not value.strip():
                return [field]
        raw_side = order.get("order_side")
        if not isinstance(raw_side, str) or raw_side != raw_side.upper():
            return ["order_side(canonical_order_side)"]
        try:
            OrderSide(raw_side)
        except ValueError:
            return ["order_side(valid_order_side)"]

        numeric_values = {}
        for field in (
            "cumulative_quantity",
            "leaves_quantity",
            "filled_value",
            "total_fees",
            "number_of_fills",
            "completion_percentage",
        ):
            value = order.get(field)
            if isinstance(value, bool):
                return [f"{field}(finite_nonnegative_number)"]
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                return [f"{field}(finite_nonnegative_number)"]
            if not isfinite(numeric_value) or numeric_value < 0:
                return [f"{field}(finite_nonnegative_number)"]
            numeric_values[field] = numeric_value

        number_of_fills = numeric_values["number_of_fills"]
        if not number_of_fills.is_integer():
            return ["number_of_fills(nonnegative_integer)"]

        has_fill_progress = any(
            numeric_values[field] > 0
            for field in (
                "cumulative_quantity",
                "filled_value",
                "number_of_fills",
                "completion_percentage",
            )
        )
        if has_fill_progress:
            effective_price = next(
                (
                    order.get(field)
                    for field in ("avg_price", "limit_price", "price")
                    if order.get(field) not in (None, "")
                ),
                None,
            )
            try:
                parsed_price = float(effective_price)
            except (TypeError, ValueError):
                return ["effective_price(finite_positive_number)"]
            if not isfinite(parsed_price) or parsed_price <= 0:
                return ["effective_price(finite_positive_number)"]
        return []

    def _process_dispatched_user_order(
        self,
        generation: int,
        order: dict,
    ) -> None:
        fence_reason = None
        with self._user_generation_condition:
            active_generation = self._user_stream_generation
            active_phase = self._user_feed_phase
            if generation != active_generation:
                fence_reason = "stale_generation"
            elif active_phase == UserFeedPhase.DESYNCHRONIZED:
                fence_reason = "desynchronized"
            else:
                self._user_generation_inflight[generation] = (
                    self._user_generation_inflight.get(generation, 0) + 1
                )
        if fence_reason is not None:
            try:
                self._host.log_message(
                    "event",
                    self._host.build_event_log_payload(
                        "user_order_dispatch_fenced",
                        reason=fence_reason,
                        queued_generation=generation,
                        active_generation=active_generation,
                        active_phase=active_phase.value,
                        client_order_id=order.get("client_order_id"),
                        exchange_order_id=order.get("order_id"),
                        status=order.get("status"),
                    ),
                )
            except Exception:
                # A diagnostic sink failure cannot bypass the fence.
                pass
            return
        try:
            self._host.process_user_order(order)
        except Exception as exc:
            self._host.log_message(
                "error",
                self._host.build_event_log_payload(
                    "user_order_processing_exception",
                    client_order_id=order.get("client_order_id"),
                    error=str(exc),
                ),
            )
            self._mark_user_stream_desynchronized(
                generation=generation,
                reason="user_order_processing_exception",
                client_order_id=order.get("client_order_id"),
            )
        finally:
            with self._user_generation_condition:
                remaining = self._user_generation_inflight[generation] - 1
                if remaining:
                    self._user_generation_inflight[generation] = remaining
                else:
                    self._user_generation_inflight.pop(generation, None)
                    self._user_generation_condition.notify_all()

    def process_recovered_terminal_order(self, order: dict) -> None:
        """Synchronously route exact terminal truth through the per-COID FIFO."""

        if not isinstance(order, dict):
            raise OrderProcessingError("recovered terminal order must be a dict")
        client_order_id = order.get("client_order_id")
        if not client_order_id:
            raise OrderProcessingError(
                "recovered terminal order is missing client_order_id"
            )
        status = str(order.get("status") or "").upper()
        if status not in {
            OrderStatus.CANCELLED.value,
            OrderStatus.FILLED.value,
        }:
            raise OrderProcessingError(
                f"recovered order has non-terminal status {status!r}"
            )

        dispatcher = getattr(self, "_user_order_dispatcher", None)
        if dispatcher is None:
            raise RuntimeError("user order dispatcher is unavailable")
        recovered_order = dict(order)
        recovered_order["status"] = status
        future = dispatcher.submit(
            str(client_order_id),
            self._host.process_user_order,
            recovered_order,
        )
        future.result()

    def _dispatch_live_user_orders(
        self,
        event: dict,
        *,
        dispatch_async: bool,
        generation: int,
        require_complete_rows: bool,
        pending_live_orders: Optional[List[dict]] = None,
    ) -> bool:
        if "orders" not in event:
            return True
        orders = event.get("orders")
        if not isinstance(orders, list):
            self._mark_user_stream_desynchronized(
                generation=generation,
                reason="invalid_live_orders_payload",
            )
            return False

        valid_orders = []
        for order in orders:
            if not isinstance(order, dict):
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="malformed_live_order_row",
                )
                return False
            if require_complete_rows:
                missing_fields = self._validate_complete_user_order(order)
                if missing_fields:
                    self._mark_user_stream_desynchronized(
                        generation=generation,
                        reason="incomplete_live_order_row",
                        client_order_id=order.get("client_order_id"),
                        missing_fields=missing_fields,
                    )
                    return False
            elif not order.get("client_order_id"):
                self._host.log_message(
                    "warning",
                    self._host.build_event_log_payload(
                        "missing_client_order_id_in_order_event",
                        source={
                            "client_order_id": (
                                order.get("client_order_id")
                            ),
                            "order_id": (
                                order.get("order_id")
                            ),
                            "product_id": (
                                order.get("product_id")
                            ),
                            "status": (
                                order.get("status")
                            ),
                        },
                        **self._host.include_debug_fields(raw_order=order),
                    ),
                )
                continue
            valid_orders.append(order)

        if pending_live_orders is not None:
            pending_live_orders.extend(valid_orders)
            return True
        return self._dispatch_validated_user_orders(
            valid_orders,
            dispatch_async=dispatch_async,
            generation=generation,
        )

    def _dispatch_validated_user_orders(
        self,
        valid_orders: List[dict],
        *,
        dispatch_async: bool,
        generation: int,
    ) -> bool:
        """Atomically admit all validated lifecycle rows from one envelope."""

        if not valid_orders:
            return True
        dispatcher = getattr(self, "_user_order_dispatcher", None)
        if dispatch_async and dispatcher is not None:
            try:
                dispatcher.submit_many(
                    tuple(
                        (
                            order["client_order_id"],
                            self._process_dispatched_user_order,
                            (generation, order),
                            {},
                        )
                        for order in valid_orders
                    )
                )
            except Exception as exc:
                self._mark_user_stream_desynchronized(
                    generation=generation,
                    reason="user_order_dispatch_rejected",
                    client_order_ids=[
                        order.get("client_order_id") for order in valid_orders
                    ],
                    error=str(exc),
                )
                return False
        else:
            for order in valid_orders:
                self._host.process_user_order(order)
        return True
