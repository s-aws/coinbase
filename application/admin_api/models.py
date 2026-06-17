"""Typed Admin API command contracts.

These models describe the enterprise API boundary. They do not submit orders
or mutate exchange state by themselves.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleStatus,
    AdminApiCommandStatus,
    AdminApiCommandRoutesMode,
    AdminApiErrorCode,
    AdminApiErrorSeverity,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminApiAuthMode,
    AdminApiFunctionalityExposureStatus,
    AdminApiFunctionalityWorkflowType,
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
    AdminApiLiveReadinessPrecondition,
    AdminMovementRepricingEvidenceType,
    AdminApiMutationFamilyType,
    AdminApiModuleSupportStatus,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiRole,
    AdminApiSessionStatus,
    AdminApiSpotCommandSuiteGapFamily,
    AdminApiStealthAdmissionContextField,
    AdminApiStealthAdmissionEvidence,
    AdminApiStealthCommandSuiteGapFamily,
    AdminApiStealthDecisionResolutionEvidenceType,
    AdminApiStealthLiveReadinessDecision,
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
    SpotRecoveryExchangeStateSnapshotSource,
    SpotRecoveryCompletionState,
    SpotRecoveryRepairCategory,
    StealthExchangeTruthEvidenceSource,
    StealthCommandExecutionBlocker,
    StealthCommandExecutionPrerequisite,
    StealthCommandExecutionPrerequisiteLookupStatus,
    StealthCreateLifecycleExecutionBlocker,
    StealthCreateLifecycleExecutionPrerequisite,
    StealthCreateLifecycleExecutionPrerequisiteLookupStatus,
    StealthCoinbaseExchangePolicyEvidenceSource,
    StealthStateMutationPolicyEvidenceSource,
    StealthLifecycleWriteGuardEvidenceSource,
    StealthManagerPolicyEvidenceSource,
    StealthMutationClaimEvidenceSource,
    StealthMutationKind,
    StealthCancelReplaceProofEvidenceSource,
    StealthPostWriteReconciliationEvidenceSource,
    StealthPostWriteReconciliationExecutionPolicyEvidenceSource,
    StealthReconciliationProofEvidenceSource,
    StealthRevealTriggerEvidenceSource,
    StealthRecoveryProofEvidenceSource,
    TargetMovementType,
    TimeInForce,
)

SPOT_PNL_CHECKPOINT_LEGACY_AUDIT_DETAIL = (
    "Checkpoint does not include a verified Admin API audit link; treat it as "
    "legacy local checkpoint evidence until a linked record is written."
)
SPOT_PNL_CHECKPOINT_LEGACY_RECOVERY_DETAIL = (
    "Checkpoint does not include recovery-link evidence; use backend recovery "
    "gate and fill-ledger-health reads for operator triage before recording a "
    "linked checkpoint."
)
SPOT_PNL_CHECKPOINT_LEGACY_RECONCILIATION_DETAIL = (
    "Checkpoint does not include reconciliation-plan link evidence; use "
    "backend reconciliation plan reads for operator triage before recording a "
    "linked checkpoint."
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


class StealthCommandSuiteAdmissionContextItem(BaseModel):
    """One command-envelope field required before stealth admission lookup."""

    model_config = ConfigDict(extra="forbid")

    field_name: AdminApiStealthAdmissionContextField
    source: str
    required: bool = True
    present: bool = False
    blocking: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCommandAdmissionContextEvidence(BaseModel):
    """Exact command-envelope context evidence for stealth command responses."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_command_admission_context"
    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    module_id: str
    identity_key: str = "stealth_order_id"
    identity_value: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    required_context_count: int
    present_context_count: int
    missing_context_count: int = 0
    missing_context: list[str] = Field(default_factory=list)
    context_requirements: list[StealthCommandSuiteAdmissionContextItem] = Field(
        default_factory=list
    )
    exact_context_present: bool = True
    resolver_lookup_allowed: bool = True
    resolver_lookup_ran: bool = True
    proof_resolution_attempted: bool = True
    admission_decision_attached: bool = True
    admission_allowed: bool = False
    executable: bool = False
    live_enabled: bool = False
    coinbase_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
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


class StealthRevealRequest(BaseModel):
    """Stealth reveal request body keyed by path ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthMoveRequest(BaseModel):
    """Stealth move request body keyed by path ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    new_limit_price: DecimalString
    reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthRecoveryRequest(BaseModel):
    """Stealth recovery request body keyed by path ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    recovery_evidence_ref: str | None = Field(default=None, min_length=1)
    reason: str | None = None
    dry_run: bool = True
    manual_live_acknowledgement: bool = False


class StealthReconciliationRequest(BaseModel):
    """Stealth reconciliation request body keyed by path ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_plan_id: str | None = Field(default=None, min_length=1)
    reconciliation_proof_id: str | None = Field(default=None, min_length=1)
    reason: str | None = None
    dry_run: bool = True
    manual_live_acknowledgement: bool = False


class StealthActivePlacementExchangeTruthSnapshotRequest(BaseModel):
    """Stealth active-placement exchange-truth snapshot keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    active_placement_client_order_id: str | None = Field(default=None, min_length=1)
    active_exchange_order_id: str | None = Field(default=None, min_length=1)
    product_id: str | None = Field(default=None, min_length=1, examples=["BTC-USDC"])
    source_timestamp: str = Field(min_length=1)
    evidence_source: StealthExchangeTruthEvidenceSource
    snapshot_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    exchange_truth_snapshot_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthActivePlacementExchangeTruthProofRequest(BaseModel):
    """Stealth active-placement exchange-truth proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    exchange_truth_snapshot_id: str = Field(min_length=1)
    active_placement_client_order_id: str | None = Field(default=None, min_length=1)
    active_exchange_order_id: str | None = Field(default=None, min_length=1)
    exchange_truth_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    exchange_truth_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthCreateLifecycleWriteGuardProofRequest(BaseModel):
    """Stealth create lifecycle-write guard proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = "/api/v1/stealth/orders"
    guarded_command_method: str = "POST"
    guarded_service_method: str = "create_stealth_order"
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    side: OrderSide
    total_size: DecimalString
    limit_price: DecimalString
    evidence_source: StealthLifecycleWriteGuardEvidenceSource
    guard_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    lifecycle_write_guard_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthMutationClaimSnapshotProofRequest(BaseModel):
    """Stealth mutation-claim snapshot proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    mutation_kind: StealthMutationKind
    claim_reader_source: str = Field(min_length=1)
    runtime_claims_observed: bool = False
    runtime_claim_count: int = Field(default=0, ge=0)
    active_claim_count: int = Field(default=0, ge=0)
    evidence_source: StealthMutationClaimEvidenceSource
    snapshot_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    mutation_claim_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthManagerInvocationPolicyProofRequest(BaseModel):
    """Stealth manager-invocation policy proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    manager_policy_ref: str = Field(min_length=1)
    mutation_lock_policy_ref: str = Field(min_length=1)
    exchange_reality_policy_ref: str = Field(min_length=1)
    evidence_source: StealthManagerPolicyEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    manager_policy_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthCoinbaseExchangeSubmissionPolicyProofRequest(BaseModel):
    """Stealth Coinbase exchange submission-policy proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    exchange_submission_policy_ref: str = Field(min_length=1)
    coinbase_cancel_policy_ref: str = Field(min_length=1)
    live_coinbase_read_policy_ref: str = Field(min_length=1)
    live_cap_evidence_ref: str = Field(min_length=1)
    evidence_source: StealthCoinbaseExchangePolicyEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    coinbase_exchange_policy_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthStateMutationPolicyProofRequest(BaseModel):
    """Stealth state-mutation policy proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    state_mutation_policy_ref: str = Field(min_length=1)
    lifecycle_state_policy_ref: str = Field(min_length=1)
    order_state_policy_ref: str = Field(min_length=1)
    exchange_state_policy_ref: str = Field(min_length=1)
    post_write_reconciliation_policy_ref: str = Field(min_length=1)
    evidence_source: StealthStateMutationPolicyEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    state_mutation_policy_proof_id: str | None = Field(
        default=None,
        min_length=1,
    )
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthRevealTriggerProofRequest(BaseModel):
    """Stealth reveal-trigger proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    guarded_command_method: str = "POST"
    guarded_service_method: str = "reveal_stealth_order_by_stealth_order_id"
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    reveal_condition_ref: str = Field(min_length=1)
    trigger_evidence_ref: str = Field(min_length=1)
    condition_snapshot_ref: str = Field(min_length=1)
    evidence_source: StealthRevealTriggerEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reveal_trigger_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthRecoveryProofRequest(BaseModel):
    """Stealth recovery proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = "/api/v1/stealth/orders/{stealth_order_id}/recovery"
    guarded_command_method: str = "POST"
    guarded_service_method: str = "recover_stealth_order_by_stealth_order_id"
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    recovery_evidence_ref: str = Field(min_length=1)
    recovery_plan_ref: str = Field(min_length=1)
    evidence_source: StealthRecoveryProofEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    recovery_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthReconciliationProofRequest(BaseModel):
    """Stealth reconciliation proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = (
        "/api/v1/stealth/orders/{stealth_order_id}/reconciliation"
    )
    guarded_command_method: str = "POST"
    guarded_service_method: str = "reconcile_stealth_order_by_stealth_order_id"
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    reconciliation_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_ref: str = Field(min_length=1)
    active_placement_evidence_ref: str = Field(min_length=1)
    evidence_source: StealthReconciliationProofEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthCancelReplaceProofRequest(BaseModel):
    """Stealth cancel/replace proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    active_placement_evidence_ref: str = Field(min_length=1)
    mutation_claim_evidence_ref: str | None = Field(default=None, min_length=1)
    cancel_replace_evidence_ref: str = Field(min_length=1)
    evidence_source: StealthCancelReplaceProofEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    cancel_replace_proof_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthPostWriteReconciliationProofRequest(BaseModel):
    """Stealth post-write reconciliation proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    route_bound_reconciliation_plan_ref: str = Field(min_length=1)
    post_write_execution_journal_ref: str = Field(min_length=1)
    post_write_completion_proof_ref: str = Field(min_length=1)
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    post_write_reconciliation_proof_id: str | None = Field(
        default=None,
        min_length=1,
    )
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthPostWriteReconciliationExecutionPolicyProofRequest(BaseModel):
    """Stealth post-write reconciliation execution-policy proof keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    post_write_reconciliation_execution_policy_ref: str = Field(min_length=1)
    route_bound_reconciliation_plan_ref: str = Field(min_length=1)
    post_write_execution_journal_policy_ref: str = Field(min_length=1)
    post_write_reconciliation_verification_policy_ref: str = Field(min_length=1)
    safe_reconciliation_chain_ref: str = Field(min_length=1)
    evidence_source: StealthPostWriteReconciliationExecutionPolicyEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    post_write_reconciliation_policy_proof_id: str | None = Field(
        default=None,
        min_length=1,
    )
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthPostWriteExecutionJournalRequest(BaseModel):
    """Stealth post-write execution-journal acceptance keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    post_write_reconciliation_proof_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    post_write_execution_journal_ref: str = Field(min_length=1)
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    execution_journal_acceptance_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthPostWriteReconciliationVerificationRequest(BaseModel):
    """Stealth post-write reconciliation verification keyed by path id."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(min_length=1)
    post_write_reconciliation_proof_id: str = Field(min_length=1)
    execution_journal_acceptance_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    post_write_execution_journal_ref: str = Field(min_length=1)
    post_write_completion_proof_ref: str = Field(min_length=1)
    reconciliation_verification_ref: str = Field(min_length=1)
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_verification_id: str | None = Field(
        default=None,
        min_length=1,
    )
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class StealthCreateRequest(BaseModel):
    """Stealth create request shape for future gated lifecycle writes."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str | None = Field(default=None, min_length=1)
    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    side: OrderSide
    total_size: DecimalString
    limit_price: DecimalString
    reveal_condition: FlexibleDict
    sizing_strategy: FlexibleDict | None = None
    parent_order_id: str | None = Field(default=None, min_length=1)
    follow_up_reveal_direction: str | None = None
    reason: str = "normal_placement"
    notes: str = ""
    max_order_replacements: int | None = Field(default=None, ge=0)
    target_movement: DecimalString = "0.0"
    target_movement_type: TargetMovementType = TargetMovementType.PERCENTAGE
    reveal_pricing_policy: str | None = None
    allow_partial_fills: bool = False
    anchor_repricing_policy: FlexibleDict | None = None
    enable_hotpoint_replication: bool = False
    cancel_reentry_policy: FlexibleDict | None = None
    post_fill_retreat_policy: FlexibleDict | None = None
    manual_live_acknowledgement: bool = False


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


class SpotSweepAutomationRunRequest(BaseModel):
    """Spot sweep automation request shape for future gated sweep runs."""

    model_config = ConfigDict(extra="forbid")

    sweep_config_id: str = Field(min_length=1, examples=["spot-sweep-usdc-hourly"])
    side: OrderSide
    quote_notional_per_product: DecimalString | None = None
    repeat_every_hours: DecimalString | None = None
    max_runs: int | None = Field(default=None, ge=1)
    max_products: int | None = Field(default=None, ge=1)
    max_total_notional_per_run: DecimalString | None = None
    max_notional_per_order: DecimalString | None = None
    max_planned_orders: int | None = Field(default=None, ge=1)
    run_if_due: bool = True
    dry_run: bool = True
    manual_live_acknowledgement: bool = False


class SpotRecoveryApplyExecutionRequest(BaseModel):
    """Spot recovery apply request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    rollback_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    exchange_state_proof_id: str = Field(min_length=1)
    state_repair_requested: bool = False
    repair_target_id: str | None = None
    pre_apply_snapshot_id: str | None = None
    dry_run_repair_plan_id: str | None = None
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class SpotRecoveryRollbackExecutionRequest(BaseModel):
    """Spot recovery rollback request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    rollback_plan_id: str = Field(min_length=1)
    recovery_apply_audit_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    state_repair_requested: bool = False
    repair_target_id: str | None = None
    pre_apply_snapshot_id: str | None = None
    dry_run_repair_plan_id: str | None = None
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class SpotRecoveryExchangeStateProofRequest(BaseModel):
    """Spot recovery exchange-state proof request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    exchange_state_proof_id: str | None = None
    exchange_state_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class SpotRecoveryExchangeStateSnapshotRequest(BaseModel):
    """Spot recovery exchange-state snapshot request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    exchange_state_snapshot_id: str | None = None
    source_timestamp: str = Field(min_length=1)
    snapshot_source: SpotRecoveryExchangeStateSnapshotSource
    snapshot_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    reconciliation_proof_id: str = Field(min_length=1)
    completion_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class SpotRecoveryReconciliationProofRecordRequest(BaseModel):
    """Spot recovery reconciliation-proof request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    exchange_state_proof_id: str = Field(min_length=1)
    reconciliation_proof_id: str | None = None
    recovery_apply_audit_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False


class SpotRecoveryReconciliationExecutionRequest(BaseModel):
    """Spot recovery reconciliation execution request keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    exchange_state_snapshot_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    reconciliation_proof_id: str = Field(min_length=1)
    completion_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
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


class StealthCreateCommand(BaseModel):
    """Shared service command for route-bound stealth create."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: StealthCreateRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthRevealCommand(BaseModel):
    """Shared service command for reveal-by-stealth-order-id."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthRevealRequest
    allow_live_execution: bool = False


class StealthMoveCommand(BaseModel):
    """Shared service command for move-revealed-by-stealth-order-id."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthMoveRequest
    allow_live_execution: bool = False


class StealthRecoveryCommand(BaseModel):
    """Shared service command for live-disabled stealth recovery."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthRecoveryRequest
    allow_live_execution: bool = False


class StealthReconciliationCommand(BaseModel):
    """Shared service command for live-disabled stealth reconciliation."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthReconciliationRequest
    allow_live_execution: bool = False


class StealthActivePlacementExchangeTruthSnapshotCommand(BaseModel):
    """Shared service command for active-placement snapshot evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthActivePlacementExchangeTruthSnapshotRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthActivePlacementExchangeTruthProofCommand(BaseModel):
    """Shared service command for active-placement proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthActivePlacementExchangeTruthProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthCreateLifecycleWriteGuardProofCommand(BaseModel):
    """Shared service command for create lifecycle-write guard proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthCreateLifecycleWriteGuardProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthMutationClaimSnapshotProofCommand(BaseModel):
    """Shared service command for mutation-claim snapshot proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthMutationClaimSnapshotProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthManagerInvocationPolicyProofCommand(BaseModel):
    """Shared service command for manager-invocation policy proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthManagerInvocationPolicyProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthCoinbaseExchangeSubmissionPolicyProofCommand(BaseModel):
    """Shared service command for Coinbase exchange policy proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthCoinbaseExchangeSubmissionPolicyProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthStateMutationPolicyProofCommand(BaseModel):
    """Shared service command for state-mutation policy proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthStateMutationPolicyProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthRevealTriggerProofCommand(BaseModel):
    """Shared service command for reveal-trigger proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthRevealTriggerProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthRecoveryProofCommand(BaseModel):
    """Shared service command for stealth recovery proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthRecoveryProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthReconciliationProofCommand(BaseModel):
    """Shared service command for stealth reconciliation proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthReconciliationProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthCancelReplaceProofCommand(BaseModel):
    """Shared service command for stealth cancel/replace proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthCancelReplaceProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthPostWriteReconciliationProofCommand(BaseModel):
    """Shared service command for stealth post-write reconciliation proof evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthPostWriteReconciliationProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthPostWriteReconciliationExecutionPolicyProofCommand(BaseModel):
    """Shared service command for post-write reconciliation policy evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthPostWriteReconciliationExecutionPolicyProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthPostWriteExecutionJournalCommand(BaseModel):
    """Shared service command for stealth post-write execution-journal evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthPostWriteExecutionJournalRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class StealthPostWriteReconciliationVerificationCommand(BaseModel):
    """Shared service command for stealth post-write verification evidence."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    stealth_order_id: str = Field(min_length=1)
    request: StealthPostWriteReconciliationVerificationRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
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


class SpotSweepAutomationRunCommand(BaseModel):
    """Shared service command for spot sweep automation runs."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotSweepAutomationRunRequest
    allow_live_execution: bool = False


class SpotRecoveryApplyExecutionCommand(BaseModel):
    """Shared service command for disabled spot recovery apply execution."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryApplyExecutionRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class SpotRecoveryRollbackExecutionCommand(BaseModel):
    """Shared service command for disabled spot recovery rollback execution."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryRollbackExecutionRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class SpotRecoveryExchangeStateProofCommand(BaseModel):
    """Shared service command for spot recovery exchange-state proof records."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryExchangeStateProofRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class SpotRecoveryExchangeStateSnapshotCommand(BaseModel):
    """Shared service command for exchange-state snapshot records."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryExchangeStateSnapshotRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class SpotRecoveryReconciliationProofRecordCommand(BaseModel):
    """Shared service command for spot recovery reconciliation proof records."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryReconciliationProofRecordRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class SpotRecoveryReconciliationExecutionCommand(BaseModel):
    """Shared service command for disabled spot recovery reconciliation execution."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: SpotRecoveryReconciliationExecutionRequest
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    allow_live_execution: bool = False


class AdminApprovalRequestCreateRequest(BaseModel):
    """Request a backend-owned approval snapshot for a command attempt."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    operator_intent: str = Field(min_length=1)
    command_idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    request_reason: str | None = None


class AdminApprovalDecisionRequest(BaseModel):
    """Approve or reject a requested backend-owned approval snapshot."""

    model_config = ConfigDict(extra="forbid")

    decision: AdminApiApprovalLifecycleStatus
    decision_reason: str | None = None
    expires_at: str | None = None
    cap_guard_decision_ref: str | None = None
    reconciliation_plan_ref: str | None = None


class AdminApprovalRevokeRequest(BaseModel):
    """Revoke an approved backend approval snapshot."""

    model_config = ConfigDict(extra="forbid")

    revoke_reason: str | None = None


class AdminApprovalLifecycleItem(BaseModel):
    """Operator-visible state for one backend approval lifecycle."""

    model_config = ConfigDict(extra="forbid")

    approval_request_id: str
    approval_id: str | None = None
    status: AdminApiApprovalLifecycleStatus
    requested_at: str
    decided_at: str | None = None
    revoked_at: str | None = None
    expires_at: str | None = None
    expired: bool = False
    route: str
    method: str
    module_id: str
    identity_key: str
    identity_value: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    requested_by_actor_id: str
    decision_actor_id: str | None = None
    revoked_by_actor_id: str | None = None
    operator_intent: str
    command_idempotency_key: str
    payload_hash: str
    cap_guard_decision_ref: str | None = None
    reconciliation_plan_ref: str | None = None
    request_reason: str | None = None
    decision_reason: str | None = None
    revoke_reason: str | None = None
    snapshot_linked: bool = False
    live_execution_authority: bool = False
    live_exchange_submitted: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminApprovalListResponse(BaseModel):
    """List backend-owned approval lifecycle records."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_approval_lifecycle_list"
    approvals: list[AdminApprovalLifecycleItem] = Field(default_factory=list)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    approved_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    revoked_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    live_coinbase_orders_ran: bool = False


class AdminApprovalLifecycleResponse(BaseModel):
    """Response for approval lifecycle mutations and detail reads."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_approval_lifecycle"
    status: AdminApiCommandStatus
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission
    service_method: str
    message: str
    approval: AdminApprovalLifecycleItem | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


class AdminAdmissionAuditCreateRequest(BaseModel):
    """Append one backend-owned admission audit proof for command admission."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    command_idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)
    approval_snapshot_approved_by_actor_id: str | None = None
    approval_snapshot_requested_by_actor_id: str | None = None
    approval_snapshot_expires_at: str | None = None
    approval_cap_guard_decision_ref: str = Field(min_length=1)
    approval_reconciliation_plan_ref: str = Field(min_length=1)
    allowed: bool = False
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    reason: str = Field(min_length=1)


class AdminAdmissionAuditItem(BaseModel):
    """Operator-visible append-only admission audit evidence."""

    model_config = ConfigDict(extra="forbid")

    admission_audit_id: str
    recorded_at: str
    route: str
    method: str
    module_id: str
    identity_key: str
    identity_value: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    command_idempotency_key: str
    payload_hash: str
    approval_snapshot_id: str
    approval_snapshot_approved_by_actor_id: str | None = None
    approval_snapshot_requested_by_actor_id: str | None = None
    approval_snapshot_expires_at: str | None = None
    approval_cap_guard_decision_ref: str
    approval_reconciliation_plan_ref: str
    live_execution_intent_ref: str
    allowed: bool = False
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    source: str = "admin_api_audit_log"
    resolver_eligible: bool = False
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    detail: str


class AdminAdmissionAuditListResponse(BaseModel):
    """List backend-owned admission audit records."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_admission_audit_list"
    admission_audits: list[AdminAdmissionAuditItem] = Field(default_factory=list)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    resolver_eligible_count: int = Field(ge=0)
    live_coinbase_orders_ran: bool = False


class AdminAdmissionAuditResponse(BaseModel):
    """Response for admission audit mutations and detail reads."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_admission_audit"
    status: AdminApiCommandStatus
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission
    service_method: str
    message: str
    admission_audit: AdminAdmissionAuditItem | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


class AdminCapGuardDecisionCreateRequest(BaseModel):
    """Append one backend-owned cap/guard decision for command admission."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    command_idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)
    approval_cap_guard_decision_ref: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    allowed: bool
    status: AdminApiGateStatus
    cap_policy_ref: str = Field(min_length=1)
    guard_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    max_submitted_notional_usdc: DecimalString
    max_executed_notional_usdc: DecimalString
    reason: str = Field(min_length=1)


class AdminCapGuardDecisionItem(BaseModel):
    """Operator-visible backend cap/guard decision evidence."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    recorded_at: str
    route: str
    method: str
    module_id: str
    identity_key: str
    identity_value: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    command_idempotency_key: str
    payload_hash: str
    approval_snapshot_id: str
    admission_audit_id: str
    allowed: bool
    status: AdminApiGateStatus
    source: str = "admin_api_cap_guard_log"
    cap_policy_ref: str
    guard_policy_ref: str
    product_scope: str
    max_submitted_notional_usdc: DecimalString
    max_executed_notional_usdc: DecimalString
    reason: str
    resolver_eligible: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    detail: str


class AdminCapGuardDecisionListResponse(BaseModel):
    """List backend-owned cap/guard decision records."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_cap_guard_decision_list"
    decisions: list[AdminCapGuardDecisionItem] = Field(default_factory=list)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    resolver_eligible_count: int = Field(ge=0)
    live_coinbase_orders_ran: bool = False


class AdminCapGuardDecisionResponse(BaseModel):
    """Response for cap/guard decision mutations and detail reads."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_cap_guard_decision"
    status: AdminApiCommandStatus
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission
    service_method: str
    message: str
    decision: AdminCapGuardDecisionItem | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


class AdminReconciliationPlanCreateRequest(BaseModel):
    """Append one backend-owned reconciliation plan proof for command admission."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    command_idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)
    approval_reconciliation_plan_ref: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    allowed: bool
    status: AdminApiGateStatus
    reconciliation_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    exchange_submission_required: bool = True
    post_submit_reconciliation_required: bool = True
    retained_inventory_required: bool = True
    max_submitted_notional_usdc: DecimalString
    max_executed_notional_usdc: DecimalString
    reason: str = Field(min_length=1)


class AdminReconciliationPlanItem(BaseModel):
    """Operator-visible backend reconciliation plan proof evidence."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    recorded_at: str
    route: str
    method: str
    module_id: str
    identity_key: str
    identity_value: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    command_idempotency_key: str
    payload_hash: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    allowed: bool
    status: AdminApiGateStatus
    source: str = "admin_api_reconciliation_plan_log"
    reconciliation_policy_ref: str
    product_scope: str
    exchange_submission_required: bool = True
    post_submit_reconciliation_required: bool = True
    retained_inventory_required: bool = True
    max_submitted_notional_usdc: DecimalString
    max_executed_notional_usdc: DecimalString
    reason: str
    resolver_eligible: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    reconciliation_execution_ran: bool = False
    order_exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    detail: str


class AdminReconciliationPlanListResponse(BaseModel):
    """List backend-owned reconciliation plan proof records."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_reconciliation_plan_list"
    plans: list[AdminReconciliationPlanItem] = Field(default_factory=list)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    resolver_eligible_count: int = Field(ge=0)
    reconciliation_execution_ran: bool = False
    live_coinbase_orders_ran: bool = False


class AdminReconciliationPlanResponse(BaseModel):
    """Response for reconciliation plan mutations and detail reads."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_reconciliation_plan"
    status: AdminApiCommandStatus
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission
    service_method: str
    message: str
    plan: AdminReconciliationPlanItem | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    reconciliation_execution_ran: bool = False
    order_exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


class SpotPnlCheckpointCreateRequest(BaseModel):
    """Append one backend-owned Spot P/L review checkpoint."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)
    scope: str = Field(min_length=1, examples=["portfolio"])
    product_ids: list[str] = Field(default_factory=list)
    pnl_snapshot: FlexibleDict
    average_cost_snapshot: FlexibleDict | None = None
    source_report_route: str = Field(
        default="/api/v1/spot/sweep/pnl",
        min_length=1,
    )
    review_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    operator_notes: str = Field(min_length=1)


class SpotPnlCheckpointItem(BaseModel):
    """Durable Spot P/L review checkpoint evidence."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    recorded_at: str
    scope: str
    product_ids: list[str] = Field(default_factory=list)
    pnl_snapshot: FlexibleDict
    average_cost_snapshot: FlexibleDict | None = None
    average_cost_reviewed: bool = False
    average_cost_review_source: str | None = None
    average_cost_review_detail: str
    source_report_route: str
    review_status: AdminApiGateStatus
    actor_id: str
    operator_intent: str
    idempotency_key: str
    payload_hash: str
    audit_id: str | None = None
    audit_linked: bool = False
    audit_source: str | None = None
    audit_detail: str = SPOT_PNL_CHECKPOINT_LEGACY_AUDIT_DETAIL
    recovery_linked: bool = False
    recovery_source: str | None = None
    recovery_routes: list[str] = Field(default_factory=list)
    recovery_detail: str = SPOT_PNL_CHECKPOINT_LEGACY_RECOVERY_DETAIL
    reconciliation_linked: bool = False
    reconciliation_source: str | None = None
    reconciliation_routes: list[str] = Field(default_factory=list)
    reconciliation_detail: str = SPOT_PNL_CHECKPOINT_LEGACY_RECONCILIATION_DETAIL
    source: str = "admin_api_spot_pnl_checkpoint_log"
    operator_notes: str
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    profitability_authority: bool = False
    sell_authority: bool = False
    checkpoint_is_tax_accounting: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    detail: str


class SpotPnlCheckpointListResponse(BaseModel):
    """List backend-owned Spot P/L checkpoint records."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_pnl_checkpoint_list"
    checkpoints: list[SpotPnlCheckpointItem] = Field(default_factory=list)
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    average_cost_review_count: int = Field(ge=0)
    audit_linked_count: int = Field(ge=0)
    recovery_linked_count: int = Field(ge=0)
    reconciliation_linked_count: int = Field(ge=0)
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class SpotPnlCheckpointResponse(BaseModel):
    """Response for Spot P/L checkpoint mutations and detail reads."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_pnl_checkpoint"
    status: AdminApiCommandStatus
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission
    service_method: str
    message: str
    checkpoint: SpotPnlCheckpointItem | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    read_only: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    profitability_authority: bool = False
    sell_authority: bool = False
    checkpoint_is_tax_accounting: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


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
    stealth_admission_context: StealthCommandAdmissionContextEvidence | None = None
    stealth_lifecycle_execution_contract: (
        StealthCreateLifecycleWriteExecutionContractEvidence | None
    ) = None
    stealth_command_execution_contract: (
        StealthCommandExecutionContractEvidence | None
    ) = None
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


class AdminEnterpriseFunctionalityInventoryItem(BaseModel):
    """One backend workflow and its enterprise admin exposure posture."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    module_id: str
    module: str
    workflow_type: AdminApiFunctionalityWorkflowType
    exposure_status: AdminApiFunctionalityExposureStatus
    support_status: AdminApiModuleSupportStatus
    summary: str
    backend_supported: bool
    admin_api_exposed: bool
    frontend_exposed: bool
    command_capable: bool = False
    live_designated: bool = False
    live_enabled: bool = False
    read_routes: list[str] = Field(default_factory=list)
    command_routes: list[str] = Field(default_factory=list)
    recovery_routes: list[str] = Field(default_factory=list)
    automation_routes: list[str] = Field(default_factory=list)
    legacy_surfaces: list[str] = Field(default_factory=list)
    identity_keys: list[str] = Field(default_factory=list)
    backend_contract_refs: list[str] = Field(default_factory=list)
    frontend_contract_refs: list[str] = Field(default_factory=list)
    documentation_refs: list[str] = Field(default_factory=list)
    required_next_contract: str | None = None
    blockers: list[str] = Field(default_factory=list)
    frontend_boundary: str
    spot_rule_boundary: str
    live_coinbase_execution: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.NOT_RUN
    notional_usdc: DecimalString = "0"


class AdminEnterpriseMutationTaxonomyItem(BaseModel):
    """One backend-owned admin mutation family and its authority contract."""

    model_config = ConfigDict(extra="forbid")

    mutation_id: str
    mutation_family: AdminApiMutationFamilyType
    workflow_id: str
    related_workflow_ids: list[str] = Field(default_factory=list)
    module_id: str
    module: str
    exposure_status: AdminApiFunctionalityExposureStatus
    support_status: AdminApiModuleSupportStatus
    summary: str
    command_surfaces: list[str] = Field(default_factory=list)
    action_classes: list[AdminApiActionClass] = Field(default_factory=list)
    required_permissions: list[AdminApiPermission | str] = Field(default_factory=list)
    identity_keys: list[str] = Field(default_factory=list)
    payload_binding_fields: list[str] = Field(default_factory=list)
    idempotency_required: bool = True
    idempotency_contract: str
    operator_intent_required: bool = True
    rbac_required: bool = True
    approval_required: bool = True
    approval_contract: str
    cap_guard_required: bool = True
    cap_guard_contract: str
    admission_audit_required: bool = True
    admission_audit_contract: str
    reconciliation_required: bool = True
    reconciliation_contract: str
    live_adapter_required: bool = True
    owning_backend_service: str
    shared_command_service_method: str | None = None
    route_inventory_refs: list[str] = Field(default_factory=list)
    backend_contract_refs: list[str] = Field(default_factory=list)
    frontend_contract_refs: list[str] = Field(default_factory=list)
    documentation_refs: list[str] = Field(default_factory=list)
    required_next_contract: str | None = None
    blockers: list[str] = Field(default_factory=list)
    frontend_boundary: str
    bff_boundary: str = (
        "BFF may forward only to backend Admin API; it must not execute or "
        "approve commands."
    )
    route_local_boundary: str = (
        "FastAPI route adapters must not implement route-local trading behavior."
    )
    browser_authority: str = "display_only"
    bff_execution_authority: str = "forward_only_no_execution"
    route_local_execution_allowed: bool = False
    spot_rule_boundary: str
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
    functionality_inventory_count: int = 0
    backend_supported_workflow_count: int = 0
    admin_exposed_workflow_count: int = 0
    command_workflow_count: int = 0
    live_designated_workflow_count: int = 0
    recovery_workflow_count: int = 0
    automation_workflow_count: int = 0
    repair_workflow_count: int = 0
    mutation_taxonomy_count: int = 0
    route_bound_mutation_taxonomy_count: int = 0
    live_disabled_mutation_count: int = 0
    backend_contract_required_mutation_count: int = 0
    compatibility_mutation_count: int = 0
    modules: list[AdminEnterpriseReadinessModuleItem] = Field(default_factory=list)
    functionality_inventory: list[AdminEnterpriseFunctionalityInventoryItem] = Field(default_factory=list)
    mutation_taxonomy: list[AdminEnterpriseMutationTaxonomyItem] = Field(default_factory=list)
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


class AdminStealthActivePlacementAuditEvidence(BaseModel):
    """Read-only active-placement evidence for stealth detail views."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    active_placement_present: bool = False
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    exchange_truth_verified: bool = False
    exchange_truth_source: str = "local_stealth_state_only"
    coinbase_read_required: bool = True
    coinbase_read_ran: bool = False
    coinbase_order_cancel_submitted: bool = False
    lifecycle_mutation_allowed: bool = False
    required_for_mutation_families: list[AdminApiMutationFamilyType] = Field(
        default_factory=list
    )
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthActivePlacementExchangeTruthSnapshotRecordItem(BaseModel):
    """Read-only persisted active-placement exchange-truth snapshot evidence."""

    model_config = ConfigDict(extra="forbid")

    exchange_truth_snapshot_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    product_id: str | None = None
    source_timestamp: str
    evidence_source: StealthExchangeTruthEvidenceSource
    snapshot_evidence_ref: str
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_exchange_truth_snapshot_log"
    snapshot_recorded: bool = True
    exchange_truth_verified: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthActivePlacementExchangeTruthProofRecordItem(BaseModel):
    """Read-only persisted active-placement exchange-truth proof evidence."""

    model_config = ConfigDict(extra="forbid")

    exchange_truth_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    exchange_truth_snapshot_id: str
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    exchange_truth_evidence_ref: str
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_exchange_truth_proof_log"
    proof_persisted: bool = True
    exchange_truth_verified: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCreateLifecycleWriteGuardProofRecordItem(BaseModel):
    """Read-only persisted stealth create lifecycle-write guard proof evidence."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_write_guard_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    product_id: str
    side: OrderSide
    total_size: DecimalString
    limit_price: DecimalString
    evidence_source: StealthLifecycleWriteGuardEvidenceSource
    guard_evidence_ref: str
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_lifecycle_write_guard_proof_log"
    proof_persisted: bool = True
    lifecycle_write_guard_verified: bool = False
    manager_invocation_ran: bool = False
    stealth_row_write_ran: bool = False
    order_parent_write_ran: bool = False
    lifecycle_event_dispatch_ran: bool = False
    local_lifecycle_mutation_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthMutationClaimSnapshotProofRecordItem(BaseModel):
    """Read-only persisted stealth mutation-claim snapshot proof evidence."""

    model_config = ConfigDict(extra="forbid")

    mutation_claim_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    mutation_kind: StealthMutationKind
    claim_reader_source: str
    runtime_claims_observed: bool = False
    runtime_claim_count: int = Field(default=0, ge=0)
    active_claim_count: int = Field(default=0, ge=0)
    evidence_source: StealthMutationClaimEvidenceSource
    snapshot_evidence_ref: str
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_mutation_claim_snapshot_proof_log"
    proof_persisted: bool = True
    mutation_claim_snapshot_verified: bool = False
    manager_invocation_ran: bool = False
    claim_acquire_ran: bool = False
    claim_release_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthRevealTriggerProofRecordItem(BaseModel):
    """Read-only persisted stealth reveal-trigger proof evidence."""

    model_config = ConfigDict(extra="forbid")

    reveal_trigger_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    reveal_condition_ref: str
    trigger_evidence_ref: str
    condition_snapshot_ref: str
    evidence_source: StealthRevealTriggerEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_reveal_trigger_proof_log"
    proof_persisted: bool = True
    reveal_trigger_verified: bool = False
    manager_invocation_ran: bool = False
    trigger_evaluation_ran: bool = False
    should_trigger_reveal_called: bool = False
    reveal_order_slice_called: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthManagerInvocationPolicyProofRecordItem(BaseModel):
    """Read-only persisted stealth manager-invocation policy evidence."""

    model_config = ConfigDict(extra="forbid")

    manager_policy_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    manager_policy_ref: str
    mutation_lock_policy_ref: str
    exchange_reality_policy_ref: str
    evidence_source: StealthManagerPolicyEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_manager_invocation_policy_log"
    proof_persisted: bool = True
    manager_policy_verified: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    mutation_lock_policy_verified: bool = False
    exchange_reality_policy_verified: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCoinbaseExchangeSubmissionPolicyProofRecordItem(BaseModel):
    """Read-only persisted stealth Coinbase exchange policy evidence."""

    model_config = ConfigDict(extra="forbid")

    coinbase_exchange_policy_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    exchange_submission_policy_ref: str
    coinbase_cancel_policy_ref: str
    live_coinbase_read_policy_ref: str
    live_cap_evidence_ref: str
    evidence_source: StealthCoinbaseExchangePolicyEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_coinbase_exchange_submission_policy_log"
    proof_persisted: bool = True
    exchange_submission_policy_verified: bool = False
    coinbase_submit_allowed: bool = False
    coinbase_cancel_allowed: bool = False
    live_coinbase_read_allowed: bool = False
    live_cap_verified: bool = False
    manager_invocation_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthStateMutationPolicyProofRecordItem(BaseModel):
    """Read-only persisted stealth state-mutation policy evidence."""

    model_config = ConfigDict(extra="forbid")

    state_mutation_policy_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    state_mutation_policy_ref: str
    lifecycle_state_policy_ref: str
    order_state_policy_ref: str
    exchange_state_policy_ref: str
    post_write_reconciliation_policy_ref: str
    evidence_source: StealthStateMutationPolicyEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_state_mutation_policy_log"
    proof_persisted: bool = True
    state_mutation_policy_verified: bool = False
    state_mutation_allowed: bool = False
    lifecycle_state_mutation_allowed: bool = False
    order_state_mutation_allowed: bool = False
    exchange_state_mutation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthRecoveryProofRecordItem(BaseModel):
    """Read-only persisted stealth recovery proof evidence."""

    model_config = ConfigDict(extra="forbid")

    recovery_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    recovery_evidence_ref: str
    recovery_plan_ref: str
    evidence_source: StealthRecoveryProofEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_recovery_proof_log"
    proof_persisted: bool = True
    recovery_proof_verified: bool = False
    manager_invocation_ran: bool = False
    recovery_plan_built: bool = False
    recovery_repair_executed: bool = False
    rollback_executed: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthReconciliationProofRecordItem(BaseModel):
    """Read-only persisted stealth reconciliation proof evidence."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    reconciliation_evidence_ref: str
    reconciliation_plan_ref: str
    active_placement_evidence_ref: str
    evidence_source: StealthReconciliationProofEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_reconciliation_proof_log"
    proof_persisted: bool = True
    reconciliation_proof_verified: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCancelReplaceProofRecordItem(BaseModel):
    """Read-only persisted stealth cancel/replace proof evidence."""

    model_config = ConfigDict(extra="forbid")

    cancel_replace_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    active_placement_evidence_ref: str
    mutation_claim_evidence_ref: str | None = None
    cancel_replace_evidence_ref: str
    evidence_source: StealthCancelReplaceProofEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_cancel_replace_proof_log"
    proof_persisted: bool = True
    cancel_replace_proof_verified: bool = False
    manager_invocation_ran: bool = False
    cancel_replace_plan_built: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthPostWriteReconciliationProofRecordItem(BaseModel):
    """Read-only persisted stealth post-write reconciliation proof evidence."""

    model_config = ConfigDict(extra="forbid")

    post_write_reconciliation_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    route_bound_reconciliation_plan_ref: str
    post_write_execution_journal_ref: str
    post_write_completion_proof_ref: str
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_post_write_reconciliation_proof_log"
    proof_persisted: bool = True
    post_write_reconciliation_verified: bool = False
    route_bound_reconciliation_plan_recorded: bool = True
    execution_journal_accepted: bool = False
    completion_proof_recorded: bool = True
    manager_invocation_ran: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthPostWriteReconciliationExecutionPolicyProofRecordItem(BaseModel):
    """Read-only persisted post-write reconciliation execution-policy evidence."""

    model_config = ConfigDict(extra="forbid")

    post_write_reconciliation_policy_proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    post_write_reconciliation_execution_policy_ref: str
    route_bound_reconciliation_plan_ref: str
    post_write_execution_journal_policy_ref: str
    post_write_reconciliation_verification_policy_ref: str
    safe_reconciliation_chain_ref: str
    evidence_source: StealthPostWriteReconciliationExecutionPolicyEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_post_write_reconciliation_execution_policy_log"
    proof_persisted: bool = True
    post_write_reconciliation_execution_policy_verified: bool = False
    post_write_reconciliation_execution_allowed: bool = False
    route_bound_reconciliation_plan_required: bool = True
    execution_journal_required: bool = True
    reconciliation_verification_required: bool = True
    safe_reconciliation_chain_verified: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthPostWriteExecutionJournalRecordItem(BaseModel):
    """Read-only persisted stealth post-write execution-journal acceptance."""

    model_config = ConfigDict(extra="forbid")

    execution_journal_acceptance_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    post_write_reconciliation_proof_id: str
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    post_write_execution_journal_ref: str
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_post_write_execution_journal_log"
    journal_acceptance_persisted: bool = True
    execution_journal_accepted: bool = True
    post_write_reconciliation_verified: bool = False
    manager_invocation_ran: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthPostWriteReconciliationVerificationRecordItem(BaseModel):
    """Read-only persisted stealth post-write reconciliation verification."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_verification_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    post_write_reconciliation_proof_id: str
    execution_journal_acceptance_id: str
    stealth_order_id: str
    guarded_command_route: str
    guarded_command_method: str
    guarded_service_method: str
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str
    guarded_operator_intent: str
    guarded_idempotency_key: str
    guarded_payload_hash: str
    post_write_execution_journal_ref: str
    post_write_completion_proof_ref: str
    reconciliation_verification_ref: str
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_post_write_reconciliation_verification_log"
    verification_persisted: bool = True
    execution_journal_accepted: bool = True
    post_write_reconciliation_verified: bool = True
    manager_invocation_ran: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminMutationClaimEvidence(BaseModel):
    """Runtime claim evidence for repeatable stealth mutations."""

    model_config = ConfigDict(extra="forbid")

    kind: StealthMutationKind
    state: str | None = None
    runtime_observed: bool = False
    source: str


class AdminStealthMutationClaimAuditEvidence(BaseModel):
    """Read-only mutation-claim evidence for stealth detail views."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    runtime_claims: list[AdminMutationClaimEvidence] = Field(default_factory=list)
    runtime_claims_observed: bool = False
    runtime_claim_count: int = 0
    active_claim_count: int = 0
    claim_reader_source: str = "stealth_manager.snapshot_mutation_claims"
    claim_reader_ran: bool = False
    coinbase_read_ran: bool = False
    coinbase_order_cancel_submitted: bool = False
    lifecycle_mutation_allowed: bool = False
    required_for_mutation_families: list[AdminApiMutationFamilyType] = Field(
        default_factory=list
    )
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminStealthRevealTriggerAuditEvidence(BaseModel):
    """Read-only reveal-trigger evidence for stealth detail views."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    reveal_condition_present: bool = False
    reveal_condition_type: str | None = None
    reveal_condition: FlexibleDict | None = None
    trigger_state_source: str = "local_stealth_row_only"
    trigger_evaluation_ran: bool = False
    should_trigger_reveal_called: bool = False
    reveal_order_slice_called: bool = False
    coinbase_order_submit_ran: bool = False
    lifecycle_mutation_allowed: bool = False
    required_for_mutation_families: list[AdminApiMutationFamilyType] = Field(
        default_factory=list
    )
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminStealthRevealSubmissionAuditEvidence(BaseModel):
    """Read-only reveal submission-adapter evidence for stealth detail views."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    command_route: str = "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    service_method: str = "reveal_stealth_order_by_stealth_order_id"
    reveal_manager_method: str = "core/stealth_order_manager.py::reveal_order_slice"
    submission_adapter_configured: bool = False
    route_bound: bool = True
    backend_owned: bool = True
    existing_active_placement_present: bool = False
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    reveal_order_slice_called: bool = False
    coinbase_order_submit_ran: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_created: bool = False
    lifecycle_mutation_allowed: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    required_for_mutation_families: list[AdminApiMutationFamilyType] = Field(
        default_factory=list
    )
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminStealthRevealReconciliationAuditEvidence(BaseModel):
    """Read-only reveal reconciliation-proof evidence for stealth detail views."""

    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    command_route: str = "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    reconciliation_required: bool = True
    reconciliation_plan_required: bool = True
    reconciliation_proof_required: bool = True
    reconciliation_plan_resolved: bool = False
    reconciliation_proof_resolved: bool = False
    reconciliation_plan_id: str | None = None
    reconciliation_proof_id: str | None = None
    active_placement_client_order_id: str | None = None
    active_exchange_order_id: str | None = None
    exchange_order_id_evidence_only: bool = True
    coinbase_read_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_mutation_allowed: bool = False
    post_submit_reconciliation_satisfied: bool = False
    required_for_mutation_families: list[AdminApiMutationFamilyType] = Field(
        default_factory=list
    )
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class AdminStealthOrderDetailResponse(BaseModel):
    """Read-only stealth detail response keyed by ``stealth_order_id``."""

    model_config = ConfigDict(extra="forbid")

    type: str = "admin_stealth_order_detail"
    stealth_order_id: str
    found: bool
    order: AdminStealthOrderReadItem | None = None
    active_placement_audit: AdminStealthActivePlacementAuditEvidence | None = None
    mutation_claim_audit: AdminStealthMutationClaimAuditEvidence | None = None
    reveal_trigger_audit: AdminStealthRevealTriggerAuditEvidence | None = None
    reveal_submission_audit: AdminStealthRevealSubmissionAuditEvidence | None = None
    reveal_reconciliation_audit: (
        AdminStealthRevealReconciliationAuditEvidence | None
    ) = None
    read_only: bool = True
    command_routes_mode: AdminApiCommandRoutesMode = AdminApiCommandRoutesMode.LIVE_DISABLED
    live_coinbase_orders_ran: bool = False


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
    construction_precondition_required: bool = True
    construction_precondition_resolved: bool = False
    construction_precondition_authority: str = (
        "backend_route_binding_only_no_execution"
    )
    required_construction_artifacts: list[str] = Field(default_factory=list)
    missing_construction_artifacts: list[str] = Field(default_factory=list)
    construction_contract_refs: list[str] = Field(default_factory=list)
    construction_verification_gates: list[str] = Field(default_factory=list)
    construction_blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    forbidden_methods: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveExecutionServiceContractEvidence(BaseModel):
    """Read-only evidence for the disabled backend live execution service."""

    model_config = ConfigDict(extra="forbid")

    required: bool = True
    present: bool = True
    enabled: bool = False
    backend_owned: bool = True
    route_bound: bool = True
    final_boundary: bool = True
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "disabled_backend_service"
    missing_reason: str | None = "live_execution_disabled"
    module_id: str
    route: str
    method: str
    service_method: str
    service_reference: str
    action_class: AdminApiActionClass
    executable: bool = False
    live_exchange_submission_allowed: bool = False
    live_exchange_submitted: bool = False
    enablement_precondition_required: bool = True
    enablement_precondition_resolved: bool = False
    enablement_precondition_authority: str = "backend_runtime_configuration_only"
    required_enablement_artifacts: list[str] = Field(default_factory=list)
    missing_enablement_artifacts: list[str] = Field(default_factory=list)
    enablement_contract_refs: list[str] = Field(default_factory=list)
    enablement_verification_gates: list[str] = Field(default_factory=list)
    enablement_blockers: list[str] = Field(default_factory=list)
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    forbidden_methods: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class AdminLiveReadinessPreconditionItem(BaseModel):
    """One normalized backend-owned live-readiness precondition."""

    model_config = ConfigDict(extra="forbid")

    precondition: AdminApiLiveReadinessPrecondition
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    configured: bool = False
    blocking: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    source: str
    expected_source: str
    blocker: AdminApiLiveAdmissionBlocker | None = None
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
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
    readiness_preconditions: list[AdminLiveReadinessPreconditionItem] = Field(
        default_factory=list
    )
    readiness_precondition_count: int = 0
    blocking_readiness_precondition_count: int = 0
    passed_readiness_precondition_count: int = 0
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
    readiness_precondition_count: int = 0
    blocking_readiness_precondition_count: int = 0
    passed_readiness_precondition_count: int = 0
    read_only: bool = True
    live_coinbase_orders_ran: bool = False


class AdminApiReadPayload(BaseModel):
    """Loose typed shell for existing dashboard-shaped read-only payloads."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    status: str | None = None
    live_coinbase_orders_ran: bool = False


class StealthActivePlacementExchangeTruthReadResponse(AdminApiReadPayload):
    """Read-only active-placement exchange-truth evidence readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_active_placement_exchange_truth"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    exchange_truth_verified: bool = False
    persisted_snapshot_count: int = Field(default=0, ge=0)
    persisted_snapshots: list[StealthActivePlacementExchangeTruthSnapshotRecordItem] = (
        Field(default_factory=list)
    )
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthActivePlacementExchangeTruthProofRecordItem] = (
        Field(default_factory=list)
    )
    latest_exchange_truth_snapshot_id: str | None = None
    latest_exchange_truth_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthCreateLifecycleWriteGuardReadResponse(AdminApiReadPayload):
    """Read-only stealth create lifecycle-write guard proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_create_lifecycle_write_guard"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    lifecycle_write_guard_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthCreateLifecycleWriteGuardProofRecordItem] = (
        Field(default_factory=list)
    )
    latest_lifecycle_write_guard_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    stealth_row_write_allowed: bool = False
    stealth_row_write_ran: bool = False
    order_parent_write_allowed: bool = False
    order_parent_write_ran: bool = False
    lifecycle_event_dispatch_allowed: bool = False
    lifecycle_event_dispatch_ran: bool = False
    local_lifecycle_mutation_allowed: bool = False
    local_lifecycle_mutation_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    post_write_reconciliation_satisfied: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthMutationClaimSnapshotReadResponse(AdminApiReadPayload):
    """Read-only stealth mutation-claim snapshot proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_mutation_claim_snapshot"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    mutation_claim_snapshot_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthMutationClaimSnapshotProofRecordItem] = (
        Field(default_factory=list)
    )
    latest_mutation_claim_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    claim_acquire_allowed: bool = False
    claim_acquire_ran: bool = False
    claim_release_allowed: bool = False
    claim_release_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthRevealTriggerProofReadResponse(AdminApiReadPayload):
    """Read-only stealth reveal-trigger proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_reveal_trigger_proof"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    reveal_trigger_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthRevealTriggerProofRecordItem] = Field(default_factory=list)
    latest_reveal_trigger_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    trigger_evaluation_allowed: bool = False
    trigger_evaluation_ran: bool = False
    should_trigger_reveal_allowed: bool = False
    should_trigger_reveal_called: bool = False
    reveal_order_slice_allowed: bool = False
    reveal_order_slice_called: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthManagerInvocationPolicyReadResponse(AdminApiReadPayload):
    """Read-only stealth manager-invocation policy proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_manager_invocation_policy"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    manager_policy_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[
        StealthManagerInvocationPolicyProofRecordItem
    ] = Field(default_factory=list)
    latest_manager_policy_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    mutation_lock_policy_verified: bool = False
    exchange_reality_policy_verified: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthCoinbaseExchangeSubmissionPolicyReadResponse(AdminApiReadPayload):
    """Read-only stealth Coinbase exchange policy proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_coinbase_exchange_submission_policy"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    exchange_submission_policy_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[
        StealthCoinbaseExchangeSubmissionPolicyProofRecordItem
    ] = Field(default_factory=list)
    latest_coinbase_exchange_policy_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    coinbase_submit_allowed: bool = False
    coinbase_cancel_allowed: bool = False
    live_coinbase_read_allowed: bool = False
    live_cap_verified: bool = False
    manager_invocation_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthStateMutationPolicyReadResponse(AdminApiReadPayload):
    """Read-only stealth state-mutation policy proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_state_mutation_policy"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    state_mutation_policy_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthStateMutationPolicyProofRecordItem] = Field(
        default_factory=list
    )
    latest_state_mutation_policy_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    state_mutation_allowed: bool = False
    lifecycle_state_mutation_allowed: bool = False
    order_state_mutation_allowed: bool = False
    exchange_state_mutation_allowed: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_build_allowed: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthRecoveryProofReadResponse(AdminApiReadPayload):
    """Read-only stealth recovery proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_recovery_proof"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    recovery_proof_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthRecoveryProofRecordItem] = Field(default_factory=list)
    latest_recovery_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    recovery_plan_build_allowed: bool = False
    recovery_plan_built: bool = False
    recovery_repair_allowed: bool = False
    recovery_repair_executed: bool = False
    rollback_allowed: bool = False
    rollback_executed: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthReconciliationProofReadResponse(AdminApiReadPayload):
    """Read-only stealth reconciliation proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_reconciliation_proof"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    reconciliation_proof_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthReconciliationProofRecordItem] = Field(
        default_factory=list
    )
    latest_reconciliation_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_build_allowed: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthCancelReplaceProofReadResponse(AdminApiReadPayload):
    """Read-only stealth cancel/replace proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_cancel_replace_proof"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    cancel_replace_proof_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthCancelReplaceProofRecordItem] = Field(
        default_factory=list
    )
    latest_cancel_replace_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    cancel_replace_plan_build_allowed: bool = False
    cancel_replace_plan_built: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthPostWriteReconciliationProofReadResponse(AdminApiReadPayload):
    """Read-only stealth post-write reconciliation proof readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_post_write_reconciliation_proof"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    post_write_reconciliation_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[StealthPostWriteReconciliationProofRecordItem] = (
        Field(default_factory=list)
    )
    latest_post_write_reconciliation_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    route_bound_reconciliation_plan_recorded: bool = False
    reconciliation_plan_build_allowed: bool = False
    reconciliation_plan_built: bool = False
    execution_journal_required: bool = True
    execution_journal_accepted: bool = False
    reconciliation_verification_required: bool = True
    reconciliation_verification_count: int = Field(default=0, ge=0)
    latest_reconciliation_verification_id: str | None = None
    completion_proof_required: bool = True
    completion_proof_recorded: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthPostWriteReconciliationExecutionPolicyReadResponse(AdminApiReadPayload):
    """Read-only stealth post-write reconciliation execution-policy readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_post_write_reconciliation_execution_policy"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    post_write_reconciliation_execution_policy_verified: bool = False
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[
        StealthPostWriteReconciliationExecutionPolicyProofRecordItem
    ] = Field(default_factory=list)
    latest_post_write_reconciliation_policy_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    proof_records_created: bool = False
    post_write_reconciliation_execution_allowed: bool = False
    route_bound_reconciliation_plan_required: bool = True
    execution_journal_required: bool = True
    reconciliation_verification_required: bool = True
    safe_reconciliation_chain_verified: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_build_allowed: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthPostWriteExecutionJournalReadResponse(AdminApiReadPayload):
    """Read-only stealth post-write execution-journal acceptance readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_post_write_execution_journal"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    persisted_acceptance_count: int = Field(default=0, ge=0)
    accepted_execution_journal_count: int = Field(default=0, ge=0)
    persisted_acceptances: list[StealthPostWriteExecutionJournalRecordItem] = (
        Field(default_factory=list)
    )
    latest_execution_journal_acceptance_id: str | None = None
    latest_post_write_reconciliation_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    execution_journal_required: bool = True
    execution_journal_accepted: bool = False
    reconciliation_verification_required: bool = True
    reconciliation_verification_count: int = Field(default=0, ge=0)
    latest_reconciliation_verification_id: str | None = None
    post_write_reconciliation_verified: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class StealthPostWriteReconciliationVerificationReadResponse(AdminApiReadPayload):
    """Read-only stealth post-write reconciliation verification readback."""

    model_config = ConfigDict(extra="forbid")

    type: str = "stealth_post_write_reconciliation_verification"
    module_id: str = "stealth_orders"
    approved_phase_range: str
    stealth_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    persisted_verification_count: int = Field(default=0, ge=0)
    verified_post_write_reconciliation_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Count of unique persisted verification records that match an "
            "exact safe proof plus accepted execution-journal chain. This is "
            "display evidence only and may participate in resolving the "
            "post_write_reconciliation prerequisite evidence only as part of "
            "the exact safe proof/journal/verification chain."
        ),
    )
    persisted_verifications: (
        list[StealthPostWriteReconciliationVerificationRecordItem]
    ) = Field(default_factory=list)
    latest_reconciliation_verification_id: str | None = None
    latest_execution_journal_acceptance_id: str | None = None
    latest_post_write_reconciliation_proof_id: str | None = None
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = True
    execution_journal_required: bool = True
    execution_journal_accepted: bool = Field(
        default=False,
        description=(
            "True only when an accepted execution journal participates in an "
            "exact safe verification chain for this readback; display "
            "evidence only."
        ),
    )
    reconciliation_verification_required: bool = True
    post_write_reconciliation_verified: bool = Field(
        default=False,
        description=(
            "True only for an exact safe proof, accepted journal, and "
            "verification chain. This does not execute reconciliation, does "
            "not call Coinbase, and may resolve only the "
            "post_write_reconciliation prerequisite evidence."
        ),
    )
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_execution_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


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


class SpotRecoveryPreviewSourceItem(BaseModel):
    """One backend-owned read source contributing recovery-preview evidence."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: AdminApiGateStatus
    route: str
    method: str = "GET"
    action_class: AdminApiActionClass = AdminApiActionClass.READ_ONLY
    required_permission: AdminApiPermission | str
    shared_method: str
    candidate_count: int = Field(ge=0)
    candidates: list[FlexibleDict] = Field(default_factory=list)
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class SpotRecoveryPreviewResponse(AdminApiReadPayload):
    """Read-only spot recovery preview evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_recovery_preview"
    module_id: str = "spot_operations"
    approved_phase_range: str
    status: AdminApiGateStatus = AdminApiGateStatus.WARNING
    filters: FlexibleDict = Field(default_factory=dict)
    source_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    sources: list[SpotRecoveryPreviewSourceItem] = Field(default_factory=list)
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    apply_review_contract_available: bool = False
    rollback_plan_contract_available: bool = False
    reconciliation_proof_contract_available: bool = False
    recovery_apply_available: bool = False
    rollback_plan_available: bool = False
    reconciliation_proof_available: bool = False
    backend_owned: bool = True
    read_only: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    spot_rule_boundary: str
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class SpotRecoveryContractCandidateItem(BaseModel):
    """Spot recovery candidate identity evidence for contract review routes."""

    model_config = ConfigDict(extra="forbid")

    candidate_type: str
    identity_key: str = "client_order_id"
    identity_value: str
    preview_source: str
    source_route: str
    apply_review_route: str = "/api/v1/spot/recovery/apply-review"
    rollback_plan_route: str = "/api/v1/spot/recovery/rollback-plan"
    reconciliation_proof_route: str = "/api/v1/spot/recovery/reconciliation-proof"
    preview_only: bool = True
    backend_owned: bool = True
    detail: str


class SpotRecoveryContractGateItem(BaseModel):
    """Backend-owned recovery contract gate evidence."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    route: str | None = None
    method: str | None = None
    action_class: AdminApiActionClass = AdminApiActionClass.READ_ONLY
    required_permission: AdminApiPermission | str | None = None
    required: bool = True
    blocking: bool = True
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class SpotRecoveryStateRepairTaxonomyItem(BaseModel):
    """Allowed and rejected Spot recovery state-repair category evidence."""

    model_config = ConfigDict(extra="forbid")

    category: SpotRecoveryRepairCategory
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    allowed_local_state_scope: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    rejected_mutations: list[str] = Field(default_factory=list)
    state_repair_available: bool = False
    order_state_mutation_allowed: bool = False
    fill_ledger_mutation_allowed: bool = False
    reconciliation_state_mutation_allowed: bool = False
    exchange_state_mutation_allowed: bool = False
    coinbase_read_allowed: bool = False
    coinbase_submission_allowed: bool = False
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class SpotRecoveryRepairTargetItem(BaseModel):
    """Backend-owned repair target keyed by ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    client_order_id: str
    identity_key: str = "client_order_id"
    candidate_type: str
    preview_source: str
    source_route: str
    categories: list[SpotRecoveryRepairCategory] = Field(default_factory=list)
    execution_journal_ids: list[str] = Field(default_factory=list)
    repair_result_ids: list[str] = Field(default_factory=list)
    completion_ids: list[str] = Field(default_factory=list)
    latest_apply_journal_id: str | None = None
    latest_rollback_journal_id: str | None = None
    exchange_state_proof_ids: list[str] = Field(default_factory=list)
    reconciliation_proof_ids: list[str] = Field(default_factory=list)
    rollback_plan_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    reconciliation_plan_ids: list[str] = Field(default_factory=list)
    pre_apply_snapshot_id: str
    dry_run_repair_plan_id: str
    completion_state: SpotRecoveryCompletionState
    post_apply_reconciliation_completed: bool = False
    fully_reconciled: bool = False
    state_repair_available: bool = Field(
        default=False,
        description=(
            "True when backend recovery-state repair evidence can be derived "
            "for this target."
        ),
    )
    state_repair_executed: bool = Field(
        default=False,
        description=(
            "True only when guarded local repair-result evidence exists for "
            "this target. This does not mean order-state mutation, "
            "exchange-state mutation, reconciliation execution, Coinbase REST "
            "reads, or Coinbase order submission occurred."
        ),
    )
    order_state_mutated: bool = Field(
        default=False,
        description="True only when backend order state was actually mutated.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="True only when backend exchange state was actually mutated.",
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="True only when backend reconciliation execution actually ran.",
    )
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class SpotRecoveryPreApplySnapshotItem(BaseModel):
    """Read-only pre-apply snapshot evidence for one repair target."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    target_id: str
    client_order_id: str
    source: str = "admin_api_spot_recovery_pre_apply_snapshot"
    snapshot_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    snapshot_captured: bool = False
    required_before_state_repair: bool = True
    execution_journal_ids: list[str] = Field(default_factory=list)
    proof_ids: list[str] = Field(default_factory=list)
    repair_result_ids: list[str] = Field(default_factory=list)
    rollback_plan_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    reconciliation_plan_ids: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class SpotRecoveryDryRunRepairPlanItem(BaseModel):
    """Dry-run local repair plan evidence without mutation authority."""

    model_config = ConfigDict(extra="forbid")

    repair_plan_id: str
    target_id: str
    client_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    categories: list[SpotRecoveryRepairCategory] = Field(default_factory=list)
    intended_local_mutations: list[str] = Field(default_factory=list)
    rejected_mutations: list[str] = Field(default_factory=list)
    required_guard_chain: list[str] = Field(default_factory=list)
    pre_apply_snapshot_id: str
    executable: bool = False
    state_repair_executed: bool = Field(
        default=False,
        description=(
            "Dry-run plans never execute repair. This remains false until a "
            "separate guarded local repair-result record is accepted."
        ),
    )
    order_state_mutated: bool = Field(
        default=False,
        description="Dry-run repair plans do not mutate backend order state.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="Dry-run repair plans do not mutate exchange state.",
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="Dry-run repair plans do not execute reconciliation.",
    )
    live_coinbase_orders_ran: bool = Field(
        default=False,
        description="Dry-run repair plans do not submit Coinbase orders.",
    )
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class SpotRecoveryCompletionStateItem(BaseModel):
    """Recovery completion state derived from backend-owned evidence."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    target_id: str
    state: SpotRecoveryCompletionState
    completion_id: str | None = None
    journal_accepted: bool = False
    repair_applied: bool = False
    rollback_applied: bool = False
    reconciliation_proof_satisfied: bool = False
    post_apply_reconciliation_completed: bool = False
    fully_reconciled: bool = False
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    detail: str


class SpotRecoveryApplyReviewResponse(AdminApiReadPayload):
    """Read-only Spot recovery apply-review contract evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_recovery_apply_review"
    module_id: str = "spot_operations"
    approved_phase_range: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    filters: FlexibleDict = Field(default_factory=dict)
    candidate_count: int = Field(ge=0)
    candidates: list[SpotRecoveryContractCandidateItem] = Field(default_factory=list)
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    required_gate_chain: list[str] = Field(default_factory=list)
    contract_gate_evidence: list[SpotRecoveryContractGateItem] = Field(default_factory=list)
    state_repair_taxonomy: list[SpotRecoveryStateRepairTaxonomyItem] = Field(default_factory=list)
    repair_targets: list[SpotRecoveryRepairTargetItem] = Field(default_factory=list)
    pre_apply_snapshots: list[SpotRecoveryPreApplySnapshotItem] = Field(default_factory=list)
    dry_run_repair_plans: list[SpotRecoveryDryRunRepairPlanItem] = Field(default_factory=list)
    completion_states: list[SpotRecoveryCompletionStateItem] = Field(default_factory=list)
    persisted_execution_count: int = Field(default=0, ge=0)
    persisted_executions: list[SpotRecoveryExecutionRecordItem] = Field(default_factory=list)
    persisted_repair_result_count: int = Field(default=0, ge=0)
    persisted_repair_results: list[SpotRecoveryRepairResultRecordItem] = Field(default_factory=list)
    latest_apply_journal_id: str | None = None
    latest_repair_result_id: str | None = None
    execution_journal_available: bool = True
    state_repair_taxonomy_available: bool = True
    repair_target_model_available: bool = True
    pre_apply_snapshot_required: bool = True
    dry_run_repair_plan_available: bool = True
    state_repair_contract_available: bool = Field(
        default=False,
        description=(
            "True when the guarded local repair-result contract is available "
            "for apply-review evidence. This is backend-owned evidence only, "
            "not browser authority, Coinbase activity, order-state mutation, "
            "or exchange-state mutation."
        ),
    )
    missing_contracts: list[str] = Field(default_factory=list)
    apply_review_contract_available: bool = True
    recovery_apply_available: bool = True
    rollback_plan_required: bool = True
    reconciliation_proof_required: bool = True
    post_apply_reconciliation_required: bool = True
    post_apply_reconciliation_satisfied_count: int = Field(default=0, ge=0)
    backend_owned: bool = True
    read_only: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    spot_rule_boundary: str
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class SpotRecoveryRollbackPlanResponse(AdminApiReadPayload):
    """Read-only Spot recovery rollback-plan contract evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_recovery_rollback_plan"
    module_id: str = "spot_operations"
    approved_phase_range: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    filters: FlexibleDict = Field(default_factory=dict)
    candidate_count: int = Field(ge=0)
    candidates: list[SpotRecoveryContractCandidateItem] = Field(default_factory=list)
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    rollback_steps: list[FlexibleDict] = Field(default_factory=list)
    state_repair_taxonomy: list[SpotRecoveryStateRepairTaxonomyItem] = Field(default_factory=list)
    repair_targets: list[SpotRecoveryRepairTargetItem] = Field(default_factory=list)
    pre_apply_snapshots: list[SpotRecoveryPreApplySnapshotItem] = Field(default_factory=list)
    dry_run_repair_plans: list[SpotRecoveryDryRunRepairPlanItem] = Field(default_factory=list)
    completion_states: list[SpotRecoveryCompletionStateItem] = Field(default_factory=list)
    persisted_execution_count: int = Field(default=0, ge=0)
    persisted_executions: list[SpotRecoveryExecutionRecordItem] = Field(default_factory=list)
    persisted_repair_result_count: int = Field(default=0, ge=0)
    persisted_repair_results: list[SpotRecoveryRepairResultRecordItem] = Field(default_factory=list)
    latest_rollback_journal_id: str | None = None
    latest_repair_result_id: str | None = None
    execution_journal_available: bool = True
    state_repair_taxonomy_available: bool = True
    repair_target_model_available: bool = True
    pre_apply_snapshot_required: bool = True
    dry_run_repair_plan_available: bool = True
    rollback_repair_contract_available: bool = Field(
        default=False,
        description=(
            "True when the guarded local repair-result contract is available "
            "for rollback-plan evidence. This is backend-owned evidence only, "
            "not browser authority, Coinbase activity, order-state mutation, "
            "or exchange-state mutation."
        ),
    )
    missing_contracts: list[str] = Field(default_factory=list)
    rollback_plan_contract_available: bool = True
    rollback_execution_available: bool = True
    recovery_apply_available: bool = True
    backend_owned: bool = True
    read_only: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    spot_rule_boundary: str
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class SpotRecoveryProofRecordItem(BaseModel):
    """Read-only Spot recovery proof record evidence."""

    model_config = ConfigDict(extra="forbid")

    proof_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    client_order_id: str
    exchange_state_proof_id: str | None = None
    reconciliation_proof_id: str | None = None
    exchange_state_evidence_ref: str | None = None
    recovery_apply_audit_id: str | None = None
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_spot_recovery_proof_log"
    proof_persisted: bool = True
    recovery_apply_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for recovery apply journal/proof "
            "acceptance only. This field does not mean state repair executed; "
            "prefer execution_journal_accepted, recovery_apply_journal_accepted, "
            "repair-result readback, and explicit mutation flags when available."
        ),
    )
    rollback_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for rollback journal/proof acceptance "
            "only. This field does not mean rollback mutated order or exchange "
            "state; prefer rollback_journal_accepted, repair-result readback, "
            "and explicit mutation flags when available."
        ),
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="True only when backend reconciliation execution has actually run.",
    )
    order_state_mutated: bool = Field(
        default=False,
        description="True only when backend order state was actually mutated.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="True only when backend exchange-state evidence was actually mutated.",
    )
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryExchangeStateSnapshotRecordItem(BaseModel):
    """Read-only Spot recovery exchange-state snapshot evidence."""

    model_config = ConfigDict(extra="forbid")

    exchange_state_snapshot_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT
    )
    client_order_id: str
    product_id: str
    source_timestamp: str
    snapshot_source: SpotRecoveryExchangeStateSnapshotSource
    snapshot_evidence_ref: str
    reconciliation_plan_id: str
    reconciliation_proof_id: str
    completion_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_spot_recovery_snapshot_log"
    snapshot_recorded: bool = True
    source_trusted: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryExecutionRecordItem(BaseModel):
    """Read-only Spot recovery apply/rollback journal evidence."""

    model_config = ConfigDict(extra="forbid")

    journal_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    client_order_id: str
    rollback_plan_id: str
    recovery_apply_audit_id: str | None = None
    recovery_apply_journal_id: str | None = None
    exchange_state_proof_id: str | None = None
    reconciliation_proof_id: str | None = None
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    audit_id: str
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_spot_recovery_execution_journal"
    repair_journal_persisted: bool = True
    state_repair_requested: bool = False
    repair_guard_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    repair_guard_passed: bool = False
    repair_guard_failures: list[str] = Field(default_factory=list)
    repair_guard_required_chain: list[str] = Field(default_factory=list)
    repair_target_id: str | None = None
    expected_repair_target_id: str | None = None
    pre_apply_snapshot_id: str | None = None
    expected_pre_apply_snapshot_id: str | None = None
    dry_run_repair_plan_id: str | None = None
    expected_dry_run_repair_plan_id: str | None = None
    repair_result_id: str | None = None
    repair_result_journal_persisted: bool = False
    execution_journal_accepted: bool = Field(
        default=True,
        description=(
            "Append-only local execution journal acceptance. This is evidence "
            "only and does not imply state repair, rollback mutation, "
            "reconciliation execution, or Coinbase activity."
        ),
    )
    recovery_apply_journal_accepted: bool = Field(
        default=False,
        description=(
            "True when the accepted journal row is a recovery-apply journal. "
            "Prefer this over legacy recovery_apply_executed for new consumers."
        ),
    )
    rollback_journal_accepted: bool = Field(
        default=False,
        description=(
            "True when the accepted journal row is a rollback journal. Prefer "
            "this over legacy rollback_executed for new consumers."
        ),
    )
    recovery_apply_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for recovery apply journal acceptance "
            "only. This does not mean state repair executed; prefer "
            "execution_journal_accepted, recovery_apply_journal_accepted, "
            "repair_result_journal_persisted, and mutation flags."
        ),
    )
    rollback_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for rollback journal acceptance only. "
            "This does not mean rollback mutated order or exchange state; "
            "prefer execution_journal_accepted, rollback_journal_accepted, "
            "repair_result_journal_persisted, and mutation flags."
        ),
    )
    post_apply_reconciliation_required: bool = True
    post_apply_reconciliation_satisfied: bool = False
    repair_intent_accepted: bool = True
    state_repair_executed: bool = Field(
        default=False,
        description=(
            "True only when the guarded local repair-result contract was "
            "accepted for backend recovery-state evidence. This is not "
            "order-state mutation, exchange-state mutation, reconciliation "
            "execution, Coinbase REST reads, or Coinbase order submission; "
            "check the explicit mutation and Coinbase flags for those."
        ),
    )
    order_state_mutated: bool = Field(
        default=False,
        description="True only when backend order state was actually mutated.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="True only when backend exchange state was actually mutated.",
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="True only when backend reconciliation execution actually ran.",
    )
    coinbase_order_submitted: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryRepairResultRecordItem(BaseModel):
    """Read-only Spot recovery guarded local repair result evidence."""

    model_config = ConfigDict(extra="forbid")

    repair_result_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    completion_state: SpotRecoveryCompletionState
    client_order_id: str
    journal_id: str
    audit_id: str
    rollback_plan_id: str
    recovery_apply_audit_id: str | None = None
    recovery_apply_journal_id: str | None = None
    exchange_state_proof_id: str | None = None
    reconciliation_proof_id: str | None = None
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    repair_target_id: str
    pre_apply_snapshot_id: str
    dry_run_repair_plan_id: str
    guard_passed: bool = True
    guard_failures: list[str] = Field(default_factory=list)
    state_repair_executed: bool = Field(
        default=True,
        description=(
            "True for guarded local repair-result records accepted into "
            "backend recovery-state evidence. This does not imply order-state "
            "mutation, exchange-state mutation, reconciliation execution, "
            "Coinbase REST reads, or Coinbase order submission."
        ),
    )
    repair_applied: bool = Field(
        default=False,
        description=(
            "True when this local repair-result record represents the apply "
            "side of the recovery-state contract, not an order/exchange "
            "state mutation."
        ),
    )
    rollback_applied: bool = Field(
        default=False,
        description=(
            "True when this local repair-result record represents the "
            "rollback side of the recovery-state contract, not an "
            "order/exchange state mutation."
        ),
    )
    post_apply_reconciliation_completed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryCompletionRecordItem(BaseModel):
    """Read-only Spot recovery post-apply completion evidence."""

    model_config = ConfigDict(extra="forbid")

    completion_id: str
    recorded_at: str
    mutation_family: AdminApiMutationFamilyType
    completion_state: SpotRecoveryCompletionState
    client_order_id: str
    repair_result_id: str
    journal_id: str
    audit_id: str
    reconciliation_proof_id: str
    proof_id: str
    proof_audit_id: str
    reconciliation_plan_id: str
    approval_snapshot_id: str
    admission_audit_id: str
    cap_guard_decision_id: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str
    actor_id: str
    operator_intent: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    guard_passed: bool = True
    guard_failures: list[str] = Field(default_factory=list)
    post_apply_reconciliation_completed: bool = True
    reconciliation_proof_satisfied: bool = True
    fully_reconciled: bool = True
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryReconciliationExecutionBoundaryItem(BaseModel):
    """Fail-closed boundary for future Spot recovery reconciliation execution."""

    model_config = ConfigDict(extra="forbid")

    boundary_id: str
    client_order_id: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION
    )
    read_route: str = "/api/v1/spot/recovery/reconciliation-proof"
    command_route: str | None = None
    method: str | None = None
    route_inventory_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    action_class: AdminApiActionClass = AdminApiActionClass.READ_ONLY
    required_permission: AdminApiPermission | str = (
        AdminApiPermission.AUDIT_READ
    )
    future_action_class: AdminApiActionClass = (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    future_required_permission: AdminApiPermission | str = (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE
    )
    service_method: str | None = None
    required_inputs: list[str] = Field(default_factory=list)
    present_inputs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    reconciliation_plan_id: str | None = None
    reconciliation_proof_id: str | None = None
    product_id: str | None = None
    exchange_state_snapshot_id: str | None = None
    source_timestamp: str | None = None
    snapshot_source: SpotRecoveryExchangeStateSnapshotSource | None = None
    snapshot_evidence_ref: str | None = None
    completion_id: str | None = None
    repair_result_id: str | None = None
    journal_id: str | None = None
    approval_snapshot_id: str | None = None
    admission_audit_id: str | None = None
    cap_guard_decision_id: str | None = None
    idempotency_key: str | None = None
    payload_hash: str | None = None
    operator_intent: str | None = None
    blockers: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    read_only: bool = True
    route_bound: bool = False
    noop_review_allowed: bool = True
    local_state_reconciliation_allowed: bool = False
    order_state_mutation_allowed: bool = False
    exchange_state_mutation_allowed: bool = False
    coinbase_rest_read_allowed: bool = False
    coinbase_order_submission_allowed: bool = False
    snapshot_recorded: bool = False
    source_trusted: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryReconciliationProofResponse(AdminApiReadPayload):
    """Read-only Spot recovery reconciliation-proof contract evidence."""

    model_config = ConfigDict(extra="forbid")

    type: str = "spot_recovery_reconciliation_proof"
    module_id: str = "spot_operations"
    approved_phase_range: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    filters: FlexibleDict = Field(default_factory=dict)
    candidate_count: int = Field(ge=0)
    candidates: list[SpotRecoveryContractCandidateItem] = Field(default_factory=list)
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    required_proof_fields: list[str] = Field(default_factory=list)
    state_repair_taxonomy: list[SpotRecoveryStateRepairTaxonomyItem] = Field(default_factory=list)
    repair_targets: list[SpotRecoveryRepairTargetItem] = Field(default_factory=list)
    pre_apply_snapshots: list[SpotRecoveryPreApplySnapshotItem] = Field(default_factory=list)
    dry_run_repair_plans: list[SpotRecoveryDryRunRepairPlanItem] = Field(default_factory=list)
    completion_states: list[SpotRecoveryCompletionStateItem] = Field(default_factory=list)
    persisted_proof_count: int = Field(default=0, ge=0)
    persisted_proofs: list[SpotRecoveryProofRecordItem] = Field(default_factory=list)
    proof_persistence_available: bool = True
    execution_journal_available: bool = True
    state_repair_taxonomy_available: bool = True
    repair_target_model_available: bool = True
    pre_apply_snapshot_required: bool = True
    dry_run_repair_plan_available: bool = True
    post_apply_reconciliation_completion_available: bool = False
    persisted_execution_count: int = Field(default=0, ge=0)
    persisted_executions: list[SpotRecoveryExecutionRecordItem] = Field(default_factory=list)
    persisted_repair_result_count: int = Field(default=0, ge=0)
    persisted_repair_results: list[SpotRecoveryRepairResultRecordItem] = Field(default_factory=list)
    persisted_completion_count: int = Field(default=0, ge=0)
    persisted_completions: list[SpotRecoveryCompletionRecordItem] = Field(default_factory=list)
    persisted_snapshot_count: int = Field(default=0, ge=0)
    persisted_snapshots: list[SpotRecoveryExchangeStateSnapshotRecordItem] = (
        Field(default_factory=list)
    )
    reconciliation_execution_boundary_available: bool = True
    reconciliation_execution_boundary_count: int = Field(default=0, ge=0)
    reconciliation_execution_boundaries: list[
        SpotRecoveryReconciliationExecutionBoundaryItem
    ] = Field(default_factory=list)
    latest_reconciliation_execution_boundary_id: str | None = None
    latest_exchange_state_proof_id: str | None = None
    latest_reconciliation_proof_id: str | None = None
    latest_apply_journal_id: str | None = None
    latest_rollback_journal_id: str | None = None
    latest_repair_result_id: str | None = None
    latest_completion_id: str | None = None
    latest_exchange_state_snapshot_id: str | None = None
    post_apply_reconciliation_required_count: int = Field(default=0, ge=0)
    post_apply_reconciliation_satisfied_count: int = Field(default=0, ge=0)
    post_apply_reconciliation_completed_count: int = Field(default=0, ge=0)
    missing_contracts: list[str] = Field(default_factory=list)
    reconciliation_proof_contract_available: bool = True
    exchange_state_proof_writer_available: bool = True
    exchange_state_snapshot_contract_available: bool = True
    reconciliation_proof_writer_available: bool = True
    reconciliation_execution_available: bool = False
    recovery_apply_available: bool = True
    backend_owned: bool = True
    read_only: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    spot_rule_boundary: str
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class SpotCommandSuiteProofRouteItem(BaseModel):
    """Backend proof route required before a spot command can be executable."""

    model_config = ConfigDict(extra="forbid")

    gate: AdminApiLivePreflightCategory
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    blocking: bool = True
    identity_key: str
    command_identity_key: str
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class SpotCommandSuiteCommandItem(BaseModel):
    """One spot admin command surface and its remaining gate chain."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    identity_key: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    live_execution_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    live_enabled: bool = False
    live_eligible: bool = False
    executable: bool = False
    live_adapter_configured: bool = False
    approval_required: bool = True
    cap_guard_required: bool = True
    admission_audit_required: bool = True
    reconciliation_required: bool = True
    idempotency_required: bool = True
    operator_intent_required: bool = True
    payload_hash_required: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    product_scope: str = "USDC spot command scope"
    spot_rule_boundary: str
    required_gate_chain: list[str] = Field(default_factory=list)
    missing_gate_chain: list[str] = Field(default_factory=list)
    readiness_preconditions: list[AdminLiveReadinessPreconditionItem] = Field(
        default_factory=list
    )
    readiness_precondition_count: int = 0
    blocking_readiness_precondition_count: int = 0
    passed_readiness_precondition_count: int = 0
    backend_contract_refs: list[str] = Field(default_factory=list)
    frontend_contract_refs: list[str] = Field(default_factory=list)
    documentation_refs: list[str] = Field(default_factory=list)
    proof_routes: list[SpotCommandSuiteProofRouteItem] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class SpotCommandSuiteCoverageGapEvidenceRouteItem(BaseModel):
    """Read route that supplies evidence for a spot command-suite coverage gap."""

    model_config = ConfigDict(extra="forbid")

    route: str
    method: str = "GET"
    action_class: AdminApiActionClass = AdminApiActionClass.READ_ONLY
    required_permission: AdminApiPermission | str
    shared_method: str
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class SpotCommandSuiteCoverageGapItem(BaseModel):
    """Remaining spot admin suite family that is not yet command-complete."""

    model_config = ConfigDict(extra="forbid")

    family: AdminApiSpotCommandSuiteGapFamily
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    exposure_status: AdminApiFunctionalityExposureStatus
    command_route: str | None = None
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    current_read_evidence: list[SpotCommandSuiteCoverageGapEvidenceRouteItem] = Field(
        default_factory=list
    )
    required_backend_contract: str
    required_gate_chain: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    spot_rule_boundary: str
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class SpotCommandSuiteResponse(AdminApiReadPayload):
    """Read-only M54 spot command-suite readiness evidence."""

    type: str = "spot_command_suite"
    module_id: str = "spot_operations"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    approved_phase_range: str
    command_count: int = 0
    blocked_command_count: int = 0
    live_enabled_command_count: int = 0
    executable_command_count: int = 0
    spot_rules_platform_default: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    commands: list[SpotCommandSuiteCommandItem] = Field(default_factory=list)
    coverage_gap_count: int = 0
    coverage_gaps: list[SpotCommandSuiteCoverageGapItem] = Field(default_factory=list)
    read_routes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    message: str | None = None


class StealthCommandSuiteProofRouteItem(BaseModel):
    """Backend proof route required before a stealth command can be executable."""

    model_config = ConfigDict(extra="forbid")

    gate: AdminApiLivePreflightCategory
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    blocking: bool = True
    identity_key: str
    command_identity_key: str
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteCommandItem(BaseModel):
    """One stealth admin command surface and its remaining gate chain."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    identity_key: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    live_execution_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    live_enabled: bool = False
    live_eligible: bool = False
    executable: bool = False
    live_adapter_configured: bool = False
    approval_required: bool = True
    cap_guard_required: bool = True
    admission_audit_required: bool = True
    reconciliation_required: bool = True
    idempotency_required: bool = True
    operator_intent_required: bool = True
    payload_hash_required: bool = True
    exchange_truth_required: bool = True
    active_placement_evidence_required: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    product_scope: str = "stealth command scope"
    stealth_rule_boundary: str
    required_gate_chain: list[str] = Field(default_factory=list)
    missing_gate_chain: list[str] = Field(default_factory=list)
    readiness_preconditions: list[AdminLiveReadinessPreconditionItem] = Field(
        default_factory=list
    )
    readiness_precondition_count: int = 0
    blocking_readiness_precondition_count: int = 0
    passed_readiness_precondition_count: int = 0
    backend_contract_refs: list[str] = Field(default_factory=list)
    frontend_contract_refs: list[str] = Field(default_factory=list)
    documentation_refs: list[str] = Field(default_factory=list)
    proof_routes: list[StealthCommandSuiteProofRouteItem] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteCoverageGapEvidenceRouteItem(BaseModel):
    """Read route that supplies evidence for a stealth command-suite coverage gap."""

    model_config = ConfigDict(extra="forbid")

    route: str
    method: str = "GET"
    action_class: AdminApiActionClass = AdminApiActionClass.READ_ONLY
    required_permission: AdminApiPermission | str
    shared_method: str
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "read_only_forward"
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteCoverageGapItem(BaseModel):
    """Remaining stealth admin suite family that is not yet command-complete."""

    model_config = ConfigDict(extra="forbid")

    family: AdminApiStealthCommandSuiteGapFamily
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    exposure_status: AdminApiFunctionalityExposureStatus
    command_route: str | None = None
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    current_read_evidence: list[StealthCommandSuiteCoverageGapEvidenceRouteItem] = Field(
        default_factory=list
    )
    required_backend_contract: str
    required_gate_chain: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    stealth_rule_boundary: str
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteExchangeTruthItem(BaseModel):
    """Backend-owned exchange-truth prerequisite for a stealth command."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    identity_key: str
    command_identity_key: str = "stealth_order_id"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    exchange_truth_required: bool = True
    active_placement_evidence_required: bool = True
    active_placement_exchange_truth_resolved: bool = False
    active_placement_exchange_truth_proof_id: str | None = None
    accepted_command_identity_keys: list[str] = Field(default_factory=list)
    rejected_command_identity_keys: list[str] = Field(default_factory=list)
    active_placement_client_order_id_authority: str = "evidence_only"
    exchange_order_id_authority: str = "evidence_only"
    current_read_evidence_routes: list[str] = Field(default_factory=list)
    current_read_evidence: list[StealthCommandSuiteCoverageGapEvidenceRouteItem] = (
        Field(default_factory=list)
    )
    required_gate_chain: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    live_enabled: bool = False
    executable: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class StealthCommandSuiteCancelReplaceBoundaryItem(BaseModel):
    """Backend-owned cancel/replace prerequisite boundary for revealed placements."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    identity_key: str = "stealth_order_id"
    command_identity_key: str = "stealth_order_id"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    cancel_replace_required: bool = True
    cancel_replace_allowed: bool = False
    cancel_replace_ran: bool = False
    cancel_replace_proof_required: bool = True
    cancel_replace_proof_resolved: bool = False
    cancel_replace_proof_id: str | None = None
    active_placement_exchange_truth_required: bool = True
    active_placement_exchange_truth_resolved: bool = False
    accepted_command_identity_keys: list[str] = Field(default_factory=list)
    rejected_command_identity_keys: list[str] = Field(default_factory=list)
    active_placement_client_order_id_authority: str = "evidence_only"
    exchange_order_id_authority: str = "evidence_only"
    required_gate_chain: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    canonical_behavior_path: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_cancel_ran: bool = False
    coinbase_submit_ran: bool = False
    coinbase_read_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    documentation_refs: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteAdmissionRequirementItem(BaseModel):
    """One backend-owned evidence requirement for a stealth command admission."""

    model_config = ConfigDict(extra="forbid")

    evidence_name: AdminApiStealthAdmissionEvidence
    source: str
    route: str
    method: str
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    identity_key: str
    command_identity_key: str = "stealth_order_id"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    present: bool = False
    blocking: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCommandSuiteAdmissionReadinessItem(BaseModel):
    """Per-command admission readiness map before stealth execution can run."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    route: str
    method: str
    identity_key: str
    command_identity_key: str = "stealth_order_id"
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    shared_method: str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    live_execution_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    admission_allowed: bool = False
    executable: bool = False
    live_enabled: bool = False
    live_adapter_invocation_allowed: bool = False
    manager_invocation_allowed: bool = False
    route_local_execution_allowed: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    accepted_command_identity_keys: list[str] = Field(default_factory=list)
    rejected_command_identity_keys: list[str] = Field(default_factory=list)
    required_evidence_count: int = 0
    present_evidence_count: int = 0
    missing_evidence_count: int = 0
    missing_evidence: list[str] = Field(default_factory=list)
    requirements: list[StealthCommandSuiteAdmissionRequirementItem] = Field(
        default_factory=list
    )
    required_context_count: int = 0
    present_context_count: int = 0
    missing_context_count: int = 0
    missing_context: list[str] = Field(default_factory=list)
    context_requirements: list[StealthCommandSuiteAdmissionContextItem] = Field(
        default_factory=list
    )
    exact_context_present: bool = False
    resolver_lookup_allowed: bool = False
    resolver_lookup_ran: bool = False
    proof_resolution_attempted: bool = False
    active_placement_exchange_truth_required: bool = True
    exchange_truth_verified: bool = False
    lifecycle_write_guard_required: bool = False
    coinbase_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandExecutionPrerequisiteResolverItem(BaseModel):
    """Read-only prerequisite lookup evidence for non-create stealth execution."""

    model_config = ConfigDict(extra="forbid")

    prerequisite: StealthCommandExecutionPrerequisite
    source: str = Field(min_length=1)
    route: str
    method: str = "POST"
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    lookup_status: StealthCommandExecutionPrerequisiteLookupStatus
    lookup_ran: bool = False
    resolved: bool = False
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    stale_or_invalid: bool = False
    authority: str = "read_only_no_execution"
    proof_lookup_authority: str = "none"
    writes_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class StealthCommandExecutionReadinessStageItem(BaseModel):
    """Ordered fail-closed stage evidence before stealth command execution."""

    model_config = ConfigDict(extra="forbid")

    stage_order: int = Field(ge=1)
    workflow_family: AdminApiStealthCommandSuiteGapFamily
    mutation_family: AdminApiMutationFamilyType
    prerequisite: StealthCommandExecutionPrerequisite
    source: str = Field(min_length=1)
    route: str
    method: str = "POST"
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    lookup_status: StealthCommandExecutionPrerequisiteLookupStatus
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    blocking: bool = True
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    next_required_contract: str
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    no_live_execution: bool = True
    manager_invocation_allowed: bool = False
    coinbase_read_allowed: bool = False
    coinbase_write_allowed: bool = False
    state_mutation_allowed: bool = False
    detail: str


class StealthPostWriteReconciliationBoundaryEvidence(BaseModel):
    """Fail-closed post-write reconciliation boundary for stealth commands."""

    model_config = ConfigDict(extra="forbid")

    boundary_type: str = "stealth_post_write_reconciliation_plan_boundary"
    mutation_family: AdminApiMutationFamilyType
    command_route: str
    command_method: str = "POST"
    service_method: str
    identity_key: str = "stealth_order_id"
    stealth_order_id: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = False
    payload_bound: bool = False
    idempotency_bound: bool = False
    operator_intent_bound: bool = False
    idempotency_key: str | None = None
    payload_hash: str | None = None
    operator_intent: str | None = None
    post_write_reconciliation_route: str = "/api/v1/admin/reconciliation/plans"
    post_write_reconciliation_method: str = "POST"
    post_write_reconciliation_source: str = "post_write_reconciliation_contract"
    post_write_reconciliation_missing_reason: str | None = (
        "post_write_reconciliation_missing"
    )
    reconciliation_mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.ADMIN_RECONCILIATION_PLAN
    )
    reconciliation_action_class: AdminApiActionClass = (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    reconciliation_required_permission: AdminApiPermission | str = (
        AdminApiPermission.RECONCILIATION_RECORD
    )
    required_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    blocking: bool = True
    execution_allowed: bool = False
    plan_write_allowed: bool = False
    plan_write_ran: bool = False
    post_write_completion_required: bool = True
    post_write_completion_recorded: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    lifecycle_state_mutation_allowed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutation_allowed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutation_allowed: bool = False
    exchange_state_mutated: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    execution_boundary_authority: str = "backend_contract_only_no_execution"
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthPostWriteReconciliationCompletionVerifierEvidence(BaseModel):
    """Fail-closed completion verifier for stealth post-write reconciliation."""

    model_config = ConfigDict(extra="forbid")

    boundary_type: str = "stealth_post_write_reconciliation_completion_verifier"
    mutation_family: AdminApiMutationFamilyType
    command_route: str
    command_method: str = "POST"
    service_method: str
    identity_key: str = "stealth_order_id"
    stealth_order_id: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    blocking: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = False
    payload_bound: bool = False
    idempotency_bound: bool = False
    operator_intent_bound: bool = False
    idempotency_key: str | None = None
    payload_hash: str | None = None
    operator_intent: str | None = None
    proof_lookup_authority: str = "backend_store_read_only_no_execution"
    post_write_reconciliation_proof_id: str | None = None
    post_write_proof_found: bool = False
    post_write_proof_safe: bool = False
    safe_post_write_proof_required: bool = True
    execution_journal_required: bool = True
    execution_journal_accepted: bool = False
    execution_journal_acceptance_id: str | None = None
    execution_journal_acceptance_found: bool = False
    execution_journal_acceptance_safe: bool = False
    execution_journal_acceptance_route: str = (
        "/api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals"
    )
    execution_journal_acceptance_method: str = "POST"
    execution_journal_acceptance_source: str = (
        "admin_api_stealth_post_write_execution_journal_log"
    )
    reconciliation_verification_required: bool = True
    reconciliation_verification_id: str | None = None
    reconciliation_verification_found: bool = False
    reconciliation_verification_safe: bool = False
    reconciliation_verification_route: str = (
        "/api/v1/stealth/orders/{stealth_order_id}/"
        "post-write-reconciliation-verifications"
    )
    reconciliation_verification_method: str = "POST"
    reconciliation_verification_source: str = (
        "admin_api_stealth_post_write_reconciliation_verification_log"
    )
    post_write_reconciliation_verified: bool = False
    completion_proof_required: bool = True
    completion_proof_recorded: bool = False
    required_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    execution_allowed: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    lifecycle_state_mutation_allowed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutation_allowed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutation_allowed: bool = False
    exchange_state_mutated: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    execution_boundary_authority: str = "backend_contract_only_no_execution"
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandExecutionBlockerChainItem(BaseModel):
    """Typed blocker evidence that remains after prerequisite resolution."""

    model_config = ConfigDict(extra="forbid")

    blocker_order: int = Field(ge=1)
    blocker: StealthCommandExecutionBlocker
    source_prerequisite: StealthCommandExecutionPrerequisite | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    blocking: bool = True
    resolved: bool = False
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    next_required_contract: str
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    no_live_execution: bool = True
    manager_invocation_allowed: bool = False
    coinbase_submit_allowed: bool = False
    coinbase_cancel_allowed: bool = False
    coinbase_read_allowed: bool = False
    cancel_replace_allowed: bool = False
    reconciliation_execution_allowed: bool = False
    state_mutation_allowed: bool = False
    detail: str


class StealthExecutionCandidateEvidence(BaseModel):
    """Read-only evidence for the future backend execution candidate."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    workflow_family: AdminApiStealthCommandSuiteGapFamily
    command_route: str
    command_method: str = "POST"
    service_method: str
    manager_methods: list[str] = Field(default_factory=list)
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    execution_candidate_available: bool = True
    execution_candidate_authority: str = "read_only_planning_evidence"
    execution_allowed: bool = False
    executable: bool = False
    exact_command_context_present: bool = False
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    live_execution_service_required: bool = True
    live_execution_service_enabled: bool = False
    live_execution_adapter_required: bool = True
    live_execution_adapter_executable: bool = False
    unresolved_blocker_count: int = Field(default=0, ge=0)
    unresolved_blockers: list[str] = Field(default_factory=list)
    next_required_contracts: list[str] = Field(default_factory=list)
    canonical_execution_path: list[str] = Field(default_factory=list)
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    state_mutation_allowed: bool = False
    state_mutated: bool = False
    no_live_execution: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionPreflightEvidence(BaseModel):
    """Candidate-bound pre-execution checks for stealth command evidence."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    workflow_family: AdminApiStealthCommandSuiteGapFamily
    command_route: str
    command_method: str = "POST"
    service_method: str
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    preflight_available: bool = True
    preflight_authority: str = "read_only_candidate_preflight"
    candidate_ref: str = "execution_candidate"
    candidate_available: bool = True
    candidate_executable: bool = False
    candidate_execution_allowed: bool = False
    all_blockers_resolved: bool = False
    unresolved_blocker_count: int = Field(default=0, ge=0)
    unresolved_blockers: list[str] = Field(default_factory=list)
    next_required_contracts: list[str] = Field(default_factory=list)
    check_count: int = Field(default=0, ge=0)
    blocking_check_count: int = Field(default=0, ge=0)
    passed_check_count: int = Field(default=0, ge=0)
    preflight_checks: list[AdminLivePreflightCheckItem] = Field(default_factory=list)
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    execution_allowed: bool = False
    executable: bool = False
    live_execution_service_enabled: bool = False
    live_execution_adapter_executable: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    state_mutation_allowed: bool = False
    state_mutated: bool = False
    no_live_execution: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionTransitionBarrierEvidence(BaseModel):
    """Read-only barrier between preflight evidence and execution authority."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    workflow_family: AdminApiStealthCommandSuiteGapFamily
    command_route: str
    command_method: str = "POST"
    service_method: str
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    transition_available: bool = True
    transition_authority: str = "read_only_transition_barrier"
    source_ref: str = "execution_preflight"
    candidate_ref: str = "execution_candidate"
    transition_allowed: bool = False
    transition_executable: bool = False
    all_preflight_checks_passed: bool = False
    first_blocking_check: str | None = None
    first_blocking_category: AdminApiLivePreflightCategory | None = None
    required_clearance_order: list[str] = Field(default_factory=list)
    preflight_check_count: int = Field(default=0, ge=0)
    blocking_check_count: int = Field(default=0, ge=0)
    passed_check_count: int = Field(default=0, ge=0)
    unresolved_blocker_count: int = Field(default=0, ge=0)
    unresolved_blockers: list[str] = Field(default_factory=list)
    next_required_contracts: list[str] = Field(default_factory=list)
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    live_execution_service_enabled: bool = False
    live_execution_adapter_executable: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    state_mutation_allowed: bool = False
    state_mutated: bool = False
    no_live_execution: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionDecisionResolutionReadinessItem(BaseModel):
    """Blocked per-item readiness evidence for a backend decision plan."""

    model_config = ConfigDict(extra="forbid")

    item_type: AdminApiStealthDecisionResolutionEvidenceType
    item_name: str
    item_order: int = Field(ge=1)
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    source_ref: str
    missing_reason: str
    readiness_authority: str = "backend_planning_only_no_resolution"
    execution_allowed: bool = False
    executed: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class StealthExecutionDecisionResolutionReadinessSummary(BaseModel):
    """Backend-derived aggregate over blocked decision readiness items."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "resolution_readiness_items"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    total_item_count: int = Field(ge=0)
    required_item_count: int = Field(ge=0)
    resolved_item_count: int = Field(ge=0)
    blocked_item_count: int = Field(ge=0)
    plan_step_count: int = Field(ge=0)
    dependency_count: int = Field(ge=0)
    verification_gate_count: int = Field(ge=0)
    blocking_item_names: list[str]
    missing_reasons: list[str]
    first_blocking_item_name: str | None = None
    summary_authority: str = "backend_derived_from_readiness_items"
    execution_allowed: bool = False
    executed: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class StealthExecutionDecisionResolutionClearanceAction(BaseModel):
    """Backend-owned action contract required to clear a handoff blocker."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "resolution_handoff"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    decision: AdminApiStealthLiveReadinessDecision
    clearance_category: AdminApiLivePreflightCategory
    clearance_ref: str
    readiness_item_type: AdminApiStealthDecisionResolutionEvidenceType
    readiness_item_order: int = Field(ge=1)
    clearance_sequence: int = Field(ge=1)
    required_predecessor_refs: list[str]
    blocking_successor_refs: list[str]
    owner: str
    required_artifact: str
    required_backend_contract: str
    required_backend_route: str | None = None
    required_backend_method: str | None = None
    required_backend_service: str | None = None
    required_evidence_ref: str
    dependency_authority: str = "backend_derived_from_readiness_item_order"
    dependency_ready: bool = False
    action_authority: str = "backend_planning_only_no_clearance"
    clearance_ready: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    execution_allowed: bool = False
    executed: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionDecisionResolutionClearanceDependencySummary(BaseModel):
    """Backend-owned aggregate over clearance action dependency evidence."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "resolution_handoff.clearance_actions"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    decision: AdminApiStealthLiveReadinessDecision
    total_action_count: int = Field(ge=0)
    blocked_action_count: int = Field(ge=0)
    ready_action_count: int = Field(ge=0)
    dependency_ready_count: int = Field(ge=0)
    dependency_blocked_count: int = Field(ge=0)
    predecessor_edge_count: int = Field(ge=0)
    successor_edge_count: int = Field(ge=0)
    dependency_blocked_refs: list[str]
    clearable_action_refs: list[str]
    terminal_action_refs: list[str]
    first_clearance_ref: str | None = None
    first_dependency_blocked_ref: str | None = None
    summary_authority: str = "backend_derived_from_clearance_actions"
    dependency_graph_ready: bool = False
    clearance_allowed: bool = False
    execution_allowed: bool = False
    executed: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionDecisionResolutionHandoff(BaseModel):
    """Backend-owned handoff classification for an unresolved decision."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "resolution_readiness_summary"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    decision: AdminApiStealthLiveReadinessDecision
    owner: str
    required_artifact: str
    handoff_authority: str = "backend_planning_only_no_resolution"
    clearance_categories: list[AdminApiLivePreflightCategory]
    blocked_clearance_refs: list[str]
    clearance_actions: list[
        StealthExecutionDecisionResolutionClearanceAction
    ]
    clearance_dependency_summary: (
        StealthExecutionDecisionResolutionClearanceDependencySummary
    )
    first_clearance_category: AdminApiLivePreflightCategory | None = None
    first_clearance_ref: str | None = None
    resolution_ready: bool = False
    execution_allowed: bool = False
    executed: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionBackendDecisionEvidence(BaseModel):
    """Blocked backend decision evidence required after live-readiness closure."""

    model_config = ConfigDict(extra="forbid")

    decision: AdminApiStealthLiveReadinessDecision
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    source_ref: str = "execution_live_readiness"
    decision_authority: str = "backend_decision_required"
    owner: str
    required_artifact: str
    missing_reason: str
    resolution_authority: str
    resolution_required: bool
    resolution_allowed: bool
    resolution_resolved: bool
    resolution_artifacts: list[str]
    resolved_resolution_artifacts: list[str] = Field(
        description=(
            "Evidence-only policy artifacts proven by prerequisite lookups. "
            "These artifacts remove the matching artifact from the missing "
            "evidence list but do not resolve the backend decision or enable "
            "live execution."
        )
    )
    resolved_resolution_evidence_ids: list[str] = Field(
        description=(
            "Evidence-only prerequisite proof ids for resolved policy "
            "artifacts. Proof ids are audit evidence and are not execution "
            "authorization."
        )
    )
    resolved_resolution_sources: list[str] = Field(
        description=(
            "Evidence-only backend proof-store sources for resolved policy "
            "artifacts. Sources are display and audit context only."
        )
    )
    resolution_evidence_present: bool = Field(
        description=(
            "True when prerequisite evidence exists for at least one policy "
            "artifact. This does not make the backend decision resolved and "
            "does not enable live execution."
        )
    )
    missing_resolution_artifacts: list[str]
    resolution_contract_refs: list[str]
    resolution_evidence_refs: list[str]
    resolver_allowed: bool
    resolver_ran: bool
    decision_write_allowed: bool
    decision_written: bool
    resolution_plan_required: bool
    resolution_plan_available: bool
    resolution_plan_status: AdminApiGateStatus
    resolution_plan_authority: str
    resolution_plan_steps: list[str]
    missing_resolution_plan_steps: list[str]
    resolution_dependency_refs: list[str]
    resolution_verification_gates: list[str]
    resolution_readiness_items: list[
        StealthExecutionDecisionResolutionReadinessItem
    ]
    resolution_readiness_summary: (
        StealthExecutionDecisionResolutionReadinessSummary
    )
    resolution_handoff: StealthExecutionDecisionResolutionHandoff
    resolution_plan_execution_allowed: bool
    resolution_plan_executed: bool
    blocks_m55_completion: bool = True
    blocks_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    no_live_execution: bool = True
    live_execution_allowed: bool = False
    executable: bool = False
    manager_invocation_allowed: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    state_mutation_allowed: bool = False
    state_mutated: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionBackendDecisionResolutionWorkItem(BaseModel):
    """Backend-owned first clearance action for an unresolved decision."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = (
        "execution_live_readiness.backend_decisions[]."
        "resolution_handoff.clearance_actions"
    )
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    work_item_index: int = Field(ge=1)
    decision: AdminApiStealthLiveReadinessDecision
    owner: str
    required_artifact: str
    missing_reason: str
    clearance_category: AdminApiLivePreflightCategory
    clearance_ref: str
    readiness_item_type: AdminApiStealthDecisionResolutionEvidenceType
    readiness_item_order: int = Field(ge=1)
    clearance_sequence: int = Field(ge=1)
    required_predecessor_refs: list[str]
    blocking_successor_refs: list[str]
    required_backend_contract: str
    required_backend_route: str | None = None
    required_backend_method: str | None = None
    required_backend_service: str | None = None
    required_evidence_ref: str
    work_item_authority: str = (
        "backend_derived_from_first_blocked_clearance_action"
    )
    dependency_ready: bool = False
    clearance_ready: bool = False
    resolution_ready: bool = False
    blocks_m55_completion: bool = True
    blocks_live_execution: bool = True
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    execution_allowed: bool = False
    executed: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionBackendDecisionResolutionWorkQueueSummary(BaseModel):
    """Backend-owned aggregate over decision resolution work items."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "backend_decision_resolution_work_items"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    total_work_item_count: int = Field(ge=0)
    blocked_work_item_count: int = Field(ge=0)
    ready_work_item_count: int = Field(ge=0)
    owner_count: int = Field(ge=0)
    work_item_refs: list[str]
    blocking_decisions: list[AdminApiStealthLiveReadinessDecision]
    blocking_owners: list[str]
    required_artifacts: list[str]
    required_backend_contracts: list[str]
    required_backend_routes: list[str]
    required_backend_methods: list[str]
    required_backend_services: list[str]
    required_evidence_refs: list[str]
    first_work_item_ref: str | None = None
    first_work_item_decision: AdminApiStealthLiveReadinessDecision | None = None
    first_work_item_owner: str | None = None
    work_queue_authority: str = (
        "backend_derived_from_backend_decision_resolution_work_items"
    )
    work_queue_ready: bool = False
    decision_resolution_ready: bool = False
    m55_completion_claim_allowed: bool = False
    live_execution_allowed: bool = False
    executable: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    execution_allowed: bool = False
    executed: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionForbiddenExecutionClaimEvidence(BaseModel):
    """Backend-owned trace for one forbidden execution claim."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "execution_live_readiness.forbidden_execution_claims"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    claim_index: int = Field(ge=1)
    forbidden_claim: str
    blocked_by_decision: AdminApiStealthLiveReadinessDecision
    blocked_by_owner: str
    required_artifact: str
    missing_reason: str
    required_clearance_category: AdminApiLivePreflightCategory
    required_clearance_ref: str | None = None
    work_queue_ref: str | None = None
    required_backend_contract: str | None = None
    required_backend_route: str | None = None
    required_backend_method: str | None = None
    required_backend_service: str | None = None
    required_evidence_ref: str | None = None
    claim_trace_authority: str = (
        "backend_derived_from_forbidden_execution_claims"
    )
    claim_forbidden: bool = True
    claim_cleared: bool = False
    resolution_ready: bool = False
    m55_completion_claim_allowed: bool = False
    live_execution_allowed: bool = False
    executable: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    execution_allowed: bool = False
    executed: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionForbiddenExecutionClaimSummary(BaseModel):
    """Backend-owned aggregate over forbidden execution claim traces."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "forbidden_execution_claim_evidence"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    total_claim_count: int = Field(ge=0)
    blocked_claim_count: int = Field(ge=0)
    cleared_claim_count: int = Field(ge=0)
    forbidden_claims: list[str]
    blocking_decisions: list[AdminApiStealthLiveReadinessDecision]
    blocking_owners: list[str]
    required_artifacts: list[str]
    required_clearance_categories: list[AdminApiLivePreflightCategory]
    required_clearance_refs: list[str]
    work_queue_refs: list[str]
    required_backend_contracts: list[str]
    required_backend_routes: list[str]
    required_backend_methods: list[str]
    required_backend_services: list[str]
    required_evidence_refs: list[str]
    first_forbidden_claim: str | None = None
    first_blocking_decision: AdminApiStealthLiveReadinessDecision | None = None
    first_required_clearance_ref: str | None = None
    claim_trace_summary_authority: str = (
        "backend_derived_from_forbidden_execution_claim_evidence"
    )
    all_claims_cleared: bool = False
    m55_completion_claim_allowed: bool = False
    live_execution_allowed: bool = False
    executable: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    execution_allowed: bool = False
    executed: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionBackendDecisionResolutionSummary(BaseModel):
    """Backend-owned aggregate over M55 backend decision evidence."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = "execution_live_readiness.backend_decisions"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    total_decision_count: int = Field(ge=0)
    required_decision_count: int = Field(ge=0)
    resolved_decision_count: int = Field(ge=0)
    blocked_decision_count: int = Field(ge=0)
    blocking_decisions: list[AdminApiStealthLiveReadinessDecision]
    blocking_owners: list[str]
    blocking_required_artifacts: list[str]
    blocking_missing_reasons: list[str]
    first_blocking_decision: AdminApiStealthLiveReadinessDecision | None = None
    first_blocking_owner: str | None = None
    first_blocking_required_artifact: str | None = None
    clearance_action_count: int = Field(ge=0)
    blocked_clearance_action_count: int = Field(ge=0)
    clearable_action_count: int = Field(ge=0)
    terminal_clearance_ref_count: int = Field(ge=0)
    summary_authority: str = "backend_derived_from_backend_decisions"
    decision_resolution_ready: bool = False
    m55_completion_claim_allowed: bool = False
    live_execution_allowed: bool = False
    executable: bool = False
    resolver_allowed: bool = False
    resolver_ran: bool = False
    decision_write_allowed: bool = False
    decision_written: bool = False
    no_live_execution: bool = True
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthExecutionLiveReadinessEvidence(BaseModel):
    """Blocked live-readiness closure after the transition barrier."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    workflow_family: AdminApiStealthCommandSuiteGapFamily
    command_route: str
    command_method: str = "POST"
    service_method: str
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    readiness_available: bool = True
    readiness_authority: str = "read_only_m55_live_readiness"
    source_ref: str = "execution_transition_barrier"
    transition_barrier_passed: bool = False
    m55_completion_claim_allowed: bool = False
    live_enablement_decision_required: bool = True
    live_execution_allowed: bool = False
    executable: bool = False
    unresolved_blocker_count: int = Field(default=0, ge=0)
    unresolved_blockers: list[str] = Field(default_factory=list)
    handoff_blocker_count: int = Field(default=0, ge=0)
    handoff_blockers: list[str] = Field(default_factory=list)
    handoff_blocker_categories: list[AdminApiLivePreflightCategory] = Field(
        default_factory=list
    )
    required_backend_contracts: list[str] = Field(default_factory=list)
    required_backend_decisions: list[AdminApiStealthLiveReadinessDecision] = (
        Field(default_factory=list)
    )
    backend_decision_count: int = Field(default=0, ge=0)
    backend_decisions: list[StealthExecutionBackendDecisionEvidence] = Field(
        default_factory=list
    )
    backend_decision_resolution_summary: (
        StealthExecutionBackendDecisionResolutionSummary
    )
    backend_decision_resolution_work_items: list[
        StealthExecutionBackendDecisionResolutionWorkItem
    ]
    backend_decision_resolution_work_queue_summary: (
        StealthExecutionBackendDecisionResolutionWorkQueueSummary
    )
    forbidden_execution_claims: list[str] = Field(default_factory=list)
    forbidden_execution_claim_evidence: list[
        StealthExecutionForbiddenExecutionClaimEvidence
    ] = Field(default_factory=list)
    forbidden_execution_claim_summary: (
        StealthExecutionForbiddenExecutionClaimSummary
    )
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    no_live_execution: bool = True
    live_execution_service_enabled: bool = False
    live_execution_adapter_executable: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    state_mutation_allowed: bool = False
    state_mutated: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class StealthCommandExecutionContractEvidence(BaseModel):
    """No-live execution posture evidence for non-create stealth commands."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType
    command_route: str
    service_method: str
    manager_methods: list[str] = Field(default_factory=list)
    identity_key: str = "stealth_order_id"
    stealth_order_id: str | None = None
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    execution_contract_boundary_configured: bool = True
    execution_contract_available: bool = False
    execution_allowed: bool = False
    exact_command_context_present: bool = False
    required_context_fields: list[str] = Field(default_factory=list)
    missing_context_fields: list[str] = Field(default_factory=list)
    required_prerequisites: list[str] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    resolved_prerequisites: list[str] = Field(default_factory=list)
    prerequisite_resolver_available: bool = True
    prerequisite_resolver_lookup_ran: bool = False
    prerequisite_resolver_authority: str = "read_only_no_execution"
    prerequisite_resolution: list[
        StealthCommandExecutionPrerequisiteResolverItem
    ] = Field(default_factory=list)
    execution_readiness_stage_count: int = Field(default=0, ge=0)
    blocked_execution_readiness_stage_count: int = Field(default=0, ge=0)
    passed_execution_readiness_stage_count: int = Field(default=0, ge=0)
    execution_readiness_stages: list[
        StealthCommandExecutionReadinessStageItem
    ] = Field(default_factory=list)
    command_specific_proof_contracts: list[StealthCommandSuiteProofRouteItem] = (
        Field(default_factory=list)
    )
    blockers: list[str] = Field(default_factory=list)
    remaining_execution_blocker_count: int = Field(default=0, ge=0)
    remaining_execution_blockers: list[
        StealthCommandExecutionBlockerChainItem
    ] = Field(default_factory=list)
    active_placement_exchange_truth_required: bool = False
    active_placement_exchange_truth_resolved: bool = False
    active_placement_exchange_truth_contract: (
        StealthCommandSuiteExchangeTruthItem | None
    ) = None
    reveal_trigger_evidence_required: bool = False
    reveal_trigger_evidence_resolved: bool = False
    manager_invocation_policy_required: bool = False
    manager_invocation_policy_resolved: bool = False
    manager_invocation_policy_proof_id: str | None = None
    state_mutation_policy_required: bool = False
    state_mutation_policy_resolved: bool = False
    state_mutation_policy_proof_id: str | None = None
    mutation_claim_snapshot_required: bool = False
    mutation_claim_snapshot_resolved: bool = False
    recovery_proof_required: bool = False
    recovery_proof_resolved: bool = False
    reconciliation_proof_required: bool = False
    reconciliation_proof_resolved: bool = False
    reconciliation_proof_id: str | None = None
    cancel_replace_proof_required: bool = False
    cancel_replace_proof_resolved: bool = False
    cancel_replace_proof_id: str | None = None
    active_placement_cancel_replace_contract: (
        StealthCommandSuiteCancelReplaceBoundaryItem | None
    ) = None
    live_execution_service_required: bool = True
    live_execution_service_resolved: bool = False
    live_execution_service_source: str = "disabled_backend_service"
    live_execution_service_missing_reason: str | None = "live_execution_disabled"
    live_execution_service_contract: (
        AdminLiveExecutionServiceContractEvidence | None
    ) = None
    live_execution_intent_contract: AdminLiveExecutionIntentEvidence | None = None
    live_execution_adapter_required: bool = True
    live_execution_adapter_resolved: bool = False
    live_execution_adapter_source: str = "disabled_stealth_command_live_adapter"
    live_execution_adapter_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    live_execution_adapter_missing_reason: str | None = (
        "live_execution_adapter_disabled"
    )
    live_execution_adapter_contract: (
        AdminLiveExecutionAdapterContractEvidence | None
    ) = None
    post_write_reconciliation_required: bool = True
    post_write_reconciliation_resolved: bool = False
    post_write_reconciliation_route: str = "/api/v1/admin/reconciliation/plans"
    post_write_reconciliation_method: str = "POST"
    post_write_reconciliation_source: str = "post_write_reconciliation_contract"
    post_write_reconciliation_missing_reason: str | None = (
        "post_write_reconciliation_missing"
    )
    post_write_reconciliation_boundary: (
        StealthPostWriteReconciliationBoundaryEvidence | None
    ) = None
    post_write_completion_verifier_contract: (
        StealthPostWriteReconciliationCompletionVerifierEvidence | None
    ) = None
    execution_candidate: StealthExecutionCandidateEvidence | None = None
    execution_preflight: StealthExecutionPreflightEvidence | None = None
    execution_transition_barrier: (
        StealthExecutionTransitionBarrierEvidence | None
    ) = None
    execution_live_readiness: StealthExecutionLiveReadinessEvidence | None = None
    canonical_execution_path: list[str] = Field(default_factory=list)
    execution_boundary_authority: str = "backend_contract_only_no_execution"
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    trigger_evaluation_allowed: bool = False
    trigger_evaluation_ran: bool = False
    should_trigger_reveal_allowed: bool = False
    should_trigger_reveal_called: bool = False
    reveal_order_slice_allowed: bool = False
    reveal_order_slice_called: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    lifecycle_state_mutation_allowed: bool = False
    lifecycle_state_mutated: bool = False
    order_state_mutation_allowed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutation_allowed: bool = False
    exchange_state_mutated: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_submitted: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCreateLifecyclePrerequisiteResolverItem(BaseModel):
    """Read-only prerequisite lookup evidence for stealth create execution."""

    model_config = ConfigDict(extra="forbid")

    prerequisite: StealthCreateLifecycleExecutionPrerequisite
    source: str = Field(min_length=1)
    route: str = "/api/v1/stealth/orders"
    method: str = "POST"
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    lookup_status: StealthCreateLifecycleExecutionPrerequisiteLookupStatus
    lookup_ran: bool = False
    resolved: bool = False
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    stale_or_invalid: bool = False
    authority: str = "read_only_no_execution"
    proof_lookup_authority: str = "none"
    writes_ran: bool = False
    live_coinbase_read_ran: bool = False
    detail: str


class StealthCreateLifecycleExecutionReadinessStageItem(BaseModel):
    """Ordered fail-closed stage evidence before stealth create execution."""

    model_config = ConfigDict(extra="forbid")

    stage_order: int = Field(ge=1)
    workflow_family: AdminApiStealthCommandSuiteGapFamily = (
        AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW
    )
    mutation_family: AdminApiMutationFamilyType = AdminApiMutationFamilyType.STEALTH_CREATE
    prerequisite: StealthCreateLifecycleExecutionPrerequisite
    source: str = Field(min_length=1)
    route: str = "/api/v1/stealth/orders"
    method: str = "POST"
    identity_key: str = "stealth_order_id"
    identity_value: str | None = None
    lookup_status: StealthCreateLifecycleExecutionPrerequisiteLookupStatus
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    required: bool = True
    resolved: bool = False
    blocking: bool = True
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    next_required_contract: str
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    no_live_execution: bool = True
    manager_invocation_allowed: bool = False
    stealth_row_write_allowed: bool = False
    order_parent_write_allowed: bool = False
    lifecycle_event_dispatch_allowed: bool = False
    coinbase_submit_allowed: bool = False
    coinbase_read_allowed: bool = False
    state_mutation_allowed: bool = False
    reconciliation_execution_allowed: bool = False
    detail: str


class StealthCreateLifecycleExecutionBlockerChainItem(BaseModel):
    """Typed blocker evidence that remains after create prerequisite resolution."""

    model_config = ConfigDict(extra="forbid")

    blocker_order: int = Field(ge=1)
    blocker: StealthCreateLifecycleExecutionBlocker
    source_prerequisite: StealthCreateLifecycleExecutionPrerequisite | None = None
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    blocking: bool = True
    resolved: bool = False
    resolved_evidence_id: str | None = None
    missing_reason: str | None = None
    next_required_contract: str
    backend_owned: bool = True
    route_bound: bool = True
    command_context_bound: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    no_live_execution: bool = True
    manager_invocation_allowed: bool = False
    stealth_row_write_allowed: bool = False
    order_parent_write_allowed: bool = False
    lifecycle_event_dispatch_allowed: bool = False
    coinbase_submit_allowed: bool = False
    coinbase_cancel_allowed: bool = False
    coinbase_read_allowed: bool = False
    cancel_replace_allowed: bool = False
    reconciliation_execution_allowed: bool = False
    state_mutation_allowed: bool = False
    detail: str


class StealthCreateLifecycleWriteExecutionContractEvidence(BaseModel):
    """No-live execution-contract boundary evidence for stealth create."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType = AdminApiMutationFamilyType.STEALTH_CREATE
    command_route: str = "/api/v1/stealth/orders"
    service_method: str = "create_stealth_order"
    manager_method: str = "core/stealth_order_manager.py::create_stealth_order"
    identity_key: str = "stealth_order_id"
    stealth_order_id: str | None = None
    accepted_command_identity_keys: list[str] = Field(default_factory=list)
    rejected_command_identity_keys: list[str] = Field(default_factory=list)
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    execution_contract_boundary_configured: bool = True
    execution_contract_available: bool = False
    execution_allowed: bool = False
    exact_command_context_present: bool = False
    required_context_fields: list[str] = Field(default_factory=list)
    missing_context_fields: list[str] = Field(default_factory=list)
    required_prerequisites: list[str] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    resolved_prerequisites: list[str] = Field(default_factory=list)
    prerequisite_resolver_available: bool = True
    prerequisite_resolver_lookup_ran: bool = False
    prerequisite_resolver_authority: str = "read_only_no_execution"
    prerequisite_resolution: list[
        StealthCreateLifecyclePrerequisiteResolverItem
    ] = Field(default_factory=list)
    execution_readiness_stage_count: int = Field(default=0, ge=0)
    blocked_execution_readiness_stage_count: int = Field(default=0, ge=0)
    passed_execution_readiness_stage_count: int = Field(default=0, ge=0)
    execution_readiness_stages: list[
        StealthCreateLifecycleExecutionReadinessStageItem
    ] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    remaining_execution_blocker_count: int = Field(default=0, ge=0)
    remaining_execution_blockers: list[
        StealthCreateLifecycleExecutionBlockerChainItem
    ] = Field(default_factory=list)
    manager_invocation_policy_required: bool = True
    manager_invocation_policy_resolved: bool = False
    manager_invocation_policy_proof_id: str | None = None
    state_mutation_policy_required: bool = True
    state_mutation_policy_resolved: bool = False
    state_mutation_policy_proof_id: str | None = None
    lifecycle_write_guard_proof_required: bool = True
    lifecycle_write_guard_proof_resolved: bool = False
    lifecycle_write_guard_proof_lookup_ran: bool = False
    approval_snapshot_required: bool = True
    admission_audit_required: bool = True
    cap_guard_required: bool = True
    reconciliation_plan_required: bool = True
    live_execution_service_required: bool = True
    live_execution_service_source: str = "disabled_backend_service"
    live_execution_service_missing_reason: str | None = "live_execution_disabled"
    live_execution_service_contract: (
        AdminLiveExecutionServiceContractEvidence | None
    ) = None
    live_execution_intent_contract: AdminLiveExecutionIntentEvidence | None = None
    live_execution_adapter_required: bool = True
    live_execution_adapter_source: str = "disabled_stealth_command_live_adapter"
    live_execution_adapter_status: AdminApiLiveExecutionStatus = (
        AdminApiLiveExecutionStatus.LIVE_DISABLED
    )
    live_execution_adapter_missing_reason: str | None = (
        "live_execution_adapter_disabled"
    )
    live_execution_adapter_contract: (
        AdminLiveExecutionAdapterContractEvidence | None
    ) = None
    post_write_reconciliation_required: bool = True
    post_write_reconciliation_route: str = "/api/v1/admin/reconciliation/plans"
    post_write_reconciliation_method: str = "POST"
    post_write_reconciliation_source: str = "post_write_reconciliation_contract"
    post_write_reconciliation_missing_reason: str | None = (
        "post_write_reconciliation_missing"
    )
    post_write_reconciliation_boundary: (
        StealthPostWriteReconciliationBoundaryEvidence | None
    ) = None
    post_write_completion_verifier_contract: (
        StealthPostWriteReconciliationCompletionVerifierEvidence | None
    ) = None
    execution_candidate: StealthExecutionCandidateEvidence | None = None
    execution_preflight: StealthExecutionPreflightEvidence | None = None
    execution_transition_barrier: (
        StealthExecutionTransitionBarrierEvidence | None
    ) = None
    execution_live_readiness: StealthExecutionLiveReadinessEvidence | None = None
    canonical_execution_path: list[str] = Field(default_factory=list)
    execution_boundary_authority: str = "backend_contract_only_no_execution"
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    stealth_row_write_allowed: bool = False
    stealth_row_write_ran: bool = False
    order_parent_write_allowed: bool = False
    order_parent_write_ran: bool = False
    lifecycle_event_dispatch_allowed: bool = False
    lifecycle_event_dispatch_ran: bool = False
    local_lifecycle_mutation_allowed: bool = False
    local_lifecycle_mutation_ran: bool = False
    coinbase_order_submit_allowed: bool = False
    coinbase_order_submit_ran: bool = False
    coinbase_order_cancel_allowed: bool = False
    coinbase_order_cancel_ran: bool = False
    live_coinbase_read_allowed: bool = False
    live_coinbase_read_ran: bool = False
    active_placement_cancel_replace_allowed: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_execution_allowed: bool = False
    reconciliation_executed: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCreateLifecycleWriteAuditEvidence(BaseModel):
    """Read-only lifecycle-write evidence for stealth create readiness."""

    model_config = ConfigDict(extra="forbid")

    mutation_family: AdminApiMutationFamilyType = AdminApiMutationFamilyType.STEALTH_CREATE
    command_route: str = "/api/v1/stealth/orders"
    service_method: str = "create_stealth_order"
    manager_method: str = "core/stealth_order_manager.py::create_stealth_order"
    identity_key: str = "stealth_order_id"
    accepted_command_identity_keys: list[str] = Field(default_factory=list)
    rejected_command_identity_keys: list[str] = Field(default_factory=list)
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    lifecycle_write_required: bool = True
    lifecycle_write_contract_configured: bool = False
    lifecycle_write_guard_resolved: bool = False
    manager_invocation_allowed: bool = False
    manager_invocation_ran: bool = False
    stealth_row_write_allowed: bool = False
    stealth_row_write_ran: bool = False
    order_parent_write_allowed: bool = False
    order_parent_write_ran: bool = False
    lifecycle_event_dispatch_allowed: bool = False
    lifecycle_event_dispatch_ran: bool = False
    local_lifecycle_mutation_allowed: bool = False
    local_lifecycle_mutation_ran: bool = False
    coinbase_order_submit_ran: bool = False
    live_coinbase_read_ran: bool = False
    reconciliation_required: bool = True
    reconciliation_executed: bool = False
    post_write_reconciliation_satisfied: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    read_evidence_routes: list[str] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    required_gate_chain: list[str] = Field(default_factory=list)
    missing_gate_chain: list[str] = Field(default_factory=list)
    execution_contract: StealthCreateLifecycleWriteExecutionContractEvidence | None = None
    proof_route_count: int = 0
    blocking_proof_route_count: int = 0
    proof_routes: list[StealthCommandSuiteProofRouteItem] = Field(default_factory=list)
    proof_records_created: bool = False
    approval_store_mutated: bool = False
    admission_audit_store_mutated: bool = False
    cap_guard_store_mutated: bool = False
    reconciliation_plan_store_mutated: bool = False
    evidence: list[str] = Field(default_factory=list)
    detail: str


class StealthCommandSuiteResponse(AdminApiReadPayload):
    """Read-only M55 stealth command-suite readiness evidence."""

    type: str = "stealth_command_suite"
    module_id: str = "stealth_orders"
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    approved_phase_range: str
    command_count: int = 0
    blocked_command_count: int = 0
    live_enabled_command_count: int = 0
    executable_command_count: int = 0
    exchange_truth_required: bool = True
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    submitted_notional_usdc: DecimalString = "0"
    executed_notional_usdc: DecimalString = "0"
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    exchange_truth_check_count: int = 0
    blocking_exchange_truth_check_count: int = 0
    active_placement_exchange_truth_required_count: int = 0
    exchange_truth_checks: list[StealthCommandSuiteExchangeTruthItem] = Field(
        default_factory=list
    )
    cancel_replace_boundary_count: int = 0
    blocking_cancel_replace_boundary_count: int = 0
    cancel_replace_boundaries: list[StealthCommandSuiteCancelReplaceBoundaryItem] = (
        Field(default_factory=list)
    )
    admission_readiness_count: int = 0
    blocking_admission_readiness_count: int = 0
    admission_readiness: list[StealthCommandSuiteAdmissionReadinessItem] = Field(
        default_factory=list
    )
    commands: list[StealthCommandSuiteCommandItem] = Field(default_factory=list)
    coverage_gap_count: int = 0
    coverage_gaps: list[StealthCommandSuiteCoverageGapItem] = Field(default_factory=list)
    create_lifecycle_write_audit: StealthCreateLifecycleWriteAuditEvidence | None = None
    read_routes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
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
