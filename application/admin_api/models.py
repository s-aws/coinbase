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
    AdminApiCommandRoutesMode,
    AdminApiErrorCode,
    AdminApiErrorSeverity,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminApiAuthMode,
    AdminFuturesEvidenceSource,
    AdminFuturesEvidenceStatus,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminApiLiveAdmissionAuditFact,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveApprovalStoreRequirement,
    AdminApiLiveApprovalSnapshotField,
    AdminApiLiveCapGuardRequirement,
    AdminApiLiveExecutionStatus,
    AdminApiLivePreflightCategory,
    AdminMovementRepricingEvidenceType,
    AdminApiModuleSupportStatus,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiRole,
    AdminApiSessionStatus,
    AdminApiVerifierReadinessStatus,
    AdminFuturesPositionSide,
    AdminRiskEvidenceSource,
    AdminRiskEvidenceStatus,
    ActionConditionType,
    ActionGuardPhase,
    OrderSide,
    OrderType,
    ProductCapability,
    ProductType,
    StealthMutationKind,
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
FlexibleDict = Annotated[
    dict[str, Any],
    Field(json_schema_extra={"additionalProperties": True}),
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


class AdminLiveExecutionIntentEvidence(BaseModel):
    """Evidence-only command-to-live-execution intent envelope."""

    model_config = ConfigDict(extra="forbid")

    required: bool = True
    prepared: bool = False
    backend_owned: bool = True
    route_bound: bool = True
    payload_bound: bool = True
    idempotency_bound: bool = True
    executable: bool = False
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "disabled_backend_service"
    missing_reason: str | None = "live_execution_disabled"
    module_id: str
    route: str
    method: str
    identity_key: str
    identity_value: str | None = None
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    adapter_reference: str
    actor_id: str
    idempotency_key: str
    operator_intent: str
    payload_hash: str
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    blockers: list[AdminApiLiveAdmissionBlocker] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveAdmissionDecisionEvidence(BaseModel):
    """Route-bound live admission decision for a command attempt."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    allowed: bool = False
    route: str
    method: str
    module_id: str
    identity_key: str
    identity_value: str | None = None
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    idempotency_key: str
    operator_intent: str
    payload_hash: str
    approval_snapshot_required: bool = True
    approval_store_required: bool = True
    admission_audit_required: bool = True
    cap_guard_required: bool = True
    reconciliation_required: bool = True
    approval_snapshot_present: bool = False
    approval_snapshot_id: str | None = None
    approval_snapshot_source: str = "missing"
    approval_snapshot_approved_by_actor_id: str | None = None
    approval_snapshot_requested_by_actor_id: str | None = None
    approval_snapshot_expires_at: str | None = None
    approval_snapshot_missing_reason: str | None = None
    admission_audit_present: bool = False
    admission_audit_id: str | None = None
    admission_audit_source: str = "missing"
    admission_audit_recorded_at: str | None = None
    admission_audit_missing_reason: str | None = None
    cap_guard_present: bool = False
    cap_guard_decision_id: str | None = None
    cap_guard_source: str = "missing"
    cap_guard_recorded_at: str | None = None
    cap_guard_missing_reason: str | None = None
    reconciliation_plan_present: bool = False
    reconciliation_plan_id: str | None = None
    reconciliation_plan_source: str = "missing"
    reconciliation_plan_recorded_at: str | None = None
    reconciliation_plan_missing_reason: str | None = None
    live_execution_service_required: bool = True
    live_execution_service_present: bool = False
    live_execution_service_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    live_execution_service_source: str = "not_configured"
    live_execution_service_missing_reason: str | None = "live_execution_disabled"
    browser_authority: str = "rejected"
    live_exchange_submitted: bool = False
    live_execution_intent: AdminLiveExecutionIntentEvidence | None = None
    blockers: list[AdminApiLiveAdmissionBlocker] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class ManualOrderRequest(BaseModel):
    """Manual order request shape for future enterprise placement."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str | None = Field(default=None, min_length=1)
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


class StealthCancelRequest(BaseModel):
    """Stealth cancel request body keyed by path ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class MovementRepriceRequest(BaseModel):
    """Movement/reprice request body keyed by path ``stealth_order_id``."""

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


class StealthCancelCommand(BaseModel):
    """Shared service command for cancel-by-stealth-order-id."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthCancelRequest
    allow_live_execution: bool = False


class MovementRepriceCommand(BaseModel):
    """Shared service command for live-disabled stealth repricing."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: MovementRepriceRequest
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
    stealth_order_id: str | None = None
    coinbase_order_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    live_exchange_submitted: bool = False
    submission_event_recorded: bool | None = None
    audit_command: str | None = None
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    guard: FlexibleDict | None = None
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

    module_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    permission: AdminApiPermission | str
    availability: AdminApiRouteAvailability
    live_enabled: bool
    frontend_safe: bool
    shared_method: str
    idempotency: str
    approval: str
    caps: str
    audit: str
    command_contract: bool = False
    compatibility_mode: str | None = None
    parity_test: str
    notes: str


class AdminCapabilityRegistryResponse(BaseModel):
    """Route/capability registry for frontend navigation and diagnostics."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_capabilities"
    capabilities: list[AdminCapabilityItem] = Field(default_factory=list)
    live_coinbase_orders_ran: bool = False


class AdminEnterpriseCommandGapItem(BaseModel):
    """Structured evidence for a command path that is blocked or not modeled."""

    model_config = ConfigDict(extra="forbid")

    action: str
    status: AdminApiModuleSupportStatus
    reason: str
    required_backend_contract: str
    frontend_boundary: str
    live_coinbase_execution: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.NOT_RUN
    notional_usdc: DecimalString = "0"


class AdminEnterpriseModuleActionPosture(BaseModel):
    """Backend-derived action posture for one enterprise admin module."""

    model_config = ConfigDict(extra="forbid")

    module_id: str
    support_status: AdminApiModuleSupportStatus
    read_route_count: int = Field(ge=0)
    command_route_count: int = Field(ge=0)
    live_route_count: int = Field(ge=0)
    evidence_route_count: int = Field(ge=0)
    unsupported_action_count: int = Field(ge=0)
    command_gap_count: int = Field(ge=0)
    route_module_id_status: AdminApiGateStatus
    route_module_id_detail: str
    frontend_authority: str = "backend_contract_only"
    live_coinbase_execution: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.NOT_RUN
    notional_usdc: DecimalString = "0"


class AdminEnterpriseReadinessModuleItem(BaseModel):
    """One module's enterprise admin readiness posture."""

    model_config = ConfigDict(extra="forbid")

    module_id: str
    module: str
    primary_owner: str
    support_status: AdminApiModuleSupportStatus
    read_routes: list[str] = Field(default_factory=list)
    command_routes: list[str] = Field(default_factory=list)
    live_routes: list[str] = Field(default_factory=list)
    unsupported_actions: list[str] = Field(default_factory=list)
    command_gaps: list[AdminEnterpriseCommandGapItem] = Field(default_factory=list)
    identity_keys: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    evidence_routes: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    backend_contract_refs: list[str] = Field(default_factory=list)
    frontend_contract_refs: list[str] = Field(default_factory=list)
    documentation_refs: list[str] = Field(default_factory=list)
    spot_rule_boundary: str
    action_posture: AdminEnterpriseModuleActionPosture


class AdminEnterpriseReadinessResponse(BaseModel):
    """M9 enterprise readiness evidence for the whole admin platform."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_enterprise_readiness"
    candidate: str = "enterprise_admin_m9"
    approved_phase_range: str
    status: AdminApiGateStatus
    module_count: int = 0
    supported_module_count: int = 0
    unsupported_module_count: int = 0
    command_gap_count: int = 0
    module_registry_count: int = 0
    module_action_posture_count: int = 0
    modules: list[AdminEnterpriseReadinessModuleItem] = Field(default_factory=list)
    security_checks: list[AdminGateCheck] = Field(default_factory=list)
    release_checks: list[AdminGateCheck] = Field(default_factory=list)
    frontend_authority: str = "backend_contract_only"
    live_posture: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    default_live_coinbase_execution: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.NOT_RUN
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    read_only: bool = True
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
    filters: FlexibleDict = Field(default_factory=dict)
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


class AdminStealthOrderReadItem(BaseModel):
    """Read-only stealth order evidence from ``stealth_orders``."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    parent_stealth_order_id: str | None = None
    product_id: str | None = None
    side: str | None = None
    status: str | None = None
    total_size: str | None = None
    revealed_size: str | None = None
    remaining_size: str | None = None
    executed_size: str | None = None
    limit_price: str | None = None
    target_movement: str | None = None
    target_movement_type: str | None = None
    visibility_score: str | None = None
    reveal_condition_type: str | None = None
    reveal_condition: FlexibleDict | None = None
    sizing_strategy: FlexibleDict | None = None
    revealed_orders: list[FlexibleDict] = Field(default_factory=list)
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    last_placement_at: str | None = None
    last_lifecycle_event: str | None = None
    failure_reason: str | None = None
    cancel_reentry_policy: FlexibleDict | None = None
    cancel_reentry_state: FlexibleDict | None = None
    post_fill_retreat_policy: FlexibleDict | None = None
    anchor_repricing_policy: FlexibleDict | None = None
    anchor_repricing_state: FlexibleDict | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source: str = "stealth_orders"


class AdminStealthOrderListResponse(BaseModel):
    """Read-only stealth order list/filter response."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_stealth_order_list"
    filters: FlexibleDict = Field(default_factory=dict)
    count: int
    pagination: AdminOrderPagination
    items: list[AdminStealthOrderReadItem] = Field(default_factory=list)
    read_only: bool = True
    command_routes_mode: AdminApiCommandRoutesMode = AdminApiCommandRoutesMode.LIVE_DISABLED
    live_coinbase_orders_ran: bool = False


class AdminStealthOrderDetailResponse(BaseModel):
    """Read-only stealth detail response keyed by ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_stealth_order_detail"
    stealth_order_id: str
    found: bool
    order: AdminStealthOrderReadItem | None = None
    read_only: bool = True
    command_routes_mode: AdminApiCommandRoutesMode = AdminApiCommandRoutesMode.LIVE_DISABLED
    live_coinbase_orders_ran: bool = False


class AdminMutationClaimEvidence(BaseModel):
    """Runtime claim evidence for repeatable stealth mutations."""

    model_config = ConfigDict(extra="forbid")

    kind: StealthMutationKind
    state: str | None = None
    runtime_observed: bool = False
    source: str


class AdminReplacementSlotEvidence(BaseModel):
    """Replacement-slot evidence for a parent/placement client id."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str | None = None
    max_order_replacement: int | None = None
    current_order_replacement: int | None = None
    pending_replacement_claims: int | None = None
    pending_claims_runtime_observed: bool = False
    source: str


class AdminMovementRepricingEvidenceItem(BaseModel):
    """Read-only movement/repricing evidence from durable and runtime-safe sources."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: AdminMovementRepricingEvidenceType
    client_order_id: str | None = None
    original_parent_client_order_id: str | None = None
    new_parent_client_order_id: str | None = None
    stealth_order_id: str | None = None
    product_id: str | None = None
    side: str | None = None
    status: str | None = None
    move_on_cancel: bool | None = None
    reason: str | None = None
    notes: str | None = None
    old_placement_client_order_id: str | None = None
    old_exchange_order_id: str | None = None
    old_submitted_price: str | None = None
    new_placement_client_order_id: str | None = None
    new_exchange_order_id: str | None = None
    new_submitted_price: str | None = None
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    active_exchange_price: str | None = None
    exchange_order_id_evidence_only: bool = True
    target_movement: str | None = None
    target_movement_type: str | None = None
    replacement_slots: list[AdminReplacementSlotEvidence] = Field(default_factory=list)
    mutation_claims: list[AdminMutationClaimEvidence] = Field(default_factory=list)
    anchor_repricing_policy: FlexibleDict | None = None
    anchor_repricing_state: FlexibleDict | None = None
    reprice_history: list[Any] = Field(default_factory=list)
    reprice_reason: str | None = None
    last_reprice_at: str | None = None
    next_reprice_at: str | None = None
    post_fill_retreat_offset: str | None = None
    market_bid: str | None = None
    market_ask: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    moved_at: str | None = None
    source: str


class AdminMovementRepricingListResponse(BaseModel):
    """Read-only movement/repricing evidence list response."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_movement_repricing_evidence"
    filters: FlexibleDict = Field(default_factory=dict)
    count: int
    pagination: AdminOrderPagination
    items: list[AdminMovementRepricingEvidenceItem] = Field(default_factory=list)
    read_only: bool = True
    command_routes_mode: AdminApiCommandRoutesMode = AdminApiCommandRoutesMode.LIVE_DISABLED
    live_coinbase_orders_ran: bool = False


class AdminMovementRepricingDetailResponse(BaseModel):
    """Read-only movement/repricing detail response for order or stealth scope."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_movement_repricing_detail"
    scope: str
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    found: bool
    items: list[AdminMovementRepricingEvidenceItem] = Field(default_factory=list)
    read_only: bool = True
    command_routes_mode: AdminApiCommandRoutesMode = AdminApiCommandRoutesMode.LIVE_DISABLED
    live_coinbase_orders_ran: bool = False


class AdminFuturesEvidenceItem(BaseModel):
    """One futures/perpetual evidence cell with explicit availability."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: AdminFuturesEvidenceStatus
    source: AdminFuturesEvidenceSource
    value: Any | None = None
    detail: str | None = None


class AdminFuturesPositionReadItem(BaseModel):
    """Read-only futures/perpetual position evidence keyed by position identity."""

    model_config = ConfigDict(extra="forbid")

    position_key: str
    product_id: str
    product_type: ProductType = ProductType.FUTURE
    portfolio_uuid: str | None = None
    position_side: AdminFuturesPositionSide | None = None
    number_of_contracts: str | None = None
    net_size: str | None = None
    entry_price: str | None = None
    entry_vwap: str | None = None
    current_price: str | None = None
    margin_type: str | None = None
    margin_amount: FlexibleDict | None = None
    leverage: str | None = None
    liquidation_buffer_percentage: str | None = None
    open_order_side: OrderSide | None = None
    close_order_side: OrderSide | None = None
    reduce_only_order_side: OrderSide | None = None
    close_only_order_side: OrderSide | None = None
    position_pnl: FlexibleDict | None = None
    product_metadata: FlexibleDict | None = None
    mandatory_fee_per_contract: str | None = None
    raw_position: FlexibleDict = Field(default_factory=dict)
    source: AdminFuturesEvidenceSource = AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK
    updated_at: str | None = None


class AdminFuturesPositionListResponse(BaseModel):
    """Read-only futures/perpetual position list response."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_futures_positions"
    filters: FlexibleDict = Field(default_factory=dict)
    count: int
    pagination: AdminOrderPagination
    items: list[AdminFuturesPositionReadItem] = Field(default_factory=list)
    read_only: bool = True
    command_routes_mode: str = "not_modeled"
    live_coinbase_orders_ran: bool = False


class AdminFuturesPositionDetailResponse(BaseModel):
    """Read-only futures/perpetual position detail response."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_futures_position_detail"
    position_key: str
    found: bool
    position: AdminFuturesPositionReadItem | None = None
    read_only: bool = True
    command_routes_mode: str = "not_modeled"
    live_coinbase_orders_ran: bool = False


class AdminFuturesAccountReadResponse(BaseModel):
    """Read-only futures/perpetual account, collateral, margin, and risk evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_futures_account"
    configured_product_scope: list[str] = Field(default_factory=list)
    observed_position_scope: list[str] = Field(default_factory=list)
    collateral: AdminFuturesEvidenceItem
    margin: AdminFuturesEvidenceItem
    funding: AdminFuturesEvidenceItem
    liquidation: AdminFuturesEvidenceItem
    reduce_only_close_only: AdminFuturesEvidenceItem
    position_pnl: AdminFuturesEvidenceItem
    position_count: int = 0
    read_only: bool = True
    command_routes_mode: str = "not_modeled"
    live_coinbase_orders_ran: bool = False


class AdminRiskEvidenceItem(BaseModel):
    """One backend-owned guard/risk evidence cell."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: AdminRiskEvidenceStatus
    source: AdminRiskEvidenceSource
    value: Any | None = None
    detail: str | None = None


class AdminRiskPolicyRuleItem(BaseModel):
    """One configured action-condition limit/cap rule."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    enabled: bool = True
    product_id: str | None = None
    product_type: ProductType | str | None = None
    side: OrderSide | str | None = None
    phases: list[ActionGuardPhase | str] = Field(default_factory=list)
    max_notional: DecimalString | None = None
    max_base_size: DecimalString | None = None
    raw_rule: FlexibleDict = Field(default_factory=dict)


class AdminRiskRejectionCategoryItem(BaseModel):
    """Backend-owned guard rejection category shown as evidence only."""

    model_config = ConfigDict(extra="forbid")

    condition: ActionConditionType
    source: AdminRiskEvidenceSource
    applies_to_product_type: ProductType | str | None = None
    blocks_before_exchange: bool = True
    detail: str


class AdminProductCapabilityDecisionItem(BaseModel):
    """Read-only product capability policy decision for one capability."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_type: ProductType | str
    capability: ProductCapability
    mode: str
    allowed: bool
    reason: str


class AdminRiskPolicyReadResponse(BaseModel):
    """Read-only guard/risk policy evidence for Admin API modules."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_guard_risk_policy"
    filters: FlexibleDict = Field(default_factory=dict)
    action_condition_policy: AdminRiskEvidenceItem
    configured_limit_rules: list[AdminRiskPolicyRuleItem] = Field(default_factory=list)
    live_execution_gate: AdminRiskEvidenceItem
    product_capability_policy: AdminRiskEvidenceItem
    product_capability_decisions: list[AdminProductCapabilityDecisionItem] = Field(default_factory=list)
    profitability_policy: AdminRiskEvidenceItem
    authority_sources: list[AdminRiskEvidenceItem] = Field(default_factory=list)
    rejection_categories: list[AdminRiskRejectionCategoryItem] = Field(default_factory=list)
    read_only: bool = True
    command_routes_mode: str = "not_modeled"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False


class AdminAuditModuleSummaryItem(BaseModel):
    """Cross-module audit workbench summary for one admin module."""

    model_config = ConfigDict(extra="forbid")

    module: AdminAuditWorkbenchModule
    read_route_count: int = 0
    command_route_count: int = 0
    live_enabled: bool = False
    primary_identity: str
    evidence_sources: list[AdminAuditEvidenceSource] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    notes: str | None = None


class AdminAuditWorkbenchEventItem(BaseModel):
    """One normalized cross-module audit/correlation evidence row."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    module: AdminAuditWorkbenchModule
    source: AdminAuditEvidenceSource
    action_class: AdminApiActionClass | None = None
    endpoint: str | None = None
    status: str | None = None
    actor_id: str | None = None
    permission: AdminApiPermission | str | None = None
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    position_key: str | None = None
    product_id: str | None = None
    correlation_id: str | None = None
    audit_id: str | None = None
    request_id: str | None = None
    operator_intent: str | None = None
    idempotency_key: str | None = None
    exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    recorded_at: str | None = None
    message: str | None = None
    admission_decision: FlexibleDict | None = None
    live_coinbase_orders_ran: bool = False
    raw_event: FlexibleDict = Field(default_factory=dict)


class AdminAuditWorkbenchReadResponse(BaseModel):
    """Read-only cross-module audit and correlation workbench."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_audit_workbench"
    filters: FlexibleDict = Field(default_factory=dict)
    module_summary: list[AdminAuditModuleSummaryItem] = Field(default_factory=list)
    events: list[AdminAuditWorkbenchEventItem] = Field(default_factory=list)
    pagination: AdminOrderPagination
    read_only: bool = True
    command_routes_mode: str = "evidence_only"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False


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
    fixtures: FlexibleDict = Field(default_factory=dict)
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


class AdminLivePreflightCheckItem(BaseModel):
    """One controlled-live preflight check for a live-shaped route."""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: AdminApiLivePreflightCategory
    status: AdminApiGateStatus
    required: bool = True
    blocking: bool = True
    owner: str
    evidence: str
    detail: str


class AdminLiveApprovalSnapshotRequiredFieldItem(BaseModel):
    """One field required by a future route-specific live approval snapshot."""

    model_config = ConfigDict(extra="forbid")

    field: AdminApiLiveApprovalSnapshotField
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    expected_source: str
    expected_value: str | None = None
    detail: str


class AdminLiveApprovalSnapshotEvidence(BaseModel):
    """Read-only evidence for a route's missing live approval snapshot."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    present: bool = False
    durable: bool = False
    route_specific: bool = True
    backend_owned: bool = True
    browser_authority: str = "display_only"
    source: str = "not_configured"
    required_field_count: int = 0
    missing_required_field_count: int = 0
    required_fields: list[AdminLiveApprovalSnapshotRequiredFieldItem] = Field(
        default_factory=list
    )
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveApprovalStoreRequirementItem(BaseModel):
    """One behavior required from a future durable approval store."""

    model_config = ConfigDict(extra="forbid")

    requirement: AdminApiLiveApprovalStoreRequirement
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    expected_source: str
    expected_value: str | None = None
    detail: str


class AdminLiveApprovalStoreContractEvidence(BaseModel):
    """Read-only evidence for the missing live approval store contract."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    configured: bool = False
    durable: bool = False
    backend_owned: bool = True
    browser_authority: str = "display_only"
    source: str = "not_configured"
    requirement_count: int = 0
    missing_requirement_count: int = 0
    requirements: list[AdminLiveApprovalStoreRequirementItem] = Field(
        default_factory=list
    )
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveAdmissionAuditFactItem(BaseModel):
    """One fact required by a future live-admission audit trail."""

    model_config = ConfigDict(extra="forbid")

    fact: AdminApiLiveAdmissionAuditFact
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    expected_source: str
    expected_value: str | None = None
    detail: str


class AdminLiveAdmissionAuditTrailEvidence(BaseModel):
    """Read-only evidence for the missing live-admission audit trail."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    configured: bool = False
    append_only: bool = False
    backend_owned: bool = True
    browser_authority: str = "display_only"
    source: str = "not_configured"
    fact_count: int = 0
    missing_fact_count: int = 0
    facts: list[AdminLiveAdmissionAuditFactItem] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveCapGuardRequirementItem(BaseModel):
    """One binding required by a future live cap/guard decision."""

    model_config = ConfigDict(extra="forbid")

    requirement: AdminApiLiveCapGuardRequirement
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    expected_source: str
    expected_value: str | None = None
    detail: str


class AdminLiveCapGuardContractEvidence(BaseModel):
    """Read-only evidence for the missing route-specific cap/guard contract."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    configured: bool = False
    route_specific: bool = True
    backend_owned: bool = True
    browser_authority: str = "display_only"
    source: str = "not_configured"
    requirement_count: int = 0
    missing_requirement_count: int = 0
    requirements: list[AdminLiveCapGuardRequirementItem] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveExecutionAdapterContractEvidence(BaseModel):
    """Read-only evidence for the missing live execution adapter contract."""

    model_config = ConfigDict(extra="forbid")

    required: bool = True
    configured: bool = False
    backend_owned: bool = True
    route_bound: bool = True
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "disabled_backend_service"
    missing_reason: str = "live_execution_disabled"
    module_id: str
    route: str
    method: str
    service_method: str
    adapter_reference: str
    action_class: AdminApiActionClass
    executable: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    forbidden_methods: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveEnablementPathItem(BaseModel):
    """One live-eligible path and the gates required before enablement."""

    model_config = ConfigDict(extra="forbid")

    path_id: str
    route: str
    method: str
    module_id: str
    module: str
    module_owner: str
    identity_key: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    live_enabled: bool = False
    live_eligible: bool = False
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    governance_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    approval_required: bool = True
    cap_required: bool = True
    guard_required: bool = True
    audit_required: bool = True
    idempotency_key_required: bool = True
    operator_intent_required: bool = True
    payload_hash_required: bool = True
    request_id_required: bool = True
    audit_id_required: bool = True
    reconciliation_required: bool = True
    browser_authority: str = "display_only"
    capability_source: str = "GET /api/v1/admin/capabilities"
    readiness_source: str = "GET /api/v1/admin/enterprise-readiness"
    reconciliation_blockers: list[str] = Field(default_factory=list)
    spot_rule_boundary: str
    product_scope: str = "not_selected"
    max_submitted_notional_usdc: DecimalString | None = None
    max_executed_notional_usdc: DecimalString | None = None
    preflight_checks: list[AdminLivePreflightCheckItem] = Field(default_factory=list)
    blocking_preflight_check_count: int = 0
    passed_preflight_check_count: int = 0
    approval_snapshot: AdminLiveApprovalSnapshotEvidence
    approval_store_contract: AdminLiveApprovalStoreContractEvidence
    admission_audit_trail: AdminLiveAdmissionAuditTrailEvidence
    cap_guard_contract: AdminLiveCapGuardContractEvidence
    live_execution_adapter: AdminLiveExecutionAdapterContractEvidence
    evidence: list[str] = Field(default_factory=list)
    notes: str


class AdminLiveEnablementReadResponse(BaseModel):
    """Read-only M8 live-enablement readiness and cap evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_live_enablement"
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    approved_phase_range: str
    default_live_coinbase_execution: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.NOT_RUN
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    quote_currency: str = "USDC"
    product_scope: str
    max_submitted_notional_usdc: DecimalString
    max_executed_notional_usdc: DecimalString
    retain_inventory: bool = True
    reconciliation_required: bool = True
    live_enabled_path_count: int = 0
    live_eligible_path_count: int = 0
    paths: list[AdminLiveEnablementPathItem] = Field(default_factory=list)
    checks: list[AdminGateCheck] = Field(default_factory=list)
    preflight_check_count: int = 0
    blocking_preflight_check_count: int = 0
    passed_preflight_check_count: int = 0
    approval_snapshot_required_count: int = 0
    approval_snapshot_present_count: int = 0
    approval_snapshot_missing_count: int = 0
    approval_snapshot_required_field_count: int = 0
    approval_snapshot_missing_field_count: int = 0
    approval_store_required_count: int = 0
    approval_store_configured_count: int = 0
    approval_store_missing_count: int = 0
    approval_store_requirement_count: int = 0
    approval_store_missing_requirement_count: int = 0
    admission_audit_required_count: int = 0
    admission_audit_configured_count: int = 0
    admission_audit_missing_count: int = 0
    admission_audit_fact_count: int = 0
    admission_audit_missing_fact_count: int = 0
    cap_guard_required_count: int = 0
    cap_guard_configured_count: int = 0
    cap_guard_missing_count: int = 0
    cap_guard_requirement_count: int = 0
    cap_guard_missing_requirement_count: int = 0
    live_execution_adapter_required_count: int = 0
    live_execution_adapter_configured_count: int = 0
    live_execution_adapter_missing_count: int = 0
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class AdminApiReadPayload(BaseModel):
    """Loose typed shell for existing dashboard-shaped read-only payloads."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    status: str | None = None
    live_coinbase_orders_ran: bool = False


class AdminApiFlexibleObject(BaseModel):
    """Typed object shell that preserves backend-owned read payload detail."""

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

    module_id: str
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
