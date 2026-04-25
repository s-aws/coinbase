"""Order event stream publisher and hook registration.

Provides a thin integration layer that writes normalized lifecycle events
through existing extension hooks (fill, websocket status, order submission,
order state, and stealth lifecycle).

New hook integrations (order_state_hooks, stealth_lifecycle_hooks) are optional
keyword arguments to register_hook_integrations() so existing callers continue
to work unchanged.
"""

import uuid
from typing import Any, Dict, Optional

from calculation.formatter import safe_float
from logging_service import get_logger


logger = get_logger("OrderEventStream")


class OrderEventStreamPublisher:
    """Append-only event stream publisher for reconstructive timelines."""

    def __init__(self, db_helper) -> None:
        self.db_helper = db_helper
        self.enabled = False
        self._initialize_table()

    def _initialize_table(self) -> None:
        try:
            self.db_helper.create_order_event_stream_table()
            self.db_helper.create_stealth_order_lifecycle_history_table()
            self.db_helper.create_stealth_order_reveal_history_table()
            self.db_helper.create_stealth_order_snapshots_table()
            self.enabled = True
            logger.info("order_event_stream integration enabled")
        except Exception as exc:
            self.enabled = False
            logger.warning(f"order_event_stream integration disabled: {exc}")

    def publish_event(
        self,
        event_type: str,
        source_channel: str,
        payload: Dict[str, Any],
        idempotency_key: Optional[str],
        status_to: Optional[str] = None,
    ) -> bool:
        if not self.enabled:
            return False

        try:
            event_id = str(uuid.uuid4())
            client_order_id = payload.get("client_order_id")
            parent_client_order_id = payload.get("parent_order_id")
            product_id = payload.get("product_id") or payload.get("instrument")

            inserted_id = self.db_helper.insert_order_event(
                event_id=event_id,
                event_type=event_type,
                source_channel=source_channel,
                event_time_exchange=payload.get("timestamp") or payload.get("created_at"),
                product_id=product_id,
                client_order_id=client_order_id,
                order_id=payload.get("order_id"),
                parent_client_order_id=parent_client_order_id,
                stealth_order_id=payload.get("stealth_order_id"),
                event_status_from=None,
                event_status_to=status_to,
                side=payload.get("order_side") or payload.get("side"),
                price=safe_float(payload.get("price") or payload.get("avg_price") or payload.get("limit_price"), default=None),
                size=safe_float(payload.get("quantity") or payload.get("size") or payload.get("base_size") or payload.get("filled_size"), default=None),
                cumulative_filled_size=safe_float(payload.get("cumulative_quantity"), default=None),
                leaves_size=safe_float(payload.get("leaves_quantity"), default=None),
                fee=safe_float(payload.get("fees") or payload.get("total_fees"), default=None),
                fee_currency=payload.get("fee_currency"),
                trigger_type=payload.get("trigger_type"),
                trigger_payload_json=payload.get("trigger_payload"),
                raw_payload_json=payload,
                idempotency_key=idempotency_key,
            )
            return inserted_id is not None
        except Exception as exc:
            logger.warning(f"Failed to publish event {event_type}: {exc}")
            return False

    def register_hook_integrations(
        self,
        websocket_hooks=None,
        fill_event_hooks=None,
        order_placement_hooks=None,
        order_state_hooks=None,
        stealth_lifecycle_hooks=None,
    ) -> None:
        """Register publisher hooks on existing integration points.

        This function is intentionally idempotent at the DB layer via idempotency keys.

        Args:
            websocket_hooks:        WebSocketHookRegistry (optional).
            fill_event_hooks:       FillEventHookRegistry (optional).
            order_placement_hooks:  OrderPlacementHookRegistry (optional).
            order_state_hooks:      OrderStateHookRegistry (optional). When provided,
                                    the publisher registers post_opened and post_closed
                                    subscribers that write inventory-change events to
                                    order_event_stream (event_types: ``inventory_opened``,
                                    ``inventory_closed``).
            stealth_lifecycle_hooks: StealthLifecycleHookRegistry (optional). When
                                    provided, every StealthLifecycleEvent transition is
                                    written to order_event_stream under the event_type
                                    ``stealth_<event_lower>`` (e.g. ``stealth_reveal_failed``).
                                    Also persists last_lifecycle_event + failure_reason to
                                    the stealth_orders table via
                                    update_stealth_order_lifecycle_event().
        """
        if not self.enabled:
            return

        if websocket_hooks:
            for status in ["OPEN", "PENDING", "FILLED", "CANCELLED", "FAILED"]:
                websocket_hooks.register_post_order_status(
                    status,
                    self._build_post_status_hook(status),
                )

        if fill_event_hooks:
            fill_event_hooks.register_post_fill(self._post_fill_hook)

        if order_placement_hooks:
            order_placement_hooks.register_pre_submission(self._pre_submission_hook)
            order_placement_hooks.register_post_submission(self._post_submission_hook)

        if order_state_hooks:
            order_state_hooks.register_on_opened(self._order_state_opened_hook)
            order_state_hooks.register_on_closed(self._order_state_closed_hook)

        if stealth_lifecycle_hooks:
            stealth_lifecycle_hooks.register_on_transition(
                self._stealth_lifecycle_hook
            )

    def _pre_submission_hook(self, order: Dict[str, Any]) -> None:
        """Emit stealth condition-met events before REST submission when applicable."""
        stealth_order_id = order.get("stealth_order_id")
        if not stealth_order_id:
            return

        reveal_number = order.get("reveal_number", 1)
        key = f"stealth:condition_met:{stealth_order_id}:{reveal_number}"
        payload = dict(order)
        payload["client_order_id"] = order.get("client_order_id") or stealth_order_id
        payload["trigger_type"] = order.get("reveal_condition_type") or "stealth_condition"
        payload["trigger_payload"] = {
            "condition_confirmed_at": order.get("condition_confirmed_at"),
            "reveal_number": reveal_number,
            "reveal_condition": order.get("reveal_condition_json"),
        }
        self.publish_event(
            event_type="stealth_condition_met",
            source_channel="placement_pre_hook",
            payload=payload,
            idempotency_key=key,
            status_to="TRIGGERED",
        )

    def _build_post_status_hook(self, status: str):
        def _hook(order: Dict[str, Any]) -> None:
            client_order_id = order.get("client_order_id")
            key = f"ws:{status}:{client_order_id}:{order.get('status')}"
            self.publish_event(
                event_type=f"order_{status.lower()}",
                source_channel="ws_user",
                payload=order,
                idempotency_key=key,
                status_to=status,
            )

        return _hook

    def _post_fill_hook(self, fill_data: Dict[str, Any], trade_id: str) -> None:
        key = f"fill:{trade_id}"
        payload = dict(fill_data)
        payload["trade_id"] = trade_id
        self.publish_event(
            event_type="fill_recorded",
            source_channel="fill_hook",
            payload=payload,
            idempotency_key=key,
            status_to="FILLED",
        )

    def _post_submission_hook(self, order: Dict[str, Any], result: Any) -> None:
        order_id = None
        if isinstance(result, dict):
            success_response = result.get("success_response") or {}
            order_id = success_response.get("order_id") or result.get("order_id")

        payload = dict(order)
        if order_id:
            payload["order_id"] = order_id

        client_order_id = payload.get("client_order_id")
        key = f"submit:{client_order_id}:{order_id}"
        self.publish_event(
            event_type="order_submitted",
            source_channel="rest_submit",
            payload=payload,
            idempotency_key=key,
            status_to="PENDING",
        )

        stealth_order_id = payload.get("stealth_order_id")
        if stealth_order_id:
            reveal_number = payload.get("reveal_number", 1)
            reveal_key = f"stealth:revealed:{stealth_order_id}:{reveal_number}"
            reveal_payload = dict(payload)
            reveal_payload["trigger_type"] = payload.get("reveal_condition_type") or "stealth_condition"
            reveal_payload["trigger_payload"] = {
                "reveal_number": reveal_number,
                "reveal_condition": payload.get("reveal_condition_json"),
                "condition_confirmed_at": payload.get("condition_confirmed_at"),
            }
            self.publish_event(
                event_type="stealth_revealed",
                source_channel="placement_post_hook",
                payload=reveal_payload,
                idempotency_key=reveal_key,
                status_to="REVEALED",
            )

            if payload.get("reason") == "follow_up_replacement":
                follow_up_key = f"stealth:follow_up_created:{stealth_order_id}:{reveal_number}"
                follow_up_payload = dict(payload)
                follow_up_payload["trigger_type"] = "follow_up"
                follow_up_payload["trigger_payload"] = {
                    "parent_order_id": payload.get("parent_order_id"),
                    "reason": payload.get("reason"),
                    "reveal_number": reveal_number,
                }
                self.publish_event(
                    event_type="stealth_follow_up_created",
                    source_channel="placement_post_hook",
                    payload=follow_up_payload,
                    idempotency_key=follow_up_key,
                    status_to="PENDING",
                )

    # ------------------------------------------------------------------
    # OrderStateHookRegistry handlers
    # ------------------------------------------------------------------

    def _order_state_opened_hook(self, order) -> None:
        """Publish an inventory_opened event when an order becomes working."""
        client_order_id = getattr(order, "client_order_id", None)
        key = f"inventory:opened:{client_order_id}"
        payload = {
            "client_order_id": client_order_id,
            "product_id": getattr(order, "product_id", None),
            "side": getattr(order, "order_side", None),
            "size": getattr(order, "size", None),
            "price": getattr(order, "price", None),
            "product_type": str(getattr(order, "product_type", "")),
            "created_at": str(getattr(order, "created_at", "")),
        }
        self.publish_event(
            event_type="inventory_opened",
            source_channel="order_state_hook",
            payload=payload,
            idempotency_key=key,
            status_to="OPENED",
        )

    def _order_state_closed_hook(self, order, event) -> None:
        """Publish an inventory_closed event when an order exits the working state."""
        client_order_id = getattr(order, "client_order_id", None)
        event_str = event.value if hasattr(event, "value") else str(event)
        key = f"inventory:closed:{client_order_id}:{event_str}"
        payload = {
            "client_order_id": client_order_id,
            "product_id": getattr(order, "product_id", None),
            "side": getattr(order, "order_side", None),
            "size": getattr(order, "size", None),
            "close_event": event_str,
            "product_type": str(getattr(order, "product_type", "")),
        }
        self.publish_event(
            event_type="inventory_closed",
            source_channel="order_state_hook",
            payload=payload,
            idempotency_key=key,
            status_to=event_str,
        )

    # ------------------------------------------------------------------
    # StealthLifecycleHookRegistry handler
    # ------------------------------------------------------------------

    def _stealth_lifecycle_hook(
        self, stealth_order_id: str, event, context: Dict[str, Any]
    ) -> None:
        """Publish a stealth lifecycle event to order_event_stream and persist to DB.

        Two side effects:
        1. Writes an immutable row to order_event_stream for the play-by-play audit trail.
        2. Writes a dedicated row to stealth_order_lifecycle_history for state-change audit.
        3. Calls update_stealth_order_lifecycle_event() to persist last_lifecycle_event
           and failure_reason on the stealth_orders row, enabling restart rebuild.
        """
        from core.enums import StealthLifecycleEvent
        from database.order import (
            insert_stealth_order_snapshot,
            insert_stealth_order_lifecycle_event,
            update_stealth_order_lifecycle_event,
        )

        event_str = event.value if hasattr(event, "value") else str(event)
        event_type = f"stealth_{event_str.lower()}"
        failure_reason = context.get("failure_reason")
        key = (
            f"stealth_lc:{stealth_order_id}:{event_str}:"
            f"{context.get('placed_order_id', '')}:{context.get('timestamp', '')}"
        )

        payload = dict(context)
        payload["stealth_order_id"] = stealth_order_id
        payload["lifecycle_event"] = event_str

        self.publish_event(
            event_type=event_type,
            source_channel="stealth_lifecycle_hook",
            payload=payload,
            idempotency_key=key,
            status_to=event_str,
        )

        try:
            insert_stealth_order_lifecycle_event(
                stealth_order_id=stealth_order_id,
                lifecycle_event=event_str,
                context=context,
            )
        except Exception as exc:
            logger.warning(
                f"[OrderEventStream] Failed to write lifecycle history "
                f"{event_str} for {stealth_order_id}: {exc}"
            )

        # Event-scoped snapshots for reveal-timing forensics.
        if event_str in {
            StealthLifecycleEvent.CONDITION_WATCHING.value,
            StealthLifecycleEvent.CONDITION_MET.value,
            StealthLifecycleEvent.REVEAL_SUCCEEDED.value,
        }:
            try:
                insert_stealth_order_snapshot(
                    stealth_order_id=stealth_order_id,
                    lifecycle_event=event_str,
                    context=context,
                )
            except Exception as exc:
                logger.warning(
                    f"[OrderEventStream] Failed to write lifecycle snapshot "
                    f"{event_str} for {stealth_order_id}: {exc}"
                )

        # Persist last_lifecycle_event (and failure_reason if present) to DB
        # so OrderInventory.rebuild_from_database() can restore state after restart.
        try:
            update_stealth_order_lifecycle_event(
                stealth_order_id=stealth_order_id,
                lifecycle_event=event_str,
                failure_reason=failure_reason,
            )
        except Exception as exc:
            logger.warning(
                f"[OrderEventStream] Failed to persist lifecycle event "
                f"{event_str} for {stealth_order_id}: {exc}"
            )
