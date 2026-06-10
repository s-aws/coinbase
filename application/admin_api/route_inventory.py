"""Admin API route/message inventory."""

from __future__ import annotations

from core.enums import (
    AdminApiActionClass,
    AdminApiCompatibilityMode,
    AdminApiPermission,
)

from .models import AdminApiRouteInventoryItem


ADMIN_API_ROUTE_INVENTORY: tuple[AdminApiRouteInventoryItem, ...] = (
    AdminApiRouteInventoryItem(
        surface="POST /api/v1/orders",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="place_manual_order",
        parity_test="HTTP vs place_order guard/result parity",
    ),
    AdminApiRouteInventoryItem(
        surface="place_order WebSocket",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission="compatibility policy",
        idempotency="enterprise-gated or compatibility-only",
        approval="enterprise-gated or compatibility-only",
        caps="required",
        audit="required",
        shared_method="place_manual_order",
        parity_test="WebSocket vs HTTP guard/result parity",
        compatibility_mode=AdminApiCompatibilityMode.COMPATIBILITY_ONLY.value,
    ),
    AdminApiRouteInventoryItem(
        surface="POST /api/v1/orders/{client_order_id}/cancel",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="not required unless policy adds approval",
        caps="required for rate/session controls",
        audit="required",
        shared_method="cancel_order_by_client_order_id",
        parity_test="HTTP vs cancel_order parity",
    ),
    AdminApiRouteInventoryItem(
        surface="cancel_order WebSocket",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission="compatibility policy",
        idempotency="enterprise-gated or compatibility-only",
        approval="not required unless policy adds approval",
        caps="required for rate/session controls",
        audit="required",
        shared_method="cancel_order_by_client_order_id",
        parity_test="WebSocket vs HTTP parity",
        compatibility_mode=AdminApiCompatibilityMode.COMPATIBILITY_ONLY.value,
    ),
    AdminApiRouteInventoryItem(
        surface="read-only status routes",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="read service method",
        parity_test="no Coinbase REST placement",
    ),
)

