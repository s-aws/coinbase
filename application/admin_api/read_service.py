"""Read-only Admin API service wrappers."""

from __future__ import annotations

from typing import Any


class AdminApiReadService:
    """Read-only status service for operator views.

    The current implementation delegates to existing dashboard payload builders
    without using the dashboard WebSocket transport. These methods must remain
    read-only.
    """

    def build_spot_readiness(
        self,
        *,
        product_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_readiness_payload

        return _build_spot_readiness_payload(product_ids=product_ids)

    def build_spot_sweep_status(self, *, state_file: str | None = None) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_status_payload

        return _build_spot_sweep_status_payload(state_file=state_file)

    def build_spot_sweep_pnl(
        self,
        *,
        product_ids: list[str] | None = None,
        include_coinbase_average_cost: bool = False,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_pnl_payload

        return _build_spot_sweep_pnl_payload(
            product_ids=product_ids,
            include_coinbase_average_cost=include_coinbase_average_cost,
        )

    def build_spot_cost_basis_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_cost_basis_payload

        return _build_spot_cost_basis_payload(state_file=state_file)

    def build_spot_campaign_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_campaign_payload

        return _build_spot_campaign_payload(state_file=state_file)

    def build_spot_direct_order_audit(
        self,
        *,
        client_order_id: str,
        include_events: bool = True,
        include_fills: bool = True,
        event_limit: int = 100,
        fill_limit: int = 1000,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_direct_order_audit_payload

        return _build_spot_direct_order_audit_payload(
            client_order_id=client_order_id,
            include_events=include_events,
            include_fills=include_fills,
            event_limit=event_limit,
            fill_limit=fill_limit,
        )
