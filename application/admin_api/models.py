"""Typed Admin API command contracts.

These models describe the enterprise API boundary. They do not submit orders
or mutate exchange state by themselves.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiErrorCode,
    AdminApiErrorSeverity,
    AdminApiAuthMode,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiRole,
    AdminApiSessionStatus,
    AdminApiVerifierReadinessStatus,
    OrderSide,
    OrderType,
    TimeInForce,
)


DecimalString = Annotated[
    str,
    Field(
        pattern=r"^-?(0|[1-9]\d*)(\.\d+)?$",
        description="Decimal value serialized as a string; floats are not part of the API contract.",
        examples=["1.00"],
    ),
]


class AdminApiActor(BaseModel):
    """Authenticated actor evidence supplied by future auth middleware."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    roles: list[AdminApiRole] = Field(default_factory=list)


class AdminApiCommandEnvelope(BaseModel):
    """Headers and actor evidence common to mutating command routes."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    actor: AdminApiActor


class ManualOrderRequest(BaseModel):
    """Manual order request shape for future enterprise placement."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    side: OrderSide
    order_type: OrderType
    base_size: DecimalString | None = None
    quote_size: DecimalString | None = None
    limit_price: DecimalString | None = None
    post_only: bool = False
    time_in_force: TimeInForce | None = None
    manual_live_acknowledgement: bool = False


class CancelOrderRequest(BaseModel):
    """Cancel request body keyed by path ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class CampaignExecutionRequest(BaseModel):
    """Campaign execution request shape for future gated spot campaigns."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1, examples=["usdc-sweep-001"])
    side: OrderSide
    quote_notional_per_product: DecimalString | None = None
    product_ids: list[str] | None = None
    max_products: int | None = Field(default=None, ge=1)
    dry_run: bool = True
    manual_live_acknowledgement: bool = False


class ManualOrderCommand(BaseModel):
    """Shared service command for manual placement."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: ManualOrderRequest
    order_configuration_override: dict[str, Any] | None = None
    allow_live_execution: bool = False


class CancelOrderCommand(BaseModel):
    """Shared service command for cancel-by-client-order-id."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    client_order_id: str = Field(min_length=1)
    request: CancelOrderRequest
    allow_live_execution: bool = False


class CampaignExecutionCommand(BaseModel):
    """Shared service command for campaign execution."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: CampaignExecutionRequest
    allow_live_execution: bool = False


class AdminApiCommandResponse(BaseModel):
    """Typed response returned by Admin API command adapters."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiCommandStatus
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission
    service_method: str
    message: str
    client_order_id: str | None = None
    coinbase_order_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    live_exchange_submitted: bool = False
    submission_event_recorded: bool | None = None
    audit_command: str | None = None
    guard: dict[str, Any] | None = None
    data: Any | None = None
    failure_stage: str | None = None


class AdminApiErrorResponse(BaseModel):
    """Structured error body shared by Admin API routes."""

    model_config = ConfigDict(extra="forbid")

    code: AdminApiErrorCode
    message: str
    severity: AdminApiErrorSeverity
    guard_name: str | None = None
    field_path: str | None = None
    correlation_id: str | None = None
    audit_id: str | None = None
    live_coinbase_orders_ran: bool = False


class AdminApiRouteDiagnostic(BaseModel):
    """Health diagnostic for one route surface."""

    model_config = ConfigDict(extra="forbid")

    path: str
    method: str
    status: AdminApiRouteAvailability
    message: str


class AdminBootstrapResponse(BaseModel):
    """Frontend bootstrap payload for backend association and safety posture."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_bootstrap"
    backend_repository: str
    api_version: str
    schema_version: str
    environment: str
    mutating_routes_live_disabled: bool
    live_execution_enabled: bool
    auth_required: bool
    auth_mode: AdminApiAuthMode
    cors_configured: bool
    csrf_required: bool
    csrf_header_name: str = "X-CSRF-Token"
    capabilities_route: str
    session_route: str
    live_coinbase_orders_ran: bool = False


class AdminHealthResponse(BaseModel):
    """Read-only backend health and diagnostics payload."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_health"
    status: AdminApiHealthStatus
    api_version: str
    diagnostics: list[AdminApiRouteDiagnostic] = Field(default_factory=list)
    failed_route_count: int = 0
    live_execution_enabled: bool = False
    live_coinbase_orders_ran: bool = False


class AdminSessionResponse(BaseModel):
    """Authenticated session/RBAC evidence for the frontend."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_session"
    status: AdminApiSessionStatus
    actor: AdminApiActor
    permissions: list[AdminApiPermission] = Field(default_factory=list)
    auth_mode: AdminApiAuthMode
    bearer_token_visible_to_browser: bool = False
    live_coinbase_orders_ran: bool = False


class AdminOidcJwtReadinessResponse(BaseModel):
    """Backend OIDC/JWT verifier readiness evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_oidc_jwt_readiness"
    active_auth_mode: AdminApiAuthMode
    mode: AdminApiAuthMode
    status: AdminApiVerifierReadinessStatus
    verifier_implemented: bool
    required_env_vars: list[str]
    missing_env_vars: list[str] = Field(default_factory=list)
    claims_contract: dict[str, str]
    failure_reason: str | None = None
    jwks_reachability: str
    jwks_failure_reason: str | None = None
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    live_coinbase_orders_ran: bool = False


class AdminCapabilityItem(BaseModel):
    """One backend-owned capability advertised to the frontend."""

    model_config = ConfigDict(extra="forbid")

    route: str
    method: str
    action_class: AdminApiActionClass
    permission: AdminApiPermission | str
    availability: AdminApiRouteAvailability
    live_enabled: bool
    frontend_safe: bool
    shared_method: str
    notes: str


class AdminCapabilityRegistryResponse(BaseModel):
    """Route/capability registry for frontend navigation and diagnostics."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_capabilities"
    capabilities: list[AdminCapabilityItem] = Field(default_factory=list)
    live_coinbase_orders_ran: bool = False


class AdminOrderReadItem(BaseModel):
    """Read-only order row keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    product_id: str | None = None
    side: str | None = None
    status: str | None = None
    order_type: str | None = None
    size: str | None = None
    price: str | None = None
    parent_client_order_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    correlation_id: str | None = None
    audit_id: str | None = None
    source: str = "order_parent"


class AdminOrderPagination(BaseModel):
    """Pagination evidence for order list reads."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    total_matching_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    has_more: bool = False


class AdminOrderListResponse(BaseModel):
    """Read-only order list/filter response."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_order_list"
    filters: dict[str, Any] = Field(default_factory=dict)
    count: int
    pagination: AdminOrderPagination
    items: list[AdminOrderReadItem] = Field(default_factory=list)
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class AdminOrderDetailResponse(BaseModel):
    """Read-only order detail response keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_order_detail"
    client_order_id: str
    found: bool
    order: AdminOrderReadItem | None = None
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class AdminGateCheck(BaseModel):
    """One release/recovery check exposed to the frontend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: AdminApiGateStatus
    detail: str


class AdminGateReadResponse(BaseModel):
    """Read-only gate response for release and recovery views."""

    model_config = ConfigDict(extra="forbid")

    type: str
    status: AdminApiGateStatus
    checks: list[AdminGateCheck] = Field(default_factory=list)
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class AdminFrontendFixturesResponse(BaseModel):
    """Backend-owned fixture examples for frontend mock synchronization."""

    model_config = ConfigDict(extra="allow")

    type: str = "admin_frontend_fixtures"
    schema_version: str
    fixtures: dict[str, Any] = Field(default_factory=dict)
    live_coinbase_orders_ran: bool = False


class AdminCsrfContractResponse(BaseModel):
    """Read-only CSRF contract for BFF/session deployments."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_csrf_contract"
    csrf_required: bool
    csrf_header_name: str = "X-CSRF-Token"
    token_issued_by_backend: bool = False
    token_visible_to_browser: bool = False
    token_source: str = "session_or_bff_boundary"
    rotation_policy: str = "rotate_on_session_or_deploy_secret_change"
    live_coinbase_orders_ran: bool = False


class AdminApiReadPayload(BaseModel):
    """Loose typed shell for existing dashboard-shaped read-only payloads."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    status: str | None = None
    live_coinbase_orders_ran: bool = False


class AdminApiFlexibleObject(BaseModel):
    """Typed object shell that preserves dashboard-owned read payload detail."""

    model_config = ConfigDict(extra="allow")


class SpotReadinessResponse(AdminApiReadPayload):
    """Spot readiness response."""

    products: list[AdminApiFlexibleObject | str] = Field(default_factory=list)
    planned_budget: AdminApiFlexibleObject = Field(default_factory=AdminApiFlexibleObject)
    wallet_snapshot: AdminApiFlexibleObject | None = None
    action_guard_summary: list[AdminApiFlexibleObject] = Field(default_factory=list)
    message: str | None = None


class SpotSweepStatusResponse(AdminApiReadPayload):
    """Spot sweep status response."""

    operator_status: AdminApiFlexibleObject | None = None
    state_file: str | None = None
    message: str | None = None


class SpotSweepPnlResponse(AdminApiReadPayload):
    """Spot sweep P/L response."""

    pnl_report: AdminApiFlexibleObject | None = None
    read_only_coinbase_requests: list[str] = Field(default_factory=list)
    message: str | None = None


class SpotCostBasisStatusResponse(AdminApiReadPayload):
    """Spot cost-basis status response."""

    operator_status: AdminApiFlexibleObject | None = None
    state_file: str | None = None
    message: str | None = None


class SpotCampaignStatusResponse(AdminApiReadPayload):
    """Spot campaign status response."""

    operator_status: AdminApiFlexibleObject | None = None
    state_file: str | None = None
    message: str | None = None


class SpotDirectOrderAuditResponse(AdminApiReadPayload):
    """Direct spot order audit response keyed by ``client_order_id``."""

    client_order_id: str | None = None
    audit: AdminApiFlexibleObject | None = None
    events: list[AdminApiFlexibleObject] = Field(default_factory=list)
    fills: list[AdminApiFlexibleObject] = Field(default_factory=list)
    message: str | None = None


class AdminApiRouteInventoryItem(BaseModel):
    """Route/message inventory row used by docs and regression tests."""

    model_config = ConfigDict(extra="forbid")

    surface: str
    action_class: AdminApiActionClass
    permission: AdminApiPermission | str
    idempotency: str
    approval: str
    caps: str
    audit: str
    shared_method: str
    parity_test: str
    compatibility_mode: str | None = None
