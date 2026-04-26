"""Per-order WS-progress tracker — single source of truth for cumulative-counter deltas.

Owns the watermark used by BOTH:
  * fill-ledger row generation (one row per real per-match delta), and
  * partial-fill follow-up creation (when accumulated carry crosses min_order_size).

Replaces the two parallel state dicts that previously lived on ``OrderEngine``
(``_partial_fill_state`` and ``_fill_recording_state``). One delta object,
one lock per ``client_order_id``, one persistence point.

Pure logic in this module — DB persistence is wired in the engine in step 4.

See ai-context.md and the design plan for the full architecture rationale.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from calculation.formatter import safe_float
from calculation.resolver import (
    resolve_cumulative_filled,
    resolve_order_side,
    resolve_remaining_size,
)
from core.constants import get_local_now
from core.enums import OrderStatus


_TERMINAL_STATUSES = frozenset({
    OrderStatus.FILLED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.FAILED.value,
    OrderStatus.EXPIRED.value,
})


@dataclass(frozen=True)
class OrderSnapshotDelta:
    """A per-order WS snapshot reduced to its derivative ("what is new") form.

    Every consumer of WS order progress receives this object. It carries both
    the absolute counters (current state) and the deltas vs the previous
    processed snapshot, plus a deterministic ``derived_trade_key`` that is
    suitable as a unique idempotency key for downstream inserts.
    """

    # Identity
    client_order_id: str
    product_id: str
    side: str

    # Absolute counters at this snapshot
    cumulative_quantity: float
    filled_value: float
    total_fees: float
    number_of_fills: int
    leaves_quantity: float
    completion_percentage: float
    outstanding_hold_amount: float
    status: str

    # Per-snapshot derivatives (vs last processed)
    size_delta: float
    value_delta: float
    fee_delta: float

    # Derived helpers
    derived_price: float
    derived_trade_key: str
    snapshot_seq: int
    observed_at: datetime

    @property
    def is_new_match(self) -> bool:
        """True when this snapshot contains a positive cumulative-quantity advance."""
        return self.size_delta > 0.0

    @property
    def is_terminal(self) -> bool:
        """True when the order's lifecycle has reached a terminal status."""
        return self.status in _TERMINAL_STATUSES


@dataclass
class _WatermarkRecord:
    """Mutable per-order state held inside the tracker."""

    parent_client_order_id: Optional[str]
    product_id: str
    side: str
    original_order_size: float
    min_order_size: float
    last_cumulative_qty_processed: float = 0.0
    last_filled_value: float = 0.0
    last_total_fees: float = 0.0
    last_number_of_fills_seen: int = 0
    last_completion_pct_seen: float = 0.0
    carry_remainder_qty: float = 0.0
    partial_follow_ups_created: int = 0
    snapshot_seq: int = 0


class OrderProgressTracker:
    """Single-owner state machine for all per-order WS-derived progress.

    Thread-safe at per-``client_order_id`` granularity. The tracker is pure
    in-memory in this module; the engine layer is responsible for binding
    its lifecycle methods to DB persistence (``partial_fill_progress`` upsert,
    ``order_match_audit`` append) and for hydrating state at startup.

    Usage:
        tracker = OrderProgressTracker(min_order_size_resolver=...)
        delta = tracker.ingest(normalized_order)
        if delta is None:
            return  # snapshot carried no new info
        if delta.is_new_match:
            ledger.append_derived_fill(delta)
        if delta.is_terminal:
            tracker.finalize(delta.client_order_id, terminal_status=delta.status)
    """

    def __init__(self, min_order_size_resolver=None, parent_resolver=None):
        """Args:
            min_order_size_resolver: Callable ``(product_id) -> float`` returning
                the product's base increment. Used the first time we see an
                order so we can persist ``original_order_size``/``min_order_size``
                in the watermark for downstream partial-fill decisions. May be
                None in unit tests; the watermark will record 0.0 for both.
            parent_resolver: Callable ``(client_order_id) -> Optional[str]``
                that returns the parent ``client_order_id`` for child orders
                (or ``None``/the input itself when the order is its own root).
                Consulted only when the WS payload does not already carry a
                ``parent_client_order_id`` / ``parent_order_id`` field.
        """
        self._records: Dict[str, _WatermarkRecord] = {}
        self._records_lock = threading.RLock()
        self._order_locks: Dict[str, threading.RLock] = {}
        self._order_locks_guard = threading.RLock()
        self._min_order_size_resolver = min_order_size_resolver
        self._parent_resolver = parent_resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, normalized_order: dict) -> Optional[OrderSnapshotDelta]:
        """Atomically advance the watermark for one WS snapshot.

        Returns the resulting :class:`OrderSnapshotDelta` if any of the
        cumulative counters advanced, otherwise ``None``. Replays of an
        identical snapshot return ``None`` and do not mutate state.

        Idempotency key for downstream inserts:
        ``derived_trade_key = uuid5(NAMESPACE_OID, "coinbase-fill:{coid}:{cumulative}")``.
        """
        client_order_id = normalized_order.get("client_order_id")
        if not client_order_id:
            return None

        cumulative = resolve_cumulative_filled(normalized_order)
        filled_value = safe_float(normalized_order.get("filled_value"), default=0.0)
        total_fees = safe_float(normalized_order.get("total_fees"), default=0.0)
        number_of_fills = int(normalized_order.get("number_of_fills") or 0)
        completion_pct = safe_float(normalized_order.get("completion_percentage"), default=0.0)
        leaves_qty = resolve_remaining_size(normalized_order)
        outstanding_hold = safe_float(
            normalized_order.get("outstanding_hold_amount"), default=0.0
        )
        status = str(normalized_order.get("status") or "").upper()
        product_id = normalized_order.get("product_id") or ""
        side = resolve_order_side(normalized_order) or ""

        with self._get_order_lock(client_order_id):
            record = self._records.get(client_order_id)
            if record is None:
                record = self._initialize_record(
                    client_order_id=client_order_id,
                    normalized_order=normalized_order,
                    product_id=product_id,
                    side=side,
                    cumulative=cumulative,
                    leaves_qty=leaves_qty,
                )

            # Compute deltas vs last processed snapshot.
            size_delta = cumulative - record.last_cumulative_qty_processed
            value_delta = filled_value - record.last_filled_value
            fee_delta = total_fees - record.last_total_fees

            # No advance and no status change worth re-emitting → skip.
            counters_advanced = (
                size_delta > 0.0
                or value_delta > 0.0
                or fee_delta > 0.0
                or number_of_fills > record.last_number_of_fills_seen
                or completion_pct > record.last_completion_pct_seen
            )
            became_terminal = status in _TERMINAL_STATUSES and not counters_advanced
            if not counters_advanced and not became_terminal:
                return None

            # Derive per-match price from value/size when available.
            if size_delta > 0.0 and value_delta > 0.0:
                derived_price = value_delta / size_delta
            else:
                derived_price = safe_float(
                    normalized_order.get("avg_price")
                    or normalized_order.get("limit_price")
                    or normalized_order.get("price"),
                    default=0.0,
                )

            derived_trade_key = str(uuid.uuid5(
                uuid.NAMESPACE_OID,
                f"coinbase-fill:{client_order_id}:{cumulative}",
            ))

            record.snapshot_seq += 1
            seq = record.snapshot_seq

            # Advance watermark BEFORE returning so concurrent ingest of the
            # same snapshot from another thread sees no delta.
            record.last_cumulative_qty_processed = cumulative
            record.last_filled_value = filled_value
            record.last_total_fees = total_fees
            record.last_number_of_fills_seen = max(
                number_of_fills, record.last_number_of_fills_seen
            )
            record.last_completion_pct_seen = max(
                completion_pct, record.last_completion_pct_seen
            )
            # Update carry only on a real size advance.
            if size_delta > 0.0:
                record.carry_remainder_qty += size_delta

            return OrderSnapshotDelta(
                client_order_id=client_order_id,
                product_id=product_id or record.product_id,
                side=side or record.side,
                cumulative_quantity=cumulative,
                filled_value=filled_value,
                total_fees=total_fees,
                number_of_fills=number_of_fills,
                leaves_quantity=leaves_qty,
                completion_percentage=completion_pct,
                outstanding_hold_amount=outstanding_hold,
                status=status,
                size_delta=max(size_delta, 0.0),
                value_delta=max(value_delta, 0.0),
                fee_delta=max(fee_delta, 0.0),
                derived_price=derived_price,
                derived_trade_key=derived_trade_key,
                snapshot_seq=seq,
                observed_at=get_local_now(),
            )

    def consume_carry_units(self, client_order_id: str, units: int) -> None:
        """Decrement ``carry_remainder_qty`` after a partial-fill follow-up was placed.

        Args:
            client_order_id: Order whose carry should be reduced.
            units: Number of ``min_order_size`` units that were placed.
        """
        if units <= 0:
            return
        with self._get_order_lock(client_order_id):
            record = self._records.get(client_order_id)
            if record is None or record.min_order_size <= 0.0:
                return
            consumed = units * record.min_order_size
            record.carry_remainder_qty = max(
                0.0, record.carry_remainder_qty - consumed
            )
            record.partial_follow_ups_created += units

    def get_record(self, client_order_id: str) -> Optional[_WatermarkRecord]:
        """Read-only snapshot of the per-order watermark (returns a copy)."""
        with self._records_lock:
            record = self._records.get(client_order_id)
            if record is None:
                return None
            # Return a shallow copy so callers cannot mutate internal state.
            return _WatermarkRecord(**record.__dict__)

    def finalize(self, client_order_id: str, terminal_status: str) -> None:
        """Drop watermark + per-order lock for an order that reached a terminal state."""
        with self._records_lock:
            self._records.pop(client_order_id, None)
        with self._order_locks_guard:
            self._order_locks.pop(client_order_id, None)

    def hydrate(self, rows) -> None:
        """Populate the in-memory map from persisted ``partial_fill_progress`` rows.

        Called once at engine startup. Each ``row`` is a dict-like with the
        column names defined in :func:`database.order.create_partial_fill_progress_table`.
        Unknown columns are tolerated (forward-compatible with later migrations).
        """
        with self._records_lock:
            self._records.clear()
            for row in rows or []:
                coid = row.get("client_order_id")
                if not coid:
                    continue
                self._records[coid] = _WatermarkRecord(
                    parent_client_order_id=row.get("parent_client_order_id"),
                    product_id=row.get("product_id") or "",
                    side=row.get("side") or "",
                    original_order_size=safe_float(
                        row.get("original_order_size"), default=0.0
                    ),
                    min_order_size=safe_float(row.get("min_order_size"), default=0.0),
                    last_cumulative_qty_processed=safe_float(
                        row.get("last_cumulative_qty_processed"), default=0.0
                    ),
                    last_filled_value=safe_float(
                        row.get("last_filled_value"), default=0.0
                    ),
                    last_total_fees=safe_float(
                        row.get("last_total_fees"), default=0.0
                    ),
                    last_number_of_fills_seen=int(
                        row.get("last_number_of_fills_seen") or 0
                    ),
                    last_completion_pct_seen=safe_float(
                        row.get("last_completion_pct_seen"), default=0.0
                    ),
                    carry_remainder_qty=safe_float(
                        row.get("carry_remainder_qty"), default=0.0
                    ),
                    partial_follow_ups_created=int(
                        row.get("partial_follow_ups_created") or 0
                    ),
                    snapshot_seq=int(row.get("snapshot_seq") or 0),
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _initialize_record(
        self,
        client_order_id: str,
        normalized_order: dict,
        product_id: str,
        side: str,
        cumulative: float,
        leaves_qty: float,
    ) -> _WatermarkRecord:
        """Create the first watermark for an order we have not seen before."""
        original_order_size = leaves_qty + cumulative
        if original_order_size <= 0.0:
            original_order_size = safe_float(
                normalized_order.get("base_size") or normalized_order.get("size"),
                default=0.0,
            )

        min_order_size = 0.0
        if self._min_order_size_resolver is not None and product_id:
            try:
                min_order_size = float(self._min_order_size_resolver(product_id))
            except Exception:  # pragma: no cover — resolver is engine-supplied
                min_order_size = 0.0

        parent_id = (
            normalized_order.get("parent_client_order_id")
            or normalized_order.get("parent_order_id")
        )
        if not parent_id and self._parent_resolver is not None:
            try:
                parent_id = self._parent_resolver(client_order_id)
            except Exception:  # pragma: no cover — resolver is engine-supplied
                parent_id = None
        if not parent_id:
            parent_id = client_order_id

        record = _WatermarkRecord(
            parent_client_order_id=parent_id,
            product_id=product_id,
            side=side,
            original_order_size=original_order_size,
            min_order_size=min_order_size,
        )
        self._records[client_order_id] = record
        return record

    def _get_order_lock(self, client_order_id: str) -> threading.RLock:
        with self._order_locks_guard:
            lock = self._order_locks.get(client_order_id)
            if lock is None:
                lock = threading.RLock()
                self._order_locks[client_order_id] = lock
            return lock
