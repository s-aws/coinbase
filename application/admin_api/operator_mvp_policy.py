"""Installed operator-ready MVP policy ceilings.

These values are backend authority. Browser and BFF payloads may request a
smaller bound, but cannot widen the installed policy.
"""

from __future__ import annotations

from decimal import Decimal


OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC = Decimal("1.00")
OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT = "3.10"
OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT = "1.00"

OPERATOR_MVP_MANUAL_ORDER_ROUTE = "/api/v1/orders"
OPERATOR_MVP_CANCEL_ORDER_ROUTE = "/api/v1/orders/{client_order_id}/cancel"
OPERATOR_MVP_FOLLOW_UP_MATERIALIZATION_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent/materialization"
)
OPERATOR_MVP_FOLLOW_UP_SAFE_CLOSEOUT_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent/"
    "materialization/safe-closeout"
)
OPERATOR_MVP_FILL_TRIGGERED_FOLLOW_UP_MATERIALIZATION_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent/"
    "fill-triggered-activation/materialization"
)
OPERATOR_MVP_FILL_TRIGGERED_FOLLOW_UP_SAFE_CLOSEOUT_ROUTE = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent/"
    "fill-triggered-activation/safe-closeout"
)
OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_CREATE_ROUTE = (
    "/api/v1/automation/runs/{run_id}/authorize-single-child"
)
OPERATOR_MVP_AUTOMATION_PREVIEW_GATED_SINGLE_CHILD_ROUTE = (
    "/api/v1/automation/runs/{run_id}/authorize-preview-gated-single-child"
)
OPERATOR_MVP_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_ROUTE = (
    "/api/v1/automation/atomic-market-snapshot-candidates/authorize"
)
OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE = (
    "/api/v1/automation/runs/{run_id}/safe-closeout-child"
)
OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE = (
    "/api/v1/hotpoint/run-once"
)
OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE = (
    "/api/v1/hotpoint/safe-closeout"
)
OPERATOR_MVP_SPOT_MODULE_ID = "spot_operations"
OPERATOR_MVP_CANCEL_PRODUCT_SCOPE = "Test profile Spot root order"
OPERATOR_MVP_SUPPORTED_LIVE_ROUTES = frozenset(
    {
        ("POST", OPERATOR_MVP_MANUAL_ORDER_ROUTE),
        ("POST", OPERATOR_MVP_CANCEL_ORDER_ROUTE),
        ("POST", OPERATOR_MVP_FOLLOW_UP_MATERIALIZATION_ROUTE),
        ("POST", OPERATOR_MVP_FOLLOW_UP_SAFE_CLOSEOUT_ROUTE),
        (
            "POST",
            OPERATOR_MVP_FILL_TRIGGERED_FOLLOW_UP_MATERIALIZATION_ROUTE,
        ),
        (
            "POST",
            OPERATOR_MVP_FILL_TRIGGERED_FOLLOW_UP_SAFE_CLOSEOUT_ROUTE,
        ),
        ("POST", OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_CREATE_ROUTE),
        (
            "POST",
            OPERATOR_MVP_AUTOMATION_PREVIEW_GATED_SINGLE_CHILD_ROUTE,
        ),
        (
            "POST",
            OPERATOR_MVP_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_ROUTE,
        ),
        (
            "POST",
            OPERATOR_MVP_AUTOMATION_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
        ),
        ("POST", OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE),
        (
            "POST",
            OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
        ),
    }
)

OPERATOR_MVP_WALLET_EVIDENCE_SOURCES = frozenset(
    {
        "admin_ui_backend_wallet_inventory_evidence",
        "backend_coinbase_account_wallet_read",
        "coinbase_accounts:list_account_available_balance",
    }
)
