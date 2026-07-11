"""Shared Admin API command service.

FastAPI routes and legacy dashboard compatibility adapters call this service
instead of implementing placement or cancellation separately.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Any, Callable, Iterator, Mapping
import uuid

from calculation.formatter import safe_float
from core.action_condition_guard import (
    ActionConditionGuard,
    evaluate_spot_standing_price_limit,
    get_action_condition_guard_policy,
    normalize_action_guard_wallet_policy,
)
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    EventSourceChannel,
    EventStreamType,
    OrderOwnershipProvenance,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductCapability,
    ProductType,
    TimeInForce,
    StealthMutationKind,
    TargetMovementType,
)
from core.exceptions import CoinbaseAPIError, OrderCreationError
from core.product_capability import evaluate_product_capability
from core.spot_follow_up_policy import evaluate_spot_follow_up_policy
from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    get_runtime_controller,
)

from .approval import evaluate_live_execution_gate
from .audit import FileAdminApiAuditStore
from .models import (
    AdminApiCommandResponse,
    AdminOrderFillFollowUpTriggerCommand,
    CampaignExecutionCommand,
    CancelOrderCommand,
    FuturesCancelOrderCommand,
    FuturesCloseReduceCommand,
    FuturesPlaceOrderCommand,
    FuturesReconciliationCommand,
    FuturesRiskProofRecordCommand,
    ManualOrderCommand,
    MovementRepriceCommand,
    SpotRecoveryApplyExecutionCommand,
    SpotRecoveryExchangeStateProofCommand,
    SpotRecoveryExchangeStateSnapshotCommand,
    SpotRecoveryReconciliationExecutionCommand,
    SpotRecoveryReconciliationProofRecordCommand,
    SpotRecoveryRollbackExecutionCommand,
    SpotSweepAutomationRunCommand,
    StealthActivePlacementExchangeTruthProofCommand,
    StealthActivePlacementExchangeTruthSnapshotCommand,
    StealthCancelCommand,
    StealthCancelReplaceProofCommand,
    StealthCoinbaseExchangeSubmissionPolicyProofCommand,
    StealthCreateLifecycleWriteGuardProofCommand,
    StealthCreateCommand,
    StealthManagerInvocationPolicyProofCommand,
    StealthMutationClaimSnapshotProofCommand,
    StealthMoveCommand,
    StealthStateMutationPolicyProofCommand,
    StealthPostWriteExecutionJournalCommand,
    StealthPostWriteReconciliationExecutionPolicyProofCommand,
    StealthPostWriteReconciliationProofCommand,
    StealthPostWriteReconciliationVerificationCommand,
    StealthRevealTriggerProofCommand,
    StealthReconciliationProofCommand,
    StealthRecoveryProofCommand,
    StealthRecoveryCommand,
    StealthReconciliationCommand,
    StealthRevealCommand,
)
from .spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    evaluate_spot_test_portfolio_binding,
)
from .spot_recovery_execution import (
    FileSpotRecoveryExecutionJournalStore,
    SpotRecoveryExecutionRecord,
)
from .spot_recovery_execution_service import (
    AdminApiSpotRecoveryExecutionService,
    SpotRecoveryExecutionError,
)
from .spot_recovery_completion import (
    FileSpotRecoveryCompletionJournalStore,
    SpotRecoveryCompletionGuardResult,
    SpotRecoveryCompletionRecord,
    build_spot_recovery_completion_record,
    evaluate_spot_recovery_completion_guard,
)
from .spot_recovery_proof import FileSpotRecoveryProofStore, SpotRecoveryProofRecord
from .spot_recovery_snapshot import (
    FileSpotRecoverySnapshotStore,
    SpotRecoveryExchangeStateSnapshotRecord,
)
from .spot_recovery_repair import FileSpotRecoveryRepairResultJournalStore
from .spot_recovery_proof_service import (
    AdminApiSpotRecoveryProofService,
    SpotRecoveryProofError,
)
from .spot_recovery_snapshot_service import (
    AdminApiSpotRecoverySnapshotService,
    SpotRecoverySnapshotError,
)
from .futures_risk_proof import (
    FileFuturesRiskProofStore,
    FuturesRiskProofRecord,
)
from .futures_risk_proof_service import (
    AdminApiFuturesRiskProofService,
    FuturesRiskProofError,
)
from .stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
    FileStealthExchangeTruthSnapshotStore,
    StealthActivePlacementExchangeTruthProofRecord,
    StealthActivePlacementExchangeTruthSnapshotRecord,
)
from .stealth_exchange_truth_service import (
    AdminApiStealthExchangeTruthService,
    StealthExchangeTruthError,
)
from .stealth_lifecycle_write import (
    FileStealthLifecycleWriteGuardProofStore,
    StealthCreateLifecycleWriteGuardProofRecord,
)
from .stealth_lifecycle_write_service import (
    AdminApiStealthLifecycleWriteGuardService,
    StealthLifecycleWriteGuardError,
)
from .stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
    StealthMutationClaimSnapshotProofRecord,
)
from .stealth_mutation_claim_service import (
    AdminApiStealthMutationClaimProofService,
    StealthMutationClaimProofError,
)
from .stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
    StealthManagerInvocationPolicyProofRecord,
)
from .stealth_manager_policy_service import (
    AdminApiStealthManagerInvocationPolicyService,
    StealthManagerInvocationPolicyError,
)
from .stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    StealthCoinbaseExchangeSubmissionPolicyProofRecord,
)
from .stealth_coinbase_exchange_policy_service import (
    AdminApiStealthCoinbaseExchangeSubmissionPolicyService,
    StealthCoinbaseExchangeSubmissionPolicyError,
)
from .stealth_state_mutation_policy import (
    FileStealthStateMutationPolicyProofStore,
    StealthStateMutationPolicyProofRecord,
)
from .stealth_state_mutation_policy_service import (
    AdminApiStealthStateMutationPolicyService,
    StealthStateMutationPolicyError,
)
from .stealth_recovery_proof import (
    FileStealthRecoveryProofStore,
    StealthRecoveryProofRecord,
)
from .stealth_recovery_proof_service import (
    AdminApiStealthRecoveryProofService,
    StealthRecoveryProofError,
)
from .stealth_reconciliation_proof import (
    FileStealthReconciliationProofStore,
    StealthReconciliationProofRecord,
)
from .stealth_reconciliation_proof_service import (
    AdminApiStealthReconciliationProofService,
    StealthReconciliationProofError,
)
from .stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
    StealthCancelReplaceProofRecord,
)
from .stealth_cancel_replace_proof_service import (
    AdminApiStealthCancelReplaceProofService,
    StealthCancelReplaceProofError,
)
from .stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    StealthPostWriteExecutionJournalAcceptanceRecord,
    FileStealthPostWriteReconciliationProofStore,
    StealthPostWriteReconciliationProofRecord,
    FileStealthPostWriteReconciliationVerificationStore,
    StealthPostWriteReconciliationVerificationRecord,
)
from .stealth_post_write_reconciliation_policy import (
    FileStealthPostWriteReconciliationExecutionPolicyProofStore,
    StealthPostWriteReconciliationExecutionPolicyProofRecord,
)
from .stealth_post_write_reconciliation_policy_service import (
    AdminApiStealthPostWriteReconciliationExecutionPolicyService,
    StealthPostWriteReconciliationExecutionPolicyError,
)
from .stealth_post_write_reconciliation_service import (
    AdminApiStealthPostWriteExecutionJournalService,
    StealthPostWriteExecutionJournalError,
    AdminApiStealthPostWriteReconciliationProofService,
    StealthPostWriteReconciliationProofError,
    AdminApiStealthPostWriteReconciliationVerificationService,
    StealthPostWriteReconciliationVerificationError,
)
from .stealth_reveal_trigger_proof import (
    FileStealthRevealTriggerProofStore,
    StealthRevealTriggerProofRecord,
)
from .stealth_reveal_trigger_proof_service import (
    AdminApiStealthRevealTriggerProofService,
    StealthRevealTriggerProofError,
)
from .stealth_lifecycle_execution import (
    build_stealth_create_lifecycle_write_execution_contract,
)
from .stealth_create_pre_execution import (
    build_stealth_create_pre_execution_contract,
)


INTENTIONAL_FILL_OPERATOR_INTENT = (
    "execute_one_approved_intentional_test_profile_spot_fill"
)
INTENTIONAL_FILL_PRODUCT_ID = "BTC-USDC"
INTENTIONAL_FILL_MAX_NOTIONAL_USDC = Decimal("9.99")
INTENTIONAL_FILL_MAX_ASK_RATIO = Decimal("1.005")
COINBASE_ACTIVE_SPOT_ORDER_STATUSES = (
    "PENDING",
    "OPEN",
    "QUEUED",
    "CANCEL_QUEUED",
    "EDIT_QUEUED",
)


def _noop_log(_level: str, _message: str) -> None:
    return None


def _empty_budget() -> dict[str, float]:
    return {}


def _insert_order_parent(**kwargs: Any) -> Any:
    from database.order import insert_order_parent

    return insert_order_parent(**kwargs)


def _update_order_parent_status(client_order_id: str, status: str) -> Any:
    from database.order import update_order_parent_status

    return update_order_parent_status(client_order_id, status)


class SpotProfileOrderAdmissionCoordinator:
    """Serialize Spot submit/cancel decisions and retain runtime uncertainty.

    The lock is keyed by the credential-bound portfolio UUID.  Callers hold it
    from the authoritative open-order read through the REST outcome and final
    local/audit evidence so two request-scoped command-service instances cannot
    both admit an order from the same zero-open snapshot.
    """

    def __init__(self) -> None:
        self._registry_lock = RLock()
        self._profile_locks: dict[str, RLock] = {}
        self._uncertain_submissions: dict[str, dict[str, str]] = {}

    def _profile_lock(self, retail_portfolio_id: str) -> RLock:
        with self._registry_lock:
            return self._profile_locks.setdefault(retail_portfolio_id, RLock())

    @contextmanager
    def claim(self, retail_portfolio_id: str) -> Iterator[None]:
        portfolio_id = str(retail_portfolio_id or "").strip()
        if not portfolio_id:
            raise ValueError("spot_portfolio_id_missing_for_admission_claim")
        lock = self._profile_lock(portfolio_id)
        with lock:
            yield

    def record_uncertainty(
        self,
        *,
        retail_portfolio_id: str,
        client_order_id: str,
        reason: str,
    ) -> None:
        with self._registry_lock:
            self._uncertain_submissions.setdefault(
                str(retail_portfolio_id),
                {},
            )[str(client_order_id)] = str(reason)

    def resolve_uncertainty(
        self,
        *,
        retail_portfolio_id: str,
        client_order_id: str,
    ) -> None:
        with self._registry_lock:
            profile = self._uncertain_submissions.get(str(retail_portfolio_id))
            if profile is None:
                return
            profile.pop(str(client_order_id), None)
            if not profile:
                self._uncertain_submissions.pop(str(retail_portfolio_id), None)

    def uncertainty_snapshot(
        self,
        retail_portfolio_id: str,
    ) -> list[dict[str, str]]:
        with self._registry_lock:
            profile = dict(
                self._uncertain_submissions.get(str(retail_portfolio_id), {})
            )
        return [
            {"client_order_id": client_order_id, "reason": reason}
            for client_order_id, reason in sorted(profile.items())
        ]


_SPOT_PROFILE_ORDER_ADMISSION_COORDINATOR = SpotProfileOrderAdmissionCoordinator()


@dataclass(slots=True)
class AdminApiCommandDependencies:
    """Runtime dependencies required by live command execution."""

    rest_client: Any = None
    rest_client_available: bool = False
    live_runtime_enabled: bool | None = None
    command_runtime_ready: bool | None = None
    command_runtime_missing_reason: str | None = None
    command_runtime_source: str = "application/admin_api/command_runtime.py"
    spot_portfolio_id: str | None = None
    spot_portfolio_label: str = DEFAULT_SPOT_PORTFOLIO_LABEL
    spot_market_reference_getter: Callable[[str], Mapping[str, Any] | None] = (
        lambda _product_id: None
    )
    order_root_registrar_getter: Callable[[], Any | None] = lambda: None
    spot_order_admission_coordinator: SpotProfileOrderAdmissionCoordinator = field(
        default_factory=lambda: _SPOT_PROFILE_ORDER_ADMISSION_COORDINATOR
    )
    runtime_controller_factory: Callable[[], Any] = get_runtime_controller
    add_log_entry: Callable[[str, str], None] = _noop_log
    order_event_publisher_getter: Callable[[], Any | None] = lambda: None
    fill_follow_up_executor_getter: Callable[[], Any | None] = lambda: None
    read_service_getter: Callable[[], Any | None] | None = None
    planned_budget_fetcher: Callable[[], dict[str, float]] = _empty_budget
    lot_authority_evaluator_getter: Callable[[], Any | None] = lambda: None
    uuid_factory: Callable[[], str] = field(default_factory=lambda: lambda: str(uuid.uuid4()))
    insert_order_parent: Callable[..., Any] = _insert_order_parent
    update_order_parent_status: Callable[[str, str], Any] = _update_order_parent_status
    spot_recovery_proof_store_getter: Callable[
        [],
        FileSpotRecoveryProofStore,
    ] = FileSpotRecoveryProofStore
    spot_recovery_execution_store_getter: Callable[
        [],
        FileSpotRecoveryExecutionJournalStore,
    ] = FileSpotRecoveryExecutionJournalStore
    spot_recovery_snapshot_store_getter: Callable[
        [],
        FileSpotRecoverySnapshotStore,
    ] = FileSpotRecoverySnapshotStore
    spot_recovery_repair_result_store_getter: Callable[
        [],
        FileSpotRecoveryRepairResultJournalStore,
    ] = FileSpotRecoveryRepairResultJournalStore
    spot_recovery_completion_store_getter: Callable[
        [],
        FileSpotRecoveryCompletionJournalStore,
    ] = FileSpotRecoveryCompletionJournalStore
    futures_risk_proof_store_getter: Callable[
        [],
        FileFuturesRiskProofStore,
    ] = FileFuturesRiskProofStore
    stealth_exchange_truth_snapshot_store_getter: Callable[
        [],
        FileStealthExchangeTruthSnapshotStore,
    ] = FileStealthExchangeTruthSnapshotStore
    stealth_exchange_truth_proof_store_getter: Callable[
        [],
        FileStealthExchangeTruthProofStore,
    ] = FileStealthExchangeTruthProofStore
    stealth_lifecycle_write_guard_proof_store_getter: Callable[
        [],
        FileStealthLifecycleWriteGuardProofStore,
    ] = FileStealthLifecycleWriteGuardProofStore
    stealth_mutation_claim_proof_store_getter: Callable[
        [],
        FileStealthMutationClaimProofStore,
    ] = FileStealthMutationClaimProofStore
    stealth_manager_policy_proof_store_getter: Callable[
        [],
        FileStealthManagerInvocationPolicyProofStore,
    ] = FileStealthManagerInvocationPolicyProofStore
    stealth_coinbase_exchange_policy_proof_store_getter: Callable[
        [],
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    ] = FileStealthCoinbaseExchangeSubmissionPolicyProofStore
    stealth_state_mutation_policy_proof_store_getter: Callable[
        [],
        FileStealthStateMutationPolicyProofStore,
    ] = FileStealthStateMutationPolicyProofStore
    stealth_recovery_proof_store_getter: Callable[
        [],
        FileStealthRecoveryProofStore,
    ] = FileStealthRecoveryProofStore
    stealth_reveal_trigger_proof_store_getter: Callable[
        [],
        FileStealthRevealTriggerProofStore,
    ] = FileStealthRevealTriggerProofStore
    stealth_reconciliation_proof_store_getter: Callable[
        [],
        FileStealthReconciliationProofStore,
    ] = FileStealthReconciliationProofStore
    stealth_cancel_replace_proof_store_getter: Callable[
        [],
        FileStealthCancelReplaceProofStore,
    ] = FileStealthCancelReplaceProofStore
    stealth_post_write_reconciliation_proof_store_getter: Callable[
        [],
        FileStealthPostWriteReconciliationProofStore,
    ] = FileStealthPostWriteReconciliationProofStore
    stealth_post_write_execution_journal_store_getter: Callable[
        [],
        FileStealthPostWriteExecutionJournalStore,
    ] = FileStealthPostWriteExecutionJournalStore
    stealth_post_write_reconciliation_verification_store_getter: Callable[
        [],
        FileStealthPostWriteReconciliationVerificationStore,
    ] = FileStealthPostWriteReconciliationVerificationStore
    stealth_post_write_reconciliation_policy_proof_store_getter: Callable[
        [],
        FileStealthPostWriteReconciliationExecutionPolicyProofStore,
    ] = FileStealthPostWriteReconciliationExecutionPolicyProofStore
    audit_store_getter: Callable[[], FileAdminApiAuditStore] = FileAdminApiAuditStore
    spot_recovery_proof_service: AdminApiSpotRecoveryProofService = field(
        default_factory=AdminApiSpotRecoveryProofService
    )
    spot_recovery_execution_service: AdminApiSpotRecoveryExecutionService = field(
        default_factory=AdminApiSpotRecoveryExecutionService
    )
    spot_recovery_snapshot_service: AdminApiSpotRecoverySnapshotService = field(
        default_factory=AdminApiSpotRecoverySnapshotService
    )
    futures_risk_proof_service: AdminApiFuturesRiskProofService = field(
        default_factory=AdminApiFuturesRiskProofService
    )
    stealth_exchange_truth_service: AdminApiStealthExchangeTruthService = field(
        default_factory=AdminApiStealthExchangeTruthService
    )
    stealth_lifecycle_write_guard_service: (
        AdminApiStealthLifecycleWriteGuardService
    ) = field(default_factory=AdminApiStealthLifecycleWriteGuardService)
    stealth_mutation_claim_proof_service: (
        AdminApiStealthMutationClaimProofService
    ) = field(default_factory=AdminApiStealthMutationClaimProofService)
    stealth_manager_policy_service: (
        AdminApiStealthManagerInvocationPolicyService
    ) = field(default_factory=AdminApiStealthManagerInvocationPolicyService)
    stealth_coinbase_exchange_policy_service: (
        AdminApiStealthCoinbaseExchangeSubmissionPolicyService
    ) = field(default_factory=AdminApiStealthCoinbaseExchangeSubmissionPolicyService)
    stealth_state_mutation_policy_service: (
        AdminApiStealthStateMutationPolicyService
    ) = field(default_factory=AdminApiStealthStateMutationPolicyService)
    stealth_recovery_proof_service: AdminApiStealthRecoveryProofService = field(
        default_factory=AdminApiStealthRecoveryProofService
    )
    stealth_reveal_trigger_proof_service: (
        AdminApiStealthRevealTriggerProofService
    ) = field(default_factory=AdminApiStealthRevealTriggerProofService)
    stealth_reconciliation_proof_service: (
        AdminApiStealthReconciliationProofService
    ) = field(default_factory=AdminApiStealthReconciliationProofService)
    stealth_cancel_replace_proof_service: (
        AdminApiStealthCancelReplaceProofService
    ) = field(default_factory=AdminApiStealthCancelReplaceProofService)
    stealth_post_write_reconciliation_proof_service: (
        AdminApiStealthPostWriteReconciliationProofService
    ) = field(default_factory=AdminApiStealthPostWriteReconciliationProofService)
    stealth_post_write_execution_journal_service: (
        AdminApiStealthPostWriteExecutionJournalService
    ) = field(default_factory=AdminApiStealthPostWriteExecutionJournalService)
    stealth_post_write_reconciliation_verification_service: (
        AdminApiStealthPostWriteReconciliationVerificationService
    ) = field(
        default_factory=AdminApiStealthPostWriteReconciliationVerificationService
    )
    stealth_post_write_reconciliation_policy_service: (
        AdminApiStealthPostWriteReconciliationExecutionPolicyService
    ) = field(
        default_factory=AdminApiStealthPostWriteReconciliationExecutionPolicyService
    )


def direct_spot_live_acknowledged(order_params: Mapping[str, Any]) -> bool:
    """Return True when a raw direct spot order includes manual live consent."""

    direct_ack = order_params.get("manual_live_acknowledgement")
    if direct_ack is None:
        direct_ack = order_params.get("manual_live_acknowledged")
    if isinstance(direct_ack, str):
        return direct_ack.strip().lower() in {"true", "yes", "1"}
    return bool(direct_ack)


def _evaluate_configured_price_increment(
    *,
    product_id: str,
    limit_price: Any,
) -> dict[str, Any]:
    """Return fail-closed evidence for an operator-supplied limit price.

    Manual order prices are operator intent.  The command boundary therefore
    validates exact alignment with the configured product tick and never
    quantizes the value to a different price.
    """

    configured_increment: Any = None
    try:
        from configuration import PRODUCT_METADATA, get_trading_product_id

        canonical_product_id = get_trading_product_id(str(product_id or ""))
        metadata = PRODUCT_METADATA.get(canonical_product_id) or {}
        configured_increment = metadata.get("price_increment")
        price_decimal = Decimal(str(limit_price))
        increment_decimal = Decimal(str(configured_increment))
        tick_aligned = bool(
            price_decimal.is_finite()
            and price_decimal > 0
            and increment_decimal.is_finite()
            and increment_decimal > 0
            and price_decimal % increment_decimal == 0
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        canonical_product_id = str(product_id or "")
        tick_aligned = False

    return {
        "product_id": canonical_product_id,
        "limit_price": str(limit_price),
        "configured_price_increment": (
            str(configured_increment)
            if configured_increment is not None and configured_increment != ""
            else None
        ),
        "tick_aligned": tick_aligned,
    }


def _intentional_fill_decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _evaluate_intentional_fill_standing_price_override(
    *,
    command: ManualOrderCommand,
    product_id: str,
    profile_scope: Mapping[str, Any] | None,
    market_reference: Mapping[str, Any] | None,
    standing_price_limit: Mapping[str, Any],
    approved_base_size: Any,
) -> dict[str, Any]:
    """Evaluate the one-shot approval-bound intentional-fill exception.

    The ordinary 50%/150% standing authority remains unchanged. This exception
    is deliberately narrower: one exact route-approved Test-profile BTC-USDC
    BUY, FOK, under 10 USDC, with fresh exact best-ask evidence and every child
    exchange-reveal capability disabled before parent submission.
    """

    request = command.request
    operator_intent = str(command.envelope.operator_intent or "")
    side = str(getattr(request.side, "value", request.side) or "").upper()
    order_type = str(
        getattr(request.order_type, "value", request.order_type) or ""
    ).upper()
    time_in_force = str(
        getattr(request.time_in_force, "value", request.time_in_force) or ""
    ).upper()
    market = dict(market_reference or {})
    scope = dict(profile_scope or {})

    def decimal_or_none(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value or ""))
        except (ArithmeticError, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    best_bid = decimal_or_none(standing_price_limit.get("best_bid"))
    best_ask = decimal_or_none(market.get("best_ask"))
    requested_limit = decimal_or_none(request.limit_price)
    base_size = decimal_or_none(approved_base_size)
    approved_cap = decimal_or_none(command.admin_max_submitted_notional_usdc)
    planned_notional = (
        base_size * requested_limit
        if base_size is not None and requested_limit is not None
        else None
    )
    maximum_marketable_limit = (
        best_ask * INTENTIONAL_FILL_MAX_ASK_RATIO
        if best_ask is not None and best_ask > 0
        else None
    )

    filled_capability = evaluate_product_capability(
        product_id=product_id,
        capability=ProductCapability.FILLED_FOLLOW_UP,
        allow_conditional=True,
    )
    partial_capability = evaluate_product_capability(
        product_id=product_id,
        capability=ProductCapability.PARTIAL_FILL_FOLLOW_UP,
        allow_conditional=True,
    )
    cancelled_capability = evaluate_product_capability(
        product_id=product_id,
        capability=ProductCapability.CANCELLED_FOLLOW_UP,
        allow_conditional=True,
    )
    reveal_capability = evaluate_product_capability(
        product_id=product_id,
        capability=ProductCapability.STEALTH_REVEAL,
    )
    planning_capability = evaluate_product_capability(
        product_id=product_id,
        capability=ProductCapability.STEALTH_PLANNING,
    )
    follow_up_policy = evaluate_spot_follow_up_policy(
        product_id=product_id,
        source_side=OrderSide.BUY.value,
        follow_up_side=OrderSide.SELL.value,
        trigger="filled",
    )
    wallet_policy = normalize_action_guard_wallet_policy(
        get_action_condition_guard_policy()
    )

    blocker = None
    if operator_intent != INTENTIONAL_FILL_OPERATOR_INTENT:
        blocker = "intentional_fill_operator_intent_mismatch"
    elif command.order_configuration_override is not None:
        blocker = "intentional_fill_order_configuration_override_forbidden"
    elif standing_price_limit.get("blocker") is None:
        blocker = "intentional_fill_standing_override_not_required"
    elif standing_price_limit.get("blocker") != "standing_price_limit_not_authorized":
        blocker = "intentional_fill_fresh_standing_reference_not_proven"
    elif not command.admin_approval_snapshot_id:
        blocker = "intentional_fill_approval_missing"
    elif not command.admission_audit_id:
        blocker = "intentional_fill_admission_audit_missing"
    elif not command.admin_cap_guard_decision_id:
        blocker = "intentional_fill_cap_guard_missing"
    elif approved_cap is None or approved_cap <= 0:
        blocker = "intentional_fill_cap_invalid"
    elif approved_cap > INTENTIONAL_FILL_MAX_NOTIONAL_USDC:
        blocker = "intentional_fill_cap_exceeds_approved_maximum"
    elif scope.get("status") != "matched" or scope.get("profile_alias") != "Test":
        blocker = "intentional_fill_test_profile_not_proven"
    elif str(scope.get("portfolio_id") or "") != str(
        scope.get("expected_portfolio_id") or ""
    ):
        blocker = "intentional_fill_test_profile_not_proven"
    elif product_id != INTENTIONAL_FILL_PRODUCT_ID:
        blocker = "intentional_fill_product_not_authorized"
    elif side != OrderSide.BUY.value:
        blocker = "intentional_fill_side_not_authorized"
    elif order_type != OrderType.LIMIT.value:
        blocker = "intentional_fill_order_type_not_authorized"
    elif time_in_force != TimeInForce.FILL_OR_KILL.value:
        blocker = "intentional_fill_time_in_force_not_authorized"
    elif request.post_only is not False:
        blocker = "intentional_fill_post_only_must_be_false"
    elif request.quote_size is not None:
        blocker = "intentional_fill_quote_size_not_authorized"
    elif str(market.get("product_id") or "") != INTENTIONAL_FILL_PRODUCT_ID:
        blocker = "intentional_fill_market_product_mismatch"
    elif best_ask is None or best_ask <= 0:
        blocker = "intentional_fill_best_ask_unavailable"
    elif best_bid is None or best_ask < best_bid:
        blocker = "intentional_fill_best_ask_invalid"
    elif requested_limit is None or requested_limit <= 0:
        blocker = "intentional_fill_limit_price_invalid"
    elif requested_limit < best_ask:
        blocker = "intentional_fill_limit_not_marketable"
    elif (
        maximum_marketable_limit is None
        or requested_limit > maximum_marketable_limit
    ):
        blocker = "intentional_fill_limit_exceeds_slippage_band"
    elif base_size is None or base_size <= 0:
        blocker = "intentional_fill_base_size_invalid"
    elif planned_notional is None or planned_notional <= 0:
        blocker = "intentional_fill_notional_invalid"
    elif planned_notional >= Decimal("10") or planned_notional > approved_cap:
        blocker = "intentional_fill_notional_exceeds_cap"
    elif not planning_capability.allowed:
        blocker = "intentional_fill_stealth_planning_not_enabled"
    elif not filled_capability.allowed or filled_capability.mode != "conditional":
        blocker = "intentional_fill_follow_up_not_conditional"
    elif partial_capability.mode != "disabled":
        blocker = "intentional_fill_partial_follow_up_not_disabled"
    elif cancelled_capability.mode != "disabled":
        blocker = "intentional_fill_cancelled_follow_up_not_disabled"
    elif reveal_capability.mode != "disabled" or reveal_capability.allowed:
        blocker = "intentional_fill_child_reveal_not_disabled"
    elif not follow_up_policy.allowed or follow_up_policy.intent != "exit":
        blocker = "intentional_fill_exit_follow_up_not_enabled"
    elif wallet_policy.get("enabled") is not True:
        blocker = "intentional_fill_wallet_guard_not_enabled"
    elif wallet_policy.get("check_follow_up_planning") is not False:
        blocker = "intentional_fill_fill_backed_planning_not_enabled"
    elif wallet_policy.get("fail_open_on_fetch_error") is True:
        blocker = "intentional_fill_wallet_guard_fail_open"

    return {
        "requested": operator_intent == INTENTIONAL_FILL_OPERATOR_INTENT,
        "allowed": blocker is None,
        "blocker": blocker,
        "operator_intent": operator_intent,
        "order_configuration_override_present": (
            command.order_configuration_override is not None
        ),
        "approval_snapshot_id": command.admin_approval_snapshot_id,
        "admission_audit_id": command.admission_audit_id,
        "cap_guard_decision_id": command.admin_cap_guard_decision_id,
        "profile_alias": scope.get("profile_alias"),
        "portfolio_id": scope.get("portfolio_id"),
        "product_id": product_id,
        "side": side,
        "order_type": order_type,
        "time_in_force": time_in_force,
        "post_only": request.post_only,
        "best_bid": standing_price_limit.get("best_bid"),
        "best_ask": _intentional_fill_decimal_text(best_ask),
        "market_source": market.get("source"),
        "market_observed_at": standing_price_limit.get("market_observed_at"),
        "requested_limit_price": _intentional_fill_decimal_text(requested_limit),
        "maximum_marketable_limit_price": _intentional_fill_decimal_text(
            maximum_marketable_limit
        ),
        "maximum_ask_ratio": str(INTENTIONAL_FILL_MAX_ASK_RATIO),
        "base_size": _intentional_fill_decimal_text(base_size),
        "planned_notional_usdc": _intentional_fill_decimal_text(planned_notional),
        "approved_max_notional_usdc": _intentional_fill_decimal_text(
            approved_cap
        ),
        "marketable": bool(
            best_ask is not None
            and requested_limit is not None
            and requested_limit >= best_ask
        ),
        "filled_follow_up_capability": filled_capability.to_dict(),
        "partial_fill_follow_up_capability": partial_capability.to_dict(),
        "cancelled_follow_up_capability": cancelled_capability.to_dict(),
        "stealth_reveal_capability": reveal_capability.to_dict(),
        "follow_up_policy": follow_up_policy.to_dict(),
        "wallet_policy": wallet_policy,
        "child_exchange_reveal_authorized": False,
    }


def manual_order_action_guard_policy(command: ManualOrderCommand) -> dict[str, Any]:
    """Return action-condition policy scoped to this Admin manual-order command."""

    policy = dict(get_action_condition_guard_policy())
    max_notional = safe_float(
        command.admin_max_submitted_notional_usdc,
        default=None,
    )
    if max_notional is None:
        return policy

    raw_limits = policy.get("limits") or []
    if isinstance(raw_limits, Mapping):
        limits = list(raw_limits.values())
    elif isinstance(raw_limits, list):
        limits = list(raw_limits)
    else:
        limits = []

    limits.append({
        "name": (
            "admin_cap_guard:"
            f"{command.admin_cap_guard_decision_id or 'manual_order'}"
        ),
        "product_type": ProductType.SPOT.value,
        ActionConditionType.MAX_NOTIONAL.value: max_notional,
        "phases": [ActionGuardPhase.PLANNING.value],
    })
    policy["limits"] = limits
    return policy


def coinbase_order_response_to_dict(result: Any) -> dict[str, Any]:
    """Normalize Coinbase order response objects without losing nested fields."""

    converter = getattr(result, "to_dict", None)
    if callable(converter):
        data = converter()
    elif isinstance(result, Mapping):
        data = dict(result)
    elif hasattr(result, "__dict__"):
        data = dict(result.__dict__)
    else:
        data = {}
    return data if isinstance(data, dict) else {}


class CoinbaseOrderReadbackError(RuntimeError):
    """Fail-closed classification for malformed/incomplete order readback."""

    def __init__(self, blocker: str, detail: str) -> None:
        super().__init__(detail)
        self.blocker = blocker
        self.detail = detail


def read_authoritative_coinbase_orders(
    rest_client: Any,
    *,
    order_status: list[str] | None = None,
    order_ids: list[str] | None = None,
    product_ids: list[str] | None = None,
    product_type: str | None = None,
    maximum_pages: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read and validate every Coinbase order page for an exact decision.

    Absence is returned as evidence but is never interpreted here as a
    terminal status.  Missing ``has_next``, an unusable cursor, malformed order
    rows, or a repeated cursor makes the read non-authoritative.
    """

    list_orders = getattr(rest_client, "list_orders", None)
    if not callable(list_orders):
        raise CoinbaseOrderReadbackError(
            "order_read_unavailable",
            "Coinbase list_orders is unavailable",
        )

    cursor: str | None = None
    seen_cursors: set[str] = set()
    rows: list[dict[str, Any]] = []
    page_count = 0
    while True:
        page_count += 1
        if page_count > maximum_pages:
            raise CoinbaseOrderReadbackError(
                "order_read_pagination_limit",
                "Coinbase order read exceeded the bounded pagination limit",
            )
        kwargs: dict[str, Any] = {"limit": 100}
        if order_status is not None:
            kwargs["order_status"] = list(order_status)
        if order_ids is not None:
            kwargs["order_ids"] = list(order_ids)
        if product_ids is not None:
            kwargs["product_ids"] = list(product_ids)
        if product_type is not None:
            kwargs["product_type"] = product_type
        if cursor is not None:
            kwargs["cursor"] = cursor

        try:
            response = list_orders(**kwargs)
        except CoinbaseOrderReadbackError:
            raise
        except Exception as exc:
            raise CoinbaseOrderReadbackError(
                "order_read_failed",
                f"Coinbase order read failed: {type(exc).__name__}: {exc}",
            ) from exc

        data = coinbase_order_response_to_dict(response)
        raw_orders = data.get("orders")
        has_next = data.get("has_next")
        if not isinstance(raw_orders, list) or not isinstance(has_next, bool):
            raise CoinbaseOrderReadbackError(
                "order_read_malformed",
                "Coinbase order page requires orders:list and has_next:bool",
            )
        for raw_order in raw_orders:
            if not isinstance(raw_order, Mapping):
                raise CoinbaseOrderReadbackError(
                    "order_read_malformed",
                    "Coinbase order page contains a non-object order row",
                )
            row = dict(raw_order)
            if not all(
                str(row.get(field) or "").strip()
                for field in ("client_order_id", "order_id", "status")
            ):
                raise CoinbaseOrderReadbackError(
                    "order_read_malformed",
                    "Coinbase order row lacks client_order_id, order_id, or status",
                )
            rows.append(row)

        if not has_next:
            return rows, {
                "authoritative": True,
                "page_count": page_count,
                "order_count": len(rows),
                "pagination_complete": True,
            }

        next_cursor = data.get("cursor")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            raise CoinbaseOrderReadbackError(
                "order_read_malformed_pagination",
                "Coinbase has_next page lacks a usable cursor",
            )
        next_cursor = next_cursor.strip()
        if next_cursor in seen_cursors:
            raise CoinbaseOrderReadbackError(
                "order_read_malformed_pagination",
                "Coinbase order pagination repeated a cursor",
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def exact_coinbase_order_readback(
    rest_client: Any,
    *,
    client_order_id: str,
    exchange_order_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Return exact identity/status proof without treating absence as terminal."""

    if exchange_order_id:
        get_order = getattr(rest_client, "get_order", None)
        if not callable(get_order):
            raise CoinbaseOrderReadbackError(
                "order_read_unavailable",
                "Coinbase get_order is unavailable for exact exchange identity readback",
            )
        try:
            response = get_order(exchange_order_id)
        except CoinbaseOrderReadbackError:
            raise
        except Exception as exc:
            raise CoinbaseOrderReadbackError(
                "order_read_failed",
                f"Coinbase order read failed: {type(exc).__name__}: {exc}",
            ) from exc
        data = coinbase_order_response_to_dict(response)
        raw_order = data.get("order")
        if not isinstance(raw_order, Mapping):
            raise CoinbaseOrderReadbackError(
                "order_read_malformed",
                "Coinbase get_order response requires an order object",
            )
        row = dict(raw_order)
        if not all(
            str(row.get(field) or "").strip()
            for field in ("client_order_id", "order_id", "status")
        ):
            raise CoinbaseOrderReadbackError(
                "order_read_malformed",
                "Coinbase order row lacks client_order_id, order_id, or status",
            )
        rows = [row]
        pagination = {
            "authoritative": True,
            "page_count": 1,
            "order_count": 1,
            "pagination_complete": True,
            "read_method": "get_order",
        }
    else:
        rows, pagination = read_authoritative_coinbase_orders(
            rest_client,
            product_ids=[product_id] if product_id else None,
            product_type=ProductType.SPOT.value,
        )
    matches = [
        row
        for row in rows
        if str(row.get("client_order_id") or "") == str(client_order_id)
        and (
            exchange_order_id is None
            or str(row.get("order_id") or "") == str(exchange_order_id)
        )
        and (
            product_id is None
            or str(row.get("product_id") or "") == str(product_id)
        )
    ]
    exact = len(matches) == 1 and (
        exchange_order_id is None or len(rows) == 1
    )
    matched = matches[0] if exact else None
    return {
        **pagination,
        "client_order_id": client_order_id,
        "exchange_order_id": (
            str(matched.get("order_id")) if matched is not None else exchange_order_id
        ),
        "exact_identity_match": exact,
        "confirmed_absent": len(matches) == 0,
        "authoritative_status": (
            str(matched.get("status") or "").upper() if matched is not None else None
        ),
        "matched_order": matched,
    }


def coinbase_order_response_success(
    result: Any,
    data: Mapping[str, Any],
) -> bool | None:
    """Return Coinbase success evidence when available."""

    success_attr = getattr(result, "success", None)
    if isinstance(success_attr, bool):
        return success_attr
    success = data.get("success")
    if isinstance(success, bool):
        return success
    if data.get("error_response") or data.get("failure_reason"):
        return False
    return None


def coinbase_order_response_error_message(result: Any, data: Mapping[str, Any]) -> str:
    """Extract a Coinbase error message from SDK response shapes."""

    error_response = (
        data.get("error_response")
        or getattr(result, "error_response", None)
    )
    if isinstance(error_response, Mapping):
        return str(
            error_response.get("message")
            or error_response.get("error")
            or "Unknown error"
        )
    message = getattr(error_response, "message", None)
    if message:
        return str(message)
    error = getattr(error_response, "error", None)
    if error:
        return str(error)
    failure_reason = data.get("failure_reason")
    if failure_reason:
        return str(failure_reason)
    return "Unknown error"


def coinbase_order_response_order_id(
    result: Any,
    data: Mapping[str, Any],
) -> str | None:
    """Extract exchange-native order id evidence from SDK response shapes."""

    order_id = getattr(result, "order_id", None)
    if order_id:
        return str(order_id)
    success_response = data.get("success_response")
    if isinstance(success_response, Mapping) and success_response.get("order_id"):
        return str(success_response["order_id"])
    if data.get("order_id"):
        return str(data["order_id"])
    order = data.get("order")
    if isinstance(order, Mapping) and order.get("order_id"):
        return str(order["order_id"])
    return None


def publish_direct_order_submission_event(
    *,
    publisher_getter: Callable[[], Any | None],
    client_order_id: str,
    order_id: str | None,
    order_params: Mapping[str, Any],
    order_configuration: Mapping[str, Any],
) -> bool:
    """Publish durable submission evidence for direct manual placement."""

    publisher = publisher_getter()
    if publisher is None or not getattr(publisher, "enabled", False):
        return False

    inner_key = next(iter(order_configuration), None)
    inner = order_configuration.get(inner_key, {}) if inner_key else {}
    payload = {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "product_id": order_params.get("product_id"),
        "side": order_params.get("side"),
        "order_configuration_type": inner_key,
        "order_configuration": order_configuration,
        "base_size": inner.get("base_size"),
        "quote_size": inner.get("quote_size"),
        "limit_price": inner.get("limit_price"),
        "post_only": inner.get("post_only"),
        "retail_portfolio_id": order_params.get("retail_portfolio_id"),
        "portfolio_profile_alias": order_params.get("portfolio_profile_alias"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"dashboard_submit:{client_order_id}:{order_id or ''}"
    return bool(
        publisher.publish_event(
            event_type=EventStreamType.ORDER_SUBMITTED.value,
            source_channel=EventSourceChannel.REST_SUBMIT.value,
            payload=payload,
            idempotency_key=key,
            status_to=OrderStatus.PENDING.value,
        )
    )


def _spot_recovery_proof_response_data(
    record: SpotRecoveryProofRecord,
    *,
    exchange_state_proof_recorded: bool,
    reconciliation_proof_recorded: bool,
    completion_guard: SpotRecoveryCompletionGuardResult | None = None,
    completion_record: SpotRecoveryCompletionRecord | None = None,
) -> dict[str, Any]:
    """Return command-response data for a persisted recovery proof record."""

    data = record.model_dump(mode="json")
    completion_guard_passed = (
        completion_guard.guard_passed if completion_guard is not None else False
    )
    completion_recorded = completion_record is not None
    data.update({
        "exchange_state_proof_recorded": exchange_state_proof_recorded,
        "reconciliation_proof_recorded": reconciliation_proof_recorded,
        "post_apply_reconciliation_completion_recorded": completion_recorded,
        "completion_guard_passed": completion_guard_passed,
        "completion_guard_status": (
            completion_guard.guard_status.value
            if completion_guard is not None
            else AdminApiGateStatus.BLOCKED.value
        ),
        "completion_guard_failures": (
            completion_guard.guard_failures if completion_guard is not None else []
        ),
        "completion_id": (
            completion_record.completion_id
            if completion_record is not None
            else (
                completion_guard.completion_id
                if completion_guard is not None
                else None
            )
        ),
        "execution_journal_accepted": False,
        "recovery_apply_journal_accepted": False,
        "rollback_journal_accepted": False,
        "recovery_apply_executed": False,
        "rollback_executed": False,
        "reconciliation_executed": False,
        "post_apply_reconciliation_completed": completion_recorded,
        "fully_reconciled": completion_recorded,
        "state_repair_executed": False,
        "coinbase_order_submitted": False,
        "coinbase_rest_read_ran": False,
        "order_state_mutated": False,
        "exchange_state_mutated": False,
        "proof_persisted": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _spot_recovery_execution_response_data(
    record: SpotRecoveryExecutionRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted recovery execution journal."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": False,
        "repair_journal_persisted": True,
        "execution_journal_accepted": True,
        "state_repair_executed": record.state_repair_executed,
        "exchange_state_proof_recorded": False,
        "reconciliation_proof_recorded": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _spot_recovery_snapshot_response_data(
    record: SpotRecoveryExchangeStateSnapshotRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted exchange-state snapshot."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": False,
        "repair_journal_persisted": False,
        "execution_journal_accepted": False,
        "exchange_state_proof_recorded": False,
        "reconciliation_proof_recorded": False,
        "snapshot_recorded": True,
        "source_trusted": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "order_state_mutated": False,
        "exchange_state_mutated": False,
        "reconciliation_executed": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_exchange_truth_snapshot_response_data(
    record: StealthActivePlacementExchangeTruthSnapshotRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted stealth snapshot."""

    data = record.model_dump(mode="json")
    data.update({
        "snapshot_recorded": True,
        "proof_persisted": False,
        "exchange_truth_verified": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_exchange_truth_proof_response_data(
    record: StealthActivePlacementExchangeTruthProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted stealth proof."""

    data = record.model_dump(mode="json")
    data.update({
        "snapshot_recorded": False,
        "proof_persisted": True,
        "exchange_truth_verified": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_lifecycle_write_guard_proof_response_data(
    record: StealthCreateLifecycleWriteGuardProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted lifecycle-write proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "lifecycle_write_guard_verified": False,
        "manager_invocation_ran": False,
        "stealth_row_write_ran": False,
        "order_parent_write_ran": False,
        "lifecycle_event_dispatch_ran": False,
        "local_lifecycle_mutation_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_mutation_claim_proof_response_data(
    record: StealthMutationClaimSnapshotProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted mutation-claim proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "mutation_claim_snapshot_verified": False,
        "manager_invocation_ran": False,
        "claim_acquire_ran": False,
        "claim_release_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_recovery_proof_response_data(
    record: StealthRecoveryProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted recovery proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "recovery_proof_verified": False,
        "manager_invocation_ran": False,
        "recovery_plan_built": False,
        "recovery_repair_executed": False,
        "rollback_executed": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _futures_risk_proof_response_data(
    record: FuturesRiskProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted futures risk proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "risk_proof_verified": False,
        "risk_proof_accepted": False,
        "command_route_registered": False,
        "command_draft_created": False,
        "command_execution_allowed": False,
        "margin_validated": False,
        "collateral_validated": False,
        "liquidation_validated": False,
        "funding_validated": False,
        "reduce_only_validated": False,
        "close_only_validated": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "exchange_state_mutated": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_reveal_trigger_proof_response_data(
    record: StealthRevealTriggerProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted reveal-trigger proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "reveal_trigger_verified": False,
        "manager_invocation_ran": False,
        "trigger_evaluation_ran": False,
        "should_trigger_reveal_called": False,
        "reveal_order_slice_called": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_manager_policy_proof_response_data(
    record: StealthManagerInvocationPolicyProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted manager policy proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "manager_policy_verified": False,
        "manager_invocation_allowed": False,
        "manager_invocation_ran": False,
        "mutation_lock_policy_verified": False,
        "exchange_reality_policy_verified": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_coinbase_exchange_policy_proof_response_data(
    record: StealthCoinbaseExchangeSubmissionPolicyProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted Coinbase exchange policy proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "exchange_submission_policy_verified": False,
        "coinbase_submit_allowed": False,
        "coinbase_cancel_allowed": False,
        "live_coinbase_read_allowed": False,
        "live_cap_verified": False,
        "manager_invocation_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_state_mutation_policy_proof_response_data(
    record: StealthStateMutationPolicyProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted state-mutation policy proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "state_mutation_policy_verified": False,
        "state_mutation_allowed": False,
        "lifecycle_state_mutation_allowed": False,
        "order_state_mutation_allowed": False,
        "exchange_state_mutation_allowed": False,
        "manager_invocation_ran": False,
        "reconciliation_plan_built": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_reconciliation_proof_response_data(
    record: StealthReconciliationProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted reconciliation proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "reconciliation_proof_verified": False,
        "manager_invocation_ran": False,
        "reconciliation_plan_built": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_cancel_replace_proof_response_data(
    record: StealthCancelReplaceProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted cancel/replace proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "cancel_replace_proof_verified": False,
        "manager_invocation_ran": False,
        "cancel_replace_plan_built": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_post_write_reconciliation_proof_response_data(
    record: StealthPostWriteReconciliationProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted post-write proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "post_write_reconciliation_verified": False,
        "route_bound_reconciliation_plan_recorded": True,
        "execution_journal_accepted": False,
        "completion_proof_recorded": True,
        "manager_invocation_ran": False,
        "reconciliation_plan_built": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_post_write_reconciliation_policy_proof_response_data(
    record: StealthPostWriteReconciliationExecutionPolicyProofRecord,
) -> dict[str, Any]:
    """Return command-response data for a persisted post-write policy proof."""

    data = record.model_dump(mode="json")
    data.update({
        "proof_persisted": True,
        "post_write_reconciliation_execution_policy_verified": False,
        "post_write_reconciliation_execution_allowed": False,
        "route_bound_reconciliation_plan_required": True,
        "execution_journal_required": True,
        "reconciliation_verification_required": True,
        "safe_reconciliation_chain_verified": False,
        "manager_invocation_ran": False,
        "reconciliation_plan_built": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_post_write_execution_journal_response_data(
    record: StealthPostWriteExecutionJournalAcceptanceRecord,
) -> dict[str, Any]:
    """Return command-response data for accepted post-write journal evidence."""

    data = record.model_dump(mode="json")
    data.update({
        "journal_acceptance_persisted": True,
        "execution_journal_accepted": True,
        "post_write_reconciliation_verified": False,
        "manager_invocation_ran": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def _stealth_post_write_reconciliation_verification_response_data(
    record: StealthPostWriteReconciliationVerificationRecord,
) -> dict[str, Any]:
    """Return command-response data for verified post-write evidence."""

    data = record.model_dump(mode="json")
    data.update({
        "verification_persisted": True,
        "execution_journal_accepted": True,
        "post_write_reconciliation_verified": True,
        "manager_invocation_ran": False,
        "reconciliation_execution_ran": False,
        "coinbase_read_attempted": False,
        "coinbase_read_succeeded": False,
        "coinbase_rest_read_ran": False,
        "coinbase_order_submitted": False,
        "coinbase_order_cancel_submitted": False,
        "active_placement_cancel_replace_ran": False,
        "reconciliation_executed": False,
        "order_state_mutated": False,
        "lifecycle_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    })
    return data


def manual_order_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate the shared service response to the legacy dashboard payload."""

    status = "success" if response.status == AdminApiCommandStatus.ACCEPTED else "error"
    payload: dict[str, Any] = {
        "type": "order_response",
        "status": status,
        "message": response.message,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.coinbase_order_id:
        payload["order_id"] = response.coinbase_order_id
    if response.submission_event_recorded is not None:
        payload["submission_event_recorded"] = response.submission_event_recorded
    if response.audit_command:
        payload["audit_command"] = response.audit_command
    if response.guard:
        payload["guard"] = response.guard
    if isinstance(response.data, Mapping):
        payload.update(response.data)
    return payload


def cancel_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate the shared cancel response to the legacy dashboard payload."""

    status = "success" if response.status == AdminApiCommandStatus.ACCEPTED else "error"
    payload: dict[str, Any] = {
        "type": "cancel_response",
        "status": status,
        "message": response.message,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.data is not None:
        payload["data"] = response.data
    return payload


def hotpoint_test_order_response_to_dashboard_payload(
    response: AdminApiCommandResponse,
) -> dict[str, Any]:
    """Translate shared hotpoint test placement responses to dashboard JSON."""

    success = response.status == AdminApiCommandStatus.ACCEPTED
    payload: dict[str, Any] = {
        "type": "place_hotpoint_test_order_response",
        "success": success,
    }
    if response.client_order_id:
        payload["client_order_id"] = response.client_order_id
    if response.coinbase_order_id:
        payload["order_id"] = response.coinbase_order_id
    if response.submission_event_recorded is not None:
        payload["submission_event_recorded"] = response.submission_event_recorded
    if response.guard:
        payload["guard"] = response.guard
    if isinstance(response.data, Mapping):
        payload.update(response.data)
    if not success:
        payload.setdefault("error", response.failure_stage or "rejected")
        payload.setdefault("message", response.message)
    return payload


def _ordered_unique_strings(values: list[str | None]) -> list[str]:
    """Return non-empty strings once, preserving first observation order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_FILL_FOLLOW_UP_REQUEST_SCOPED_READINESS_BLOCKERS = frozenset(
    {
        "fill_testing_approval_missing",
        "fill_follow_up_wallet_proof_missing",
        "fill_follow_up_cap_guard_proof_missing",
        "fill_follow_up_reconciliation_proof_missing",
        "fill_follow_up_live_fill_readback_proof_missing",
        "fill_follow_up_rollback_readback_missing",
        "fill_follow_up_operator_visible_audit_missing",
        "audit_correlation_id_missing",
    }
)


def _fill_follow_up_readiness_blockers_for_request(
    blockers: list[str],
) -> list[str]:
    """Drop live/readiness blockers not meant to block the no-live trigger path."""

    return [
        blocker
        for blocker in blockers
        if blocker not in _FILL_FOLLOW_UP_REQUEST_SCOPED_READINESS_BLOCKERS
    ]


def _fill_follow_up_ref_validation(
    *,
    requested_ref: str | None,
    present_attr: str,
    resolved_attr: str,
    missing_reason_attr: str,
    missing_blocker: str,
    unverified_blocker: str,
    mismatch_blocker: str,
    admission_decision: Any | None,
) -> tuple[dict[str, Any], str | None]:
    """Validate a route-bound prerequisite ref against admission evidence."""

    if not requested_ref:
        return (
            {
                "required": True,
                "requested_ref": None,
                "status": "missing",
                "verified": False,
                "blocker": missing_blocker,
                "source": "request_body",
                "missing_reason": "request_ref_missing",
            },
            missing_blocker,
        )
    if admission_decision is None:
        return (
            {
                "required": True,
                "requested_ref": requested_ref,
                "status": "unverified",
                "verified": False,
                "blocker": unverified_blocker,
                "source": "admin_live_admission_decision",
                "missing_reason": "admission_decision_missing",
            },
            unverified_blocker,
        )

    resolved_ref = getattr(admission_decision, resolved_attr, None)
    if bool(getattr(admission_decision, present_attr, False)):
        if resolved_ref == requested_ref:
            return (
                {
                    "required": True,
                    "requested_ref": requested_ref,
                    "status": "verified",
                    "verified": True,
                    "blocker": None,
                    "source": "admin_live_admission_decision",
                    "missing_reason": None,
                },
                None,
            )
        return (
            {
                "required": True,
                "requested_ref": requested_ref,
                "status": "mismatch",
                "verified": False,
                "blocker": mismatch_blocker,
                "source": "admin_live_admission_decision",
                "missing_reason": (
                    "requested_ref_does_not_match_admission_decision"
                ),
                "resolved_ref": resolved_ref,
            },
            mismatch_blocker,
        )

    return (
        {
            "required": True,
            "requested_ref": requested_ref,
            "status": "unverified",
            "verified": False,
            "blocker": unverified_blocker,
            "source": "admin_live_admission_decision",
            "missing_reason": getattr(
                admission_decision,
                missing_reason_attr,
                "admission_proof_missing",
            ),
        },
        unverified_blocker,
    )


def _fill_follow_up_wallet_validation(
    wallet_proof_ref: str | None,
    *,
    cap_guard_wallet_proof_ref: str | None,
    cap_guard_wallet_check_status: str | None,
    cap_guard_wallet_available_notional_usdc: str | None,
    cap_guard_wallet_check_source: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Classify wallet proof without accepting a bare string as authority."""

    if not wallet_proof_ref:
        return (
            {
                "required": True,
                "requested_ref": None,
                "status": "missing",
                "verified": False,
                "blocker": "fill_follow_up_wallet_proof_missing",
                "source": "request_body",
                "missing_reason": "request_ref_missing",
            },
            "fill_follow_up_wallet_proof_missing",
        )
    if cap_guard_wallet_proof_ref:
        if wallet_proof_ref != cap_guard_wallet_proof_ref:
            return (
                {
                    "required": True,
                    "requested_ref": wallet_proof_ref,
                    "expected_ref": cap_guard_wallet_proof_ref,
                    "status": "mismatch",
                    "verified": False,
                    "blocker": "fill_follow_up_wallet_proof_ref_mismatch",
                    "source": "cap_guard_decision_wallet_check",
                    "missing_reason": (
                        "requested_ref_does_not_match_cap_guard_wallet_proof"
                    ),
                },
                "fill_follow_up_wallet_proof_ref_mismatch",
            )
        if cap_guard_wallet_check_status != AdminApiGateStatus.PASSED.value:
            return (
                {
                    "required": True,
                    "requested_ref": wallet_proof_ref,
                    "expected_ref": cap_guard_wallet_proof_ref,
                    "status": "unverified",
                    "verified": False,
                    "blocker": "fill_follow_up_wallet_proof_unverified",
                    "source": "cap_guard_decision_wallet_check",
                    "missing_reason": "cap_guard_wallet_check_not_passed",
                    "wallet_check_status": cap_guard_wallet_check_status,
                },
                "fill_follow_up_wallet_proof_unverified",
            )
        if safe_float(cap_guard_wallet_available_notional_usdc, default=0.0) <= 0.0:
            return (
                {
                    "required": True,
                    "requested_ref": wallet_proof_ref,
                    "expected_ref": cap_guard_wallet_proof_ref,
                    "status": "unverified",
                    "verified": False,
                    "blocker": "fill_follow_up_wallet_proof_unverified",
                    "source": "cap_guard_decision_wallet_check",
                    "missing_reason": (
                        "cap_guard_wallet_available_notional_not_positive"
                    ),
                    "wallet_check_status": cap_guard_wallet_check_status,
                    "wallet_available_notional_usdc": (
                        cap_guard_wallet_available_notional_usdc
                    ),
                },
                "fill_follow_up_wallet_proof_unverified",
            )
        return (
            {
                "required": True,
                "requested_ref": wallet_proof_ref,
                "expected_ref": cap_guard_wallet_proof_ref,
                "status": "verified",
                "verified": True,
                "blocker": None,
                "source": "cap_guard_decision_wallet_check",
                "missing_reason": None,
                "wallet_check_status": cap_guard_wallet_check_status,
                "wallet_available_notional_usdc": (
                    cap_guard_wallet_available_notional_usdc
                ),
                "wallet_check_source": cap_guard_wallet_check_source,
            },
            None,
        )
    return (
        {
            "required": True,
            "requested_ref": wallet_proof_ref,
            "status": "unverified",
            "verified": False,
            "blocker": "fill_follow_up_wallet_proof_unverified",
            "source": "fill_follow_up_wallet_proof_store_missing",
            "missing_reason": "no_fill_follow_up_wallet_proof_store",
        },
        "fill_follow_up_wallet_proof_unverified",
    )


def _fill_follow_up_audit_correlation_validation(
    *,
    requested_ref: str | None,
    expected_ref: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Validate the operator-supplied audit correlation id."""

    if not requested_ref:
        return (
            {
                "required": True,
                "requested_ref": None,
                "expected_ref": expected_ref,
                "status": "missing",
                "verified": False,
                "blocker": "audit_correlation_id_missing",
            },
            "audit_correlation_id_missing",
        )
    if not expected_ref:
        return (
            {
                "required": True,
                "requested_ref": requested_ref,
                "expected_ref": None,
                "status": "unverified",
                "verified": False,
                "blocker": "audit_correlation_id_unverified",
            },
            "audit_correlation_id_unverified",
        )
    if requested_ref != expected_ref:
        return (
            {
                "required": True,
                "requested_ref": requested_ref,
                "expected_ref": expected_ref,
                "status": "mismatch",
                "verified": False,
                "blocker": "audit_correlation_id_mismatch",
            },
            "audit_correlation_id_mismatch",
        )
    return (
        {
            "required": True,
            "requested_ref": requested_ref,
            "expected_ref": expected_ref,
            "status": "matched",
            "verified": True,
            "blocker": None,
        },
        None,
    )


def _fill_follow_up_duplicate_claim_ack_validation(
    acknowledged: bool,
) -> tuple[dict[str, Any], str | None]:
    """Validate the explicit operator duplicate-claim acknowledgement."""

    if acknowledged:
        return (
            {
                "required": True,
                "acknowledged": True,
                "status": "acknowledged",
                "verified": True,
                "blocker": None,
            },
            None,
        )
    return (
        {
            "required": True,
            "acknowledged": False,
            "status": "missing",
            "verified": False,
            "blocker": "duplicate_claim_protection_ack_missing",
        },
        "duplicate_claim_protection_ack_missing",
    )


def _fill_follow_up_duplicate_claim_guard_validation(
    *,
    observed: bool,
    claim_state: str | None,
    claim_source: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Validate read-only duplicate-claim guard state before execution exists."""

    source = claim_source or "runtime_orderbook_unavailable"
    normalized_state = str(claim_state).strip().lower() if claim_state else None
    if not observed:
        return (
            {
                "required": True,
                "observed": False,
                "claim_state": normalized_state,
                "status": "unobserved",
                "verified": False,
                "blocker": "duplicate_claim_protection_unobserved",
                "source": source,
                "claim_acquired": False,
            },
            "duplicate_claim_protection_unobserved",
        )
    if normalized_state in {"processing", "done"}:
        blocker = f"duplicate_claim_{normalized_state}"
        return (
            {
                "required": True,
                "observed": True,
                "claim_state": normalized_state,
                "status": normalized_state,
                "verified": False,
                "blocker": blocker,
                "source": source,
                "claim_acquired": False,
            },
            blocker,
        )
    if normalized_state:
        return (
            {
                "required": True,
                "observed": True,
                "claim_state": normalized_state,
                "status": "unrecognized",
                "verified": False,
                "blocker": "duplicate_claim_state_unrecognized",
                "source": source,
                "claim_acquired": False,
            },
            "duplicate_claim_state_unrecognized",
        )
    return (
        {
            "required": True,
            "observed": True,
            "claim_state": None,
            "status": "available",
            "verified": True,
            "blocker": None,
            "source": source,
            "claim_acquired": False,
        },
        None,
    )


def _fill_follow_up_prerequisite_validation(
    *,
    request: Any,
    audit_correlation_id: str | None,
    admission_decision: Any | None,
    cap_guard_wallet_proof_ref: str | None,
    cap_guard_wallet_check_status: str | None,
    cap_guard_wallet_available_notional_usdc: str | None,
    cap_guard_wallet_check_source: str | None,
    duplicate_claim_observed: bool,
    duplicate_claim_state: str | None,
    duplicate_claim_source: str | None,
) -> tuple[dict[str, Any], list[str | None]]:
    """Build request-scoped fill-follow-up prerequisite validation evidence."""

    approval_validation, approval_blocker = _fill_follow_up_ref_validation(
        requested_ref=request.fill_testing_approval_id,
        present_attr="approval_snapshot_present",
        resolved_attr="approval_snapshot_id",
        missing_reason_attr="approval_snapshot_missing_reason",
        missing_blocker="fill_testing_approval_missing",
        unverified_blocker="fill_testing_approval_unverified",
        mismatch_blocker="fill_testing_approval_ref_mismatch",
        admission_decision=admission_decision,
    )
    wallet_validation, wallet_blocker = _fill_follow_up_wallet_validation(
        request.wallet_proof_ref,
        cap_guard_wallet_proof_ref=cap_guard_wallet_proof_ref,
        cap_guard_wallet_check_status=cap_guard_wallet_check_status,
        cap_guard_wallet_available_notional_usdc=(
            cap_guard_wallet_available_notional_usdc
        ),
        cap_guard_wallet_check_source=cap_guard_wallet_check_source,
    )
    cap_guard_validation, cap_guard_blocker = _fill_follow_up_ref_validation(
        requested_ref=request.cap_guard_decision_id,
        present_attr="cap_guard_present",
        resolved_attr="cap_guard_decision_id",
        missing_reason_attr="cap_guard_missing_reason",
        missing_blocker="fill_follow_up_cap_guard_proof_missing",
        unverified_blocker="fill_follow_up_cap_guard_proof_unverified",
        mismatch_blocker="fill_follow_up_cap_guard_proof_ref_mismatch",
        admission_decision=admission_decision,
    )
    reconciliation_validation, reconciliation_blocker = (
        _fill_follow_up_ref_validation(
            requested_ref=request.reconciliation_plan_id,
            present_attr="reconciliation_plan_present",
            resolved_attr="reconciliation_plan_id",
            missing_reason_attr="reconciliation_plan_missing_reason",
            missing_blocker="fill_follow_up_reconciliation_proof_missing",
            unverified_blocker="fill_follow_up_reconciliation_proof_unverified",
            mismatch_blocker="fill_follow_up_reconciliation_proof_ref_mismatch",
            admission_decision=admission_decision,
        )
    )
    audit_validation, audit_blocker = _fill_follow_up_audit_correlation_validation(
        requested_ref=request.audit_correlation_id,
        expected_ref=audit_correlation_id,
    )
    duplicate_ack_validation, duplicate_ack_blocker = (
        _fill_follow_up_duplicate_claim_ack_validation(
            request.confirm_duplicate_claim_protection
        )
    )
    duplicate_guard_validation, duplicate_guard_blocker = (
        _fill_follow_up_duplicate_claim_guard_validation(
            observed=duplicate_claim_observed,
            claim_state=duplicate_claim_state,
            claim_source=duplicate_claim_source,
        )
    )
    validation = {
        "fill_testing_approval": approval_validation,
        "wallet_proof": wallet_validation,
        "cap_guard_decision": cap_guard_validation,
        "reconciliation_plan": reconciliation_validation,
        "audit_correlation": audit_validation,
        "duplicate_claim_ack": duplicate_ack_validation,
        "duplicate_claim_guard": duplicate_guard_validation,
    }
    blockers = [
        approval_blocker,
        wallet_blocker,
        cap_guard_blocker,
        reconciliation_blocker,
        audit_blocker,
        duplicate_ack_blocker,
        duplicate_guard_blocker,
    ]
    return validation, blockers


def _fill_follow_up_order_payload(active_order: Any | None) -> dict[str, Any]:
    """Build the filled-order payload expected by the existing order engine."""

    if active_order is None:
        return {}
    if hasattr(active_order, "model_dump"):
        payload = active_order.model_dump(mode="json")
    elif isinstance(active_order, dict):
        payload = dict(active_order)
    else:
        return {}
    parent_client_order_id = payload.get("parent_client_order_id")
    if parent_client_order_id is not None:
        payload.setdefault("parent_order_id", parent_client_order_id)
    if payload.get("size") is not None:
        payload.setdefault("filled_size", payload.get("size"))
    if payload.get("price") is not None:
        payload.setdefault("avg_price", payload.get("price"))
    return payload


def _invoke_fill_follow_up_executor(
    executor: Any,
    *,
    order: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Invoke the backend fill-follow-up executor boundary."""

    trigger = getattr(executor, "trigger_filled_follow_up", None)
    if callable(trigger):
        result = trigger(order=order, context=context)
    elif callable(executor):
        result = executor(order=order, context=context)
    else:
        raise TypeError("fill_follow_up_executor_not_callable")
    if result is None:
        return {}
    if isinstance(result, dict):
        return dict(result)
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return {"result": str(result)}


def _fill_follow_up_execution_flag(
    execution_result: dict[str, Any] | None,
    name: str,
    *,
    default: bool = False,
) -> bool:
    if not execution_result:
        return default
    value = execution_result.get(name, default)
    return bool(value)


def _fill_follow_up_execution_reports_live_exchange_activity(
    execution_result: dict[str, Any] | None,
) -> bool:
    return any(
        _fill_follow_up_execution_flag(execution_result, name)
        for name in (
            "coinbase_order_submit_ran",
            "live_coinbase_orders_ran",
            "live_exchange_submitted",
            "exchange_state_mutated",
        )
    )


def _fill_follow_up_readback_reports_duplicate_claim(
    claim_state: str | None,
) -> bool:
    return claim_state in {"processing", "done"}


def _fill_follow_up_post_trigger_chain_blockers(chain: Any) -> list[str]:
    blockers: list[str] = []
    chain_blockers = getattr(chain, "blockers", [])
    if isinstance(chain_blockers, list):
        blockers.extend(
            blocker
            for blocker in chain_blockers
            if isinstance(blocker, str) and blocker
        )
    duplicate_child_ids = getattr(chain, "duplicate_child_client_order_ids", [])
    if isinstance(duplicate_child_ids, list) and duplicate_child_ids:
        blockers.append("follow_up_child_duplicate_source_ids")
    nested_child_ids = getattr(chain, "nested_child_client_order_ids", [])
    nested_parent_ids = getattr(chain, "nested_parent_client_order_ids", [])
    flat_violation_count = getattr(chain, "flat_hierarchy_violation_count", 0)
    try:
        flat_violation_count_int = int(flat_violation_count or 0)
    except (TypeError, ValueError):
        flat_violation_count_int = 0
    if (
        (isinstance(nested_child_ids, list) and nested_child_ids)
        or (isinstance(nested_parent_ids, list) and nested_parent_ids)
        or flat_violation_count_int > 0
    ):
        blockers.append("follow_up_nested_child_parent_detected")
    normalized = _ordered_unique_strings(blockers)
    if not normalized:
        return []
    return _ordered_unique_strings(
        ["fill_follow_up_post_trigger_chain_blocked", *normalized]
    )


_FILL_FOLLOW_UP_TRIGGER_EXECUTION_BLOCKERS = frozenset(
    {
        "fill_follow_up_execution_adapter_failed",
        "fill_follow_up_execution_adapter_live_coinbase_disallowed",
        "fill_follow_up_child_not_observed_after_execution",
        "fill_follow_up_duplicate_claim_not_acquired_after_execution",
        "fill_follow_up_child_id_mismatch_after_execution",
        "fill_follow_up_multiple_children_after_execution",
        "fill_follow_up_post_trigger_chain_blocked",
    }
)


def _fill_follow_up_trigger_failure_stage(
    *,
    trigger_accepted: bool,
    blockers: list[str],
) -> str | None:
    if trigger_accepted:
        return None
    if any(
        blocker in _FILL_FOLLOW_UP_TRIGGER_EXECUTION_BLOCKERS
        for blocker in blockers
    ):
        return "fill_follow_up_trigger_execution"
    return "fill_follow_up_trigger_prerequisite"


def _fill_follow_up_trigger_message(
    *,
    trigger_accepted: bool,
    failure_stage: str | None,
    blockers: list[str] | None = None,
) -> str:
    if trigger_accepted:
        return "Fill follow-up trigger accepted by the backend executor."
    if (
        blockers
        and "fill_follow_up_execution_adapter_live_coinbase_disallowed" in blockers
    ):
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "executor reported disallowed live exchange activity."
        )
    if blockers and "fill_follow_up_post_trigger_chain_blocked" in blockers:
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "post-trigger parent/child chain readback reported blockers."
        )
    if (
        blockers
        and "fill_follow_up_duplicate_claim_not_acquired_after_execution"
        in blockers
    ):
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "duplicate-claim readback did not prove exclusive follow-up claim."
        )
    if blockers and "fill_follow_up_child_id_mismatch_after_execution" in blockers:
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "executor child id did not match post-trigger readback."
        )
    if blockers and "fill_follow_up_multiple_children_after_execution" in blockers:
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "post-trigger readback observed multiple follow-up children."
        )
    if failure_stage == "fill_follow_up_trigger_execution":
        return (
            "Fill follow-up trigger rejected after executor invocation; "
            "post-trigger readback did not prove follow-up creation."
        )
    return (
        "Fill follow-up trigger rejected before execution; "
        "prerequisites are incomplete."
    )


def _fill_follow_up_child_id_delta(pre_chain: Any, post_chain: Any) -> list[str]:
    pre_child_ids = set(_fill_follow_up_chain_child_ids(pre_chain))
    return _ordered_unique_strings(
        [
            child_id
            for child_id in _fill_follow_up_chain_child_ids(post_chain)
            if child_id not in pre_child_ids
        ]
    )


def _fill_follow_up_chain_child_ids(chain: Any) -> list[str]:
    child_ids = getattr(chain, "follow_up_child_client_order_ids", [])
    if not isinstance(child_ids, list):
        return []
    return [child_id for child_id in child_ids if isinstance(child_id, str) and child_id]


def _fill_follow_up_execution_child_ids(
    execution_result: dict[str, Any] | None,
) -> list[str]:
    if not execution_result:
        return []
    child_ids: list[str] = []
    child_id = execution_result.get("follow_up_child_client_order_id")
    if isinstance(child_id, str) and child_id:
        child_ids.append(child_id)
    child_id_list = execution_result.get("follow_up_child_client_order_ids")
    if isinstance(child_id_list, list):
        child_ids.extend(
            item for item in child_id_list if isinstance(item, str) and item
        )
    return _ordered_unique_strings(child_ids)


def _fill_follow_up_chain_child_payload(
    chain: Any,
    child_id: str | None,
) -> dict[str, Any] | None:
    if not child_id:
        return None
    children = getattr(chain, "follow_up_children", [])
    if not isinstance(children, list):
        return None
    for child in children:
        candidate = getattr(child, "client_order_id", None)
        if candidate is None and isinstance(child, dict):
            candidate = child.get("client_order_id")
        if candidate != child_id:
            continue
        if hasattr(child, "model_dump"):
            return child.model_dump(mode="json")
        if isinstance(child, dict):
            return dict(child)
    return None


def _fill_follow_up_trigger_requested_refs(request: Any) -> dict[str, Any]:
    return {
        "fill_testing_approval_id": request.fill_testing_approval_id,
        "wallet_proof_ref": request.wallet_proof_ref,
        "cap_guard_decision_id": request.cap_guard_decision_id,
        "reconciliation_plan_id": request.reconciliation_plan_id,
        "audit_correlation_id": request.audit_correlation_id,
        "confirm_duplicate_claim_protection": (
            request.confirm_duplicate_claim_protection
        ),
    }


def _fill_follow_up_trigger_pre_execution_blockers(
    *,
    readiness: Any,
    chain: Any,
    audit: Any | None,
    prerequisite_blockers: list[str | None],
) -> list[str | None]:
    blockers: list[str | None] = []
    blockers.extend(
        _fill_follow_up_readiness_blockers_for_request(readiness.blockers)
    )
    blockers.extend(chain.blockers)
    if not readiness.found:
        blockers.append("order_not_found")
    if audit is None or audit.follow_up_decision != "eligible_no_live":
        blockers.append("fill_follow_up_decision_not_eligible")
    blockers.extend(prerequisite_blockers)
    if not readiness.duplicate_claim_protection_observed:
        blockers.append("duplicate_claim_protection_unobserved")
    if readiness.duplicate_claim_state in {"processing", "done"}:
        blockers.append(f"duplicate_claim_{readiness.duplicate_claim_state}")
    if chain.follow_up_child_count > 0:
        blockers.append("follow_up_child_already_exists")
    if chain.duplicate_child_client_order_ids:
        blockers.append("follow_up_child_duplicate_source_ids")
    return blockers


class AdminApiCommandService:
    """Shared command-service boundary for enterprise API work."""

    def __init__(self, dependencies: AdminApiCommandDependencies | None = None) -> None:
        self.dependencies = dependencies or AdminApiCommandDependencies()

    def _read_service(self) -> Any:
        getter = self.dependencies.read_service_getter
        if getter is not None:
            service = getter()
            if service is not None:
                return service
        from .read_service import AdminApiReadService

        return AdminApiReadService()

    def _command_runtime_evidence(self) -> dict[str, Any]:
        """Return backend command-runtime evidence for command responses."""

        deps = self.dependencies
        rest_client_available = bool(deps.rest_client_available)
        live_runtime_enabled = (
            deps.live_runtime_enabled
            if deps.live_runtime_enabled is not None
            else rest_client_available
        )
        runtime_ready = (
            deps.command_runtime_ready
            if deps.command_runtime_ready is not None
            else bool(live_runtime_enabled and rest_client_available)
        )
        missing_reason = deps.command_runtime_missing_reason
        if runtime_ready:
            missing_reason = None
        elif missing_reason is None:
            missing_reason = (
                "coinbase_rest_client_unavailable"
                if live_runtime_enabled
                else "live_runtime_disabled"
            )
        return {
            "live_command_runtime_enabled": bool(live_runtime_enabled),
            "live_command_rest_client_available": rest_client_available,
            "live_command_runtime_ready": bool(runtime_ready),
            "live_command_runtime_missing_reason": missing_reason,
            "live_command_runtime_source": deps.command_runtime_source,
        }

    def preview_order_fill_follow_up_trigger(
        self,
        command: AdminOrderFillFollowUpTriggerCommand,
    ) -> dict[str, Any]:
        """Return read-only trigger preview evidence without executor access."""

        read_service = self._read_service()
        readiness = read_service.build_order_fill_follow_up_live_readiness(
            client_order_id=command.client_order_id
        )
        chain = read_service.build_order_fill_follow_up_chain(
            client_order_id=command.client_order_id
        )
        request = command.request
        requested_refs = _fill_follow_up_trigger_requested_refs(request)
        audit = readiness.fill_follow_up_decision_audit
        prerequisite_validation, prerequisite_blockers = (
            _fill_follow_up_prerequisite_validation(
                request=request,
                audit_correlation_id=readiness.audit_correlation_id,
                admission_decision=command.admission_decision,
                cap_guard_wallet_proof_ref=command.cap_guard_wallet_proof_ref,
                cap_guard_wallet_check_status=(
                    command.cap_guard_wallet_check_status
                ),
                cap_guard_wallet_available_notional_usdc=(
                    command.cap_guard_wallet_available_notional_usdc
                ),
                cap_guard_wallet_check_source=(
                    command.cap_guard_wallet_check_source
                ),
                duplicate_claim_observed=(
                    readiness.duplicate_claim_protection_observed
                ),
                duplicate_claim_state=readiness.duplicate_claim_state,
                duplicate_claim_source=readiness.duplicate_claim_source,
            )
        )
        blockers = _ordered_unique_strings(
            _fill_follow_up_trigger_pre_execution_blockers(
                readiness=readiness,
                chain=chain,
                audit=audit,
                prerequisite_blockers=prerequisite_blockers,
            )
        )
        pre_execution_ready = not blockers
        preview_failure_stage = (
            None if pre_execution_ready else "fill_follow_up_trigger_prerequisite"
        )
        response_audit = chain.fill_follow_up_decision_audit or audit
        return {
            "type": "admin_order_fill_follow_up_trigger_preview_evidence",
            "trigger_attempted": False,
            "executor_invoked": False,
            "pre_execution_status": (
                "ready_no_live" if pre_execution_ready else "blocked"
            ),
            "pre_execution_ready": pre_execution_ready,
            "executor_lookup_would_run": pre_execution_ready,
            "preview_failure_stage": preview_failure_stage,
            "trigger_scope": "no_live_local_follow_up",
            "live_readiness_blocker_scope": "live_claim_only",
            "live_readiness_blockers_block_no_live_trigger": False,
            "client_order_id": command.client_order_id,
            "operator_intent": command.envelope.operator_intent,
            "requested_refs": requested_refs,
            "operator_notes": request.operator_notes,
            "prerequisite_validation": prerequisite_validation,
            "pre_execution_blockers": blockers,
            "blockers": blockers,
            "live_readiness": readiness.model_dump(mode="json"),
            "chain": chain.model_dump(mode="json"),
            "fill_follow_up_decision_audit": (
                response_audit.model_dump(mode="json") if response_audit else None
            ),
            "claim_acquired": False,
            "order_engine_handle_filled_order_called": False,
            "stealth_create_follow_up_called": False,
            "follow_up_order_created": False,
            "coinbase_order_submit_ran": False,
            "coinbase_order_cancel_submitted": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "read_only_forward",
        }

    def trigger_order_fill_follow_up(
        self,
        command: AdminOrderFillFollowUpTriggerCommand,
    ) -> AdminApiCommandResponse:
        """Attempt guarded no-live fill-follow-up execution after proof gates."""

        read_service = self._read_service()
        readiness = read_service.build_order_fill_follow_up_live_readiness(
            client_order_id=command.client_order_id
        )
        chain = read_service.build_order_fill_follow_up_chain(
            client_order_id=command.client_order_id
        )
        request = command.request
        requested_refs = _fill_follow_up_trigger_requested_refs(request)
        audit = readiness.fill_follow_up_decision_audit
        prerequisite_validation, prerequisite_blockers = (
            _fill_follow_up_prerequisite_validation(
                request=request,
                audit_correlation_id=readiness.audit_correlation_id,
                admission_decision=command.admission_decision,
                cap_guard_wallet_proof_ref=command.cap_guard_wallet_proof_ref,
                cap_guard_wallet_check_status=(
                    command.cap_guard_wallet_check_status
                ),
                cap_guard_wallet_available_notional_usdc=(
                    command.cap_guard_wallet_available_notional_usdc
                ),
                cap_guard_wallet_check_source=(
                    command.cap_guard_wallet_check_source
                ),
                duplicate_claim_observed=(
                    readiness.duplicate_claim_protection_observed
                ),
                duplicate_claim_state=readiness.duplicate_claim_state,
                duplicate_claim_source=readiness.duplicate_claim_source,
            )
        )
        blockers = _fill_follow_up_trigger_pre_execution_blockers(
            readiness=readiness,
            chain=chain,
            audit=audit,
            prerequisite_blockers=prerequisite_blockers,
        )
        pre_trigger_chain = chain
        execution_result: dict[str, Any] | None = None
        executor_invoked = False
        executor = None
        try:
            executor = self.dependencies.fill_follow_up_executor_getter()
        except Exception as exc:
            execution_result = {
                "status": "unavailable",
                "source": "fill_follow_up_executor_getter",
                "error_type": type(exc).__name__,
            }
            blockers.append("fill_follow_up_execution_adapter_unavailable")

        if executor is None and execution_result is None:
            blockers.append("fill_follow_up_execution_adapter_missing")

        if executor is not None and not _ordered_unique_strings(blockers):
            active_order_payload = _fill_follow_up_order_payload(chain.active_order)
            if not active_order_payload:
                blockers.append("fill_follow_up_active_order_missing")
            else:
                executor_invoked = True
                try:
                    execution_result = _invoke_fill_follow_up_executor(
                        executor,
                        order=active_order_payload,
                        context={
                            "client_order_id": command.client_order_id,
                            "audit_correlation_id": readiness.audit_correlation_id,
                            "idempotency_key": command.envelope.idempotency_key,
                            "correlation_id": command.envelope.correlation_id,
                            "operator_intent": command.envelope.operator_intent,
                            "operator_notes": request.operator_notes,
                            "requested_refs": requested_refs,
                            "prerequisite_validation": prerequisite_validation,
                            "pre_trigger_chain": pre_trigger_chain.model_dump(
                                mode="json"
                            ),
                        },
                    )
                except Exception as exc:
                    execution_result = {
                        "status": "failed",
                        "source": "fill_follow_up_executor",
                        "error_type": type(exc).__name__,
                    }
                    blockers.append("fill_follow_up_execution_adapter_failed")
                else:
                    if _fill_follow_up_execution_reports_live_exchange_activity(
                        execution_result
                    ):
                        blockers.append(
                            "fill_follow_up_execution_adapter_live_coinbase_disallowed"
                        )
                    chain = read_service.build_order_fill_follow_up_chain(
                        client_order_id=command.client_order_id
                    )
                    blockers.extend(_fill_follow_up_post_trigger_chain_blockers(chain))
                    post_execution_audit = chain.fill_follow_up_decision_audit
                    post_execution_claim_state = (
                        post_execution_audit.claim_state
                        if post_execution_audit
                        else None
                    )
                    if not _fill_follow_up_readback_reports_duplicate_claim(
                        post_execution_claim_state
                    ):
                        blockers.append(
                            "fill_follow_up_duplicate_claim_not_acquired_after_execution"
                        )
                    if chain.follow_up_child_count <= pre_trigger_chain.follow_up_child_count:
                        blockers.append(
                            "fill_follow_up_child_not_observed_after_execution"
                        )

        post_trigger_follow_up_child_client_order_ids = (
            _fill_follow_up_child_id_delta(pre_trigger_chain, chain)
        )
        post_trigger_follow_up_child_count_delta = max(
            0,
            chain.follow_up_child_count - pre_trigger_chain.follow_up_child_count,
        )
        execution_child_ids = _fill_follow_up_execution_child_ids(execution_result)
        if executor_invoked and post_trigger_follow_up_child_count_delta > 1:
            blockers.append("fill_follow_up_multiple_children_after_execution")
        if (
            executor_invoked
            and execution_child_ids
            and set(execution_child_ids)
            != set(post_trigger_follow_up_child_client_order_ids)
        ):
            blockers.append("fill_follow_up_child_id_mismatch_after_execution")

        normalized_blockers = _ordered_unique_strings(blockers)
        trigger_accepted = not normalized_blockers
        failure_stage = _fill_follow_up_trigger_failure_stage(
            trigger_accepted=trigger_accepted,
            blockers=normalized_blockers,
        )
        follow_up_child_delta_observed = (
            executor_invoked
            and chain.follow_up_child_count > pre_trigger_chain.follow_up_child_count
        )
        accepted_follow_up_child_client_order_id = (
            post_trigger_follow_up_child_client_order_ids[0]
            if trigger_accepted and len(post_trigger_follow_up_child_client_order_ids) == 1
            else None
        )
        accepted_follow_up_child = _fill_follow_up_chain_child_payload(
            chain,
            accepted_follow_up_child_client_order_id,
        )
        response_audit = chain.fill_follow_up_decision_audit or audit
        post_trigger_duplicate_claim_state = (
            response_audit.claim_state if response_audit else None
        )
        post_trigger_duplicate_claim_source = (
            response_audit.claim_state_source
            if response_audit
            else "runtime_orderbook_unavailable"
        )
        post_trigger_duplicate_claim_observed = bool(
            response_audit and response_audit.claim_reader_ran
        )
        execution_flags = {
            "claim_acquired": _fill_follow_up_execution_flag(
                execution_result,
                "claim_acquired",
            ),
            "order_engine_handle_filled_order_called": executor_invoked
            and _fill_follow_up_execution_flag(
                execution_result,
                "order_engine_handle_filled_order_called",
                default=bool(
                    execution_result
                    and execution_result.get("status") not in {"failed", "unavailable"}
                ),
            ),
            "stealth_create_follow_up_called": _fill_follow_up_execution_flag(
                execution_result,
                "stealth_create_follow_up_called",
                default=follow_up_child_delta_observed,
            ),
            "follow_up_order_created": _fill_follow_up_execution_flag(
                execution_result,
                "follow_up_order_created",
                default=follow_up_child_delta_observed,
            ),
            "coinbase_order_submit_ran": _fill_follow_up_execution_flag(
                execution_result,
                "coinbase_order_submit_ran",
            ),
            "coinbase_order_cancel_submitted": _fill_follow_up_execution_flag(
                execution_result,
                "coinbase_order_cancel_submitted",
            ),
            "local_state_mutated": _fill_follow_up_execution_flag(
                execution_result,
                "local_state_mutated",
                default=follow_up_child_delta_observed,
            ),
            "exchange_state_mutated": _fill_follow_up_execution_flag(
                execution_result,
                "exchange_state_mutated",
            ),
            "live_exchange_submitted": _fill_follow_up_execution_flag(
                execution_result,
                "live_exchange_submitted",
            ),
            "live_coinbase_orders_ran": _fill_follow_up_execution_flag(
                execution_result,
                "live_coinbase_orders_ran",
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        data = {
            "type": "admin_order_fill_follow_up_trigger_result",
            "trigger_attempted": True,
            "trigger_accepted": trigger_accepted,
            "trigger_scope": "no_live_local_follow_up",
            "live_readiness_blocker_scope": "live_claim_only",
            "live_readiness_blockers_block_no_live_trigger": False,
            "client_order_id": command.client_order_id,
            "operator_intent": command.envelope.operator_intent,
            "requested_refs": requested_refs,
            "operator_notes": request.operator_notes,
            "prerequisite_validation": prerequisite_validation,
            "blockers": normalized_blockers,
            "execution_result": execution_result,
            "pre_trigger_chain": pre_trigger_chain.model_dump(mode="json"),
            "post_trigger_follow_up_child_client_order_ids": (
                post_trigger_follow_up_child_client_order_ids
            ),
            "post_trigger_follow_up_child_count_delta": (
                post_trigger_follow_up_child_count_delta
            ),
            "accepted_follow_up_child_client_order_id": (
                accepted_follow_up_child_client_order_id
            ),
            "accepted_follow_up_child": accepted_follow_up_child,
            "post_trigger_duplicate_claim_state": post_trigger_duplicate_claim_state,
            "post_trigger_duplicate_claim_source": post_trigger_duplicate_claim_source,
            "post_trigger_duplicate_claim_observed": (
                post_trigger_duplicate_claim_observed
            ),
            "fill_follow_up_decision_audit": (
                response_audit.model_dump(mode="json") if response_audit else None
            ),
            "live_readiness": readiness.model_dump(mode="json"),
            "chain": chain.model_dump(mode="json"),
            **execution_flags,
        }
        return AdminApiCommandResponse(
            status=(
                AdminApiCommandStatus.ACCEPTED
                if trigger_accepted
                else AdminApiCommandStatus.REJECTED
            ),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="trigger_order_fill_follow_up",
            message=_fill_follow_up_trigger_message(
                trigger_accepted=trigger_accepted,
                failure_stage=failure_stage,
                blockers=normalized_blockers,
            ),
            client_order_id=command.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=execution_flags["live_exchange_submitted"],
            live_coinbase_orders_ran=execution_flags["live_coinbase_orders_ran"],
            data=data,
            failure_stage=failure_stage,
            **self._command_runtime_evidence(),
        )

    def place_manual_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Place a manual order through the existing guarded REST path."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                message=(
                    "Manual order placement requires enterprise auth, "
                    "idempotency, approval, and cap gates before live execution."
                ),
                client_order_id=command.request.client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
                **self._command_runtime_evidence(),
            )

        deps = self.dependencies
        client_order_id = command.request.client_order_id or deps.uuid_factory()
        order_params, order_configuration = self._manual_order_payload(command)
        root_registrar = None
        root_registration: dict[str, Any] | None = None
        standing_price_limit_evidence: dict[str, Any] | None = None
        active_order_limit_evidence: dict[str, Any] | None = None
        profile_admission_claim: Any | None = None
        submission_attempt: dict[str, Any] = {
            "rest_invocation_attempted": False,
            "outcome": "not_attempted",
            "exchange_order_id": None,
            "exchange_order_id_confirmed": False,
            "authoritative_readback_confirmed": False,
            "authoritative_status": None,
        }

        if not deps.rest_client_available:
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="REST client not available",
                failure_stage="rest_client",
            )

        try:
            product_id = order_params.get("product_id")
            inner_key = next(iter(order_configuration), None)
            inner = order_configuration.get(inner_key, {}) if inner_key else {}
            raw_size = inner.get("base_size")
            raw_quote_size = inner.get("quote_size")
            raw_price = inner.get("limit_price")

            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.DIRECT_PLACEMENT,
            )
            if not capability.allowed:
                message = (
                    "Order rejected by product capability policy: "
                    f"{capability.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={"capability": capability.to_dict()},
                    failure_stage="product_capability",
                )

            if (
                capability.product_type == ProductType.SPOT.value
                and raw_price is not None
            ):
                price_increment_evidence = _evaluate_configured_price_increment(
                    product_id=capability.product_id,
                    limit_price=raw_price,
                )
                if not price_increment_evidence["tick_aligned"]:
                    reason = (
                        "Direct Spot limit_price must be positive and exactly "
                        "aligned to the configured product price_increment; "
                        "operator price intent is not quantized."
                    )
                    deps.add_log_entry("WARNING", reason)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={"price_increment": price_increment_evidence},
                        failure_stage="price_increment",
                    )

            spot_portfolio_scope = None
            if (
                deps.spot_portfolio_id
                and capability.product_type != ProductType.SPOT.value
            ):
                portfolio_binding = evaluate_spot_test_portfolio_binding(
                    rest_client=deps.rest_client,
                    expected_portfolio_id=deps.spot_portfolio_id,
                    expected_portfolio_label=deps.spot_portfolio_label,
                )
                spot_portfolio_scope = portfolio_binding.to_dict()
                spot_portfolio_scope.update(
                    {
                        "status": "blocked",
                        "ready": False,
                        "blocker": "spot_test_runtime_product_type_mismatch",
                        "requested_product_id": product_id,
                        "requested_product_type": capability.product_type,
                    }
                )
                reason = (
                    "The Test-profile runtime is Spot-only; derivatives remain "
                    "bound to the separate Default-profile runtime."
                )
                deps.add_log_entry("WARNING", reason)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=reason,
                    data={"portfolio_scope": spot_portfolio_scope},
                    failure_stage="portfolio_scope",
                )
            if capability.product_type == ProductType.SPOT.value:
                portfolio_binding = evaluate_spot_test_portfolio_binding(
                    rest_client=deps.rest_client,
                    expected_portfolio_id=deps.spot_portfolio_id,
                    expected_portfolio_label=deps.spot_portfolio_label,
                )
                spot_portfolio_scope = portfolio_binding.to_dict()
                if not portfolio_binding.ready:
                    reason = (
                        "Direct spot place_order requires the Coinbase CDP key "
                        "to be permissioned to the approved Test portfolio: "
                        f"{portfolio_binding.blocker}"
                    )
                    deps.add_log_entry("WARNING", reason)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={"portfolio_scope": spot_portfolio_scope},
                        failure_stage="portfolio_scope",
                    )
                # Internal/audit evidence only. Coinbase selects CDP-key scope
                # from key permissions; do not send the deprecated request
                # ``retail_portfolio_id`` override to Create Order.
                order_params["retail_portfolio_id"] = (
                    portfolio_binding.observed_portfolio_id
                )
                order_params["portfolio_profile_alias"] = (
                    portfolio_binding.expected_portfolio_label
                )

            if (
                capability.product_type == ProductType.SPOT.value
                and not direct_spot_live_acknowledged(order_params)
            ):
                reason = (
                    "Direct spot place_order is a live manual order surface; "
                    "set params.manual_live_acknowledgement=true before REST submission."
                )
                guard_failure = {
                    "condition": ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value,
                    "block_category": (
                        ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT.value
                    ),
                    "reason": reason,
                    "product_id": product_id,
                    "product_type": capability.product_type,
                    "side": order_params.get("side"),
                    "client_order_id": client_order_id,
                    "phase": ActionGuardPhase.PLANNING.value,
                    "manual_live_acknowledgement_required": True,
                }
                message = f"Order rejected by manual live acknowledgement: {reason}"
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    guard=guard_failure,
                    failure_stage="manual_live_acknowledgement",
                )

            approved_base_size = None
            if raw_size is not None:
                from calculation.size_validation import validate_and_quantize_size

                size_check = validate_and_quantize_size(
                    raw_size,
                    product_id=product_id,
                    price=float(raw_price) if raw_price is not None else None,
                )
                if not size_check:
                    raise OrderCreationError(
                        f"Order rejected at boundary: {size_check.reason}",
                        client_order_id=client_order_id,
                    )
                inner["base_size"] = str(size_check.size)
                approved_base_size = size_check.size

            quote_size = safe_float(raw_quote_size, default=None)
            if raw_quote_size is not None:
                from calculation.size_validation import validate_quote_size

                quote_check = validate_quote_size(raw_quote_size, product_id=product_id)
                if not quote_check:
                    raise OrderCreationError(
                        f"Order rejected at boundary: {quote_check.reason}",
                        client_order_id=client_order_id,
                    )
                inner["quote_size"] = str(quote_check.size)
                quote_size = quote_check.size

            if approved_base_size is not None or quote_size is not None:
                action_guard = ActionConditionGuard(
                    policy=manual_order_action_guard_policy(command),
                    planned_budget_fetcher=deps.planned_budget_fetcher,
                    lot_authority_evaluator=deps.lot_authority_evaluator_getter(),
                )
                if capability.product_type == ProductType.SPOT.value:
                    if not action_guard.has_applicable_notional_cap(
                        phase=ActionGuardPhase.PLANNING,
                        product_id=product_id,
                        side=order_params.get("side"),
                    ):
                        reason = (
                            "Direct spot place_order requires an explicit "
                            "planning-phase max_notional action-condition cap "
                            "before REST submission."
                        )
                        guard_failure = {
                            "condition": (
                                ActionConditionType.DIRECT_SPOT_CAP_REQUIRED.value
                            ),
                            "block_category": (
                                ActionConditionType.DIRECT_SPOT_CAP_REQUIRED.value
                            ),
                            "reason": reason,
                            "product_id": product_id,
                            "product_type": capability.product_type,
                            "side": order_params.get("side"),
                            "client_order_id": client_order_id,
                            "phase": ActionGuardPhase.PLANNING.value,
                            "max_notional_cap_required": True,
                        }
                        message = (
                            "Order rejected by direct spot cap policy: "
                            f"{reason}"
                        )
                        deps.add_log_entry("WARNING", message)
                        return self._place_rejected(
                            command=command,
                            client_order_id=client_order_id,
                            message=message,
                            guard=guard_failure,
                            failure_stage="direct_spot_cap_required",
                        )
                    if (
                        str(order_params.get("side") or "").upper()
                        == OrderSide.SELL.value
                        and not action_guard.requires_known_inventory_for_sell(
                            phase=ActionGuardPhase.PLANNING,
                            product_id=product_id,
                            side=order_params.get("side"),
                        )
                    ):
                        reason = (
                            "Direct spot SELL requires the "
                            "known_inventory_available action-condition guard "
                            "before REST submission."
                        )
                        guard_failure = {
                            "condition": (
                                ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                            ),
                            "block_category": (
                                ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                            ),
                            "reason": reason,
                            "product_id": product_id,
                            "product_type": capability.product_type,
                            "side": order_params.get("side"),
                            "client_order_id": client_order_id,
                            "phase": ActionGuardPhase.PLANNING.value,
                            "known_inventory_available_required": True,
                        }
                        message = (
                            "Order rejected by direct spot SELL authority policy: "
                            f"{reason}"
                        )
                        deps.add_log_entry("WARNING", message)
                        return self._place_rejected(
                            command=command,
                            client_order_id=client_order_id,
                            message=message,
                            guard=guard_failure,
                            failure_stage="known_inventory_required",
                        )

                guard_ok, guard_failure = action_guard.evaluate(
                    phase=ActionGuardPhase.PLANNING,
                    product_id=product_id,
                    side=order_params.get("side"),
                    size=approved_base_size,
                    limit_price=safe_float(raw_price, default=0.0),
                    quote_size=quote_size,
                    client_order_id=client_order_id,
                )
                if not guard_ok:
                    reason = (guard_failure or {}).get("reason", "blocked")
                    message = f"Order rejected by action-condition guard: {reason}"
                    deps.add_log_entry("WARNING", message)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=message,
                        guard=guard_failure,
                        failure_stage="action_condition_guard",
                    )

            submission_event_publisher = None
            if capability.product_type == ProductType.SPOT.value:
                market_reference = deps.spot_market_reference_getter(product_id)
                standing_price_limit_evidence = (
                    evaluate_spot_standing_price_limit(
                        side=order_params.get("side"),
                        limit_price=raw_price,
                        best_bid=(market_reference or {}).get("best_bid"),
                        market_source=(market_reference or {}).get("source"),
                        market_observed_at=(market_reference or {}).get(
                            "observed_at"
                        ),
                        )
                    )
                intentional_fill_requested = (
                    str(command.envelope.operator_intent or "")
                    == INTENTIONAL_FILL_OPERATOR_INTENT
                )
                if (
                    intentional_fill_requested
                    or not standing_price_limit_evidence["allowed"]
                ):
                    intentional_fill_override = (
                        _evaluate_intentional_fill_standing_price_override(
                            command=command,
                            product_id=str(capability.product_id),
                            profile_scope=spot_portfolio_scope,
                            market_reference=market_reference,
                            standing_price_limit=standing_price_limit_evidence,
                            approved_base_size=inner.get("base_size"),
                        )
                    )
                    standing_price_limit_evidence[
                        "intentional_fill_override"
                    ] = intentional_fill_override
                    standing_price_limit_evidence["effective_allowed"] = bool(
                        intentional_fill_override["allowed"]
                    )
                ordinary_or_override_allowed = bool(
                    standing_price_limit_evidence.get("allowed")
                )
                if intentional_fill_requested:
                    ordinary_or_override_allowed = bool(
                        standing_price_limit_evidence.get(
                            "intentional_fill_override", {}
                        ).get("allowed")
                    )
                elif not ordinary_or_override_allowed:
                    ordinary_or_override_allowed = bool(
                        standing_price_limit_evidence.get(
                            "intentional_fill_override", {}
                        ).get("allowed")
                    )
                if not ordinary_or_override_allowed:
                    reason = (
                        "Direct Spot order violates the standing price limit "
                        "or lacks a fresh backend market bid: BUY must be at or below "
                        "50% of bid; SELL must be at or above 150% of bid."
                    )
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "standing_price_limit": (
                                standing_price_limit_evidence
                            ),
                        },
                        failure_stage="standing_price_limit",
                    )

                root_registrar = deps.order_root_registrar_getter()
                register_root = getattr(
                    root_registrar,
                    "register_manual_spot_root",
                    None,
                )
                read_unresolved_roots = getattr(
                    root_registrar,
                    "get_unresolved_admin_manual_root_submissions",
                    None,
                )
                if not callable(register_root) or not callable(read_unresolved_roots):
                    reason = (
                        "Direct Spot place_order requires canonical root "
                        "registration and durable unresolved-root admission reads."
                    )
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={"portfolio_scope": spot_portfolio_scope},
                        failure_stage="order_root_registration",
                    )

                profile_id = str(
                    portfolio_binding.observed_portfolio_id or ""
                )
                profile_admission_claim = (
                    deps.spot_order_admission_coordinator.claim(profile_id)
                )
                profile_admission_claim.__enter__()
                runtime_uncertainties = (
                    deps.spot_order_admission_coordinator.uncertainty_snapshot(
                        profile_id
                    )
                )
                try:
                    durable_unresolved_roots = read_unresolved_roots(profile_id)
                except Exception as exc:
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=(
                            "Durable Admin root admission read failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "runtime_submission_uncertainties": runtime_uncertainties,
                        },
                        failure_stage="submission_uncertainty",
                    )
                if not isinstance(durable_unresolved_roots, list) or any(
                    not isinstance(row, Mapping)
                    for row in durable_unresolved_roots
                ):
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message="Durable Admin root admission read was malformed.",
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "runtime_submission_uncertainties": runtime_uncertainties,
                        },
                        failure_stage="submission_uncertainty",
                    )
                if runtime_uncertainties or durable_unresolved_roots:
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=(
                            "A prior Admin Spot root remains open or uncertain; "
                            "authoritative terminal reconciliation is required "
                            "before another placement."
                        ),
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "runtime_submission_uncertainties": runtime_uncertainties,
                            "durable_unresolved_roots": [
                                dict(row) for row in durable_unresolved_roots
                            ],
                        },
                        failure_stage="submission_uncertainty",
                    )

                try:
                    active_orders, pagination = read_authoritative_coinbase_orders(
                        deps.rest_client,
                        order_status=list(COINBASE_ACTIVE_SPOT_ORDER_STATUSES),
                        product_type=ProductType.SPOT.value,
                    )
                    active_order_limit_evidence = {
                        "allowed": len(active_orders) == 0,
                        "open_order_count": len(active_orders),
                        "open_client_order_ids": [
                            str(item["client_order_id"]) for item in active_orders
                        ],
                        "cancel_before_next": True,
                        "blocker": (
                            None
                            if not active_orders
                            else "existing_open_order_requires_cancel"
                        ),
                        **pagination,
                    }
                except CoinbaseOrderReadbackError as exc:
                    active_order_limit_evidence = {
                        "allowed": False,
                        "open_order_count": None,
                        "cancel_before_next": True,
                        "blocker": (
                            "open_order_read_malformed"
                            if exc.blocker.startswith("order_read_malformed")
                            else exc.blocker.replace("order_", "open_order_", 1)
                        ),
                        "detail": exc.detail,
                        "authoritative": False,
                        "pagination_complete": False,
                    }
                if not active_order_limit_evidence["allowed"]:
                    reason = (
                        "Direct Spot order requires zero existing active orders "
                        "on the Test profile; authoritative terminal reconciliation "
                        "is required before submitting another order."
                    )
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "standing_price_limit": (
                                standing_price_limit_evidence
                            ),
                            "active_order_limit": active_order_limit_evidence,
                        },
                        failure_stage="active_order_limit",
                    )

                submission_event_publisher = deps.order_event_publisher_getter()
                if submission_event_publisher is None or not getattr(
                    submission_event_publisher,
                    "enabled",
                    False,
                ):
                    reason = (
                        "Direct spot place_order requires local durable "
                        "order_event_stream audit before REST submission."
                    )
                    guard_failure = {
                        "condition": ActionConditionType.DURABLE_AUDIT_AVAILABLE.value,
                        "block_category": (
                            ActionConditionType.DURABLE_AUDIT_AVAILABLE.value
                        ),
                        "reason": reason,
                        "product_id": product_id,
                        "product_type": capability.product_type,
                        "side": order_params.get("side"),
                        "client_order_id": client_order_id,
                        "phase": ActionGuardPhase.PLANNING.value,
                        "durable_audit_required": True,
                    }
                    message = (
                        "Order rejected by direct spot durable audit policy: "
                        f"{reason}"
                    )
                    deps.add_log_entry("WARNING", message)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=message,
                        guard=guard_failure,
                        failure_stage="durable_audit_required",
                    )

                if (
                    not inner_key
                    or not str(inner_key).startswith("limit_")
                    or approved_base_size is None
                    or raw_price is None
                ):
                    reason = (
                        "Direct Spot root registration requires a LIMIT order "
                        "with base_size and limit_price before REST submission."
                    )
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={"portfolio_scope": spot_portfolio_scope},
                        failure_stage="order_root_registration",
                    )

                intentional_fill_override = (
                    standing_price_limit_evidence.get(
                        "intentional_fill_override", {}
                    )
                    if standing_price_limit_evidence
                    else {}
                )
                target_movement_override = None
                if intentional_fill_override.get("allowed"):
                    build_target = getattr(
                        root_registrar,
                        "build_intentional_fill_target_movement",
                        None,
                    )
                    if not callable(build_target):
                        target_evidence = {
                            "ready": False,
                            "blocker": (
                                "intentional_fill_target_builder_unavailable"
                            ),
                        }
                    else:
                        try:
                            target_evidence = dict(
                                build_target(
                                    product_id=product_id,
                                    side=order_params.get("side"),
                                    base_size=inner.get("base_size"),
                                    entry_limit_price=inner.get("limit_price"),
                                )
                                or {}
                            )
                        except Exception as exc:
                            target_evidence = {
                                "ready": False,
                                "blocker": (
                                    "intentional_fill_target_builder_failed"
                                ),
                                "detail": f"{type(exc).__name__}: {exc}",
                            }
                    intentional_fill_override[
                        "follow_up_target_movement"
                    ] = target_evidence
                    if not target_evidence.get("ready"):
                        return self._place_rejected(
                            command=command,
                            client_order_id=client_order_id,
                            message=(
                                "Intentional fill requires a fresh fee-aware "
                                "profitable hidden-child target before root "
                                "submission."
                            ),
                            data={
                                "portfolio_scope": spot_portfolio_scope,
                                "standing_price_limit": (
                                    standing_price_limit_evidence
                                ),
                                "active_order_limit": (
                                    active_order_limit_evidence
                                ),
                            },
                            failure_stage=(
                                "intentional_fill_follow_up_target"
                            ),
                        )
                    target_movement_override = target_evidence.get(
                        "target_movement"
                    )

                try:
                    root_registration_kwargs = {
                        "client_order_id": client_order_id,
                        "product_id": product_id,
                        "side": order_params.get("side"),
                        "base_size": inner.get("base_size"),
                        "limit_price": inner.get("limit_price"),
                        "retail_portfolio_id": (
                            portfolio_binding.observed_portfolio_id
                        ),
                        "correlation_id": command.envelope.correlation_id,
                        "audit_id": command.admission_audit_id,
                    }
                    if target_movement_override is not None:
                        root_registration_kwargs[
                            "target_movement_override"
                        ] = target_movement_override
                    root_registration = register_root(
                        **root_registration_kwargs,
                    )
                except Exception as exc:
                    reason = f"Canonical Spot root registration failed: {exc}"
                    deps.add_log_entry("ERROR", reason)
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=reason,
                        data={"portfolio_scope": spot_portfolio_scope},
                        failure_stage="order_root_registration",
                    )
                target_registration_matches = True
                if target_movement_override is not None:
                    try:
                        target_registration_matches = bool(
                            Decimal(
                                str(
                                    root_registration.get("target_movement")
                                )
                            )
                            == Decimal(str(target_movement_override))
                            and root_registration.get(
                                "target_movement_source"
                            )
                            == "fee_aware_intentional_fill_target"
                        )
                    except (ArithmeticError, AttributeError, TypeError, ValueError):
                        target_registration_matches = False
                if not (
                    isinstance(root_registration, Mapping)
                    and root_registration.get("registered") is True
                    and str(root_registration.get("client_order_id") or "")
                    == client_order_id
                    and str(root_registration.get("retail_portfolio_id") or "")
                    == str(portfolio_binding.observed_portfolio_id or "")
                    and str(root_registration.get("ownership_provenance") or "")
                    == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                    and target_registration_matches
                ):
                    return self._place_rejected(
                        command=command,
                        client_order_id=client_order_id,
                        message=(
                            "Canonical Spot root registration returned "
                            "incomplete or mismatched durable evidence."
                        ),
                        data={
                            "portfolio_scope": spot_portfolio_scope,
                            "root_registration": (
                                dict(root_registration)
                                if isinstance(root_registration, Mapping)
                                else None
                            ),
                        },
                        failure_stage="order_root_registration",
                    )

            controller = deps.runtime_controller_factory()
            try:
                with controller.track_inflight(INFLIGHT_REST_PLACE):
                    submission_attempt["rest_invocation_attempted"] = True
                    result = deps.rest_client.create_order(
                        client_order_id=client_order_id,
                        product_id=product_id,
                        side=order_params.get("side"),
                        order_configuration=order_configuration,
                    )
            except Exception as exc:
                submission_attempt["outcome"] = "unknown"
                profile_id = str(
                    (spot_portfolio_scope or {}).get("observed_portfolio_id")
                    or (spot_portfolio_scope or {}).get("portfolio_id")
                    or ""
                )
                if profile_id:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason=f"coinbase_create_exception:{type(exc).__name__}",
                    )
                mark_submission_status = getattr(
                    root_registrar,
                    "mark_submission_status",
                    None,
                )
                if callable(mark_submission_status):
                    try:
                        mark_submission_status(
                            client_order_id=client_order_id,
                            status=OrderStatus.SUBMISSION_UNKNOWN.value,
                        )
                    except Exception as status_exc:
                        deps.add_log_entry(
                            "ERROR",
                            "Failed to mark uncertain Spot submission status: "
                            f"{status_exc}",
                        )
                deps.add_log_entry("ERROR", f"REST submission failed: {exc}")
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=f"Coinbase REST submission failed: {exc}",
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "submission_attempt": submission_attempt,
                    },
                    live_coinbase_orders_ran=True,
                    failure_stage="coinbase_submission_unknown",
                )

            result_dict = coinbase_order_response_to_dict(result)
            response_success = coinbase_order_response_success(result, result_dict)
            if response_success is False:
                submission_attempt["outcome"] = "explicitly_rejected"
                error_msg = coinbase_order_response_error_message(result, result_dict)
                mark_submission_status = getattr(
                    root_registrar,
                    "mark_submission_status",
                    None,
                )
                if callable(mark_submission_status):
                    mark_submission_status(
                        client_order_id=client_order_id,
                        status=OrderStatus.FAILED.value,
                    )
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=f"Order creation failed: {error_msg}",
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "submission_attempt": submission_attempt,
                    },
                    live_coinbase_orders_ran=True,
                    failure_stage="coinbase_rest",
                )

            order_id = coinbase_order_response_order_id(result, result_dict)
            submission_attempt["exchange_order_id"] = order_id
            if response_success is not True or not order_id:
                submission_attempt["outcome"] = "unknown"
                profile_id = str(
                    (spot_portfolio_scope or {}).get("observed_portfolio_id")
                    or (spot_portfolio_scope or {}).get("portfolio_id")
                    or ""
                )
                if profile_id:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="coinbase_create_response_incomplete",
                    )
                mark_submission_status = getattr(
                    root_registrar,
                    "mark_submission_status",
                    None,
                )
                if callable(mark_submission_status):
                    try:
                        mark_submission_status(
                            client_order_id=client_order_id,
                            status=OrderStatus.SUBMISSION_UNKNOWN.value,
                        )
                    except Exception as status_exc:
                        deps.add_log_entry(
                            "ERROR",
                            "Failed to persist incomplete Spot submission "
                            f"response: {status_exc}",
                        )
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=(
                        "Coinbase create response lacked explicit success or "
                        "exchange order identity."
                    ),
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "submission_attempt": submission_attempt,
                    },
                    live_coinbase_orders_ran=True,
                    failure_stage="coinbase_submission_unknown",
                )

            submission_attempt["outcome"] = "accepted_pending_readback"
            submission_attempt["exchange_order_id_confirmed"] = True
            try:
                submission_readback = exact_coinbase_order_readback(
                    deps.rest_client,
                    client_order_id=client_order_id,
                    exchange_order_id=order_id,
                    product_id=product_id,
                )
            except CoinbaseOrderReadbackError as exc:
                submission_readback = {
                    "authoritative": False,
                    "exact_identity_match": False,
                    "confirmed_absent": False,
                    "authoritative_status": None,
                    "blocker": exc.blocker,
                    "detail": exc.detail,
                }
            authoritative_status = str(
                submission_readback.get("authoritative_status") or ""
            ).upper()
            valid_exchange_statuses = {
                OrderStatus.PENDING.value,
                OrderStatus.OPEN.value,
                OrderStatus.FILLED.value,
                OrderStatus.CANCELLED.value,
                OrderStatus.EXPIRED.value,
                OrderStatus.FAILED.value,
            }
            readback_confirmed = bool(
                submission_readback.get("authoritative")
                and submission_readback.get("exact_identity_match")
                and authoritative_status in valid_exchange_statuses
            )
            submission_attempt.update(
                {
                    "authoritative_readback_confirmed": readback_confirmed,
                    "authoritative_status": authoritative_status or None,
                    "readback": submission_readback,
                }
            )
            if not readback_confirmed:
                submission_attempt["outcome"] = "unknown"
                profile_id = str(
                    (spot_portfolio_scope or {}).get("observed_portfolio_id")
                    or (spot_portfolio_scope or {}).get("portfolio_id")
                    or ""
                )
                if profile_id:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="coinbase_create_readback_unconfirmed",
                    )
                mark_submission_status = getattr(
                    root_registrar,
                    "mark_submission_status",
                    None,
                )
                if callable(mark_submission_status):
                    try:
                        mark_submission_status(
                            client_order_id=client_order_id,
                            status=OrderStatus.SUBMISSION_UNKNOWN.value,
                        )
                    except Exception as status_exc:
                        deps.add_log_entry(
                            "ERROR",
                            "Failed to persist unconfirmed Spot readback: "
                            f"{status_exc}",
                        )
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=(
                        "Coinbase create succeeded but exact authoritative "
                        "identity/status readback was not proven."
                    ),
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "submission_attempt": submission_attempt,
                    },
                    coinbase_order_id=order_id,
                    live_coinbase_orders_ran=True,
                    failure_stage="coinbase_submission_unknown",
                )

            submission_attempt["outcome"] = "accepted"
            mark_submission_status = getattr(
                root_registrar,
                "mark_submission_status",
                None,
            )
            root_status_update_error = None
            if callable(mark_submission_status):
                try:
                    mark_submission_status(
                        client_order_id=client_order_id,
                        status=authoritative_status,
                    )
                except Exception as exc:
                    root_status_update_error = f"{type(exc).__name__}: {exc}"
                    deps.add_log_entry(
                        "ERROR",
                        "Order submitted but root status update failed: "
                        f"{root_status_update_error}",
                    )
            if root_status_update_error:
                profile_id = str(
                    (spot_portfolio_scope or {}).get("observed_portfolio_id")
                    or (spot_portfolio_scope or {}).get("portfolio_id")
                    or ""
                )
                if profile_id:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="root_status_persistence_failed",
                    )
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=(
                        "Coinbase order is proven but local root status "
                        "persistence failed."
                    ),
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "root_status_update_error": root_status_update_error,
                        "submission_attempt": submission_attempt,
                    },
                    coinbase_order_id=order_id,
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="order_root_status_persistence",
                )

            try:
                submission_event_recorded = publish_direct_order_submission_event(
                    publisher_getter=lambda: (
                        submission_event_publisher
                        or deps.order_event_publisher_getter()
                    ),
                    client_order_id=client_order_id,
                    order_id=order_id,
                    order_params=order_params,
                    order_configuration=order_configuration,
                )
            except Exception as exc:
                submission_event_recorded = False
                submission_attempt["audit_persistence_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            if not submission_event_recorded:
                profile_id = str(
                    (spot_portfolio_scope or {}).get("observed_portfolio_id")
                    or (spot_portfolio_scope or {}).get("portfolio_id")
                    or ""
                )
                if profile_id:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="submission_audit_persistence_failed",
                    )
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=(
                        "Coinbase order is proven but durable owned-submission "
                        "audit persistence failed."
                    ),
                    data={
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "standing_price_limit": standing_price_limit_evidence,
                        "active_order_limit": active_order_limit_evidence,
                        "submission_attempt": submission_attempt,
                    },
                    coinbase_order_id=order_id,
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    submission_event_recorded=False,
                    failure_stage="submission_audit_persistence",
                )
            deps.add_log_entry(
                "INFO",
                f"Order created: {order_params.get('product_id')} {order_params.get('side')}",
            )
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                message="Order created",
                client_order_id=client_order_id,
                coinbase_order_id=order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                submission_event_recorded=submission_event_recorded,
                data=(
                    {
                        "portfolio_scope": spot_portfolio_scope,
                        "root_registration": root_registration,
                        "root_status_update_error": root_status_update_error,
                        "standing_price_limit": standing_price_limit_evidence,
                        "active_order_limit": active_order_limit_evidence,
                        "submission_attempt": submission_attempt,
                    }
                    if spot_portfolio_scope is not None
                    else None
                ),
                audit_command=(
                    "python tools\\run_spot_direct_order_audit.py "
                    f"--client-order-id {client_order_id}"
                ),
                **self._command_runtime_evidence(),
            )
        except CoinbaseAPIError as exc:
            deps.add_log_entry("ERROR", f"API error: {exc}")
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message=str(exc),
                failure_stage="coinbase_rest",
            )
        except Exception as exc:
            raise OrderCreationError(
                f"Failed to place order: {exc}",
                client_order_id=client_order_id,
            ) from exc
        finally:
            if profile_admission_claim is not None:
                profile_admission_claim.__exit__(None, None, None)

    def cancel_order_by_client_order_id(
        self,
        command: CancelOrderCommand,
    ) -> AdminApiCommandResponse:
        """Cancel a live order through the project ``cancel_order(client_order_id)`` wrapper."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message=(
                    "Cancel requires enterprise auth, idempotency, and rate/cap "
                    "gates before live execution."
                ),
                client_order_id=command.client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
                **self._command_runtime_evidence(),
            )

        deps = self.dependencies
        client_order_id = command.client_order_id
        if not deps.rest_client_available:
            return self._cancel_rejected(
                command=command,
                message="REST client not available",
                failure_stage="rest_client",
            )
        if not client_order_id:
            return self._cancel_rejected(
                command=command,
                message=(
                    "Missing client_order_id; pass client_order_id, not "
                    "order_id, to dashboard cancel_order."
                ),
                failure_stage="validation",
            )

        portfolio_binding = evaluate_spot_test_portfolio_binding(
            rest_client=deps.rest_client,
            expected_portfolio_id=deps.spot_portfolio_id,
            expected_portfolio_label=deps.spot_portfolio_label,
        )
        portfolio_scope = portfolio_binding.to_dict()
        if not portfolio_binding.ready:
            return self._cancel_rejected(
                command=command,
                message=(
                    "Direct Spot cancellation requires the Coinbase key to "
                    "remain bound to the approved Test portfolio."
                ),
                data={"portfolio_scope": portfolio_scope},
                failure_stage="portfolio_scope",
            )

        root_registrar = deps.order_root_registrar_getter()
        read_registered_order = getattr(
            root_registrar,
            "read_registered_order",
            None,
        )
        if not callable(read_registered_order):
            return self._cancel_rejected(
                command=command,
                message="Canonical order_parent ownership read is unavailable.",
                data={"portfolio_scope": portfolio_scope},
                failure_stage="order_ownership",
            )
        try:
            local_order = read_registered_order(client_order_id)
        except Exception as exc:
            return self._cancel_rejected(
                command=command,
                message=f"Canonical order ownership read failed: {exc}",
                data={"portfolio_scope": portfolio_scope},
                failure_stage="order_ownership",
            )
        local_order_is_admin_direct_root = bool(
            isinstance(local_order, Mapping)
            and str(local_order.get("client_order_id") or "") == client_order_id
            and str(local_order.get("retail_portfolio_id") or "")
            == str(portfolio_binding.observed_portfolio_id or "")
            and str(local_order.get("ownership_provenance") or "")
            == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            and local_order.get("parent_order_id") is None
        )
        if not local_order_is_admin_direct_root:
            return self._cancel_rejected(
                command=command,
                message=(
                    "Generic cancellation is limited to a durable Admin "
                    "manual direct root on the approved Test portfolio."
                ),
                data={
                    "portfolio_scope": portfolio_scope,
                    "required_ownership_provenance": (
                        OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                    ),
                    "root_only": True,
                },
                failure_stage="order_ownership",
            )

        canonical_cancel = getattr(deps.rest_client, "cancel_order", None)
        cancel_by_exchange_id = getattr(
            deps.rest_client,
            "cancel_order_by_exchange_order_id",
            None,
        )
        mark_submission_status = getattr(
            root_registrar,
            "mark_submission_status",
            None,
        )
        if (
            not callable(canonical_cancel)
            or not callable(cancel_by_exchange_id)
            or not callable(mark_submission_status)
        ):
            return self._cancel_rejected(
                command=command,
                message=(
                    "Canonical client-id cancel, controlled exchange-id "
                    "fallback, and terminal status persistence are required."
                ),
                data={"portfolio_scope": portfolio_scope},
                failure_stage="cancellation_readback",
            )

        profile_id = str(portfolio_binding.observed_portfolio_id or "")
        product_id = str(local_order.get("product_id") or "")
        cancellation_readback: dict[str, Any] = {
            "operator_identity_key": "client_order_id",
            "client_order_id": client_order_id,
            "canonical_cancel_attempted": False,
            "canonical_cancel_accepted": False,
            "canonical_cancel_explicitly_rejected": False,
            "fallback_attempted": False,
            "fallback_exchange_order_id": None,
            "exchange_order_id_evidence_only": True,
            "authoritative_readback": None,
            "authoritative_status": None,
            "terminal_status_proven": False,
            "confirmed_absent": False,
        }
        profile_claim = deps.spot_order_admission_coordinator.claim(profile_id)
        profile_claim.__enter__()
        try:
            controller = deps.runtime_controller_factory()
            cancellation_readback["canonical_cancel_attempted"] = True
            try:
                with controller.track_inflight(INFLIGHT_REST_CANCEL):
                    canonical_result = canonical_cancel(client_order_id)
            except Exception as exc:
                cancellation_readback["canonical_cancel_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason=f"canonical_cancel_exception:{type(exc).__name__}",
                )
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Canonical client_order_id cancellation outcome is "
                        "unknown; exchange-id fallback is forbidden."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_unknown",
                )
            if not isinstance(canonical_result, bool):
                cancellation_readback["canonical_cancel_result_type"] = type(
                    canonical_result
                ).__name__
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason="canonical_cancel_result_unknown",
                )
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Canonical client_order_id cancellation returned no "
                        "explicit outcome; exchange-id fallback is forbidden."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_unknown",
                )
            cancellation_readback["canonical_cancel_accepted"] = canonical_result
            cancellation_readback[
                "canonical_cancel_explicitly_rejected"
            ] = not canonical_result

            try:
                readback = exact_coinbase_order_readback(
                    deps.rest_client,
                    client_order_id=client_order_id,
                    product_id=product_id or None,
                )
            except CoinbaseOrderReadbackError as exc:
                cancellation_readback["authoritative_readback"] = {
                    "authoritative": False,
                    "blocker": exc.blocker,
                    "detail": exc.detail,
                }
                if canonical_result:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="canonical_cancel_readback_unconfirmed",
                    )
                return self._cancel_rejected(
                    command=command,
                    message="Authoritative cancellation readback failed closed.",
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_readback",
                )

            cancellation_readback["authoritative_readback"] = readback
            cancellation_readback["confirmed_absent"] = bool(
                readback.get("confirmed_absent")
            )
            authoritative_status = str(
                readback.get("authoritative_status") or ""
            ).upper()
            cancellation_readback["authoritative_status"] = (
                authoritative_status or None
            )
            terminal_statuses = {
                OrderStatus.CANCELLED.value,
                OrderStatus.FILLED.value,
                OrderStatus.EXPIRED.value,
                OrderStatus.FAILED.value,
            }
            terminal_status_proven = bool(
                readback.get("authoritative")
                and readback.get("exact_identity_match")
                and authoritative_status in terminal_statuses
            )
            cancellation_readback[
                "terminal_status_proven"
            ] = terminal_status_proven

            if terminal_status_proven:
                try:
                    mark_submission_status(
                        client_order_id=client_order_id,
                        status=authoritative_status,
                    )
                except Exception as exc:
                    deps.spot_order_admission_coordinator.record_uncertainty(
                        retail_portfolio_id=profile_id,
                        client_order_id=client_order_id,
                        reason="cancel_terminal_status_persistence_failed",
                    )
                    cancellation_readback["terminal_status_persistence_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    return self._cancel_rejected(
                        command=command,
                        message=(
                            "Coinbase terminal status is proven but local "
                            "status persistence failed."
                        ),
                        data={
                            "portfolio_scope": portfolio_scope,
                            "cancellation_readback": cancellation_readback,
                        },
                        live_exchange_submitted=True,
                        live_coinbase_orders_ran=True,
                        failure_stage="cancellation_status_persistence",
                    )
                deps.spot_order_admission_coordinator.resolve_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                )
                if authoritative_status != OrderStatus.CANCELLED.value:
                    return self._cancel_rejected(
                        command=command,
                        message=(
                            "The order reached a non-cancel terminal status "
                            f"({authoritative_status}) before cancellation."
                        ),
                        data={
                            "portfolio_scope": portfolio_scope,
                            "cancellation_readback": cancellation_readback,
                        },
                        live_exchange_submitted=True,
                        live_coinbase_orders_ran=True,
                        failure_stage="cancellation_terminal_status",
                    )
                return AdminApiCommandResponse(
                    status=AdminApiCommandStatus.ACCEPTED,
                    action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                    required_permission=AdminApiPermission.ORDER_CANCEL,
                    service_method="cancel_order_by_client_order_id",
                    message="Order cancellation confirmed by terminal readback",
                    client_order_id=client_order_id,
                    correlation_id=command.envelope.correlation_id,
                    idempotency_key=command.envelope.idempotency_key,
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    **self._command_runtime_evidence(),
                )

            if canonical_result:
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason="canonical_cancel_terminal_status_unconfirmed",
                )
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Canonical cancellation was accepted but exact terminal "
                        "status proof is missing; absence is not cancellation."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_readback",
                )

            if not readback.get("exact_identity_match"):
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Client-id cancellation was explicitly rejected and "
                        "no exact exchange identity was proven for fallback."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_readback",
                )
            exchange_order_id = str(readback.get("exchange_order_id") or "")
            if not exchange_order_id:
                return self._cancel_rejected(
                    command=command,
                    message="Exact fallback readback lacked exchange order identity.",
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_readback",
                )

            cancellation_readback["fallback_attempted"] = True
            cancellation_readback[
                "fallback_exchange_order_id"
            ] = exchange_order_id
            try:
                with controller.track_inflight(INFLIGHT_REST_CANCEL):
                    fallback_result = cancel_by_exchange_id(exchange_order_id)
            except Exception as exc:
                cancellation_readback["fallback_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason=f"exchange_id_cancel_exception:{type(exc).__name__}",
                )
                return self._cancel_rejected(
                    command=command,
                    message="Controlled exchange-id fallback outcome is unknown.",
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_unknown",
                )
            cancellation_readback["fallback_accepted"] = fallback_result is True
            if fallback_result is not True:
                return self._cancel_rejected(
                    command=command,
                    message="Controlled exchange-id fallback was not accepted.",
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_rejected",
                )

            try:
                terminal_readback = exact_coinbase_order_readback(
                    deps.rest_client,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    product_id=product_id or None,
                )
            except CoinbaseOrderReadbackError as exc:
                terminal_readback = {
                    "authoritative": False,
                    "exact_identity_match": False,
                    "confirmed_absent": False,
                    "authoritative_status": None,
                    "blocker": exc.blocker,
                    "detail": exc.detail,
                }
            cancellation_readback["authoritative_readback"] = terminal_readback
            cancellation_readback["confirmed_absent"] = bool(
                terminal_readback.get("confirmed_absent")
            )
            authoritative_status = str(
                terminal_readback.get("authoritative_status") or ""
            ).upper()
            cancellation_readback["authoritative_status"] = (
                authoritative_status or None
            )
            terminal_status_proven = bool(
                terminal_readback.get("authoritative")
                and terminal_readback.get("exact_identity_match")
                and authoritative_status in terminal_statuses
            )
            cancellation_readback[
                "terminal_status_proven"
            ] = terminal_status_proven
            if not terminal_status_proven:
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason="fallback_cancel_terminal_status_unconfirmed",
                )
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Exchange-id fallback was accepted but exact terminal "
                        "status proof is missing; absence is not cancellation."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_readback",
                )

            try:
                mark_submission_status(
                    client_order_id=client_order_id,
                    status=authoritative_status,
                )
            except Exception as exc:
                deps.spot_order_admission_coordinator.record_uncertainty(
                    retail_portfolio_id=profile_id,
                    client_order_id=client_order_id,
                    reason="cancel_terminal_status_persistence_failed",
                )
                cancellation_readback["terminal_status_persistence_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Coinbase terminal status is proven but local status "
                        "persistence failed."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_status_persistence",
                )
            deps.spot_order_admission_coordinator.resolve_uncertainty(
                retail_portfolio_id=profile_id,
                client_order_id=client_order_id,
            )
            if authoritative_status != OrderStatus.CANCELLED.value:
                return self._cancel_rejected(
                    command=command,
                    message=(
                        "Fallback completed with a non-cancel terminal status "
                        f"({authoritative_status})."
                    ),
                    data={
                        "portfolio_scope": portfolio_scope,
                        "cancellation_readback": cancellation_readback,
                    },
                    live_exchange_submitted=True,
                    live_coinbase_orders_ran=True,
                    failure_stage="cancellation_terminal_status",
                )

            deps.add_log_entry("INFO", f"Order cancelled: client_order_id={client_order_id}")
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                message="Order cancelled",
                client_order_id=client_order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                data={
                    "portfolio_scope": portfolio_scope,
                    "cancellation_readback": cancellation_readback,
                },
                **self._command_runtime_evidence(),
            )
        finally:
            profile_claim.__exit__(None, None, None)

    def cancel_stealth_order_by_stealth_order_id(
        self,
        command: StealthCancelCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a stealth lifecycle cancel command through the live gate.

        This contract is keyed by ``stealth_order_id``. Active placement client
        ids and Coinbase order ids remain evidence only until the stealth
        lifecycle path owns the exchange handling and local-state reconciliation.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_stealth_order_by_stealth_order_id",
            message=(
                "Stealth cancel requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, and exchange-reality reconciliation "
                "before live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "identity_key": "stealth_order_id",
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
            },
            failure_stage="approval",
        )

    def create_stealth_order(
        self,
        command: StealthCreateCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a route-bound stealth create command through fail-closed gates.

        The Admin API create contract is intentionally not wired to
        ``StealthOrderManager.create_stealth_order`` yet. Future enablement must
        pass backend-owned planning guards, audit, cap/guard, reconciliation,
        and lifecycle-write review before it can create local hidden state.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        request = command.request
        execution_contract = build_stealth_create_lifecycle_write_execution_contract(
            stealth_order_id=request.stealth_order_id,
            exact_command_context_present=True,
            admission_decision=command.admission_decision,
            lifecycle_write_guard_proof_store=(
                self.dependencies.stealth_lifecycle_write_guard_proof_store_getter()
            ),
            manager_policy_proof_store=(
                self.dependencies.stealth_manager_policy_proof_store_getter()
            ),
            coinbase_exchange_policy_proof_store=(
                self.dependencies.stealth_coinbase_exchange_policy_proof_store_getter()
            ),
            post_write_reconciliation_policy_proof_store=(
                self.dependencies.stealth_post_write_reconciliation_policy_proof_store_getter()
            ),
            state_mutation_policy_proof_store=(
                self.dependencies.stealth_state_mutation_policy_proof_store_getter()
            ),
            post_write_reconciliation_proof_store=(
                self.dependencies.stealth_post_write_reconciliation_proof_store_getter()
            ),
            post_write_execution_journal_store=(
                self.dependencies.stealth_post_write_execution_journal_store_getter()
            ),
            post_write_reconciliation_verification_store=(
                self.dependencies.stealth_post_write_reconciliation_verification_store_getter()
            ),
        )
        pre_execution_contract = build_stealth_create_pre_execution_contract(
            command_envelope=command.envelope,
            request=request,
            exact_command_context_present=True,
        )
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="create_stealth_order",
            message=(
                "Stealth create requires enterprise auth, idempotency, audit, "
                "approval, cap/guard planning checks, lifecycle-write review, "
                "and reconciliation planning before local stealth state can be "
                "created through the Admin API."
            ),
            stealth_order_id=request.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            selected_create_pre_execution_contract=pre_execution_contract,
            stealth_lifecycle_execution_contract=execution_contract,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": request.stealth_order_id,
                "identity_key": "stealth_order_id",
                "selected_create_pre_execution_contract_available": (
                    pre_execution_contract is not None
                ),
                "selected_create_pre_execution_contract_exact_context": (
                    pre_execution_contract.exact_command_context_present
                    if pre_execution_contract is not None
                    else False
                ),
                "execution_contract_available": (
                    execution_contract.execution_contract_available
                ),
                "execution_allowed": execution_contract.execution_allowed,
                "execution_contract_blockers": execution_contract.blockers,
                "resolved_execution_prerequisites": (
                    execution_contract.resolved_prerequisites
                ),
                "missing_execution_prerequisites": (
                    execution_contract.missing_prerequisites
                ),
                "product_id": request.product_id,
                "side": request.side.value if isinstance(request.side, OrderSide) else str(request.side),
                "total_size": request.total_size,
                "limit_price": request.limit_price,
                "reveal_condition": request.reveal_condition,
                "sizing_strategy": request.sizing_strategy,
                "parent_order_id": request.parent_order_id,
                "target_movement": request.target_movement,
                "target_movement_type": (
                    request.target_movement_type.value
                    if hasattr(request.target_movement_type, "value")
                    else str(request.target_movement_type)
                ),
                "manual_live_acknowledgement": request.manual_live_acknowledgement,
                "stealth_manager_invoked": False,
                "local_state_mutated": False,
                "coinbase_order_submitted": False,
                "exchange_order_id_evidence_only": True,
            },
            failure_stage="approval",
        )

    def reveal_stealth_order_by_stealth_order_id(
        self,
        command: StealthRevealCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a route-bound stealth reveal command through fail-closed gates.

        Reveal is exchange-placement shaped, but this Admin API contract is not
        wired to ``StealthOrderManager.reveal_order_slice`` yet. Future live
        enablement must prove trigger evidence, approval, cap/guard, audit,
        active-placement handling, and reconciliation before any Coinbase order
        placement or local lifecycle mutation can occur.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="reveal_stealth_order_by_stealth_order_id",
            message=(
                "Stealth reveal requires enterprise auth, idempotency, audit, "
                "approval, trigger evidence, cap/guard checks, exchange "
                "placement handling, and reconciliation before live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "identity_key": "stealth_order_id",
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "requires_trigger_evidence": True,
                "reveal_order_slice_invoked": False,
                "stealth_manager_invoked": False,
                "local_state_mutated": False,
                "coinbase_order_submitted": False,
            },
            failure_stage="approval",
        )

    def move_stealth_order_by_stealth_order_id(
        self,
        command: StealthMoveCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a route-bound stealth move command through fail-closed gates.

        Move-revealed is cancel/replace-shaped. The Admin API contract is not
        wired to ``build_stealth_move_plan`` or ``execute_stealth_move`` yet.
        Future live enablement must prove mutation-claim, active-placement
        cancel/replace, audit, cap/guard, and reconciliation evidence before
        any local lifecycle state changes.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="move_stealth_order_by_stealth_order_id",
            message=(
                "Stealth move requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, mutation-claim coordination, active "
                "placement cancel/replace handling, and reconciliation before "
                "live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "new_limit_price": command.request.new_limit_price,
                "reason": command.request.reason,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "identity_key": "stealth_order_id",
                "mutation_kind": StealthMutationKind.MOVE.value,
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "build_stealth_move_plan_invoked": False,
                "execute_stealth_move_invoked": False,
                "stealth_manager_invoked": False,
                "cancel_replace_submitted": False,
                "local_state_mutated": False,
                "coinbase_order_submitted": False,
            },
            failure_stage="approval",
        )

    def recover_stealth_order_by_stealth_order_id(
        self,
        command: StealthRecoveryCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a route-bound stealth recovery command fail-closed.

        Future recovery work may add a separate repair implementation, but this
        contract is evidence-only today. It is not wired to any repair,
        rollback, manager, Coinbase, or reconciliation path.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECOVERY_EXECUTE,
            service_method="recover_stealth_order_by_stealth_order_id",
            message=(
                "Stealth recovery requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, active-placement exchange truth, "
                "repair/rollback contracts, and reconciliation before any "
                "recovery action can execute."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "recovery_evidence_ref": command.request.recovery_evidence_ref,
                "dry_run": command.request.dry_run,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "identity_key": "stealth_order_id",
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "stealth_manager_invoked": False,
                "recovery_repair_executed": False,
                "rollback_executed": False,
                "local_state_mutated": False,
                "exchange_state_mutated": False,
                "reconciliation_executed": False,
                "coinbase_rest_read_ran": False,
                "coinbase_order_submitted": False,
            },
            failure_stage="approval",
        )

    def reconcile_stealth_order_by_stealth_order_id(
        self,
        command: StealthReconciliationCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a route-bound stealth reconciliation command fail-closed."""

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECONCILIATION_EXECUTE,
            service_method="reconcile_stealth_order_by_stealth_order_id",
            message=(
                "Stealth reconciliation requires enterprise auth, idempotency, "
                "audit, approval, cap/rate gates, reconciliation plan/proof "
                "contracts, active-placement exchange truth, and lifecycle "
                "repair policy before execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "reconciliation_plan_id": command.request.reconciliation_plan_id,
                "reconciliation_proof_id": command.request.reconciliation_proof_id,
                "dry_run": command.request.dry_run,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "identity_key": "stealth_order_id",
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "reconciliation_plan_resolved": False,
                "reconciliation_proof_resolved": False,
                "stealth_manager_invoked": False,
                "local_state_mutated": False,
                "exchange_state_mutated": False,
                "reconciliation_executed": False,
                "coinbase_rest_read_ran": False,
                "coinbase_order_submitted": False,
            },
            failure_stage="approval",
        )

    def reprice_stealth_order_by_stealth_order_id(
        self,
        command: MovementRepriceCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a stealth reprice command through the live-disabled gate.

        This Admin API contract is keyed by ``stealth_order_id`` and does not
        invoke the live dashboard repricer. Future live enablement must enter
        through the existing cancel/reprice/reconcile path so revealed exchange
        placements and local stealth state stay in sync.
        """

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="reprice_stealth_order_by_stealth_order_id",
            message=(
                "Stealth reprice requires enterprise auth, idempotency, audit, "
                "approval, cap/rate gates, mutation-claim coordination, and "
                "exchange-reality reconciliation before live execution."
            ),
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "stealth_order_id": command.stealth_order_id,
                "reason": command.request.reason,
                "identity_key": "stealth_order_id",
                "mutation_kind": StealthMutationKind.REPRICE.value,
                "active_placement_client_order_id": None,
                "exchange_order_id_evidence_only": True,
                "cooldown_cleared": False,
                "stealth_manager_invoked": False,
            },
            failure_stage="approval",
        )

    def execute_spot_campaign(
        self,
        command: CampaignExecutionCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a future spot campaign execution command through the live gate."""

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
            service_method="execute_spot_campaign",
            message=(
                "Spot campaign execution requires enterprise auth, "
                "idempotency, approval, caps, and campaign safety gates before "
                "live execution."
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "campaign_id": command.request.campaign_id,
                "side": command.request.side.value,
                "dry_run": command.request.dry_run,
                "product_count": len(command.request.product_ids or []),
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
            },
            failure_stage="approval",
        )

    def run_spot_sweep_automation(
        self,
        command: SpotSweepAutomationRunCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a future spot sweep automation run through the live gate."""

        gate = evaluate_live_execution_gate(allow_live_execution=False)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
            service_method="run_spot_sweep_automation",
            message=(
                "Spot sweep automation requires enterprise scheduling, "
                "idempotency, approval, caps, run-limit, recovery, and "
                "reconciliation gates before live execution."
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            guard=gate.model_dump(),
            data={
                "sweep_config_id": command.request.sweep_config_id,
                "side": command.request.side.value,
                "dry_run": command.request.dry_run,
                "run_if_due": command.request.run_if_due,
                "max_runs": command.request.max_runs,
                "max_products": command.request.max_products,
                "max_planned_orders": command.request.max_planned_orders,
                "repeat_every_hours": command.request.repeat_every_hours,
                "quote_notional_per_product": (
                    command.request.quote_notional_per_product
                ),
                "max_total_notional_per_run": (
                    command.request.max_total_notional_per_run
                ),
                "max_notional_per_order": command.request.max_notional_per_order,
                "manual_live_acknowledgement": (
                    command.request.manual_live_acknowledgement
                ),
                "sweep_runner_invoked": False,
            },
            failure_stage="approval",
        )

    def _disabled_futures_command_response(
        self,
        *,
        command: (
            FuturesPlaceOrderCommand
            | FuturesCloseReduceCommand
            | FuturesCancelOrderCommand
            | FuturesReconciliationCommand
        ),
        service_method: str,
        action_class: AdminApiActionClass,
        required_permission: AdminApiPermission,
        message: str,
        identity_key: str,
        identity_value: str,
        command_name: str,
        data: dict[str, Any],
    ) -> AdminApiCommandResponse:
        gate = evaluate_live_execution_gate(allow_live_execution=False)
        request = command.request
        data.update(
            {
                "command": command_name,
                "identity_key": identity_key,
                "identity_value": identity_value,
                "approval_snapshot_id": request.approval_snapshot_id,
                "admission_audit_id": request.admission_audit_id,
                "cap_guard_decision_id": request.cap_guard_decision_id,
                "reconciliation_plan_id": request.reconciliation_plan_id,
                "dry_run": request.dry_run,
                "operator_reason": request.operator_reason,
                "manual_live_acknowledgement": (
                    request.manual_live_acknowledgement
                ),
                "coinbase_order_submitted": False,
                "coinbase_cancel_submitted": False,
                "reconciliation_executed": False,
                "futures_state_mutated": False,
                "order_state_mutated": False,
                "exchange_state_mutated": False,
                "live_adapter_invoked": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "spot_rule_authority": False,
            }
        )
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=action_class,
            required_permission=required_permission,
            service_method=service_method,
            message=message,
            client_order_id=(
                identity_value if identity_key == "client_order_id" else None
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            admission_decision=command.admission_decision,
            guard=gate.model_dump(),
            data=data,
            failure_stage="approval",
        )

    def place_futures_order(
        self,
        command: FuturesPlaceOrderCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a disabled futures/perpetual placement draft."""

        request = command.request
        return self._disabled_futures_command_response(
            command=command,
            service_method="place_futures_order",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            message=(
                "Futures/perpetual placement command drafts are route-bound "
                "but live-disabled until backend approval, cap/guard, "
                "admission audit, reconciliation, and adapter gates pass."
            ),
            identity_key="product_id",
            identity_value=request.product_id,
            command_name="futures_place",
            data={
                "product_id": request.product_id,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "size": request.size,
                "limit_price": request.limit_price,
                "time_in_force": (
                    request.time_in_force.value
                    if request.time_in_force is not None
                    else None
                ),
                "reduce_only": request.reduce_only,
                "close_only": request.close_only,
            },
        )

    def close_or_reduce_futures_position(
        self,
        command: FuturesCloseReduceCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a disabled futures/perpetual close/reduce draft."""

        request = command.request
        return self._disabled_futures_command_response(
            command=command,
            service_method="close_or_reduce_futures_position",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            message=(
                "Futures/perpetual close/reduce command drafts are "
                "route-bound but live-disabled until backend position, "
                "reduce-only/close-only, approval, cap/guard, audit, "
                "reconciliation, and adapter gates pass."
            ),
            identity_key="position_key",
            identity_value=command.position_key,
            command_name="futures_close_reduce",
            data={
                "position_key": command.position_key,
                "order_type": request.order_type.value,
                "size": request.size,
                "limit_price": request.limit_price,
                "time_in_force": (
                    request.time_in_force.value
                    if request.time_in_force is not None
                    else None
                ),
                "reduce_only": request.reduce_only,
                "close_only": request.close_only,
                "expected_position_state": request.expected_position_state,
            },
        )

    def cancel_futures_order(
        self,
        command: FuturesCancelOrderCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a disabled futures/perpetual cancel draft."""

        request = command.request
        return self._disabled_futures_command_response(
            command=command,
            service_method="cancel_futures_order",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            message=(
                "Futures/perpetual cancel command drafts are route-bound "
                "by client_order_id but live-disabled until backend approval, "
                "cap/guard, audit, reconciliation, and adapter gates pass."
            ),
            identity_key="client_order_id",
            identity_value=command.client_order_id,
            command_name="futures_cancel",
            data={
                "client_order_id": command.client_order_id,
                "product_id": request.product_id,
            },
        )

    def reconcile_futures_position(
        self,
        command: FuturesReconciliationCommand,
    ) -> AdminApiCommandResponse:
        """Evaluate a disabled futures/perpetual reconciliation draft."""

        request = command.request
        return self._disabled_futures_command_response(
            command=command,
            service_method="reconcile_futures_position",
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            message=(
                "Futures/perpetual reconciliation command drafts are "
                "route-bound but live-disabled until backend reconciliation "
                "proof, approval, cap/guard, audit, and adapter gates pass."
            ),
            identity_key="position_key",
            identity_value=command.position_key,
            command_name="futures_reconcile",
            data={
                "position_key": command.position_key,
                "reconciliation_reason": request.reconciliation_reason,
                "expected_position_state": request.expected_position_state,
            },
        )

    def _disabled_spot_recovery_response(
        self,
        *,
        service_method: str,
        mutation_family: AdminApiMutationFamilyType,
        command: (
            SpotRecoveryApplyExecutionCommand
            | SpotRecoveryRollbackExecutionCommand
            | SpotRecoveryExchangeStateProofCommand
            | SpotRecoveryExchangeStateSnapshotCommand
            | SpotRecoveryReconciliationExecutionCommand
            | SpotRecoveryReconciliationProofRecordCommand
        ),
        message: str,
        flags: dict[str, bool],
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": mutation_family.value,
            "client_order_id": request.client_order_id,
            "rollback_plan_id": getattr(request, "rollback_plan_id", None),
            "product_id": getattr(request, "product_id", None),
            "exchange_state_snapshot_id": getattr(
                request,
                "exchange_state_snapshot_id",
                None,
            ),
            "source_timestamp": getattr(request, "source_timestamp", None),
            "snapshot_source": getattr(request, "snapshot_source", None),
            "snapshot_evidence_ref": getattr(
                request,
                "snapshot_evidence_ref",
                None,
            ),
            "recovery_apply_audit_id": getattr(
                request,
                "recovery_apply_audit_id",
                None,
            ),
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "reconciliation_proof_id": getattr(
                request,
                "reconciliation_proof_id",
                None,
            ),
            "completion_id": getattr(request, "completion_id", None),
            "exchange_state_proof_id": getattr(
                request,
                "exchange_state_proof_id",
                None,
            ),
            "exchange_state_evidence_ref": getattr(
                request,
                "exchange_state_evidence_ref",
                None,
            ),
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "execution_journal_accepted": False,
            "recovery_apply_journal_accepted": False,
            "rollback_journal_accepted": False,
            "recovery_apply_executed": False,
            "rollback_executed": False,
            "exchange_state_proof_recorded": False,
            "reconciliation_proof_recorded": False,
            "reconciliation_executed": False,
            "reconciliation_execution_route_bound": False,
            "reconciliation_execution_service_available": False,
            "reconciliation_execution_contract_available": False,
            "coinbase_evidence_snapshot_contract_available": True,
            "snapshot_recorded": False,
            "source_trusted": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_order_submitted": False,
            "coinbase_rest_read_ran": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "proof_persisted": False,
            "repair_journal_persisted": False,
            "repair_intent_accepted": False,
            "state_repair_executed": False,
            "post_apply_reconciliation_required": True,
            "post_apply_reconciliation_satisfied": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        data.update(flags)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
            service_method=service_method,
            message=message,
            client_order_id=request.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="execution_prerequisite",
        )

    def execute_spot_recovery_reconciliation(
        self,
        command: SpotRecoveryReconciliationExecutionCommand,
    ) -> AdminApiCommandResponse:
        """Reject route-bound Spot recovery reconciliation execution for now."""

        return self._disabled_spot_recovery_response(
            service_method="execute_spot_recovery_reconciliation",
            mutation_family=(
                AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION
            ),
            command=command,
            message=(
                "Spot recovery reconciliation execution is route-bound but "
                "the backend reconciliation executor and live Coinbase read "
                "authority are disabled."
            ),
            flags={
                "completion_id": command.request.completion_id,
                "reconciliation_proof_id": command.request.reconciliation_proof_id,
                "reconciliation_executed": False,
                "reconciliation_execution_route_bound": True,
                "reconciliation_execution_service_available": False,
                "reconciliation_execution_contract_available": False,
                "coinbase_evidence_snapshot_contract_available": True,
                "order_state_mutated": False,
                "exchange_state_mutated": False,
                "coinbase_rest_read_ran": False,
                "coinbase_order_submitted": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
            },
        )

    def _rejected_spot_recovery_proof_response(
        self,
        *,
        service_method: str,
        mutation_family: AdminApiMutationFamilyType,
        command: (
            SpotRecoveryExchangeStateProofCommand
            | SpotRecoveryExchangeStateSnapshotCommand
            | SpotRecoveryReconciliationProofRecordCommand
        ),
        message: str,
        flags: dict[str, bool],
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": mutation_family.value,
            "client_order_id": request.client_order_id,
            "exchange_state_proof_id": getattr(
                request,
                "exchange_state_proof_id",
                None,
            ),
            "reconciliation_proof_id": getattr(
                request,
                "reconciliation_proof_id",
                None,
            ),
            "recovery_apply_audit_id": getattr(
                request,
                "recovery_apply_audit_id",
                None,
            ),
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "exchange_state_evidence_ref": getattr(
                request,
                "exchange_state_evidence_ref",
                None,
            ),
            "product_id": getattr(request, "product_id", None),
            "exchange_state_snapshot_id": getattr(
                request,
                "exchange_state_snapshot_id",
                None,
            ),
            "source_timestamp": getattr(request, "source_timestamp", None),
            "snapshot_source": getattr(request, "snapshot_source", None),
            "snapshot_evidence_ref": getattr(
                request,
                "snapshot_evidence_ref",
                None,
            ),
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "recovery_apply_executed": False,
            "rollback_executed": False,
            "exchange_state_proof_recorded": False,
            "snapshot_recorded": False,
            "source_trusted": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "reconciliation_proof_recorded": False,
            "reconciliation_executed": False,
            "coinbase_order_submitted": False,
            "coinbase_rest_read_ran": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "proof_persisted": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        data.update(flags)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
            service_method=service_method,
            message=message,
            client_order_id=request.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def _rejected_stealth_exchange_truth_response(
        self,
        *,
        service_method: str,
        mutation_family: AdminApiMutationFamilyType,
        command: (
            StealthActivePlacementExchangeTruthSnapshotCommand
            | StealthActivePlacementExchangeTruthProofCommand
        ),
        message: str,
        flags: dict[str, bool],
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": mutation_family.value,
            "stealth_order_id": command.stealth_order_id,
            "exchange_truth_snapshot_id": getattr(
                request,
                "exchange_truth_snapshot_id",
                None,
            ),
            "exchange_truth_proof_id": getattr(
                request,
                "exchange_truth_proof_id",
                None,
            ),
            "active_placement_client_order_id": (
                request.active_placement_client_order_id
            ),
            "active_exchange_order_id": request.active_exchange_order_id,
            "exchange_truth_evidence_ref": getattr(
                request,
                "exchange_truth_evidence_ref",
                None,
            ),
            "snapshot_evidence_ref": getattr(request, "snapshot_evidence_ref", None),
            "product_id": getattr(request, "product_id", None),
            "source_timestamp": getattr(request, "source_timestamp", None),
            "evidence_source": getattr(request, "evidence_source", None),
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "snapshot_recorded": False,
            "proof_persisted": False,
            "exchange_truth_verified": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        data.update(flags)
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
            service_method=service_method,
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_active_placement_exchange_truth_snapshot(
        self,
        command: StealthActivePlacementExchangeTruthSnapshotCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned active-placement snapshot evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_exchange_truth_response(
                service_method="record_stealth_active_placement_exchange_truth_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_SNAPSHOT
                ),
                command=command,
                message="Stealth exchange-truth snapshot admission evidence is missing.",
                flags={
                    "snapshot_recorded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_exchange_truth_service.record_snapshot(
                snapshot_store=deps.stealth_exchange_truth_snapshot_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthExchangeTruthError as exc:
            return self._rejected_stealth_exchange_truth_response(
                service_method="record_stealth_active_placement_exchange_truth_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_SNAPSHOT
                ),
                command=command,
                message=str(exc),
                flags={
                    "snapshot_recorded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
            service_method="record_stealth_active_placement_exchange_truth_snapshot",
            message=(
                "Stealth active-placement exchange-truth snapshot recorded; "
                "Coinbase was not read and no order, lifecycle, or exchange "
                "state was mutated."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_exchange_truth_snapshot_response_data(record),
        )

    def record_stealth_active_placement_exchange_truth_proof(
        self,
        command: StealthActivePlacementExchangeTruthProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned active-placement proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_exchange_truth_response(
                service_method="record_stealth_active_placement_exchange_truth_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_PROOF
                ),
                command=command,
                message="Stealth exchange-truth proof admission evidence is missing.",
                flags={
                    "proof_persisted": False,
                    "coinbase_rest_read_ran": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_exchange_truth_service.record_proof(
                snapshot_store=deps.stealth_exchange_truth_snapshot_store_getter(),
                proof_store=deps.stealth_exchange_truth_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthExchangeTruthError as exc:
            return self._rejected_stealth_exchange_truth_response(
                service_method="record_stealth_active_placement_exchange_truth_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_PROOF
                ),
                command=command,
                message=str(exc),
                flags={
                    "proof_persisted": False,
                    "coinbase_rest_read_ran": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
            service_method="record_stealth_active_placement_exchange_truth_proof",
            message=(
                "Stealth active-placement exchange-truth proof recorded as "
                "evidence only; it does not verify Coinbase state or execute "
                "reconciliation."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_exchange_truth_proof_response_data(record),
        )

    def _rejected_stealth_lifecycle_write_guard_response(
        self,
        *,
        command: StealthCreateLifecycleWriteGuardProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_CREATE_LIFECYCLE_WRITE_GUARD_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "lifecycle_write_guard_proof_id": (
                request.lifecycle_write_guard_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "product_id": request.product_id,
            "side": request.side.value,
            "total_size": request.total_size,
            "limit_price": request.limit_price,
            "evidence_source": request.evidence_source.value,
            "guard_evidence_ref": request.guard_evidence_ref,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "lifecycle_write_guard_verified": False,
            "manager_invocation_ran": False,
            "stealth_row_write_ran": False,
            "order_parent_write_ran": False,
            "lifecycle_event_dispatch_ran": False,
            "local_lifecycle_mutation_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD,
            service_method="record_stealth_create_lifecycle_write_guard_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_create_lifecycle_write_guard_proof(
        self,
        command: StealthCreateLifecycleWriteGuardProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth create lifecycle-write guard evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_lifecycle_write_guard_response(
                command=command,
                message=(
                    "Stealth lifecycle-write guard proof admission evidence is "
                    "missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_lifecycle_write_guard_service.record_proof(
                proof_store=(
                    deps.stealth_lifecycle_write_guard_proof_store_getter()
                ),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthLifecycleWriteGuardError as exc:
            return self._rejected_stealth_lifecycle_write_guard_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD,
            service_method="record_stealth_create_lifecycle_write_guard_proof",
            message=(
                "Stealth lifecycle-write guard proof recorded as evidence only; "
                "the create lifecycle was not written and Coinbase was not called."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_lifecycle_write_guard_proof_response_data(record),
        )

    def _rejected_stealth_mutation_claim_proof_response(
        self,
        *,
        command: StealthMutationClaimSnapshotProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_MUTATION_CLAIM_SNAPSHOT_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "mutation_claim_proof_id": request.mutation_claim_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "mutation_kind": request.mutation_kind.value,
            "claim_reader_source": request.claim_reader_source,
            "runtime_claims_observed": request.runtime_claims_observed,
            "runtime_claim_count": request.runtime_claim_count,
            "active_claim_count": request.active_claim_count,
            "evidence_source": request.evidence_source.value,
            "snapshot_evidence_ref": request.snapshot_evidence_ref,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "mutation_claim_snapshot_verified": False,
            "manager_invocation_ran": False,
            "claim_acquire_ran": False,
            "claim_release_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD,
            service_method="record_stealth_mutation_claim_snapshot_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_mutation_claim_snapshot_proof(
        self,
        command: StealthMutationClaimSnapshotProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth mutation-claim snapshot proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_mutation_claim_proof_response(
                command=command,
                message="Stealth mutation-claim proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_mutation_claim_proof_service.record_proof(
                proof_store=deps.stealth_mutation_claim_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthMutationClaimProofError as exc:
            return self._rejected_stealth_mutation_claim_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD,
            service_method="record_stealth_mutation_claim_snapshot_proof",
            message=(
                "Stealth mutation-claim snapshot proof recorded as evidence "
                "only; no claim was acquired or released and Coinbase was not called."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_mutation_claim_proof_response_data(record),
        )

    def _rejected_futures_risk_proof_response(
        self,
        *,
        command: FuturesRiskProofRecordCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": AdminApiMutationFamilyType.FUTURES_RISK_PROOF.value,
            "futures_risk_proof_id": request.futures_risk_proof_id,
            "command": request.command.value,
            "proof_kind": request.proof_kind.value,
            "proof_contract_ref": request.proof_contract_ref,
            "evidence_ref": request.evidence_ref,
            "evidence_source": request.evidence_source.value,
            "risk_evidence_refs": request.risk_evidence_refs,
            "product_id": request.product_id,
            "position_key": request.position_key,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "risk_proof_verified": False,
            "risk_proof_accepted": False,
            "command_route_registered": False,
            "command_draft_created": False,
            "command_execution_allowed": False,
            "margin_validated": False,
            "collateral_validated": False,
            "liquidation_validated": False,
            "funding_validated": False,
            "reduce_only_validated": False,
            "close_only_validated": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
            service_method="record_futures_risk_proof",
            message=message,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_futures_risk_proof(
        self,
        command: FuturesRiskProofRecordCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned futures/perpetual risk proof evidence."""

        if command.admission_decision is None:
            return self._rejected_futures_risk_proof_response(
                command=command,
                message="Futures risk proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.futures_risk_proof_service.record_proof(
                proof_store=deps.futures_risk_proof_store_getter(),
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except FuturesRiskProofError as exc:
            return self._rejected_futures_risk_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
            service_method="record_futures_risk_proof",
            message=(
                "Futures risk proof recorded as append-only evidence only; "
                "no futures command route, draft, validation acceptance, "
                "reconciliation execution, state mutation, or Coinbase "
                "activity ran."
            ),
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_futures_risk_proof_response_data(record),
        )

    def _rejected_stealth_recovery_proof_response(
        self,
        *,
        command: StealthRecoveryProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": AdminApiMutationFamilyType.STEALTH_RECOVERY_PROOF.value,
            "stealth_order_id": command.stealth_order_id,
            "recovery_proof_id": request.recovery_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "recovery_evidence_ref": request.recovery_evidence_ref,
            "recovery_plan_ref": request.recovery_plan_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "recovery_proof_verified": False,
            "manager_invocation_ran": False,
            "recovery_plan_built": False,
            "recovery_repair_executed": False,
            "rollback_executed": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECOVERY_RECORD,
            service_method="record_stealth_recovery_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def _rejected_stealth_reveal_trigger_proof_response(
        self,
        *,
        command: StealthRevealTriggerProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_REVEAL_TRIGGER_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "reveal_trigger_proof_id": request.reveal_trigger_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "reveal_condition_ref": request.reveal_condition_ref,
            "trigger_evidence_ref": request.trigger_evidence_ref,
            "condition_snapshot_ref": request.condition_snapshot_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "reveal_trigger_verified": False,
            "manager_invocation_ran": False,
            "trigger_evaluation_ran": False,
            "should_trigger_reveal_called": False,
            "reveal_order_slice_called": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_REVEAL_TRIGGER_RECORD,
            service_method="record_stealth_reveal_trigger_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def _rejected_stealth_manager_policy_proof_response(
        self,
        *,
        command: StealthManagerInvocationPolicyProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_MANAGER_INVOCATION_POLICY_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "manager_policy_proof_id": request.manager_policy_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "manager_policy_ref": request.manager_policy_ref,
            "mutation_lock_policy_ref": request.mutation_lock_policy_ref,
            "exchange_reality_policy_ref": request.exchange_reality_policy_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "manager_policy_verified": False,
            "manager_invocation_allowed": False,
            "manager_invocation_ran": False,
            "mutation_lock_policy_verified": False,
            "exchange_reality_policy_verified": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_MANAGER_POLICY_RECORD,
            service_method="record_stealth_manager_invocation_policy_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_manager_invocation_policy_proof(
        self,
        command: StealthManagerInvocationPolicyProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth manager-invocation policy evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_manager_policy_proof_response(
                command=command,
                message=(
                    "Stealth manager-invocation policy proof admission evidence "
                    "is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_manager_policy_service.record_proof(
                proof_store=deps.stealth_manager_policy_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthManagerInvocationPolicyError as exc:
            return self._rejected_stealth_manager_policy_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_MANAGER_POLICY_RECORD,
            service_method="record_stealth_manager_invocation_policy_proof",
            message=(
                "Stealth manager-invocation policy proof recorded as evidence "
                "only; no StealthOrderManager invocation, Coinbase activity, "
                "reconciliation, or state mutation ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_manager_policy_proof_response_data(record),
        )

    def _rejected_stealth_coinbase_exchange_policy_proof_response(
        self,
        *,
        command: StealthCoinbaseExchangeSubmissionPolicyProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_COINBASE_EXCHANGE_SUBMISSION_POLICY_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "coinbase_exchange_policy_proof_id": (
                request.coinbase_exchange_policy_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "exchange_submission_policy_ref": request.exchange_submission_policy_ref,
            "coinbase_cancel_policy_ref": request.coinbase_cancel_policy_ref,
            "live_coinbase_read_policy_ref": request.live_coinbase_read_policy_ref,
            "live_cap_evidence_ref": request.live_cap_evidence_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "exchange_submission_policy_verified": False,
            "coinbase_submit_allowed": False,
            "coinbase_cancel_allowed": False,
            "live_coinbase_read_allowed": False,
            "live_cap_verified": False,
            "manager_invocation_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD
            ),
            service_method=(
                "record_stealth_coinbase_exchange_submission_policy_proof"
            ),
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_coinbase_exchange_submission_policy_proof(
        self,
        command: StealthCoinbaseExchangeSubmissionPolicyProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth Coinbase exchange policy evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_coinbase_exchange_policy_proof_response(
                command=command,
                message=(
                    "Stealth Coinbase exchange policy proof admission evidence "
                    "is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_coinbase_exchange_policy_service.record_proof(
                proof_store=(
                    deps.stealth_coinbase_exchange_policy_proof_store_getter()
                ),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthCoinbaseExchangeSubmissionPolicyError as exc:
            return self._rejected_stealth_coinbase_exchange_policy_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD
            ),
            service_method=(
                "record_stealth_coinbase_exchange_submission_policy_proof"
            ),
            message=(
                "Stealth Coinbase exchange submission policy proof recorded as "
                "evidence only; no Coinbase submit, cancel, read, "
                "reconciliation, manager invocation, or state mutation ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_coinbase_exchange_policy_proof_response_data(record),
        )

    def _rejected_stealth_state_mutation_policy_proof_response(
        self,
        *,
        command: StealthStateMutationPolicyProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_STATE_MUTATION_POLICY_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "state_mutation_policy_proof_id": (
                request.state_mutation_policy_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "state_mutation_policy_ref": request.state_mutation_policy_ref,
            "lifecycle_state_policy_ref": request.lifecycle_state_policy_ref,
            "order_state_policy_ref": request.order_state_policy_ref,
            "exchange_state_policy_ref": request.exchange_state_policy_ref,
            "post_write_reconciliation_policy_ref": (
                request.post_write_reconciliation_policy_ref
            ),
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "state_mutation_policy_verified": False,
            "state_mutation_allowed": False,
            "lifecycle_state_mutation_allowed": False,
            "order_state_mutation_allowed": False,
            "exchange_state_mutation_allowed": False,
            "manager_invocation_ran": False,
            "reconciliation_plan_built": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_STATE_MUTATION_POLICY_RECORD
            ),
            service_method="record_stealth_state_mutation_policy_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_state_mutation_policy_proof(
        self,
        command: StealthStateMutationPolicyProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth state-mutation policy evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_state_mutation_policy_proof_response(
                command=command,
                message=(
                    "Stealth state-mutation policy proof admission evidence "
                    "is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_state_mutation_policy_service.record_proof(
                proof_store=deps.stealth_state_mutation_policy_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthStateMutationPolicyError as exc:
            return self._rejected_stealth_state_mutation_policy_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_STATE_MUTATION_POLICY_RECORD
            ),
            service_method="record_stealth_state_mutation_policy_proof",
            message=(
                "Stealth state-mutation policy proof recorded as evidence only; "
                "no state mutation, manager invocation, Coinbase activity, "
                "active-placement cancel/replace, or reconciliation execution ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_state_mutation_policy_proof_response_data(record),
        )

    def record_stealth_reveal_trigger_proof(
        self,
        command: StealthRevealTriggerProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth reveal-trigger proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_reveal_trigger_proof_response(
                command=command,
                message="Stealth reveal-trigger proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_reveal_trigger_proof_service.record_proof(
                proof_store=deps.stealth_reveal_trigger_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthRevealTriggerProofError as exc:
            return self._rejected_stealth_reveal_trigger_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_REVEAL_TRIGGER_RECORD,
            service_method="record_stealth_reveal_trigger_proof",
            message=(
                "Stealth reveal-trigger proof recorded as evidence only; no "
                "trigger evaluation, reveal_order_slice call, manager "
                "invocation, reconciliation, or Coinbase activity ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_reveal_trigger_proof_response_data(record),
        )

    def _rejected_stealth_reconciliation_proof_response(
        self,
        *,
        command: StealthReconciliationProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_RECONCILIATION_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "reconciliation_proof_id": request.reconciliation_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "reconciliation_evidence_ref": request.reconciliation_evidence_ref,
            "reconciliation_plan_ref": request.reconciliation_plan_ref,
            "active_placement_evidence_ref": (
                request.active_placement_evidence_ref
            ),
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "reconciliation_proof_verified": False,
            "manager_invocation_ran": False,
            "reconciliation_plan_built": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECONCILIATION_RECORD,
            service_method="record_stealth_reconciliation_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_reconciliation_proof(
        self,
        command: StealthReconciliationProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth reconciliation proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_reconciliation_proof_response(
                command=command,
                message="Stealth reconciliation proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_reconciliation_proof_service.record_proof(
                proof_store=deps.stealth_reconciliation_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthReconciliationProofError as exc:
            return self._rejected_stealth_reconciliation_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECONCILIATION_RECORD,
            service_method="record_stealth_reconciliation_proof",
            message=(
                "Stealth reconciliation proof recorded as evidence only; no "
                "reconciliation execution, manager invocation, active-placement "
                "cancel/replace, state mutation, or Coinbase activity ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_reconciliation_proof_response_data(record),
        )

    def _rejected_stealth_cancel_replace_proof_response(
        self,
        *,
        command: StealthCancelReplaceProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_CANCEL_REPLACE_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "cancel_replace_proof_id": request.cancel_replace_proof_id,
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "active_placement_evidence_ref": (
                request.active_placement_evidence_ref
            ),
            "mutation_claim_evidence_ref": request.mutation_claim_evidence_ref,
            "cancel_replace_evidence_ref": request.cancel_replace_evidence_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "cancel_replace_proof_verified": False,
            "manager_invocation_ran": False,
            "cancel_replace_plan_built": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD,
            service_method="record_stealth_cancel_replace_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_cancel_replace_proof(
        self,
        command: StealthCancelReplaceProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth cancel/replace proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_cancel_replace_proof_response(
                command=command,
                message="Stealth cancel/replace proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_cancel_replace_proof_service.record_proof(
                proof_store=deps.stealth_cancel_replace_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthCancelReplaceProofError as exc:
            return self._rejected_stealth_cancel_replace_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD,
            service_method="record_stealth_cancel_replace_proof",
            message=(
                "Stealth cancel/replace proof recorded as evidence only; no "
                "manager invocation, Coinbase cancel/replace, state mutation, "
                "or reconciliation execution ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_cancel_replace_proof_response_data(record),
        )

    def _rejected_stealth_post_write_reconciliation_proof_response(
        self,
        *,
        command: StealthPostWriteReconciliationProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "post_write_reconciliation_proof_id": (
                request.post_write_reconciliation_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "route_bound_reconciliation_plan_ref": (
                request.route_bound_reconciliation_plan_ref
            ),
            "post_write_execution_journal_ref": (
                request.post_write_execution_journal_ref
            ),
            "post_write_completion_proof_ref": (
                request.post_write_completion_proof_ref
            ),
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "post_write_reconciliation_verified": False,
            "route_bound_reconciliation_plan_recorded": False,
            "execution_journal_accepted": False,
            "completion_proof_recorded": False,
            "manager_invocation_ran": False,
            "reconciliation_plan_built": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method="record_stealth_post_write_reconciliation_proof",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_post_write_reconciliation_proof(
        self,
        command: StealthPostWriteReconciliationProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth post-write reconciliation proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_post_write_reconciliation_proof_response(
                command=command,
                message=(
                    "Stealth post-write reconciliation proof admission evidence "
                    "is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = (
                deps.stealth_post_write_reconciliation_proof_service.record_proof(
                    proof_store=(
                        deps.stealth_post_write_reconciliation_proof_store_getter()
                    ),
                    stealth_order_id=command.stealth_order_id,
                    body=command.request,
                    admission_decision=command.admission_decision,
                    actor_id=command.envelope.actor.actor_id,
                    operator_intent=command.envelope.operator_intent,
                    idempotency_key=command.envelope.idempotency_key,
                    correlation_id=command.envelope.correlation_id,
                    payload_hash=command.admission_decision.payload_hash,
                    audit_id=audit_id,
                )
            )
        except StealthPostWriteReconciliationProofError as exc:
            return self._rejected_stealth_post_write_reconciliation_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method="record_stealth_post_write_reconciliation_proof",
            message=(
                "Stealth post-write reconciliation proof recorded as evidence "
                "only; no manager invocation, Coinbase activity, state mutation, "
                "or reconciliation execution ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_post_write_reconciliation_proof_response_data(record),
        )

    def _rejected_stealth_post_write_reconciliation_policy_response(
        self,
        *,
        command: StealthPostWriteReconciliationExecutionPolicyProofCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_EXECUTION_POLICY_PROOF.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "post_write_reconciliation_policy_proof_id": (
                request.post_write_reconciliation_policy_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "post_write_reconciliation_execution_policy_ref": (
                request.post_write_reconciliation_execution_policy_ref
            ),
            "route_bound_reconciliation_plan_ref": (
                request.route_bound_reconciliation_plan_ref
            ),
            "post_write_execution_journal_policy_ref": (
                request.post_write_execution_journal_policy_ref
            ),
            "post_write_reconciliation_verification_policy_ref": (
                request.post_write_reconciliation_verification_policy_ref
            ),
            "safe_reconciliation_chain_ref": request.safe_reconciliation_chain_ref,
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "proof_persisted": False,
            "post_write_reconciliation_execution_policy_verified": False,
            "post_write_reconciliation_execution_allowed": False,
            "route_bound_reconciliation_plan_required": True,
            "execution_journal_required": True,
            "reconciliation_verification_required": True,
            "safe_reconciliation_chain_verified": False,
            "manager_invocation_ran": False,
            "reconciliation_plan_built": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_POST_WRITE_RECONCILIATION_POLICY_RECORD
            ),
            service_method=(
                "record_stealth_post_write_reconciliation_execution_policy_proof"
            ),
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="proof_prerequisite",
        )

    def record_stealth_post_write_reconciliation_execution_policy_proof(
        self,
        command: StealthPostWriteReconciliationExecutionPolicyProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned post-write reconciliation execution-policy evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_post_write_reconciliation_policy_response(
                command=command,
                message=(
                    "Stealth post-write reconciliation execution policy proof "
                    "admission evidence is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = (
                deps.stealth_post_write_reconciliation_policy_service.record_proof(
                    proof_store=(
                        deps.stealth_post_write_reconciliation_policy_proof_store_getter()
                    ),
                    stealth_order_id=command.stealth_order_id,
                    body=command.request,
                    admission_decision=command.admission_decision,
                    actor_id=command.envelope.actor.actor_id,
                    operator_intent=command.envelope.operator_intent,
                    idempotency_key=command.envelope.idempotency_key,
                    correlation_id=command.envelope.correlation_id,
                    payload_hash=command.admission_decision.payload_hash,
                    audit_id=audit_id,
                )
            )
        except StealthPostWriteReconciliationExecutionPolicyError as exc:
            return self._rejected_stealth_post_write_reconciliation_policy_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=(
                AdminApiPermission.STEALTH_POST_WRITE_RECONCILIATION_POLICY_RECORD
            ),
            service_method=(
                "record_stealth_post_write_reconciliation_execution_policy_proof"
            ),
            message=(
                "Stealth post-write reconciliation execution policy proof "
                "recorded as evidence only; no reconciliation execution, "
                "Coinbase activity, manager invocation, or state mutation ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_post_write_reconciliation_policy_proof_response_data(record),
        )

    def _rejected_stealth_post_write_execution_journal_response(
        self,
        *,
        command: StealthPostWriteExecutionJournalCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_POST_WRITE_EXECUTION_JOURNAL.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "execution_journal_acceptance_id": (
                request.execution_journal_acceptance_id
            ),
            "post_write_reconciliation_proof_id": (
                request.post_write_reconciliation_proof_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "post_write_execution_journal_ref": (
                request.post_write_execution_journal_ref
            ),
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "journal_acceptance_persisted": False,
            "execution_journal_accepted": False,
            "post_write_reconciliation_verified": False,
            "manager_invocation_ran": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method="record_stealth_post_write_execution_journal",
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="journal_prerequisite",
        )

    def record_stealth_post_write_execution_journal(
        self,
        command: StealthPostWriteExecutionJournalCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned post-write execution-journal acceptance."""

        if command.admission_decision is None:
            return self._rejected_stealth_post_write_execution_journal_response(
                command=command,
                message=(
                    "Stealth post-write execution journal admission evidence "
                    "is missing."
                ),
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = (
                deps.stealth_post_write_execution_journal_service.record_execution_journal(
                    journal_store=(
                        deps.stealth_post_write_execution_journal_store_getter()
                    ),
                    proof_store=(
                        deps.stealth_post_write_reconciliation_proof_store_getter()
                    ),
                    stealth_order_id=command.stealth_order_id,
                    body=command.request,
                    admission_decision=command.admission_decision,
                    actor_id=command.envelope.actor.actor_id,
                    operator_intent=command.envelope.operator_intent,
                    idempotency_key=command.envelope.idempotency_key,
                    correlation_id=command.envelope.correlation_id,
                    payload_hash=command.admission_decision.payload_hash,
                    audit_id=audit_id,
                )
            )
        except StealthPostWriteExecutionJournalError as exc:
            return self._rejected_stealth_post_write_execution_journal_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method="record_stealth_post_write_execution_journal",
            message=(
                "Stealth post-write execution journal accepted as append-only "
                "evidence only; no manager invocation, Coinbase activity, "
                "state mutation, or reconciliation execution ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_post_write_execution_journal_response_data(record),
        )

    def _rejected_stealth_post_write_reconciliation_verification_response(
        self,
        *,
        command: StealthPostWriteReconciliationVerificationCommand,
        message: str,
    ) -> AdminApiCommandResponse:
        request = command.request
        data: dict[str, Any] = {
            "mutation_family": (
                AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_VERIFICATION.value
            ),
            "stealth_order_id": command.stealth_order_id,
            "reconciliation_verification_id": (
                request.reconciliation_verification_id
            ),
            "post_write_reconciliation_proof_id": (
                request.post_write_reconciliation_proof_id
            ),
            "execution_journal_acceptance_id": (
                request.execution_journal_acceptance_id
            ),
            "guarded_command_route": request.guarded_command_route,
            "guarded_command_method": request.guarded_command_method,
            "guarded_service_method": request.guarded_service_method,
            "guarded_mutation_family": request.guarded_mutation_family.value,
            "guarded_actor_id": request.guarded_actor_id,
            "guarded_operator_intent": request.guarded_operator_intent,
            "guarded_idempotency_key": request.guarded_idempotency_key,
            "guarded_payload_hash": request.guarded_payload_hash,
            "post_write_execution_journal_ref": (
                request.post_write_execution_journal_ref
            ),
            "post_write_completion_proof_ref": (
                request.post_write_completion_proof_ref
            ),
            "reconciliation_verification_ref": (
                request.reconciliation_verification_ref
            ),
            "evidence_source": request.evidence_source.value,
            "approval_snapshot_id": request.approval_snapshot_id,
            "admission_audit_id": request.admission_audit_id,
            "cap_guard_decision_id": request.cap_guard_decision_id,
            "reconciliation_plan_id": request.reconciliation_plan_id,
            "dry_run": request.dry_run,
            "operator_reason": request.operator_reason,
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
            "verification_persisted": False,
            "execution_journal_accepted": False,
            "post_write_reconciliation_verified": False,
            "manager_invocation_ran": False,
            "reconciliation_execution_ran": False,
            "coinbase_read_attempted": False,
            "coinbase_read_succeeded": False,
            "coinbase_rest_read_ran": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "active_placement_cancel_replace_ran": False,
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "lifecycle_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method=(
                "record_stealth_post_write_reconciliation_verification"
            ),
            message=message,
            stealth_order_id=command.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            data=data,
            failure_stage="reconciliation_verification_prerequisite",
        )

    def record_stealth_post_write_reconciliation_verification(
        self,
        command: StealthPostWriteReconciliationVerificationCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned post-write reconciliation verification."""

        if command.admission_decision is None:
            return (
                self._rejected_stealth_post_write_reconciliation_verification_response(
                    command=command,
                    message=(
                        "Stealth post-write reconciliation verification "
                        "admission evidence is missing."
                    ),
                )
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = (
                deps.stealth_post_write_reconciliation_verification_service.record_verification(
                    verification_store=(
                        deps.stealth_post_write_reconciliation_verification_store_getter()
                    ),
                    journal_store=(
                        deps.stealth_post_write_execution_journal_store_getter()
                    ),
                    proof_store=(
                        deps.stealth_post_write_reconciliation_proof_store_getter()
                    ),
                    stealth_order_id=command.stealth_order_id,
                    body=command.request,
                    admission_decision=command.admission_decision,
                    actor_id=command.envelope.actor.actor_id,
                    operator_intent=command.envelope.operator_intent,
                    idempotency_key=command.envelope.idempotency_key,
                    correlation_id=command.envelope.correlation_id,
                    payload_hash=command.admission_decision.payload_hash,
                    audit_id=audit_id,
                )
            )
        except (
            StealthPostWriteReconciliationVerificationError,
            StealthPostWriteReconciliationProofError,
        ) as exc:
            return (
                self._rejected_stealth_post_write_reconciliation_verification_response(
                    command=command,
                    message=str(exc),
                )
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.RECONCILIATION_RECORD,
            service_method=(
                "record_stealth_post_write_reconciliation_verification"
            ),
            message=(
                "Stealth post-write reconciliation verified as append-only "
                "evidence only; no manager invocation, Coinbase activity, "
                "state mutation, or reconciliation execution ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=(
                _stealth_post_write_reconciliation_verification_response_data(
                    record
                )
            ),
        )

    def record_stealth_recovery_proof(
        self,
        command: StealthRecoveryProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned stealth recovery proof evidence."""

        if command.admission_decision is None:
            return self._rejected_stealth_recovery_proof_response(
                command=command,
                message="Stealth recovery proof admission evidence is missing.",
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.stealth_recovery_proof_service.record_proof(
                proof_store=deps.stealth_recovery_proof_store_getter(),
                stealth_order_id=command.stealth_order_id,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except StealthRecoveryProofError as exc:
            return self._rejected_stealth_recovery_proof_response(
                command=command,
                message=str(exc),
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.STEALTH_RECOVERY_RECORD,
            service_method="record_stealth_recovery_proof",
            message=(
                "Stealth recovery proof recorded as evidence only; no repair, "
                "rollback, reconciliation, manager invocation, or Coinbase "
                "activity ran."
            ),
            stealth_order_id=record.stealth_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_stealth_recovery_proof_response_data(record),
        )

    def execute_spot_recovery_apply(
        self,
        command: SpotRecoveryApplyExecutionCommand,
    ) -> AdminApiCommandResponse:
        """Record a backend-owned no-live Spot recovery apply journal."""

        if command.admission_decision is None:
            return self._disabled_spot_recovery_response(
                service_method="execute_spot_recovery_apply",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
                ),
                command=command,
                message="Spot recovery apply admission evidence is missing.",
                flags={
                    "recovery_apply_executed": False,
                    "order_state_mutated": False,
                    "repair_journal_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.spot_recovery_execution_service.record_apply_execution(
                execution_store=deps.spot_recovery_execution_store_getter(),
                proof_store=deps.spot_recovery_proof_store_getter(),
                repair_result_store=(
                    deps.spot_recovery_repair_result_store_getter()
                ),
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except SpotRecoveryExecutionError as exc:
            return self._disabled_spot_recovery_response(
                service_method="execute_spot_recovery_apply",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
                ),
                command=command,
                message=str(exc),
                flags={
                    "recovery_apply_executed": False,
                    "order_state_mutated": False,
                    "repair_journal_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
            service_method="execute_spot_recovery_apply",
            message=(
                "Spot recovery apply journal recorded; local order/exchange "
                "state was not mutated and post-apply reconciliation remains required."
            ),
            client_order_id=record.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_spot_recovery_execution_response_data(record),
        )

    def execute_spot_recovery_rollback(
        self,
        command: SpotRecoveryRollbackExecutionCommand,
    ) -> AdminApiCommandResponse:
        """Record a backend-owned no-live Spot recovery rollback journal."""

        if command.admission_decision is None:
            return self._disabled_spot_recovery_response(
                service_method="execute_spot_recovery_rollback",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
                ),
                command=command,
                message="Spot recovery rollback admission evidence is missing.",
                flags={
                    "rollback_executed": False,
                    "order_state_mutated": False,
                    "repair_journal_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.spot_recovery_execution_service.record_rollback_execution(
                execution_store=deps.spot_recovery_execution_store_getter(),
                repair_result_store=(
                    deps.spot_recovery_repair_result_store_getter()
                ),
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except SpotRecoveryExecutionError as exc:
            return self._disabled_spot_recovery_response(
                service_method="execute_spot_recovery_rollback",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
                ),
                command=command,
                message=str(exc),
                flags={
                    "rollback_executed": False,
                    "order_state_mutated": False,
                    "repair_journal_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
            service_method="execute_spot_recovery_rollback",
            message=(
                "Spot recovery rollback journal recorded; local order/exchange "
                "state was not mutated and Coinbase was not contacted."
            ),
            client_order_id=record.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_spot_recovery_execution_response_data(record),
        )

    def record_spot_recovery_exchange_state_proof(
        self,
        command: SpotRecoveryExchangeStateProofCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned exchange-state proof evidence when gates match."""

        if command.admission_decision is None:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_exchange_state_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF
                ),
                command=command,
                message="Spot recovery proof admission evidence is missing.",
                flags={
                    "exchange_state_proof_recorded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = deps.spot_recovery_proof_service.record_exchange_state_proof(
                store=deps.spot_recovery_proof_store_getter(),
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
        except SpotRecoveryProofError as exc:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_exchange_state_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF
                ),
                command=command,
                message=str(exc),
                flags={
                    "exchange_state_proof_recorded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
            service_method="record_spot_recovery_exchange_state_proof",
            message="Spot recovery exchange-state proof recorded.",
            client_order_id=record.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_spot_recovery_proof_response_data(
                record,
                exchange_state_proof_recorded=True,
                reconciliation_proof_recorded=False,
            ),
        )

    def record_spot_recovery_exchange_state_snapshot(
        self,
        command: SpotRecoveryExchangeStateSnapshotCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned exchange-state snapshot evidence when gates match."""

        if command.admission_decision is None:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_exchange_state_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT
                ),
                command=command,
                message="Spot recovery exchange-state snapshot admission evidence is missing.",
                flags={
                    "snapshot_recorded": False,
                    "coinbase_read_attempted": False,
                    "coinbase_read_succeeded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        try:
            record = (
                deps.spot_recovery_snapshot_service.record_exchange_state_snapshot(
                    store=deps.spot_recovery_snapshot_store_getter(),
                    body=command.request,
                    admission_decision=command.admission_decision,
                    actor_id=command.envelope.actor.actor_id,
                    operator_intent=command.envelope.operator_intent,
                    idempotency_key=command.envelope.idempotency_key,
                    correlation_id=command.envelope.correlation_id,
                    payload_hash=command.admission_decision.payload_hash,
                    audit_id=audit_id,
                )
            )
        except SpotRecoverySnapshotError as exc:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_exchange_state_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT
                ),
                command=command,
                message=str(exc),
                flags={
                    "snapshot_recorded": False,
                    "coinbase_read_attempted": False,
                    "coinbase_read_succeeded": False,
                    "coinbase_rest_read_ran": False,
                    "proof_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
            service_method="record_spot_recovery_exchange_state_snapshot",
            message=(
                "Spot recovery exchange-state snapshot recorded; Coinbase was "
                "not read and no order or exchange state was mutated."
            ),
            client_order_id=record.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_spot_recovery_snapshot_response_data(record),
        )

    def record_spot_recovery_reconciliation_proof(
        self,
        command: SpotRecoveryReconciliationProofRecordCommand,
    ) -> AdminApiCommandResponse:
        """Record backend-owned reconciliation proof evidence when gates match."""

        if command.admission_decision is None:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_reconciliation_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF
                ),
                command=command,
                message="Spot recovery proof admission evidence is missing.",
                flags={
                    "reconciliation_proof_recorded": False,
                    "reconciliation_executed": False,
                    "proof_persisted": False,
                },
            )

        deps = self.dependencies
        audit_id = deps.uuid_factory()
        completion_guard: SpotRecoveryCompletionGuardResult | None = None
        completion_record: SpotRecoveryCompletionRecord | None = None
        try:
            audit_store = deps.audit_store_getter()
            recovery_apply_audit = audit_store.find_by_audit_id(
                str(command.request.recovery_apply_audit_id)
            )
            if (
                recovery_apply_audit is None
                or recovery_apply_audit.endpoint
                != "POST /api/v1/spot/recovery/apply-executions"
                or recovery_apply_audit.permission
                != AdminApiPermission.SPOT_RECOVERY_EXECUTE
                or recovery_apply_audit.client_order_id
                != command.request.client_order_id
                or recovery_apply_audit.live_execution_intent_ref is not None
            ):
                raise SpotRecoveryProofError(
                    "Referenced recovery apply audit was not found."
                )
            proof_store = deps.spot_recovery_proof_store_getter()
            record = deps.spot_recovery_proof_service.record_reconciliation_proof(
                store=proof_store,
                body=command.request,
                admission_decision=command.admission_decision,
                actor_id=command.envelope.actor.actor_id,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                correlation_id=command.envelope.correlation_id,
                payload_hash=command.admission_decision.payload_hash,
                audit_id=audit_id,
            )
            execution_store = deps.spot_recovery_execution_store_getter()
            apply_record = execution_store.find_by_audit_id(
                str(command.request.recovery_apply_audit_id)
            )
            repair_result = None
            repair_store = deps.spot_recovery_repair_result_store_getter()
            if apply_record is not None and apply_record.repair_result_id:
                repair_result = repair_store.find_by_repair_result_id(
                    apply_record.repair_result_id
                )
            if repair_result is None and apply_record is not None:
                repair_result = repair_store.find_by_journal_id(
                    apply_record.journal_id
                )
            completion_guard = evaluate_spot_recovery_completion_guard(
                proof_record=record,
                apply_record=apply_record,
                repair_result=repair_result,
                recovery_apply_audit=recovery_apply_audit,
                admission_decision=command.admission_decision,
                operator_intent=command.envelope.operator_intent,
                idempotency_key=command.envelope.idempotency_key,
                payload_hash=command.admission_decision.payload_hash,
            )
            completion_store = deps.spot_recovery_completion_store_getter()
            if completion_guard.guard_passed:
                completion_record = (
                    completion_store.find_by_completion_id(
                        completion_guard.completion_id
                    )
                    or build_spot_recovery_completion_record(
                        guard=completion_guard,
                        actor_id=command.envelope.actor.actor_id,
                        operator_intent=command.envelope.operator_intent,
                        idempotency_key=command.envelope.idempotency_key,
                        correlation_id=command.envelope.correlation_id,
                        payload_hash=command.admission_decision.payload_hash,
                    )
                )
                if (
                    completion_store.find_by_completion_id(
                        completion_record.completion_id
                    )
                    is None
                ):
                    completion_store.append(completion_record)
        except SpotRecoveryProofError as exc:
            return self._rejected_spot_recovery_proof_response(
                service_method="record_spot_recovery_reconciliation_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF
                ),
                command=command,
                message=str(exc),
                flags={
                    "reconciliation_proof_recorded": False,
                    "reconciliation_executed": False,
                    "proof_persisted": False,
                },
            )

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.ACCEPTED,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
            service_method="record_spot_recovery_reconciliation_proof",
            message="Spot recovery reconciliation proof recorded.",
            client_order_id=record.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            audit_id=record.audit_id,
            live_exchange_submitted=False,
            data=_spot_recovery_proof_response_data(
                record,
                exchange_state_proof_recorded=False,
                reconciliation_proof_recorded=True,
                completion_guard=completion_guard,
                completion_record=completion_record,
            ),
        )

    def place_hotpoint_test_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Place a hotpoint seed order through the shared guarded path."""

        if not command.allow_live_execution:
            gate = evaluate_live_execution_gate(allow_live_execution=False)
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.NOT_IMPLEMENTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_hotpoint_test_order",
                message=(
                    "Hotpoint test placement requires enterprise auth, "
                    "idempotency, approval, and cap gates before live execution."
                ),
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                guard=gate.model_dump(),
                failure_stage="approval",
            )

        deps = self.dependencies
        client_order_id = deps.uuid_factory()
        request = command.request
        product_id = request.product_id
        side = request.side.value if isinstance(request.side, OrderSide) else str(request.side)
        raw_price = safe_float(request.limit_price, default=0.0)
        raw_size = request.base_size

        if not (product_id and side and raw_price and raw_price > 0 and raw_size is not None):
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="Invalid hotpoint test order payload",
                failure_stage="invalid_payload",
                service_method="place_hotpoint_test_order",
            )

        if not deps.rest_client_available:
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message="REST client not available",
                failure_stage="rest_client_unavailable",
                service_method="place_hotpoint_test_order",
            )

        parent_row_inserted = False
        try:
            capability = evaluate_product_capability(
                product_id=product_id,
                capability=ProductCapability.HOTPOINT_AUTO_PLACEMENT,
            )
            if not capability.allowed:
                message = (
                    "Hotpoint test order rejected by product capability policy: "
                    f"{capability.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={
                        "error": "product_capability_blocked",
                        "capability": capability.to_dict(),
                    },
                    failure_stage="product_capability_blocked",
                    service_method="place_hotpoint_test_order",
                )

            from calculation.size_validation import validate_and_quantize_size

            size_check = validate_and_quantize_size(
                raw_size,
                product_id=product_id,
                price=raw_price,
            )
            if not size_check:
                message = (
                    "Hotpoint test order rejected at boundary: "
                    f"{size_check.reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    data={"error": "size_validation_failed"},
                    failure_stage="size_validation_failed",
                    service_method="place_hotpoint_test_order",
                )
            approved_size = size_check.size

            guard_ok, guard_failure = ActionConditionGuard(
                planned_budget_fetcher=deps.planned_budget_fetcher,
                lot_authority_evaluator=deps.lot_authority_evaluator_getter(),
            ).evaluate(
                phase=ActionGuardPhase.PLANNING,
                product_id=product_id,
                side=side,
                size=approved_size,
                limit_price=raw_price,
                client_order_id=client_order_id,
            )
            if not guard_ok:
                reason = (guard_failure or {}).get("reason", "blocked")
                message = (
                    "Hotpoint test order rejected by action-condition guard: "
                    f"{reason}"
                )
                deps.add_log_entry("WARNING", message)
                return self._place_rejected(
                    command=command,
                    client_order_id=client_order_id,
                    message=message,
                    guard=guard_failure,
                    data={"error": "action_condition_guard_blocked"},
                    failure_stage="action_condition_guard_blocked",
                    service_method="place_hotpoint_test_order",
                )

            parent_id = deps.insert_order_parent(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                size=approved_size,
                price=raw_price,
                target_movement=0.0,
                target_movement_type=TargetMovementType.PERCENTAGE.value,
                max_order_replacement=0,
                current_order_replacement=0,
                status=OrderStatus.PENDING.value,
                parent_order_id=None,
                allow_partial_fills=False,
                enable_hotpoint_replication=True,
                auto_placed_by_hotpoint=False,
            )
            if parent_id is None:
                raise OrderCreationError(
                    "failed to pre-insert hotpoint test parent order",
                    client_order_id=client_order_id,
                )
            parent_row_inserted = True

            order_configuration = {
                "limit_limit_gtc": {
                    "base_size": str(approved_size),
                    "limit_price": str(raw_price),
                    "post_only": False,
                },
            }
            controller = deps.runtime_controller_factory()
            with controller.track_inflight(INFLIGHT_REST_PLACE):
                result = deps.rest_client.limit_order_gtc(
                    product_id=product_id,
                    side=side,
                    base_size=str(approved_size),
                    limit_price=str(raw_price),
                    client_order_id=client_order_id,
                    post_only=False,
                )

            result_dict = coinbase_order_response_to_dict(result)
            response_success = coinbase_order_response_success(result, result_dict)
            if response_success is False:
                error_msg = coinbase_order_response_error_message(result, result_dict)
                raise CoinbaseAPIError(
                    f"Hotpoint test order creation failed: {error_msg}",
                    api_error_code="hotpoint_test_order_creation_failed",
                )

            order_id = coinbase_order_response_order_id(result, result_dict)
            submission_event_recorded = publish_direct_order_submission_event(
                publisher_getter=deps.order_event_publisher_getter,
                client_order_id=client_order_id,
                order_id=order_id,
                order_params={"product_id": product_id, "side": side},
                order_configuration=order_configuration,
            )
            deps.add_log_entry(
                "INFO",
                (
                    "Hotpoint test order placed: "
                    f"{client_order_id} {product_id} {side} {approved_size}@{raw_price}"
                ),
            )
            return AdminApiCommandResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_hotpoint_test_order",
                message="Hotpoint test order placed",
                client_order_id=client_order_id,
                coinbase_order_id=order_id,
                correlation_id=command.envelope.correlation_id,
                idempotency_key=command.envelope.idempotency_key,
                live_exchange_submitted=True,
                live_coinbase_orders_ran=True,
                submission_event_recorded=submission_event_recorded,
            )
        except CoinbaseAPIError as exc:
            deps.add_log_entry("ERROR", f"Hotpoint test order API error: {exc}")
            if parent_row_inserted:
                self._mark_hotpoint_parent_failed(deps, client_order_id)
            return self._place_rejected(
                command=command,
                client_order_id=client_order_id,
                message=str(exc),
                data={"error": str(exc)},
                failure_stage="coinbase_rest",
                service_method="place_hotpoint_test_order",
            )
        except Exception:
            if parent_row_inserted:
                self._mark_hotpoint_parent_failed(deps, client_order_id)
            raise

    def _manual_order_payload(
        self,
        command: ManualOrderCommand,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request = command.request
        order_params = {
            "product_id": request.product_id,
            "side": request.side.value if isinstance(request.side, OrderSide) else str(request.side),
            "manual_live_acknowledgement": request.manual_live_acknowledgement,
        }
        if command.order_configuration_override is not None:
            return order_params, dict(command.order_configuration_override)

        if request.order_type == OrderType.MARKET:
            inner: dict[str, Any] = {}
            if request.base_size is not None:
                inner["base_size"] = request.base_size
            if request.quote_size is not None:
                inner["quote_size"] = request.quote_size
            return order_params, {"market_market_ioc": inner}

        inner = {
            "base_size": request.base_size,
            "limit_price": request.limit_price,
            "post_only": request.post_only,
        }
        if request.quote_size is not None:
            inner["quote_size"] = request.quote_size
        if request.time_in_force == TimeInForce.FILL_OR_KILL:
            fok_inner = {
                key: value
                for key, value in inner.items()
                if key != "post_only" and value is not None
            }
            return order_params, {"limit_limit_fok": fok_inner}
        return order_params, {
            "limit_limit_gtc": {
                key: value for key, value in inner.items() if value is not None
            }
        }

    def _place_rejected(
        self,
        *,
        command: ManualOrderCommand,
        client_order_id: str,
        message: str,
        failure_stage: str,
        guard: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        service_method: str = "place_manual_order",
        coinbase_order_id: str | None = None,
        live_exchange_submitted: bool = False,
        live_coinbase_orders_ran: bool = False,
        submission_event_recorded: bool | None = None,
    ) -> AdminApiCommandResponse:
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method=service_method,
            message=message,
            client_order_id=client_order_id,
            coinbase_order_id=coinbase_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            guard=guard,
            data=data,
            live_exchange_submitted=live_exchange_submitted,
            live_coinbase_orders_ran=live_coinbase_orders_ran,
            submission_event_recorded=submission_event_recorded,
            failure_stage=failure_stage,
            **self._command_runtime_evidence(),
        )

    def _mark_hotpoint_parent_failed(
        self,
        deps: AdminApiCommandDependencies,
        client_order_id: str,
    ) -> None:
        try:
            deps.update_order_parent_status(client_order_id, OrderStatus.FAILED.value)
        except Exception as update_exc:
            deps.add_log_entry(
                "ERROR",
                f"failed to mark hotpoint test order parent FAILED: {update_exc}",
            )

    def _cancel_rejected(
        self,
        *,
        command: CancelOrderCommand,
        message: str,
        failure_stage: str,
        data: Any = None,
        live_exchange_submitted: bool = False,
        live_coinbase_orders_ran: bool = False,
    ) -> AdminApiCommandResponse:
        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.REJECTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_order_by_client_order_id",
            message=message,
            client_order_id=command.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            data=data,
            live_exchange_submitted=live_exchange_submitted,
            live_coinbase_orders_ran=live_coinbase_orders_ran,
            failure_stage=failure_stage,
            **self._command_runtime_evidence(),
        )
