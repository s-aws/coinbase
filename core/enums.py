"""Enums for trading engine - Order states, product types, conditions, etc.

This module defines all fixed enumeration types used throughout the trading system,
derived from Coinbase API responses and WebSocket messages. Using enums improves:
- Type safety and IDE autocomplete
- Code readability and maintainability
- Consistency across the codebase
"""

from enum import Enum


# ============================================================================
# ORDER ATTRIBUTES
# ============================================================================

class OrderSide(str, Enum):
    """Direction of an order - BUY or SELL."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Status of an order throughout its lifecycle.
    
    From Coinbase API: PENDING, OPEN, FILLED, CANCELLED, EXPIRED, FAILED

    Engine event statuses also routed through order processing:
    - UPDATE: Incremental websocket update for an existing order
    - SNAPSHOT: Initial websocket snapshot payload
    """
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCEL_QUEUED = "CANCEL_QUEUED"
    UPDATE = "UPDATE"
    SNAPSHOT = "SNAPSHOT"


class StealthOrderStatus(str, Enum):
    """Status of a stealth order throughout its internal lifecycle.
    
    Distinct from OrderStatus (which tracks API-visible states like OPEN, FILLED).
    StealthOrderStatus tracks the internal reveal and execution lifecycle of stealth orders.
    
    - HIDDEN: Order created, not yet revealed to exchange
    - PENDING: Reveal condition partially met, watching for full trigger
    - TRIGGERED: Reveal condition fully met, pending placement on exchange
    - REVEALED: Order partially or fully revealed to exchange
    - EXECUTED: Order fully executed
    - CANCELLED: Order cancelled before execution
    """
    HIDDEN = "HIDDEN"
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    REVEALED = "REVEALED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    """Type of order - how it executes.
    
    From Coinbase API: LIMIT, MARKET, STOP_LIMIT
    """
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    """How long an order remains valid.
    
    - GTC (GOOD_UNTIL_CANCELLED): Order stays until filled or manually cancelled
    - IOC (IMMEDIATE_OR_CANCEL): Fill entire order immediately or cancel
    - FOK (FILL_OR_KILL): Fill entire order immediately or cancel (no partial)
    - GTD (GOOD_UNTIL_DATE_TIME): Order expires at specified end_time
    """
    GOOD_UNTIL_CANCELLED = "GOOD_UNTIL_CANCELLED"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"
    GOOD_UNTIL_DATE_TIME = "GOOD_UNTIL_DATE_TIME"

    # Aliases for convenience
    GTC = "GOOD_UNTIL_CANCELLED"
    IOC = "IMMEDIATE_OR_CANCEL"
    FOK = "FILL_OR_KILL"
    GTD = "GOOD_UNTIL_DATE_TIME"


class TriggerStatus(str, Enum):
    """Status of trigger/stop order.
    
    From Coinbase API: UNKNOWN_TRIGGER_STATUS, INVALID_ORDER_TYPE, STOP_PENDING, STOP_TRIGGERED
    """
    UNKNOWN_TRIGGER_STATUS = "UNKNOWN_TRIGGER_STATUS"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"
    STOP_PENDING = "STOP_PENDING"
    STOP_TRIGGERED = "STOP_TRIGGERED"


# ============================================================================
# PRODUCT & MARKET ATTRIBUTES
# ============================================================================

class ProductType(str, Enum):
    """Type of trading product."""
    SPOT = "SPOT"
    FUTURE = "FUTURE"


class AdminApiActionClass(str, Enum):
    """Enterprise Admin API route risk/action classification."""

    READ_ONLY = "read_only"
    LOCAL_STATE_MUTATION = "local_state_mutation"
    LIVE_EXCHANGE_PLACE = "live_exchange_place"
    LIVE_EXCHANGE_CANCEL = "live_exchange_cancel"
    ADMIN_RUNTIME = "admin_runtime"
    AUDIT = "audit"


class AdminApiPermission(str, Enum):
    """Backend-enforced Admin API permission names."""

    ANALYTICS_READ = "analytics:read"
    AUDIT_READ = "audit:read"
    APPROVAL_READ = "approval:read"
    APPROVAL_REQUEST = "approval:request"
    APPROVAL_MANAGE = "approval:manage"
    ADMISSION_AUDIT_READ = "admission_audit:read"
    ADMISSION_AUDIT_RECORD = "admission_audit:record"
    CAP_GUARD_READ = "cap_guard:read"
    CAP_GUARD_RECORD = "cap_guard:record"
    RECONCILIATION_READ = "reconciliation:read"
    RECONCILIATION_RECORD = "reconciliation:record"
    ORDER_CREATE = "order:create"
    ORDER_CANCEL = "order:cancel"
    CAMPAIGN_READ = "campaign:read"
    CAMPAIGN_EXECUTE = "campaign:execute"
    SPOT_SWEEP_EXECUTE = "spot_sweep:execute"
    SPOT_PNL_RECORD = "spot_pnl:record"
    SPOT_RECOVERY_EXECUTE = "spot_recovery:execute"
    SPOT_RECOVERY_RECORD = "spot_recovery:record"
    STEALTH_EXCHANGE_TRUTH_RECORD = "stealth_exchange_truth:record"
    STEALTH_LIFECYCLE_WRITE_RECORD = "stealth_lifecycle_write:record"
    STEALTH_MUTATION_CLAIM_RECORD = "stealth_mutation_claim:record"
    STEALTH_REVEAL_TRIGGER_RECORD = "stealth_reveal_trigger:record"
    STEALTH_RECOVERY_RECORD = "stealth_recovery:record"
    STEALTH_RECONCILIATION_RECORD = "stealth_reconciliation:record"
    STEALTH_CANCEL_REPLACE_RECORD = "stealth_cancel_replace:record"
    STEALTH_RECOVERY_EXECUTE = "stealth_recovery:execute"
    STEALTH_RECONCILIATION_EXECUTE = "stealth_reconciliation:execute"
    CONFIG_UPDATE = "config:update"
    RUNTIME_PAUSE = "runtime:pause"
    RUNTIME_RESUME = "runtime:resume"
    RUNTIME_SHUTDOWN = "runtime:shutdown"


class AdminApiRole(str, Enum):
    """Backend-recognized Admin API role names."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    TRADER = "trader"
    ADMIN = "admin"
    AUDITOR = "auditor"
    EMERGENCY = "emergency"


class AdminApiCommandStatus(str, Enum):
    """Admin API command status values returned to operators."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_IMPLEMENTED = "not_implemented"
    REPLAYED = "replayed"
    CONFLICT = "conflict"


class AdminApiErrorCode(str, Enum):
    """Structured Admin API error codes exposed to the frontend."""

    AUTH_REQUIRED = "auth_required"
    PERMISSION_DENIED = "permission_denied"
    VALIDATION_ERROR = "validation_error"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    GUARD_BLOCKED = "guard_blocked"
    NOT_IMPLEMENTED = "not_implemented"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    REQUEST_ERROR = "request_error"


class AdminApiErrorSeverity(str, Enum):
    """Operator-facing severity for structured Admin API errors."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AdminApiRouteAvailability(str, Enum):
    """Backend availability posture for frontend-visible routes."""

    AVAILABLE = "available"
    LIVE_DISABLED = "live_disabled"
    CONTRACT_PENDING = "contract_pending"
    BACKEND_BLOCKED = "backend_blocked"


class AdminApiModuleSupportStatus(str, Enum):
    """Enterprise admin support posture for a platform or domain module."""

    PLATFORM_READY = "platform_ready"
    READ_ONLY_READY = "read_only_ready"
    COMMAND_DRAFT_LIVE_DISABLED = "command_draft_live_disabled"
    NOT_MODELED = "not_modeled"
    UNSUPPORTED = "unsupported"


class AdminApiFunctionalityWorkflowType(str, Enum):
    """Enterprise admin workflow classification for backend functionality."""

    PLATFORM_EVIDENCE = "platform_evidence"
    READ_MODEL = "read_model"
    COMMAND_DRAFT = "command_draft"
    LIVE_EXECUTION = "live_execution"
    RECOVERY = "recovery"
    AUTOMATION = "automation"
    REPAIR = "repair"
    LEGACY_COMPATIBILITY = "legacy_compatibility"


class AdminApiFunctionalityExposureStatus(str, Enum):
    """Whether a backend workflow is exposed through the enterprise admin path."""

    ADMIN_EXPOSED = "admin_exposed"
    ADMIN_DRAFT_LIVE_DISABLED = "admin_draft_live_disabled"
    BACKEND_CONTRACT_REQUIRED = "backend_contract_required"
    ADMIN_UNSUPPORTED = "admin_unsupported"
    COMPATIBILITY_ONLY = "compatibility_only"


class AdminApiMutationFamilyType(str, Enum):
    """Enterprise admin mutation family classification."""

    ADMIN_APPROVAL_LIFECYCLE = "admin_approval_lifecycle"
    ADMIN_ADMISSION_AUDIT = "admin_admission_audit"
    ADMIN_CAP_GUARD_DECISION = "admin_cap_guard_decision"
    ADMIN_RECONCILIATION_PLAN = "admin_reconciliation_plan"
    SPOT_MANUAL_ORDER = "spot_manual_order"
    SPOT_ORDER_CANCEL = "spot_order_cancel"
    SPOT_CAMPAIGN_EXECUTION = "spot_campaign_execution"
    SPOT_SWEEP_AUTOMATION = "spot_sweep_automation"
    SPOT_PNL_CHECKPOINT = "spot_pnl_checkpoint"
    SPOT_RECOVERY_APPLY_EXECUTION = "spot_recovery_apply_execution"
    SPOT_RECOVERY_ROLLBACK_EXECUTION = "spot_recovery_rollback_execution"
    SPOT_RECOVERY_EXCHANGE_STATE_PROOF = "spot_recovery_exchange_state_proof"
    SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT = "spot_recovery_exchange_state_snapshot"
    SPOT_RECOVERY_RECONCILIATION_PROOF = "spot_recovery_reconciliation_proof"
    SPOT_RECOVERY_RECONCILIATION_COMPLETION = "spot_recovery_reconciliation_completion"
    SPOT_RECOVERY_RECONCILIATION_EXECUTION = "spot_recovery_reconciliation_execution"
    STEALTH_CREATE = "stealth_create"
    STEALTH_REVEAL = "stealth_reveal"
    STEALTH_MOVE = "stealth_move"
    STEALTH_CANCEL = "stealth_cancel"
    STEALTH_RECOVERY = "stealth_recovery"
    STEALTH_RECONCILIATION = "stealth_reconciliation"
    STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_SNAPSHOT = (
        "stealth_active_placement_exchange_truth_snapshot"
    )
    STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_PROOF = (
        "stealth_active_placement_exchange_truth_proof"
    )
    STEALTH_CREATE_LIFECYCLE_WRITE_GUARD_PROOF = (
        "stealth_create_lifecycle_write_guard_proof"
    )
    STEALTH_MUTATION_CLAIM_SNAPSHOT_PROOF = (
        "stealth_mutation_claim_snapshot_proof"
    )
    STEALTH_REVEAL_TRIGGER_PROOF = "stealth_reveal_trigger_proof"
    STEALTH_RECOVERY_PROOF = "stealth_recovery_proof"
    STEALTH_RECONCILIATION_PROOF = "stealth_reconciliation_proof"
    STEALTH_CANCEL_REPLACE_PROOF = "stealth_cancel_replace_proof"
    STEALTH_POST_WRITE_RECONCILIATION_PROOF = (
        "stealth_post_write_reconciliation_proof"
    )
    STEALTH_POST_WRITE_EXECUTION_JOURNAL = (
        "stealth_post_write_execution_journal"
    )
    STEALTH_POST_WRITE_RECONCILIATION_VERIFICATION = (
        "stealth_post_write_reconciliation_verification"
    )
    MOVEMENT_REPRICE = "movement_reprice"
    FUTURES_CONTRACT_REQUIRED = "futures_contract_required"
    FILL_LEDGER_REPAIR_CONTRACT_REQUIRED = "fill_ledger_repair_contract_required"
    LEGACY_DASHBOARD_PLACE = "legacy_dashboard_place"
    LEGACY_DASHBOARD_HOTPOINT = "legacy_dashboard_hotpoint"
    LEGACY_DASHBOARD_CANCEL = "legacy_dashboard_cancel"


class AdminApiStealthAdmissionEvidence(str, Enum):
    """Evidence names required before a stealth admin command may execute."""

    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"
    ADMISSION_AUDIT = "admission_audit"
    CAP_GUARD_DECISION = "cap_guard_decision"
    RECONCILIATION_PLAN = "reconciliation_plan"
    ACTIVE_PLACEMENT_EXCHANGE_TRUTH = "active_placement_exchange_truth"
    LIFECYCLE_WRITE_GUARD = "lifecycle_write_guard"
    MUTATION_CLAIM_SNAPSHOT = "mutation_claim_snapshot"
    REVEAL_TRIGGER_EVIDENCE = "reveal_trigger_evidence"
    RECOVERY_PROOF = "recovery_proof"
    RECONCILIATION_PROOF = "reconciliation_proof"
    CANCEL_REPLACE_PROOF = "cancel_replace_proof"
    LIVE_EXECUTION_ADAPTER = "live_execution_adapter"
    POST_LIVE_RECONCILIATION = "post_live_reconciliation"


class AdminApiStealthAdmissionContextField(str, Enum):
    """Command-envelope fields required before stealth admission proof lookup."""

    ROUTE = "route"
    METHOD = "method"
    MODULE_ID = "module_id"
    MUTATION_FAMILY = "mutation_family"
    ACTION_CLASS = "action_class"
    REQUIRED_PERMISSION = "required_permission"
    STEALTH_ORDER_ID = "stealth_order_id"
    ACTOR_ID = "actor_id"
    IDEMPOTENCY_KEY = "idempotency_key"
    OPERATOR_INTENT = "operator_intent"
    PAYLOAD_HASH = "payload_hash"


class StealthCreateLifecycleExecutionPrerequisite(str, Enum):
    """Prerequisites required before stealth create lifecycle writes may execute."""

    APPROVAL_SNAPSHOT = "approval_snapshot"
    ADMISSION_AUDIT = "admission_audit"
    CAP_GUARD_DECISION = "cap_guard_decision"
    RECONCILIATION_PLAN = "reconciliation_plan"
    LIFECYCLE_WRITE_GUARD_PROOF = "lifecycle_write_guard_proof"
    LIVE_EXECUTION_SERVICE = "live_execution_service"
    LIVE_EXECUTION_ADAPTER = "live_execution_adapter"
    POST_WRITE_RECONCILIATION = "post_write_reconciliation"


class StealthCreateLifecycleExecutionPrerequisiteLookupStatus(str, Enum):
    """Read-only lookup status for stealth create execution prerequisites."""

    NOT_CHECKED = "not_checked"
    RESOLVED = "resolved"
    MISSING = "missing"
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class StealthCreateLifecycleExecutionBlocker(str, Enum):
    """Fail-closed blockers for stealth create lifecycle-write execution."""

    EXECUTION_CONTRACT_MISSING = (
        "stealth_create_lifecycle_write_execution_contract_missing"
    )
    LIVE_EXECUTION_DISABLED = "live_execution_disabled"
    STEALTH_MANAGER_INVOCATION_DISABLED = "stealth_manager_invocation_disabled"
    STEALTH_ROW_WRITE_DISABLED = "stealth_row_write_disabled"
    ORDER_PARENT_WRITE_DISABLED = "order_parent_write_disabled"
    LIFECYCLE_EVENT_DISPATCH_DISABLED = "lifecycle_event_dispatch_disabled"
    COINBASE_ORDER_SUBMIT_DISABLED = "coinbase_order_submit_disabled"
    COINBASE_READ_DISABLED = "coinbase_read_disabled"
    POST_WRITE_RECONCILIATION_MISSING = "post_write_reconciliation_missing"
    EXACT_COMMAND_CONTEXT_MISSING = "exact_command_context_missing"


class StealthCommandExecutionPrerequisite(str, Enum):
    """Prerequisites required before non-create stealth commands may execute."""

    APPROVAL_SNAPSHOT = "approval_snapshot"
    ADMISSION_AUDIT = "admission_audit"
    CAP_GUARD_DECISION = "cap_guard_decision"
    RECONCILIATION_PLAN = "reconciliation_plan"
    ACTIVE_PLACEMENT_EXCHANGE_TRUTH = "active_placement_exchange_truth"
    REVEAL_TRIGGER_EVIDENCE = "reveal_trigger_evidence"
    MUTATION_CLAIM_SNAPSHOT = "mutation_claim_snapshot"
    RECOVERY_PROOF = "recovery_proof"
    RECONCILIATION_PROOF = "reconciliation_proof"
    CANCEL_REPLACE_PROOF = "cancel_replace_proof"
    LIVE_EXECUTION_SERVICE = "live_execution_service"
    LIVE_EXECUTION_ADAPTER = "live_execution_adapter"
    POST_WRITE_RECONCILIATION = "post_write_reconciliation"


class StealthCommandExecutionPrerequisiteLookupStatus(str, Enum):
    """Read-only lookup status for stealth command execution prerequisites."""

    NOT_CHECKED = "not_checked"
    RESOLVED = "resolved"
    MISSING = "missing"
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class StealthCommandExecutionBlocker(str, Enum):
    """Fail-closed blockers for non-create stealth command execution."""

    EXECUTION_CONTRACT_MISSING = "stealth_command_execution_contract_missing"
    LIVE_EXECUTION_DISABLED = "live_execution_disabled"
    STEALTH_MANAGER_INVOCATION_DISABLED = "stealth_manager_invocation_disabled"
    ACTIVE_PLACEMENT_CANCEL_REPLACE_DISABLED = (
        "active_placement_cancel_replace_disabled"
    )
    COINBASE_ORDER_SUBMIT_DISABLED = "coinbase_order_submit_disabled"
    COINBASE_ORDER_CANCEL_DISABLED = "coinbase_order_cancel_disabled"
    COINBASE_READ_DISABLED = "coinbase_read_disabled"
    LIFECYCLE_STATE_MUTATION_DISABLED = "lifecycle_state_mutation_disabled"
    ORDER_STATE_MUTATION_DISABLED = "order_state_mutation_disabled"
    EXCHANGE_STATE_MUTATION_DISABLED = "exchange_state_mutation_disabled"
    RECONCILIATION_EXECUTION_DISABLED = "reconciliation_execution_disabled"
    POST_WRITE_RECONCILIATION_MISSING = "post_write_reconciliation_missing"
    EXACT_COMMAND_CONTEXT_MISSING = "exact_command_context_missing"


class AdminApiSpotCommandSuiteGapFamily(str, Enum):
    """Spot command-suite families that still require admin contract work."""

    SPOT_SWEEP_AUTOMATION = "spot_sweep_automation"
    SPOT_PNL_TRACKING = "spot_pnl_tracking"
    SPOT_RECOVERY_WORKFLOW = "spot_recovery_workflow"
    SPOT_RECONCILIATION_WORKFLOW = "spot_reconciliation_workflow"


class AdminApiStealthCommandSuiteGapFamily(str, Enum):
    """Stealth command-suite families that still require admin contract work."""

    STEALTH_CREATE_WORKFLOW = "stealth_create_workflow"
    STEALTH_REVEAL_WORKFLOW = "stealth_reveal_workflow"
    STEALTH_CANCEL_EXCHANGE_HANDLING = "stealth_cancel_exchange_handling"
    STEALTH_MOVE_REVEALED_WORKFLOW = "stealth_move_revealed_workflow"
    STEALTH_REPRICE_WORKFLOW = "stealth_reprice_workflow"
    STEALTH_RECOVERY_WORKFLOW = "stealth_recovery_workflow"
    STEALTH_RECONCILIATION_WORKFLOW = "stealth_reconciliation_workflow"


class SpotRecoveryExchangeStateSnapshotSource(str, Enum):
    """Source posture for backend-owned Spot recovery exchange-state snapshots."""

    MANUAL_IMPORT = "manual_import"
    TEST_EVIDENCE = "test_evidence"
    LIVE_COINBASE_DISABLED = "live_coinbase_disabled"


class StealthExchangeTruthEvidenceSource(str, Enum):
    """Source posture for stealth active-placement exchange-truth evidence."""

    MANUAL_IMPORT = "manual_import"
    TEST_EVIDENCE = "test_evidence"
    LIVE_COINBASE_DISABLED = "live_coinbase_disabled"


class StealthLifecycleWriteGuardEvidenceSource(str, Enum):
    """Source posture for stealth create lifecycle-write guard evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    LIVE_COINBASE_DISABLED = "live_coinbase_disabled"


class StealthMutationClaimEvidenceSource(str, Enum):
    """Source posture for stealth mutation-claim snapshot proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    RUNTIME_SNAPSHOT_REVIEW = "runtime_snapshot_review"


class StealthRevealTriggerEvidenceSource(str, Enum):
    """Source posture for stealth reveal-trigger proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    REVEAL_CONDITION_REVIEW = "reveal_condition_review"


class StealthRecoveryProofEvidenceSource(str, Enum):
    """Source posture for stealth recovery proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    RECOVERY_RUNBOOK_REVIEW = "recovery_runbook_review"


class StealthReconciliationProofEvidenceSource(str, Enum):
    """Source posture for stealth reconciliation proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    RECONCILIATION_RUNBOOK_REVIEW = "reconciliation_runbook_review"


class StealthCancelReplaceProofEvidenceSource(str, Enum):
    """Source posture for stealth cancel/replace proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    CANCEL_REPLACE_RUNBOOK_REVIEW = "cancel_replace_runbook_review"


class StealthPostWriteReconciliationEvidenceSource(str, Enum):
    """Source posture for stealth post-write reconciliation proof evidence."""

    MANUAL_REVIEW = "manual_review"
    TEST_EVIDENCE = "test_evidence"
    POST_WRITE_RUNBOOK_REVIEW = "post_write_runbook_review"


class AdminApiApprovalLifecycleStatus(str, Enum):
    """Lifecycle state for backend-owned approval records."""

    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AdminApiApprovalLifecycleEventType(str, Enum):
    """Append-only event type for the approval lifecycle store."""

    REQUEST_CREATED = "request_created"
    DECISION_RECORDED = "decision_recorded"
    APPROVAL_REVOKED = "approval_revoked"


class AdminApiCommandRoutesMode(str, Enum):
    """Command-route posture exposed by read models."""

    NOT_MODELED = "not_modeled"
    LIVE_DISABLED = "live_disabled"
    EVIDENCE_ONLY = "evidence_only"


class AdminApiLiveExecutionStatus(str, Enum):
    """Live-execution posture exposed by read-only Admin API readiness."""

    NOT_RUN = "not_run"
    LIVE_DISABLED = "live_disabled"
    APPROVAL_REQUIRED = "approval_required"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPLETED = "completed"


class AdminApiSessionStatus(str, Enum):
    """Authenticated Admin API session status."""

    SIGNED_IN = "signed_in"
    SIGNED_OUT = "signed_out"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"


class AdminApiHealthStatus(str, Enum):
    """Admin API health/readiness state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class AdminApiGateStatus(str, Enum):
    """Release and recovery gate status exposed by read-only Admin API routes."""

    PASSED = "passed"
    WARNING = "warning"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class AdminApiLivePreflightCategory(str, Enum):
    """Controlled-live preflight evidence categories for Admin API routes."""

    AUTHORIZATION = "authorization"
    IDEMPOTENCY = "idempotency"
    APPROVAL = "approval"
    CAP_GUARD = "cap_guard"
    AUDIT = "audit"
    RECONCILIATION = "reconciliation"
    LIFECYCLE_WRITE_GUARD = "lifecycle_write_guard"
    MUTATION_CLAIM = "mutation_claim"
    REVEAL_TRIGGER = "reveal_trigger"
    RECOVERY_PROOF = "recovery_proof"
    RECONCILIATION_PROOF = "reconciliation_proof"
    LIVE_EXECUTION_SERVICE = "live_execution_service"
    BROWSER_AUTHORITY = "browser_authority"


class AdminApiLiveApprovalSnapshotField(str, Enum):
    """Required fields for future route-specific live approval snapshots."""

    ROUTE = "route"
    METHOD = "method"
    MODULE_ID = "module_id"
    IDENTITY_KEY = "identity_key"
    IDENTITY_VALUE = "identity_value"
    ACTION_CLASS = "action_class"
    REQUIRED_PERMISSION = "required_permission"
    REQUESTED_BY_ACTOR_ID = "requested_by_actor_id"
    OPERATOR_INTENT = "operator_intent"
    IDEMPOTENCY_KEY = "idempotency_key"
    PAYLOAD_HASH = "payload_hash"
    APPROVED_BY_ACTOR_ID = "approved_by_actor_id"
    EXPIRES_AT = "expires_at"
    CAP_GUARD_DECISION_REF = "cap_guard_decision_ref"
    RECONCILIATION_PLAN_REF = "reconciliation_plan_ref"


class AdminApiLiveApprovalStoreRequirement(str, Enum):
    """Required approval-store behaviors before live route approval."""

    BACKEND_OWNED = "backend_owned"
    ROUTE_BOUND = "route_bound"
    METHOD_BOUND = "method_bound"
    MODULE_BOUND = "module_bound"
    ACTOR_BOUND = "actor_bound"
    IDEMPOTENCY_BOUND = "idempotency_bound"
    PAYLOAD_HASH_BOUND = "payload_hash_bound"
    EXPIRING = "expiring"
    CAP_GUARD_BOUND = "cap_guard_bound"
    RECONCILIATION_BOUND = "reconciliation_bound"
    APPEND_ONLY_AUDIT = "append_only_audit"
    BROWSER_AUTHORITY_REJECTED = "browser_authority_rejected"


class AdminApiLiveAdmissionAuditFact(str, Enum):
    """Required facts for a future live-admission audit trail."""

    ROUTE_ADMISSION_REQUESTED = "route_admission_requested"
    APPROVAL_SNAPSHOT_LINKED = "approval_snapshot_linked"
    APPROVAL_STORE_DECISION_LINKED = "approval_store_decision_linked"
    CAP_GUARD_DECISION_LINKED = "cap_guard_decision_linked"
    PAYLOAD_HASH_LINKED = "payload_hash_linked"
    IDENTITY_KEY_LINKED = "identity_key_linked"
    COMMAND_ADMISSION_DECISION_RECORDED = "command_admission_decision_recorded"
    EXCHANGE_SUBMISSION_LINKED = "exchange_submission_linked"
    RECONCILIATION_RESULT_LINKED = "reconciliation_result_linked"
    BROWSER_AUTHORITY_REJECTION_RECORDED = "browser_authority_rejection_recorded"


class AdminApiLiveCapGuardRequirement(str, Enum):
    """Required cap/guard bindings before live route admission."""

    BACKEND_OWNED = "backend_owned"
    ROUTE_BOUND = "route_bound"
    METHOD_BOUND = "method_bound"
    MODULE_BOUND = "module_bound"
    IDENTITY_BOUND = "identity_bound"
    PAYLOAD_HASH_BOUND = "payload_hash_bound"
    IDEMPOTENCY_BOUND = "idempotency_bound"
    OPERATOR_INTENT_BOUND = "operator_intent_bound"
    NOTIONAL_CAP_BOUND = "notional_cap_bound"
    DOMAIN_GUARD_BOUND = "domain_guard_bound"
    PRODUCT_SCOPE_BOUND = "product_scope_bound"
    APPROVAL_SNAPSHOT_BOUND = "approval_snapshot_bound"
    ADMISSION_AUDIT_BOUND = "admission_audit_bound"
    BROWSER_AUTHORITY_REJECTED = "browser_authority_rejected"


class AdminApiLiveAdmissionBlocker(str, Enum):
    """Blocking reasons before an Admin API command may reach live execution."""

    LIVE_EXECUTION_DISABLED = "live_execution_disabled"
    APPROVAL_SNAPSHOT_MISSING = "approval_snapshot_missing"
    APPROVAL_STORE_MISSING = "approval_store_missing"
    ADMISSION_AUDIT_MISSING = "admission_audit_missing"
    CAP_GUARD_MISSING = "cap_guard_missing"
    RECONCILIATION_PLAN_MISSING = "reconciliation_plan_missing"
    BROWSER_AUTHORITY_REJECTED = "browser_authority_rejected"


class AdminApiLiveReadinessPrecondition(str, Enum):
    """Backend-owned preconditions before Admin API live execution."""

    APPROVAL_STORE_CONTRACT = "approval_store_contract"
    APPROVAL_SNAPSHOT = "approval_snapshot"
    ADMISSION_AUDIT_TRAIL = "admission_audit_trail"
    CAP_GUARD_CONTRACT = "cap_guard_contract"
    RECONCILIATION_PLAN = "reconciliation_plan"
    LIVE_EXECUTION_ADAPTER = "live_execution_adapter"
    EXECUTION_INTENT_ENVELOPE = "execution_intent_envelope"
    BROWSER_BFF_BOUNDARY = "browser_bff_boundary"
    LIVE_EXECUTION_SERVICE = "live_execution_service"


class AdminApiIdempotencyDecision(str, Enum):
    """Result of comparing a command with existing idempotency evidence."""

    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"


class AdminApiCompatibilityMode(str, Enum):
    """How legacy dashboard live messages relate to enterprise API gates."""

    ENTERPRISE_GATED = "enterprise_gated"
    COMPATIBILITY_ONLY = "compatibility_only"


class AdminApiAuthMode(str, Enum):
    """Admin API authentication verifier mode."""

    BOOTSTRAP_BEARER = "bootstrap_bearer"
    OIDC_JWT = "oidc_jwt"


class AdminApiVerifierReadinessStatus(str, Enum):
    """Implementation readiness for Admin API authentication verifiers."""

    READY = "ready"
    BLOCKED = "blocked"


class AdminMovementRepricingEvidenceType(str, Enum):
    """Read-only evidence categories for movement/repricing admin views."""

    PARENT_MOVE = "parent_move"
    STEALTH_MOVE = "stealth_move"
    STEALTH_REPRICING_STATE = "stealth_repricing_state"


class AdminFuturesEvidenceStatus(str, Enum):
    """Read-only evidence availability for futures/perpetual admin views."""

    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    NOT_MODELED = "not_modeled"


class AdminFuturesEvidenceSource(str, Enum):
    """Source labels for futures/perpetual admin evidence."""

    RUNTIME_ORDERBOOK = "runtime_orderbook"
    RUNTIME_POSITIONS = "runtime_positions"
    DASHBOARD_ENGINE_STATE = "dashboard_engine_state"
    FEE_MANAGER = "fee_manager"
    POSITION_SIDE_DERIVATION = "position_side_derivation"
    PRODUCTS_JSON = "products_json"
    BACKEND_CONTRACT = "backend_contract"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class AdminRiskEvidenceStatus(str, Enum):
    """Availability/status for Admin API guard and risk evidence."""

    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    NOT_MODELED = "not_modeled"
    FAIL_CLOSED = "fail_closed"


class AdminRiskEvidenceSource(str, Enum):
    """Source labels for backend-owned guard and risk policy evidence."""

    ACTION_CONDITION_GUARD = "action_condition_guard"
    PRODUCT_CAPABILITY_POLICY = "product_capability_policy"
    LIVE_EXECUTION_GATE = "live_execution_gate"
    PROFIT_VALIDATOR = "profit_validator"
    SPOT_INVENTORY_AUTHORITY = "spot_inventory_authority"
    BACKEND_CONTRACT = "backend_contract"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class AdminAuditWorkbenchModule(str, Enum):
    """Admin audit workbench module buckets."""

    ADMIN = "admin"
    SPOT = "spot"
    ORDERS = "orders"
    STEALTH = "stealth"
    MOVEMENT_REPRICING = "movement_repricing"
    FUTURES_PERPETUALS = "futures_perpetuals"
    GUARD_RISK = "guard_risk"
    CAMPAIGNS = "campaigns"


class AdminAuditEvidenceSource(str, Enum):
    """Source labels for cross-module audit workbench evidence."""

    ROUTE_INVENTORY = "route_inventory"
    ADMIN_API_AUDIT_LOG = "admin_api_audit_log"
    ORDER_PARENT = "order_parent"
    STEALTH_ORDERS = "stealth_orders"
    MOVEMENT_REPRICING = "movement_repricing"
    FUTURES_POSITIONS = "futures_positions"
    GUARD_RISK_POLICY = "guard_risk_policy"
    BACKEND_CONTRACT = "backend_contract"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class AdminFuturesPositionSide(str, Enum):
    """Derived futures/perpetual position direction."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    UNKNOWN = "UNKNOWN"


class ProductCapability(str, Enum):
    """Feature/action capability controlled by product type policy."""

    DIRECT_PLACEMENT = "direct_placement"
    STEALTH_PLANNING = "stealth_planning"
    STEALTH_REVEAL = "stealth_reveal"
    SIZE_VALIDATION = "size_validation"
    PROFITABILITY = "profitability"
    FILLED_FOLLOW_UP = "filled_follow_up"
    PARTIAL_FILL_FOLLOW_UP = "partial_fill_follow_up"
    CANCELLED_FOLLOW_UP = "cancelled_follow_up"
    SAME_SIDE_POST_FILL_RETREAT = "same_side_post_fill_retreat"
    MOVE_REVEALED = "move_revealed"
    REPRICE_REVEALED = "reprice_revealed"
    CANCEL_REENTRY = "cancel_reentry"
    HOTPOINT_AUTO_PLACEMENT = "hotpoint_auto_placement"
    FUTURES_POSITION_FLIP = "futures_position_flip"
    MARGIN_VALIDATION = "margin_validation"
    LIQUIDATION_CHECK = "liquidation_check"
    FUNDING_CHECK = "funding_check"


class ProductCapabilityMode(str, Enum):
    """Policy decision mode for a product capability."""

    ENABLED = "enabled"
    CONDITIONAL = "conditional"
    DISABLED = "disabled"
    NOT_APPLICABLE = "not_applicable"


class ProductStatus(str, Enum):
    """Status of a trading product from Coinbase.
    
    - OPEN: Product is trading normally
    - CLOSED: Product is not available for trading
    - POST_ONLY: Only maker orders (post-only) are accepted
    - LIMIT_ONLY: Only limit orders are accepted
    """
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    POST_ONLY = "POST_ONLY"
    LIMIT_ONLY = "LIMIT_ONLY"


class ActionGuardPhase(str, Enum):
    """Action-condition guard evaluation phase."""
    PLANNING = "planning"
    REVEAL = "reveal"


class ActionConditionType(str, Enum):
    """Built-in action-condition guard types."""
    WALLET_AVAILABLE = "wallet_available"
    PLANNED_BUDGET_AVAILABLE = "planned_budget_available"
    KNOWN_INVENTORY_AVAILABLE = "known_inventory_available"
    MANUAL_LIVE_ACKNOWLEDGEMENT = "manual_live_acknowledgement"
    DIRECT_SPOT_CAP_REQUIRED = "direct_spot_cap_required"
    DURABLE_AUDIT_AVAILABLE = "durable_audit_available"
    MAX_BASE_SIZE = "max_base_size"
    MAX_NOTIONAL = "max_notional"


class InventoryCostBasisStatus(str, Enum):
    """Cost-basis authority for inventory lots."""
    KNOWN = "known"
    UNKNOWN = "unknown"


class InventoryLotSource(str, Enum):
    """Source used to derive an inventory lot."""
    FILL_LEDGER = "fill_ledger"
    IMPORTED_BASELINE = "imported_baseline"
    COINBASE_AVERAGE_COST = "coinbase_average_cost"


class InventoryAuthorityStatus(str, Enum):
    """Decision status for inventory authority checks."""
    NOT_APPLICABLE = "not_applicable"
    KNOWN_PROFITABLE = "known_profitable"
    COINBASE_AVERAGE_PROFITABLE = "coinbase_average_profitable"
    NO_LOTS = "no_lots"
    UNKNOWN_COST_BASIS = "unknown_cost_basis"
    INSUFFICIENT_KNOWN_PROFITABLE = "insufficient_known_profitable"
    UNAVAILABLE = "unavailable"


class SpotPortfolioSweepItemStatus(str, Enum):
    """Per-product status for USDC spot portfolio sweep planning."""

    PLANNED = "planned"
    SKIPPED = "skipped"


class SpotPortfolioSweepSkipReason(str, Enum):
    """Why a USDC spot portfolio sweep item could not be planned."""

    NONE = "none"
    INELIGIBLE_PRODUCT = "ineligible_product"
    INVALID_PRICE = "invalid_price"
    BELOW_QUOTE_MIN = "below_quote_min"
    BELOW_BASE_MIN = "below_base_min"
    INSUFFICIENT_QUOTE_BALANCE = "insufficient_quote_balance"
    INSUFFICIENT_BASE_BALANCE = "insufficient_base_balance"
    UNSUPPORTED_SIDE = "unsupported_side"


class SpotPortfolioSweepExecutionStatus(str, Enum):
    """Per-product status for live USDC spot portfolio sweep execution."""

    BLOCKED = "blocked"
    SUBMITTED = "submitted"
    ERROR = "error"
    SKIPPED = "skipped"


class SpotPortfolioSweepRunStatus(str, Enum):
    """Durable run status for USDC spot portfolio sweep automation."""

    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    DISABLED = "disabled"


class SpotPortfolioSweepAutomationDecision(str, Enum):
    """Scheduler decision for one run-if-due sweep invocation."""

    DUE = "due"
    NOT_DUE = "not_due"
    MAX_RUNS_REACHED = "max_runs_reached"
    DISABLED = "disabled"


class SpotPortfolioSweepOrderType(str, Enum):
    """Supported live order policies for USDC spot portfolio sweeps."""

    MARKET_IOC = "market_ioc"
    LIMIT_GTC = "limit_gtc"
    LIMIT_GTC_POST_ONLY = "limit_gtc_post_only"


class SpotPortfolioSweepSafetyDecision(str, Enum):
    """Safety-policy admission decision for a spot portfolio sweep run."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


class SpotPortfolioSweepReconciliationStatus(str, Enum):
    """Reconciliation result for a durable sweep order record."""

    MATCHED = "matched"
    NOT_SUBMITTED = "not_submitted"
    MISSING_EXCHANGE_ORDER = "missing_exchange_order"
    CLIENT_ORDER_ID_MISMATCH = "client_order_id_mismatch"
    FETCH_ERROR = "fetch_error"


class SpotSweepFillLedgerMatchStatus(str, Enum):
    """Comparison status between REST fills and local fill_ledger rows."""

    UNCHECKED = "unchecked"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


class SpotFillBackfillStatus(str, Enum):
    """Result status for REST-fill backfill into fill_ledger."""

    APPENDED = "appended"
    DUPLICATE_OR_ACCEPTED = "duplicate_or_accepted"
    SKIPPED = "skipped"
    ERROR = "error"


class SpotInventoryCoverageStatus(str, Enum):
    """Durable coverage status for wallet inventory versus local lot evidence."""

    COVERED = "covered"
    COINBASE_AVERAGE_COST = "coinbase_average_cost"
    UNKNOWN_COST_BASIS = "unknown_cost_basis"
    WALLET_ONLY = "wallet_only"
    NO_WALLET_BALANCE = "no_wallet_balance"
    UNAVAILABLE = "unavailable"


class SpotInventoryBaselineFreshness(str, Enum):
    """Freshness status for imported spot inventory baseline evidence."""

    NOT_CONFIGURED = "not_configured"
    FRESH = "fresh"
    STALE = "stale"
    MISSING_TIMESTAMP = "missing_timestamp"
    INVALID_TIMESTAMP = "invalid_timestamp"


class SpotLiveReconciliationGateStatus(str, Enum):
    """Pass/fail status for approved live spot reconciliation gates."""

    PASSED = "passed"
    FAILED = "failed"


class SpotReleaseGateStatus(str, Enum):
    """Pass/fail status for read-only spot release gates."""

    PASSED = "passed"
    FAILED = "failed"


class SpotSweepRecoveryGateStatus(str, Enum):
    """Pass/fail status for read-only spot sweep recovery gates."""

    PASSED = "passed"
    FAILED = "failed"


class SpotAuditRecordType(str, Enum):
    """Durable audit record types for spot operational gates."""

    FEATURE_INTAKE_GATE = "spot_feature_intake_gate"
    FILL_LEDGER_HEALTH = "spot_fill_ledger_health"
    FILL_LEDGER_REPAIR = "spot_fill_ledger_repair"
    COST_BASIS_SNAPSHOT = "spot_cost_basis_snapshot"
    CAMPAIGN_SNAPSHOT = "spot_campaign_snapshot"
    SWEEP_RECOVERY = "sweep_recovery"
    DIRECT_ORDER_AUDIT = "spot_direct_order_audit"


class SpotDirectOrderAuditStatus(str, Enum):
    """Read-only audit status for a manual direct dashboard order."""

    FOUND = "found"
    MISSING_CLIENT_ORDER_ID = "missing_client_order_id"
    MISSING_SUBMISSION = "missing_submission"


class SpotFeatureIntakeGateStatus(str, Enum):
    """Validation status for a requested spot-specific feature."""

    PASSED = "passed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class SpotFeatureInventoryRetentionPolicy(str, Enum):
    """How a spot feature expects post-test inventory to be handled."""

    RETAIN = "retain"
    ZERO_OUT = "zero_out"
    EXPLICIT_OPERATOR_DECISION = "explicit_operator_decision"


class SpotFillLedgerHealthStatus(str, Enum):
    """Data-health status for local spot fill-ledger evidence."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class SpotFillLedgerFindingType(str, Enum):
    """Finding categories for spot fill-ledger health audits."""

    MISSING_CLIENT_ORDER_ID = "missing_client_order_id"
    NON_POSITIVE_QUANTITY = "non_positive_quantity"
    NON_POSITIVE_PRICE = "non_positive_price"
    ZERO_NOTIONAL = "zero_notional"
    MISSING_RECONCILED_EXCHANGE_EVIDENCE = "missing_reconciled_exchange_evidence"


class SpotFillLedgerRepairStatus(str, Enum):
    """Repair status for a suspicious spot fill-ledger row."""

    PLANNED = "planned"
    DRY_RUN = "dry_run"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class SpotRecoveryRepairCategory(str, Enum):
    """Allowed local repair categories for Spot recovery evidence."""

    FILL_BACKFILL_LEDGER = "fill_backfill_ledger"
    DIRECT_ORDER_AUDIT_LINK = "direct_order_audit_link"
    RECOVERY_PROOF_LINKAGE = "recovery_proof_linkage"
    RECONCILIATION_COMPLETION_MARK = "reconciliation_completion_mark"


class SpotRecoveryCompletionState(str, Enum):
    """Backend-owned completion state for Spot recovery repair evidence."""

    JOURNAL_ACCEPTED = "journal_accepted"
    DRY_RUN_REPAIR_PLANNED = "dry_run_repair_planned"
    REPAIR_BLOCKED = "repair_blocked"
    REPAIR_APPLIED = "repair_applied"
    ROLLBACK_APPLIED = "rollback_applied"
    RECONCILIATION_PROOF_SATISFIED = "reconciliation_proof_satisfied"
    FULLY_RECONCILED = "fully_reconciled"


class FillLedgerReconciliationStatus(str, Enum):
    """Persistence status for fill_ledger reconciliation evidence."""

    WS_DERIVED = "WS_DERIVED"
    RECONCILED = "RECONCILED"
    MISMATCH = "MISMATCH"


class SpotPortfolioPnlScope(str, Enum):
    """Durable fill-ledger P/L aggregation scopes for spot portfolio reports."""

    PRODUCT = "product"
    PORTFOLIO = "portfolio"
    SINCE_LAST_PURCHASE = "since_last_purchase"
    REALIZED_LOT = "realized_lot"
    AVERAGE_COST = "average_cost"


class SpotCostBasisSource(str, Enum):
    """Sources of spot cost-basis authority."""

    FILL_LEDGER = "fill_ledger"
    IMPORTED_BASELINE = "imported_baseline"
    COINBASE_AVERAGE_COST = "coinbase_average_cost"
    WALLET_ONLY = "wallet_only"


class SpotCostBasisStatus(str, Enum):
    """Status for Coinbase average cost-basis import and comparison."""

    AVAILABLE = "available"
    MISSING_POSITION = "missing_position"
    MISSING_AVERAGE_ENTRY_PRICE = "missing_average_entry_price"
    MISSING_BALANCE = "missing_balance"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class SpotCostBasisGapStatus(str, Enum):
    """Triage status for spot cost-basis authority gaps."""

    WALLET_ONLY = "wallet_only"
    MISSING_AVERAGE_COST_POSITION = "missing_average_cost_position"
    STALE_AVERAGE_COST = "stale_average_cost"
    LOCAL_LOT_UNAVAILABLE = "local_lot_unavailable"


class SpotOperationLockStatus(str, Enum):
    """Status for local operation lock acquisition."""

    ACQUIRED = "acquired"
    BUSY = "busy"
    RELEASED = "released"
    STALE_REMOVED = "stale_removed"


class SpotCampaignProductSelection(str, Enum):
    """Product-universe selectors supported by spot campaign configs."""

    ALL_COINBASE_USDC_SPOT_US_CUSTOMER_AVAILABLE = (
        "all_coinbase_usdc_spot_us_customer_available"
    )


class SpotCampaignRunMode(str, Enum):
    """Operator mode used for durable spot campaign snapshots."""

    DRY_RUN = "dry_run"
    RELEASE_GATE = "release_gate"
    LIVE_CANARY = "live_canary"
    RETRY_PLAN = "retry_plan"
    STATUS = "status"
    TEMPLATE = "template"
    VALIDATION = "validation"
    DRY_RUN_DIFF = "dry_run_diff"
    RUN_INDEX = "run_index"
    PNL_CHECKPOINT = "pnl_checkpoint"
    RECOVERY_DRILL = "recovery_drill"
    ALL_USDC_READINESS = "all_usdc_readiness"
    SCHEDULER_STATUS = "scheduler_status"
    SELL_AUTHORITY_ALLOWLIST = "sell_authority_allowlist"
    LEDGER_CLEANUP_PLAN = "ledger_cleanup_plan"
    LEDGER_CLEANUP_APPLY = "ledger_cleanup_apply"
    SELL_AUTHORITY_DRIFT = "sell_authority_drift"
    SELL_AUTHORITY_OPERATOR_REPORT = "sell_authority_operator_report"
    STRICT_SELL_CANARY_CANDIDATES = "strict_sell_canary_candidates"
    PNL_DELTA_REPORT = "pnl_delta_report"
    CONTEXTLESS_AGENT_CHECKLIST = "contextless_agent_checklist"


class SpotCampaignStatus(str, Enum):
    """Durable status for spot campaign snapshots and release gates."""

    READY = "ready"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    RECORDED = "recorded"


class SpotCampaignGateStatus(str, Enum):
    """Pass/fail status for read-only spot campaign release gates."""

    PASSED = "passed"
    FAILED = "failed"


class SpotCampaignRetryOrderClass(str, Enum):
    """Classification for orders from a partial campaign sweep run."""

    RETRYABLE_NOT_SUBMITTED = "retryable_not_submitted"
    SUBMITTED_OR_LIVE = "submitted_or_live"
    NOT_RETRYABLE = "not_retryable"


class SpotCampaignTemplateProfile(str, Enum):
    """Canonical spot campaign config templates for operator workflows."""

    BUY_CANARY = "buy_canary"
    BUY_ALL_USDC = "buy_all_usdc"
    SELL_CANARY = "sell_canary"
    SELL_ALL_USDC = "sell_all_usdc"


class SpotCampaignSellAuthorityProfile(str, Enum):
    """SELL cost-basis authority presets for campaign configs."""

    FILL_LEDGER_STRICT = "fill_ledger_strict"
    COINBASE_AVERAGE_COST_BUFFERED = "coinbase_average_cost_buffered"


class SpotSellAuthorityAllowlistFreshness(str, Enum):
    """Freshness status for rendered SELL authority allowlist configs."""

    NOT_APPLICABLE = "not_applicable"
    FRESH = "fresh"
    STALE = "stale"
    INVALID = "invalid"


class ContractExpiryType(str, Enum):
    """Type of futures contract expiration.
    
    From Coinbase API: PERPETUAL, EXPIRING, UNKNOWN_CONTRACT_EXPIRY_TYPE
    """
    PERPETUAL = "PERPETUAL"
    EXPIRING = "EXPIRING"
    UNKNOWN_CONTRACT_EXPIRY_TYPE = "UNKNOWN_CONTRACT_EXPIRY_TYPE"


class Direction(str, Enum):
    """Directional threshold comparisons for conditions.
    
    Used in price threshold and ratio evaluators.
    """
    ABOVE = "above"
    BELOW = "below"


class RoundingDirection(str, Enum):
    """Rounding direction for quantization operations.
    
    Used in price/size quantization to determine rounding strategy.
    """
    UP = "up"
    DOWN = "down"
    NEAREST = "nearest"


class FollowUpRevealDirection(str, Enum):
    """Direction strategy for follow-up orders after stealth order reveals/fills.
    
    Used to determine how follow-up stealth orders should be configured when
    a previous order transitions to the exchange or fills.
    
    - SAME: Create follow-up order with same side (BUY stays BUY, SELL stays SELL)
    - OPPOSITE: Flip the side (BUY becomes SELL, SELL becomes BUY)
    """
    SAME = "same"
    OPPOSITE = "opposite"


class FollowUpKind(str, Enum):
    """Terminal-event kind for follow-up processing claims.

    The OrderEngine claims a per-order processing token before creating a
    follow-up so concurrent threads observing the same WS terminal event do
    not double-spawn. ``FILLED`` and ``CANCELLED`` use independent token
    namespaces -- a filled-side claim does not block a cancelled-side claim.
    """

    FILLED = "filled"
    CANCELLED = "cancelled"


class SpotFollowUpIntent(str, Enum):
    """Spot-specific intent classification for follow-up orders."""

    EXIT = "exit"
    REBUY = "rebuy"
    SAME_SIDE_REPLACEMENT = "same_side_replacement"
    UNSUPPORTED = "unsupported"


class SpotFollowUpTrigger(str, Enum):
    """Event that requested a spot follow-up order."""

    FILLED = "filled"
    PARTIAL_FILL = "partial_fill"
    CANCELLED = "cancelled"


class StealthMutationKind(str, Enum):
    """Kind of in-flight mutation against a single stealth order.

    Stealth orders may be mutated concurrently by two independent paths:
    - The ticker-driven anchor reprice loop (background, REPRICE)
    - User-initiated "move REVEALED" actions from the dashboard (MOVE)
    - Fill-driven hidden order retreat (background, RETREAT)

    Each kind has its own per-(kind, stealth_order_id) claim namespace in
    a :class:`core.orderbook.ClaimLedger`. A held MOVE claim must block a
    REPRICE attempt on the same order, and vice versa, to prevent
    double-cancellation of the exchange order.

    Unlike :class:`FollowUpKind`, stealth mutations are **repeatable** --
    a moved order may later be moved again, a repriced order may later be
    repriced again. Callers must release the claim with ``release`` after
    both success and failure paths; there is no terminal ``done`` state.
    """

    MOVE = "move"
    REPRICE = "reprice"
    RETREAT = "retreat"


class StealthMoveReason(str, Enum):
    """Why a REVEALED stealth order was moved.

    Persisted on the audit row so the move history is queryable by intent.
    """

    MANUAL_USER_MOVE = "manual_user_move"
    OPERATOR_REPRICE = "operator_reprice"


class CancelReentryState(str, Enum):
    """Runtime state for cancel/re-entry policy.

    RESTING means the order is either hidden before first reveal or has an
    active revealed placement. CANCELLED_BY_POLICY means a policy-triggered
    exchange cancel succeeded and the order is waiting for re-entry distance.
    """

    RESTING = "resting"
    CANCELLED_BY_POLICY = "cancelled_by_policy"


class CancelReentryDecision(str, Enum):
    """Pure evaluator decision for cancel/re-entry policy."""

    HOLD = "hold"
    CANCEL = "cancel"
    REENTER = "reenter"


class PostFillRetreatScope(str, Enum):
    """Which hidden orders a post-fill retreat policy may affect."""

    SAME_PRODUCT_SAME_SIDE = "same_product_same_side"


class PostFillRetreatReason(str, Enum):
    """Audit reason for hidden-order post-fill retreat."""

    SAME_SIDE_FILL = "same_side_post_fill_retreat"


class RevealPricingPolicy(str, Enum):
    """Pricing policy for stealth order reveal.

    Determines what price to use when revealing a stealth order to the exchange.

    - CONFIGURED_LIMIT: Use the limit price specified at order creation. The
      caller has taken explicit responsibility for the price and may have
      chosen one that crosses the spread, so the order submits with
      ``post_only=False`` (taker semantics) and is fee-validated against the
      taker rate.
    - TOP_OF_BOOK: Use current best bid (SELL) or best ask (BUY) from ticker.
      Submitted with ``post_only=True`` so the order rests at the touch as
      a maker. On post-only rejection the reveal path retries with the price
      one tick safer (``next_safer_tick``); after exhausting retries the
      placement is surfaced and abandoned rather than silently demoted to
      a taker fill.
    - MIDPOINT: Use midpoint between current bid and ask. Same ``post_only``
      and retry semantics as TOP_OF_BOOK \u2014 the midpoint is between the
      touch quotes by construction so it should never cross.
    """
    CONFIGURED_LIMIT = "configured_limit"
    TOP_OF_BOOK = "top_of_book"
    MIDPOINT = "midpoint"

    def implies_post_only(self) -> bool:
        """Return ``True`` when this policy must submit with ``post_only=True``.

        Single source of truth for the policy \u2192 post_only mapping. Both the
        pre-flight feasibility check (which decides whether to charge maker
        or taker fees in the round-trip math) and the reveal-time submission
        path consult this so the two cannot drift.
        """
        return self in (RevealPricingPolicy.TOP_OF_BOOK, RevealPricingPolicy.MIDPOINT)


class RevealPriceSource(str, Enum):
    """Source of the price used when revealing a stealth order.
    
    Indicates how the submitted limit price was determined at reveal time.
    Used for audit trails and understanding reveal execution decisions.
    
    - CONFIGURED_LIMIT: Used original limit price from order creation (fallback or direct use)
    - TICKER_BEST_BID: Used best bid from ticker (SELL orders with TOP_OF_BOOK policy)
    - TICKER_BEST_ASK: Used best ask from ticker (BUY orders with TOP_OF_BOOK policy)
    - TICKER_MIDPOINT: Used midpoint between bid/ask (MIDPOINT policy)
    - UNAVAILABLE: Market data unavailable, fell back to configured limit
    """
    CONFIGURED_LIMIT = "configured_limit"
    TICKER_BEST_BID = "ticker_best_bid"
    TICKER_BEST_ASK = "ticker_best_ask"
    TICKER_MIDPOINT = "ticker_midpoint"
    UNAVAILABLE = "unavailable"


# ============================================================================
# STEALTH ORDER CONDITIONS
# ============================================================================

class RevealConditionType(str, Enum):
    """Type of condition that triggers stealth order reveal.
    
    - PRICE_THRESHOLD: Reveal when price crosses threshold
    - CUMULATIVE_VOLUME: Reveal when cumulative volume at price level reached
    - TIME_DELAY: Reveal after time delay (with optional jitter)
    - SPREAD: Reveal when bid-ask spread narrows below threshold
    - PRODUCT_RATIO: Reveal when ratio between two products meets threshold
    - COMPOSITE: Reveal when multiple conditions meet (AND/OR logic)
    """
    PRICE_THRESHOLD = "price"
    CUMULATIVE_VOLUME = "cumulative_volume"
    TIME_DELAY = "time_delay"
    SPREAD = "spread"
    PRODUCT_RATIO = "product_ratio"
    COMPOSITE = "composite"


# ============================================================================
# ANCHOR REPRICING POLICY
# ============================================================================

class RepricingReferenceSource(str, Enum):
    """Market reference used by ``anchor_repricing_policy`` to compute the
    target price each tick.

    - LAST_TRADE: Use the most recent trade price from the ticker.
    - MIDPOINT: Use ``(bid + ask) / 2``.
    - TOP_OF_BOOK: Use best bid for BUY orders, best ask for SELL orders.

    Persisted as a string in
    ``stealth_orders.anchor_repricing_policy_json -> 'reference_price_source'``.
    """
    LAST_TRADE = "last_trade"
    MIDPOINT = "midpoint"
    TOP_OF_BOOK = "top_of_book"


class RepricingDistanceType(str, Enum):
    """How ``target_distance`` / ``max_distance`` are interpreted.

    - PERCENT (``"P"``): Distance is a percentage of the reference price.
    - ABSOLUTE (``"A"``): Distance is in absolute price units.

    Single-letter codes are preserved for on-disk compatibility with the
    existing dashboard payload.
    """
    PERCENT = "P"
    ABSOLUTE = "A"


class RepricingUpdateMode(str, Enum):
    """How often the repricing loop evaluates a new target.

    - ADAPTIVE: Re-evaluate when the market moves (rate-limited by the min
      interval / max-per-hour throttles).
    - FIXED: Re-evaluate on a fixed cadence (``fixed_interval_seconds``).
    """
    ADAPTIVE = "adaptive"
    FIXED = "fixed"


# ============================================================================
# WEBSOCKET & EVENT TYPES
# ============================================================================

class WebSocketEventType(str, Enum):
    """Type of WebSocket event from message.
    
    - SNAPSHOT: Initial state of orders/positions
    - UPDATE: Incremental update to existing state
    - PATCH: Update (used in user channel)
    """
    SNAPSHOT = "snapshot"
    UPDATE = "update"
    PATCH = "patch"


class EventTriggerType(str, Enum):
    """Trigger categories for audit/event-stream payloads."""
    STEALTH_CONDITION = "stealth_condition"
    FOLLOW_UP = "follow_up"


class EventSourceChannel(str, Enum):
    """Named source channels for order_event_stream rows."""
    PLACEMENT_PRE_HOOK      = "placement_pre_hook"
    WS_USER                 = "ws_user"
    FILL_HOOK               = "fill_hook"
    REST_SUBMIT             = "rest_submit"
    PLACEMENT_POST_HOOK     = "placement_post_hook"
    ORDER_STATE_HOOK        = "order_state_hook"
    STEALTH_LIFECYCLE_HOOK  = "stealth_lifecycle_hook"
    ORDER_ENGINE_OPEN       = "order_engine_open_handler"
    ORDER_ENGINE_TERMINAL   = "order_engine_terminal_handler"


class EventStreamType(str, Enum):
    """Static event_type values written to order_event_stream.

    Dynamic values (e.g. ``stealth_<lifecycle_event>`` and ``order_<status>``)
    are derived from existing enums at runtime and are NOT listed here.
    """
    STEALTH_CONDITION_MET         = "stealth_condition_met"
    FILL_RECORDED                 = "fill_recorded"
    ORDER_SUBMITTED               = "order_submitted"
    STEALTH_REVEALED              = "stealth_revealed"
    STEALTH_FOLLOW_UP_CREATED     = "stealth_follow_up_created"
    INVENTORY_OPENED              = "inventory_opened"
    INVENTORY_CLOSED              = "inventory_closed"
    PARTIAL_FILL_DETECTED         = "partial_fill_detected"
    PARTIAL_FILL_PROGRESS_UPDATED = "partial_fill_progress_updated"
    PARTIAL_FILL_FOLLOW_UP_QUEUED = "partial_fill_follow_up_queued"
    PARTIAL_FILL_BELOW_MIN        = "partial_fill_below_min_accumulated"
    PARTIAL_FILL_FINALIZED        = "partial_fill_finalized"


class ChannelType(str, Enum):
    """WebSocket channel subscription types.
    
    Public channels (no auth):
    - TICKER: Real-time price updates
    - LEVEL2: Order book updates
    - MARKET_TRADES: Trade execution data
    - CANDLES: OHLCV candle data
    - HEARTBEATS: Server heartbeat
    - STATUS: System status
    - TICKER_BATCH: Batched ticker updates
    
    Authenticated channels:
    - USER: Order and position updates
    - FUTURES_BALANCE_SUMMARY: Futures account balance
    
    Control messages:
    - SUBSCRIPTIONS: Subscription acknowledgment/change notification
    """
    # Public channels
    TICKER = "ticker"
    LEVEL2 = "level2"
    MARKET_TRADES = "market_trades"
    CANDLES = "candles"
    HEARTBEATS = "heartbeats"
    STATUS = "status"
    TICKER_BATCH = "ticker_batch"
    
    # Authenticated channels
    USER = "user"
    FUTURES_BALANCE_SUMMARY = "futures_balance_summary"
    
    # Control messages
    SUBSCRIPTIONS = "subscriptions"


class RiskManagementType(str, Enum):
    """Type of risk management for futures orders.
    
    From Coinbase API:
    - MANAGED_BY_FCM: Risk managed by FCM (broker)
    - MANAGED_BY_VENUE: Risk managed by exchange
    - UNKNOWN_RISK_MANAGEMENT_TYPE: Unknown management type
    """
    MANAGED_BY_FCM = "MANAGED_BY_FCM"
    MANAGED_BY_VENUE = "MANAGED_BY_VENUE"
    UNKNOWN_RISK_MANAGEMENT_TYPE = "UNKNOWN_RISK_MANAGEMENT_TYPE"


# ============================================================================
# ORDER INVENTORY & LIFECYCLE TRACKING
# ============================================================================

class OrderStateEvent(str, Enum):
    """Lifecycle event emitted when an exchange-visible order changes state.

    Used by OrderStateHookRegistry to notify subscribers (e.g. OrderInventory)
    of working-order transitions. These map directly to exchange-confirmed states.

    - OPENED:    Order is now working on the exchange (OPEN/PENDING from WebSocket)
    - FILLED:    Order fully filled on the exchange
    - CANCELLED: Order cancelled (user-initiated or exchange-expired)
    - EXPIRED:   Order expired (e.g. GTD time-in-force elapsed)

    Integration:
        Dispatched from StateManager AFTER its internal lock is released so that
        subscribers never hold StateManager._lock, preventing any lock-ordering
        deadlock. See data/order_inventory.py and integration/order_state_hooks.py.
    """
    OPENED    = "OPENED"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED   = "EXPIRED"


class StealthLifecycleEvent(str, Enum):
    """Fine-grained stealth order state-machine transition events.

    Provides a complete play-by-play audit trail of every stealth order from
    creation through final execution or failure. Stored in order_event_stream
    via StealthLifecycleHookRegistry -> OrderEventStreamPublisher.

    State machine flow:
        CREATED
          -> CONDITION_WATCHING  (condition partially met, watching for hold duration)
             -> CONDITION_MET    (condition fully confirmed, order TRIGGERED)
                -> REVEAL_ATTEMPTED
                   -> PLACEMENT_BLOCKED  (pre-submission hook raised)  [terminal/retriable]
                   -> REVEAL_FAILED      (REST exception / network error) [terminal/retriable]
                   -> REVEAL_SUCCEEDED   (slice placed on exchange books)
                      -> FILL_RECEIVED   (fill event arrived from exchange)
                      -> EXECUTED        (all size filled)               [terminal]
                      -> CANCELLED       (cancelled at any stage)        [terminal]

    Integration:
        Dispatched from StealthOrderManager at each transition point. Hooks are
        called OUTSIDE any internal locks where possible. Subscribers receive a
        context dict with product_id, side, product_type, size, limit_price, reason,
        failure_reason (if applicable), placed_order_id (if applicable).
        See integration/stealth_lifecycle_hooks.py and data/order_inventory.py.
    """
    CREATED            = "CREATED"             # create_stealth_order() persisted
    CONDITION_WATCHING = "CONDITION_WATCHING"  # condition first partially met -> PENDING
    CONDITION_MET      = "CONDITION_MET"       # condition confirmed -> TRIGGERED
    REVEAL_ATTEMPTED   = "REVEAL_ATTEMPTED"    # slice placement about to be sent
    PLACEMENT_BLOCKED  = "PLACEMENT_BLOCKED"   # pre-submission hook blocked placement
    REVEAL_FAILED      = "REVEAL_FAILED"       # REST/network exception during placement
    REVEAL_SUCCEEDED   = "REVEAL_SUCCEEDED"    # slice confirmed placed on exchange
    FILL_RECEIVED      = "FILL_RECEIVED"       # fill event received for revealed slice
    EXECUTED           = "EXECUTED"            # all size executed
    CANCELLED          = "CANCELLED"           # order cancelled at any stage


# ============================================================================
# ORDER PROFIT TARGETS
# ============================================================================

class TargetMovementType(str, Enum):
    """How profit target is specified.
    
    - PERCENTAGE: As percentage (e.g., 0.004 = 0.4%)
    - ABSOLUTE: As absolute amount (e.g., $500)
    """
    PERCENTAGE = "P"       # As percentage (e.g., 0.004 = 0.4%)
    ABSOLUTE = "A"         # As absolute amount (e.g., $500)


# ============================================================================
# RUNTIME LIFECYCLE
# ============================================================================

class EngineState(str, Enum):
    """Engine lifecycle states for graceful shutdown / pause / restart.

    State machine (industry-standard quiesce-drain-stop model):

        RUNNING  --request_pause()-->     PAUSING  --(drain)-->  PAUSED
        PAUSED   --resume()-->            RUNNING
        RUNNING  --request_shutdown()-->  DRAINING --(drain)-->  STOPPED
        PAUSED   --request_shutdown()-->  DRAINING --(drain)-->  STOPPED

    Admission rules (what is accepted at each state):

        | State    | New orders | Cancellations | Fill processing | DB writes |
        | RUNNING  |    yes     |     yes       |       yes       |    yes    |
        | PAUSING  |    no      |     yes       |       yes       |    yes    |
        | PAUSED   |    no      |     yes       |       yes       |    yes    |
        | DRAINING |    no      |     yes       |       yes       |    yes    |
        | STOPPED  |    no      |     no        |       no        |    no     |

    "Soft pause" -- pause stops *originating* new orders but keeps WS, fills,
    and cancellations active so existing positions remain manageable.
    """
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"


# ============================================================================
# HOTPOINT AUTO-REPLICATE
# ============================================================================

class HotpointPlacementPolicy(str, Enum):
    """Price-derivation policy for hotpoint auto-placed orders.

    Selected at trigger time. The auto-placed limit price is derived from the
    bucket and recent fills inside the bucket.
    """

    # Midpoint of the log-spaced bucket. Restart-safe and order-independent.
    WINDOW_CENTER = "WINDOW_CENTER"
    # Price of the most recent qualifying fill that contributed to the trigger.
    LAST_FILL = "LAST_FILL"
    # Arithmetic mean of qualifying fill prices in the trigger window.
    MEAN_OF_FILLS = "MEAN_OF_FILLS"


class HotpointFillSource(str, Enum):
    """Which fills feed the hotpoint detector.

    v1 ships with OWN_ORDERS only. Adding TAPE later is additive: a new
    subscriber pushes ticks into the same bucket ring buffer.
    """

    OWN_ORDERS = "OWN_ORDERS"
    TAPE = "TAPE"
