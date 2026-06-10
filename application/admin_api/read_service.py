"""Read-only Admin API service wrappers."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiSessionStatus,
)

from .models import (
    AdminApiActor,
    AdminBootstrapResponse,
    AdminCapabilityItem,
    AdminCapabilityRegistryResponse,
    AdminFrontendFixturesResponse,
    AdminGateCheck,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminOrderDetailResponse,
    AdminOrderListResponse,
    AdminOrderReadItem,
    AdminSessionResponse,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1.0"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _surface_method_and_path(surface: str) -> tuple[str, str]:
    first, _, rest = surface.partition(" ")
    if rest.startswith("/"):
        return first, rest
    if "WebSocket" in surface:
        return "WEBSOCKET", surface
    return "UNKNOWN", surface


def _route_availability(surface: str, action_class: AdminApiActionClass) -> AdminApiRouteAvailability:
    if "WebSocket" in surface:
        return AdminApiRouteAvailability.CONTRACT_PENDING
    if surface.startswith("POST /api/v1") and action_class in {
        AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
    }:
        return AdminApiRouteAvailability.LIVE_DISABLED
    return AdminApiRouteAvailability.AVAILABLE


def _frontend_safe(surface: str, action_class: AdminApiActionClass) -> bool:
    if "WebSocket" in surface:
        return False
    return action_class == AdminApiActionClass.READ_ONLY or surface.startswith("POST /api/v1")


def _order_item_from_row(row: dict[str, Any]) -> AdminOrderReadItem:
    return AdminOrderReadItem(
        client_order_id=str(row.get("client_order_id") or ""),
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        order_type=_string_or_none(row.get("order_type")),
        size=_string_or_none(row.get("size")),
        price=_string_or_none(row.get("price")),
        parent_client_order_id=_string_or_none(row.get("parent_order_id")),
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
        exchange_order_id=_string_or_none(
            row.get("exchange_order_id")
            or row.get("coinbase_order_id")
            or row.get("active_exchange_order_id")
        ),
    )


class AdminApiReadService:
    """Read-only status service for operator views.

    The current implementation delegates to existing dashboard payload builders
    without using the dashboard WebSocket transport. These methods must remain
    read-only.
    """

    def build_admin_bootstrap(self) -> AdminBootstrapResponse:
        """Return backend association and live-action posture."""

        cors_configured = bool(os.environ.get("COINBASE_ADMIN_API_CORS_ORIGINS", "").strip())
        csrf_required = os.environ.get(
            "COINBASE_ADMIN_API_CSRF_REQUIRED",
            "",
        ).strip().lower() in {"1", "true", "yes"}
        return AdminBootstrapResponse(
            backend_repository="s-aws/coinbase",
            api_version=API_VERSION,
            schema_version=SCHEMA_VERSION,
            environment=os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "local"),
            mutating_routes_live_disabled=True,
            live_execution_enabled=False,
            auth_required=True,
            cors_configured=cors_configured,
            csrf_required=csrf_required,
            capabilities_route="/api/v1/admin/capabilities",
            session_route="/api/v1/admin/session",
        )

    def build_admin_health(self) -> AdminHealthResponse:
        """Return read-only API health without probing Coinbase."""

        diagnostics = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            if "WebSocket" in item.surface:
                continue
            availability = _route_availability(item.surface, item.action_class)
            diagnostics.append({
                "path": path,
                "method": method,
                "status": availability,
                "message": (
                    "Live execution disabled by backend contract"
                    if availability == AdminApiRouteAvailability.LIVE_DISABLED
                    else "Route contract is available"
                ),
            })
        failed_route_count = sum(
            1
            for diagnostic in diagnostics
            if diagnostic["status"] == AdminApiRouteAvailability.BACKEND_BLOCKED
        )
        return AdminHealthResponse(
            status=(
                AdminApiHealthStatus.BLOCKED
                if failed_route_count
                else AdminApiHealthStatus.HEALTHY
            ),
            api_version=API_VERSION,
            diagnostics=diagnostics,
            failed_route_count=failed_route_count,
        )

    def build_admin_session(
        self,
        *,
        actor: AdminApiActor,
        permissions: list[AdminApiPermission],
    ) -> AdminSessionResponse:
        """Return authenticated actor and permission evidence."""

        return AdminSessionResponse(
            status=AdminApiSessionStatus.SIGNED_IN,
            actor=actor,
            permissions=permissions,
        )

    def build_admin_capabilities(self) -> AdminCapabilityRegistryResponse:
        """Return route capability metadata derived from the owned inventory."""

        capabilities: list[AdminCapabilityItem] = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            availability = _route_availability(item.surface, item.action_class)
            capabilities.append(
                AdminCapabilityItem(
                    route=path,
                    method=method,
                    action_class=item.action_class,
                    permission=item.permission,
                    availability=availability,
                    live_enabled=False,
                    frontend_safe=_frontend_safe(item.surface, item.action_class),
                    shared_method=item.shared_method,
                    notes=(
                        "Compatibility-only legacy dashboard surface"
                        if "WebSocket" in item.surface
                        else "Backend-owned Admin API route"
                    ),
                )
            )
        return AdminCapabilityRegistryResponse(capabilities=capabilities)

    def build_order_list(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> AdminOrderListResponse:
        """Return a read-only order list from local order_parent evidence."""

        filters: dict[str, Any] = {
            "product_id": product_id,
            "status": status,
            "limit": limit,
        }
        try:
            from database.order import get_parent_orders

            rows = get_parent_orders() or []
        except Exception as exc:
            filters["backend_read_error"] = f"{type(exc).__name__}: {exc}"
            rows = []

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if product_id and row.get("product_id") != product_id:
                continue
            if status and str(row.get("status") or "").lower() != status.lower():
                continue
            filtered.append(row)
            if len(filtered) >= max(1, min(limit, 500)):
                break
        items = [_order_item_from_row(row) for row in filtered]
        return AdminOrderListResponse(filters=filters, count=len(items), items=items)

    def build_order_detail(self, *, client_order_id: str) -> AdminOrderDetailResponse:
        """Return one read-only order row by ``client_order_id``."""

        try:
            from database.order import get_parent_order

            row = get_parent_order(client_order_id)
        except Exception:
            row = None
        return AdminOrderDetailResponse(
            client_order_id=client_order_id,
            found=row is not None,
            order=_order_item_from_row(row) if row else None,
        )

    def build_release_gate(self) -> AdminGateReadResponse:
        """Return release-gate evidence without running tests from the browser."""

        openapi_path = ROOT / "openapi" / "coinbase-admin-api.yaml"
        checks = [
            AdminGateCheck(
                name="openapi_schema_artifact",
                status=(
                    AdminApiGateStatus.PASSED
                    if openapi_path.exists()
                    else AdminApiGateStatus.BLOCKED
                ),
                detail=str(openapi_path),
            ),
            AdminGateCheck(
                name="backend_regression_gate",
                status=AdminApiGateStatus.NOT_APPLICABLE,
                detail="The browser may view release status, but it must not run pytest.",
            ),
            AdminGateCheck(
                name="live_coinbase_execution",
                status=AdminApiGateStatus.PASSED,
                detail="No live Coinbase execution is performed by this read route.",
            ),
        ]
        status = (
            AdminApiGateStatus.BLOCKED
            if any(check.status == AdminApiGateStatus.BLOCKED for check in checks)
            else AdminApiGateStatus.PASSED
        )
        return AdminGateReadResponse(
            type="admin_release_gate",
            status=status,
            checks=checks,
        )

    def build_recovery_gate(self) -> AdminGateReadResponse:
        """Return recovery-readiness route evidence."""

        return AdminGateReadResponse(
            type="admin_recovery_gate",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="direct_order_audit_route",
                    status=AdminApiGateStatus.PASSED,
                    detail="/api/v1/spot/direct-orders/{client_order_id}/audit is read-only.",
                ),
                AdminGateCheck(
                    name="repair_mutations",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Recovery repair actions remain outside the frontend mutation surface.",
                ),
            ],
        )

    def build_fill_ledger_health(self) -> AdminGateReadResponse:
        """Return fill-ledger health posture without mutating ledger rows."""

        return AdminGateReadResponse(
            type="admin_fill_ledger_health",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="read_surface",
                    status=AdminApiGateStatus.PASSED,
                    detail="Fill-ledger health is exposed as a read-only contract.",
                ),
                AdminGateCheck(
                    name="repair_surface",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Ledger repair remains CLI/operator controlled, not browser-triggered.",
                ),
                AdminGateCheck(
                    name="observed_at",
                    status=AdminApiGateStatus.PASSED,
                    detail=_now_iso(),
                ),
            ],
        )

    def build_frontend_fixtures(self) -> AdminFrontendFixturesResponse:
        """Return backend-owned fixtures for frontend mock alignment."""

        return AdminFrontendFixturesResponse(
            schema_version=SCHEMA_VERSION,
            fixtures={
                "admin.bootstrap": self.build_admin_bootstrap().model_dump(mode="json"),
                "admin.health": self.build_admin_health().model_dump(mode="json"),
                "admin.capabilities": self.build_admin_capabilities().model_dump(mode="json"),
                "orders.list": self.build_order_list().model_dump(mode="json"),
                "orders.detail.empty": self.build_order_detail(
                    client_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "release.gate": self.build_release_gate().model_dump(mode="json"),
                "recovery.gate": self.build_recovery_gate().model_dump(mode="json"),
                "fillLedger.health": self.build_fill_ledger_health().model_dump(mode="json"),
            },
        )

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
