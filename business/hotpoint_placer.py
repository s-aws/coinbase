"""Hotpoint placer — turns a HotpointTriggerEvent into one resting limit order.

Sequence:

1. Check kill switch (``HOTPOINT_AUTO_PLACE_ENABLED``). If False, no-op.
2. Acquire a slot from :class:`HotpointRateLimiter`. If denied, no-op.
3. Derive the limit price per :class:`HotpointPlacementPolicy`.
4. Normalize price through the canonical runtime ``price_increment`` boundary
   and size to ``base_increment`` / ``base_min_size`` of the product.
5. Submit a GTC limit via ``REST_CLIENT.limit_order_gtc``.
6. On success: insert ``order_parent`` row with
   ``auto_placed_by_hotpoint=TRUE``, ``enable_hotpoint_replication=FALSE``,
   ``parent_order_id=NULL`` (auto-placed orders are their own roots; they do
   not inherit chain membership), then commit the rate-limiter slot.
7. Before exchange acceptance, failures roll back the slot. After confirmed
   acceptance, local persistence failure commits the slot and is reported as
   a local-finalization error; the live order must not be resubmitted.

This module is intentionally thin and exception-safe — failures must NEVER
propagate up into ``OrderEngine._process_ws_order_delta``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from business.hotpoint_detector import HotpointTriggerEvent
from business.placement_response import classify_placement_response
from business.hotpoint_rate_limiter import HotpointRateLimiter
from calculation.price_validation import normalize_price_for_product
from core.enums import (
    HotpointPlacementPolicy,
    OrderPlacementOutcome,
    OrderStatus,
    PriceRoundingPolicy,
)

logger = logging.getLogger(__name__)


# Status string constants returned by :func:`place_hotpoint_order`.
STATUS_KILL_SWITCH_OFF = "kill_switch_off"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_PRODUCT_META_MISSING = "product_meta_missing"
STATUS_INVALID_PRICE = "invalid_price"
STATUS_REST_FAILED = "rest_failed"
STATUS_REST_INDETERMINATE = "rest_indeterminate"
STATUS_DB_INSERT_FAILED = "db_insert_failed"
STATUS_PLACED = "placed"


@dataclass(frozen=True)
class HotpointPlacementResult:
    """Outcome of a single placement attempt."""

    status: str
    client_order_id: Optional[str] = None
    submitted_price: Optional[float] = None
    submitted_size: Optional[float] = None
    error: Optional[str] = None


def derive_placement_price(
    policy: HotpointPlacementPolicy,
    event: HotpointTriggerEvent,
) -> float:
    """Map (policy, event) -> raw limit price (pre-quantization)."""
    if policy is HotpointPlacementPolicy.WINDOW_CENTER:
        return event.bucket_center
    if policy is HotpointPlacementPolicy.LAST_FILL:
        return event.last_fill_price
    if policy is HotpointPlacementPolicy.MEAN_OF_FILLS:
        return event.mean_fill_price
    raise ValueError(f"Unknown HotpointPlacementPolicy: {policy!r}")


def place_hotpoint_order(
    *,
    event: HotpointTriggerEvent,
    rate_limiter: HotpointRateLimiter,
    product_meta: Dict[str, Any],
    policy: HotpointPlacementPolicy,
    rest_client: Any,
    insert_order_parent_fn: Callable[..., Optional[int]],
    kill_switch_enabled: bool,
    log_callback: Optional[Callable[[str, Any], None]] = None,
    now_epoch: Optional[float] = None,
) -> HotpointPlacementResult:
    """Drive one full kill-switch -> place sequence for a trigger event.

    Args:
        event: The trigger from the detector.
        rate_limiter: Per-bucket sliding-window cap.
        product_meta: Dict (or :class:`core.models.Product`) with
            ``base_min_size`` and ``base_increment`` for sizing. Price ticks
            are read through the canonical runtime metadata snapshot. Missing
            or invalid required metadata surfaces as
            ``STATUS_PRODUCT_META_MISSING``.
        policy: Pricing policy.
        rest_client: Object exposing ``limit_order_gtc(...)``. In tests this
            is a Mock.
        insert_order_parent_fn: Callable matching
            :func:`database.order.insert_order_parent`. Injected so tests
            can supply a stub without DB I/O.
        kill_switch_enabled: Pre-evaluated runtime flag (caller reads
            ``core.constants.HOTPOINT_AUTO_PLACE_ENABLED`` or its
            engine-level override). The placer NEVER reads the flag itself
            — that gives the engine one place to override at runtime.
        log_callback: Optional ``(level, msg_or_payload) -> None`` for
            structured logging into the engine's event log. When omitted,
            the module logger is used.
        now_epoch: Optional clock override for tests.

    Returns:
        :class:`HotpointPlacementResult` with status + diagnostic fields.
    """
    log = log_callback or (lambda level, msg: getattr(logger, level, logger.info)(msg))
    now_epoch = float(now_epoch) if now_epoch is not None else time.time()

    if not kill_switch_enabled:
        return HotpointPlacementResult(status=STATUS_KILL_SWITCH_OFF)

    # 1. Rate-limit slot acquisition.
    decision = rate_limiter.try_acquire(
        product_id=event.product_id,
        side=event.side,
        bucket_id=event.bucket_id,
        now=now_epoch,
    )
    if not decision.allowed:
        log("info", {
            "event": "hotpoint_rate_limited",
            "product_id": event.product_id,
            "side": event.side,
            "bucket_id": event.bucket_id,
            "current_count": decision.current_count,
            "cap": decision.cap,
        })
        return HotpointPlacementResult(status=STATUS_RATE_LIMITED)

    # From here on, every exit path must commit OR rollback.
    try:
        # 2. Read product metadata.
        from core.models import Product as _Product
        if isinstance(product_meta, _Product):
            base_min_size = float(product_meta.base_min_size or 0)
            base_increment = float(product_meta.base_increment or 0)
        else:
            base_min_size = float(product_meta.get("base_min_size") or 0)
            base_increment = float(product_meta.get("base_increment") or 0)

        if base_min_size <= 0.0:
            log("warning", {
                "event": "hotpoint_product_meta_missing",
                "product_id": event.product_id,
                "base_min_size": base_min_size,
            })
            rate_limiter.rollback(
                product_id=event.product_id,
                side=event.side,
                bucket_id=event.bucket_id,
            )
            return HotpointPlacementResult(status=STATUS_PRODUCT_META_MISSING)

        # 3. Derive + quantize price.
        raw_price = derive_placement_price(policy, event)
        if raw_price <= 0.0:
            rate_limiter.rollback(
                product_id=event.product_id,
                side=event.side,
                bucket_id=event.bucket_id,
            )
            return HotpointPlacementResult(status=STATUS_INVALID_PRICE)

        # Hotpoint placement intentionally uses nearest-tick semantics to stay
        # close to the detected bucket center. The arithmetic itself is shared
        # with every other exchange-bound price path.
        price_check = normalize_price_for_product(
            raw_price,
            product_id=event.product_id,
            side=event.side,
            policy=PriceRoundingPolicy.NEAREST,
        )
        if not price_check:
            log("warning", {
                "event": "hotpoint_price_normalization_failed",
                "product_id": event.product_id,
                "side": event.side,
                "requested_price": price_check.requested_price,
                "price_increment": price_check.increment,
                "error": price_check.reason,
            })
            rate_limiter.rollback(
                product_id=event.product_id,
                side=event.side,
                bucket_id=event.bucket_id,
            )
            status = (
                STATUS_PRODUCT_META_MISSING
                if price_check.rounding_direction is None
                else STATUS_INVALID_PRICE
            )
            return HotpointPlacementResult(status=status, error=price_check.reason)
        submitted_price = float(price_check.effective_price)

        # 4. Size = venue minimum.
        # Use base_min_size as the absolute minimum tradeable quantity.
        # base_increment is the granularity; we go with base_min_size and
        # quantize to base_increment if both are present.
        if base_increment > 0.0 and base_increment > base_min_size:
            submitted_size = base_increment
        else:
            submitted_size = base_min_size

        client_order_id = str(uuid.uuid4())

        # 5. Submit REST. A returned SDK response is not itself proof that
        # Coinbase accepted the order; classify the response before writing
        # local placement state.
        try:
            rest_response = rest_client.limit_order_gtc(
                product_id=event.product_id,
                side=event.side,
                base_size=str(submitted_size),
                limit_price=str(submitted_price),
                client_order_id=client_order_id,
                post_only=False,
            )
        except Exception as e:
            placement = classify_placement_response(
                expected_client_order_id=client_order_id,
                exception=e,
            )
        else:
            placement = classify_placement_response(
                rest_response,
                expected_client_order_id=client_order_id,
            )

        if not placement.accepted:
            failure_reason = placement.failure_reason or placement.outcome.value
            log("error", {
                "event": "hotpoint_rest_failed",
                "product_id": event.product_id,
                "side": event.side,
                "bucket_id": event.bucket_id,
                "submitted_price": submitted_price,
                "submitted_size": submitted_size,
                "placement_outcome": placement.outcome.value,
                "error": failure_reason,
            })
            if placement.outcome is OrderPlacementOutcome.INDETERMINATE:
                # The exchange may have accepted the request. Quarantine the
                # slot so the next websocket trigger cannot submit a duplicate.
                rate_limiter.quarantine(
                    product_id=event.product_id,
                    side=event.side,
                    bucket_id=event.bucket_id,
                    now=now_epoch,
                )
                status = STATUS_REST_INDETERMINATE
            else:
                rate_limiter.rollback(
                    product_id=event.product_id,
                    side=event.side,
                    bucket_id=event.bucket_id,
                )
                status = STATUS_REST_FAILED
            return HotpointPlacementResult(
                status=status,
                client_order_id=client_order_id,
                submitted_price=submitted_price,
                submitted_size=submitted_size,
                error=failure_reason,
            )

        # 6. Persist.
        try:
            inserted_parent_id = insert_order_parent_fn(
                client_order_id=client_order_id,
                product_id=event.product_id,
                side=event.side,
                size=submitted_size,
                price=submitted_price,
                target_movement=0.0,
                target_movement_type="P",
                max_order_replacement=0,
                current_order_replacement=0,
                status=OrderStatus.PENDING.value,
                parent_order_id=None,
                allow_partial_fills=False,
                enable_hotpoint_replication=False,
                auto_placed_by_hotpoint=True,
            )
            if inserted_parent_id is None:
                raise RuntimeError("order_parent insert returned no row id")
        except Exception as e:
            # Order is already on the exchange. We MUST still commit the
            # rate-limiter slot (the placement is real) and surface the
            # failure loudly. The reconciler will eventually pick the row
            # up when the WS user-channel emits the placement.
            log("error", {
                "event": "hotpoint_db_insert_failed",
                "client_order_id": client_order_id,
                "exchange_order_id": placement.exchange_order_id,
                "product_id": event.product_id,
                "side": event.side,
                "submitted_price": submitted_price,
                "submitted_size": submitted_size,
                "error": str(e),
                "note": (
                    "Exchange acceptance is confirmed. Order IS LIVE on the "
                    "exchange; do not resubmit."
                ),
            })
            rate_limiter.commit(
                product_id=event.product_id,
                side=event.side,
                bucket_id=event.bucket_id,
                now=now_epoch,
            )
            return HotpointPlacementResult(
                status=STATUS_DB_INSERT_FAILED,
                client_order_id=client_order_id,
                submitted_price=submitted_price,
                submitted_size=submitted_size,
                error=str(e),
            )

        # 7. Commit slot.
        rate_limiter.commit(
            product_id=event.product_id,
            side=event.side,
            bucket_id=event.bucket_id,
            now=now_epoch,
        )

        log("info", {
            "event": "hotpoint_placed",
            "client_order_id": client_order_id,
            "product_id": event.product_id,
            "side": event.side,
            "bucket_id": event.bucket_id,
            "fills_in_window": event.fills_in_window,
            "policy": policy.value,
            "submitted_price": submitted_price,
            "submitted_size": submitted_size,
        })
        return HotpointPlacementResult(
            status=STATUS_PLACED,
            client_order_id=client_order_id,
            submitted_price=submitted_price,
            submitted_size=submitted_size,
        )
    except Exception as e:
        # Last-ditch safety: any uncaught exception must rollback the slot.
        log("error", {
            "event": "hotpoint_unexpected_failure",
            "product_id": event.product_id,
            "side": event.side,
            "bucket_id": event.bucket_id,
            "error": f"{type(e).__name__}: {e}",
        })
        rate_limiter.rollback(
            product_id=event.product_id,
            side=event.side,
            bucket_id=event.bucket_id,
        )
        return HotpointPlacementResult(
            status=STATUS_REST_FAILED,
            error=f"{type(e).__name__}: {e}",
        )
