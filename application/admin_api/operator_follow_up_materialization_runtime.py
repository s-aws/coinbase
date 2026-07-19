"""Production composition for operator-authorized follow-up materialization.

The route-facing facade in this module deliberately separates three kinds of
authority:

* PostgreSQL owns the durable one-use claim and invocation boundaries.
* A fresh runtime pass owns source-fill, product, portfolio, market, wallet,
  cap, and child-absence revalidation.
* The canonical exchange adapter owns the sole scoped Create or exact-ID
  Cancel invocation.

Passive readback calls only the PostgreSQL repository.  Raw Coinbase response
objects, portfolio identifiers, exchange identifiers, and exception text are
never represented in a public response model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from typing import Any, Literal

from application.admin_api.models import (
    AdminOrderFollowUpMaterializationAttempt,
    AdminOrderFollowUpMaterializationAuditEvent,
    AdminOrderFollowUpMaterializationAuthorizationRequestForwardability,
    AdminOrderFollowUpMaterializationCallAllowance,
    AdminOrderFollowUpMaterializationCancelResponse,
    AdminOrderFollowUpMaterializationCandidate,
    AdminOrderFollowUpMaterializationCommandResponse,
    AdminOrderFollowUpMaterializationEligibilityEvidence,
    AdminOrderFollowUpMaterializationLocalProjection,
    AdminOrderFollowUpMaterializationReadResponse,
    AdminOrderFollowUpMaterializationSafeCloseoutEligibility,
)
from application.admin_api.cap_guard import is_concrete_usdc_spot_product
from application.admin_api.operator_follow_up_materialization import (
    AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
    CANCEL_ACCEPTED_DIAGNOSTIC,
    CANCEL_REJECTED_DIAGNOSTIC,
    CANCEL_UNKNOWN_DIAGNOSTIC,
    CHILD_ALREADY_TERMINAL_DIAGNOSTIC,
    CREATE_ACCEPTED_DIAGNOSTIC,
    CREATE_REJECTED_DIAGNOSTIC,
    CREATE_UNKNOWN_DIAGNOSTIC,
    CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC,
    CURRENT_MAX_EXECUTED_NOTIONAL_USDC,
    CURRENT_MAX_SUBMITTED_NOTIONAL_USDC,
    PREPARED_DIAGNOSTIC,
    SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
    BackendMaterializationCandidate,
    ChildExchangeState,
    ChildStateEvidence,
    ExchangeInvocationOutcome,
    ExchangeInvocationResult,
    FollowUpMaterializationRecord,
    FreshMaterializationEligibility,
    InvocationBoundaryClaim,
    LocalChildPersistenceEvidence,
    LocalChildProjectionEvidence,
    MaterializationOperationResult,
    MaterializationPrepareCommand,
    MaterializationRecordState,
    OperatorFollowUpMaterializationError,
    OperatorFollowUpMaterializationService,
    PersistedInvocationResult,
)
from core.enums import (
    AdminApiCommandStatus,
    FollowUpMaterializedChildTransitionKind,
)
from database.order_follow_up_intent import (
    FollowUpMaterializationCommand as NativeMaterializationCommand,
)


_CREATE_CONSUMED_NATIVE_STATES = frozenset(
    {
        "CREATE_INVOCATION_STARTED",
        "CREATE_EXPLICITLY_REJECTED",
        "CREATE_ACCEPTED_NONTERMINAL",
        "CREATE_ACCEPTED_TERMINAL",
        "CREATE_UNKNOWN_CONSUMED",
        "CANCEL_INVOCATION_STARTED",
        "CANCEL_NOT_REQUIRED_TERMINAL",
        "CANCEL_EXPLICITLY_REJECTED",
        "CANCEL_ACCEPTED_NONTERMINAL",
        "CANCEL_ACCEPTED_TERMINAL",
        "CANCEL_UNKNOWN_CONSUMED",
    }
)
_CANCEL_CONSUMED_NATIVE_STATES = frozenset(
    {
        "CANCEL_INVOCATION_STARTED",
        "CANCEL_EXPLICITLY_REJECTED",
        "CANCEL_ACCEPTED_NONTERMINAL",
        "CANCEL_ACCEPTED_TERMINAL",
        "CANCEL_UNKNOWN_CONSUMED",
    }
)
_TERMINAL_PUBLIC_STATES = frozenset(
    {
        "CREATE_EXPLICITLY_REJECTED",
        "CREATE_ACCEPTED_TERMINAL",
        "CREATE_UNKNOWN_CONSUMED",
        "CANCEL_ACCEPTED_TERMINAL",
        "CANCEL_UNKNOWN_CONSUMED",
        "CHILD_ALREADY_TERMINAL_NO_CANCEL",
    }
)
_UNKNOWN_PUBLIC_STATES = frozenset(
    {"CREATE_UNKNOWN_CONSUMED", "CANCEL_UNKNOWN_CONSUMED"}
)
_ACTIVE_EXCHANGE_STATUSES = frozenset({"PENDING", "OPEN", "QUEUED"})
_TERMINAL_EXCHANGE_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(getattr(value, "value", value)).upper()


def _decimal(value: Any) -> Decimal | None:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _decimal_text(value: Any) -> str:
    normalized = Decimal(str(value))
    return format(normalized, "f")


def _is_sha256(value: Any) -> bool:
    normalized = _text(value).lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _exact_limit_gtc_order_tuple(
    readback: Mapping[str, Any],
    *,
    client_order_id: str,
    exchange_order_id: str,
    product_id: str,
    side: str,
    base_size: Decimal,
    limit_price: Decimal,
) -> tuple[bool, str]:
    """Validate the complete sanitized Coinbase child tuple and status."""

    matched = _mapping(readback.get("matched_order"))
    configuration = _mapping(matched.get("order_configuration"))
    limit_gtc = _mapping(configuration.get("limit_limit_gtc"))
    status = _upper(readback.get("authoritative_status"))
    exact = bool(
        readback.get("authoritative") is True
        and readback.get("exact_identity_match") is True
        and readback.get("retail_portfolio_id_matches_expected") is True
        and _text(readback.get("exchange_order_id")) == exchange_order_id
        and _text(matched.get("client_order_id")) == client_order_id
        and _text(
            matched.get("order_id") or matched.get("exchange_order_id")
        )
        == exchange_order_id
        and _text(matched.get("product_id")) == product_id
        and _upper(matched.get("side")) == side
        and _upper(matched.get("status")) == status
        and status in (_ACTIVE_EXCHANGE_STATUSES | _TERMINAL_EXCHANGE_STATUSES)
        and _decimal(limit_gtc.get("base_size")) == base_size
        and _decimal(limit_gtc.get("limit_price")) == limit_price
        and limit_gtc.get("post_only") is False
    )
    return exact, status


def _create_response_matches_candidate(
    data: Mapping[str, Any],
    candidate: BackendMaterializationCandidate,
    exchange_order_id: str,
) -> bool:
    """Require Coinbase's documented response echo to match the durable tuple."""

    success = _mapping(data.get("success_response"))
    configuration = _mapping(data.get("order_configuration"))
    limit_gtc = _mapping(configuration.get("limit_limit_gtc"))
    return bool(
        _text(success.get("order_id")) == exchange_order_id
        and _text(success.get("client_order_id"))
        == candidate.child_client_order_id
        and _text(success.get("product_id")) == candidate.product_id
        and _upper(success.get("side")) == candidate.child_side
        and _decimal(limit_gtc.get("base_size")) == candidate.base_size
        and _decimal(limit_gtc.get("limit_price")) == candidate.limit_price
        and limit_gtc.get("post_only") is False
    )


def _configured_admin_environment() -> str:
    return (
        _text(os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT"))
        or _text(os.environ.get("COINBASE_BACKEND_DEPLOYMENT_TIER"))
        or "local"
    )


def _wallet_available(wallet: Any) -> Decimal:
    value = wallet
    if isinstance(wallet, Mapping):
        value = wallet.get("available_balance", wallet.get("available"))
    else:
        value = getattr(wallet, "available_balance", None)
        if value is None:
            value = getattr(wallet, "available", None)
    if isinstance(value, Mapping):
        value = value.get("value", value.get("amount"))
    normalized = _decimal(value)
    return normalized if normalized is not None else Decimal("0")


def _native_state(value: Any) -> str:
    return _upper(value)


def _native_to_kernel_state(state: str) -> tuple[
    MaterializationRecordState,
    ChildExchangeState,
    str,
]:
    mapping = {
        "KNOWN_NOT_INVOKED": (
            MaterializationRecordState.PREPARED,
            ChildExchangeState.UNKNOWN,
            PREPARED_DIAGNOSTIC,
        ),
        "CREATE_INVOCATION_STARTED": (
            MaterializationRecordState.CREATE_INVOCATION_STARTED,
            ChildExchangeState.UNKNOWN,
            CREATE_UNKNOWN_DIAGNOSTIC,
        ),
        "CREATE_EXPLICITLY_REJECTED": (
            MaterializationRecordState.CREATE_REJECTED,
            ChildExchangeState.UNKNOWN,
            CREATE_REJECTED_DIAGNOSTIC,
        ),
        "CREATE_ACCEPTED_NONTERMINAL": (
            MaterializationRecordState.CREATE_ACCEPTED,
            ChildExchangeState.ACTIVE,
            CREATE_ACCEPTED_DIAGNOSTIC,
        ),
        "CREATE_ACCEPTED_TERMINAL": (
            MaterializationRecordState.CREATE_ACCEPTED,
            ChildExchangeState.TERMINAL,
            CREATE_ACCEPTED_DIAGNOSTIC,
        ),
        "CREATE_UNKNOWN_CONSUMED": (
            MaterializationRecordState.CREATE_UNKNOWN,
            ChildExchangeState.UNKNOWN,
            CREATE_UNKNOWN_DIAGNOSTIC,
        ),
        "CANCEL_INVOCATION_STARTED": (
            MaterializationRecordState.CANCEL_INVOCATION_STARTED,
            ChildExchangeState.ACTIVE,
            CANCEL_UNKNOWN_DIAGNOSTIC,
        ),
        "CANCEL_NOT_REQUIRED_TERMINAL": (
            MaterializationRecordState.CHILD_ALREADY_TERMINAL,
            ChildExchangeState.TERMINAL,
            CHILD_ALREADY_TERMINAL_DIAGNOSTIC,
        ),
        "CANCEL_EXPLICITLY_REJECTED": (
            MaterializationRecordState.CANCEL_REJECTED,
            ChildExchangeState.ACTIVE,
            CANCEL_REJECTED_DIAGNOSTIC,
        ),
        "CANCEL_ACCEPTED_NONTERMINAL": (
            MaterializationRecordState.CANCEL_ACCEPTED,
            ChildExchangeState.ACTIVE,
            CANCEL_ACCEPTED_DIAGNOSTIC,
        ),
        "CANCEL_ACCEPTED_TERMINAL": (
            MaterializationRecordState.CANCEL_ACCEPTED,
            ChildExchangeState.TERMINAL,
            CANCEL_ACCEPTED_DIAGNOSTIC,
        ),
        "CANCEL_UNKNOWN_CONSUMED": (
            MaterializationRecordState.CANCEL_UNKNOWN,
            ChildExchangeState.UNKNOWN,
            CANCEL_UNKNOWN_DIAGNOSTIC,
        ),
    }
    try:
        return mapping[state]
    except KeyError:
        raise RuntimeError("follow_up_materialization_state_invalid") from None


class NativeFollowUpMaterializationRepositoryAdapter:
    """Translate the native append-only repository into the kernel protocol."""

    def __init__(self, native_repository: Any) -> None:
        self.native_repository = native_repository

    def _record(self, attempt: Any) -> FollowUpMaterializationRecord:
        state = _native_state(getattr(attempt, "current_state", ""))
        kernel_state, child_state, diagnostic = _native_to_kernel_state(state)
        create_key = _text(getattr(attempt, "idempotency_key", ""))
        current_operation_hash = _text(
            getattr(attempt, "operation_idempotency_key_sha256", None)
        ).lower() or None
        cancel_hash = (
            current_operation_hash
            if state.startswith("CANCEL_")
            else None
        )
        if not create_key or (cancel_hash is not None and not _is_sha256(cancel_hash)):
            raise RuntimeError("follow_up_materialization_record_invalid")
        return FollowUpMaterializationRecord(
            materialization_id=_text(attempt.materialization_id),
            attached_intent_id=_text(attempt.follow_up_intent_id),
            source_client_order_id=_text(attempt.source_client_order_id),
            root_client_order_id=_text(attempt.root_client_order_id),
            child_client_order_id=_text(attempt.child_client_order_id),
            state=kernel_state,
            create_idempotency_key_sha256=_sha256(create_key),
            cancel_idempotency_key_sha256=cancel_hash,
            create_call_consumed=state in _CREATE_CONSUMED_NATIVE_STATES,
            cancel_call_consumed=state in _CANCEL_CONSUMED_NATIVE_STATES,
            child_state=child_state,
            diagnostic_code=diagnostic,
            correlation_id=(
                _text(getattr(attempt, "current_operation_correlation_id", ""))
                or _text(attempt.correlation_id)
            ),
            audit_id=(
                _text(getattr(attempt, "current_operation_audit_id", ""))
                or _text(attempt.audit_id)
            ),
        )

    def _read_native(self, source_client_order_id: str) -> Any:
        return self.native_repository.read_materialization(source_client_order_id)

    def read_materialization(
        self,
        *,
        source_client_order_id: str,
        operation: str,
        idempotency_key: str | None,
    ) -> FollowUpMaterializationRecord | None:
        readback = self._read_native(source_client_order_id)
        attempt = getattr(readback, "attempt", None)
        if attempt is None:
            return None
        if _text(attempt.source_client_order_id) != source_client_order_id:
            raise RuntimeError("follow_up_materialization_record_identity_mismatch")
        operation = _upper(operation)
        if operation == "CREATE" and idempotency_key is not None:
            if _text(attempt.idempotency_key) != _text(idempotency_key):
                raise RuntimeError("idempotency_conflict")
        if operation == "CANCEL" and idempotency_key is not None:
            stored_hash = _text(
                getattr(attempt, "operation_idempotency_key_sha256", None)
            ).lower()
            attempt_state = _native_state(attempt.current_state)
            if (
                attempt_state.startswith("CANCEL_")
                and stored_hash
                and stored_hash != _sha256(idempotency_key)
            ):
                raise RuntimeError("cancel_idempotency_conflict")
        return self._record(attempt)

    def prepare_materialization(
        self,
        command: MaterializationPrepareCommand,
    ) -> FollowUpMaterializationRecord:
        candidate = command.candidate
        native_command = NativeMaterializationCommand(
            source_client_order_id=candidate.source_client_order_id,
            root_client_order_id=candidate.root_client_order_id,
            follow_up_intent_id=candidate.attached_intent_id,
            actor_id=command.actor_id,
            roles=tuple(command.roles),
            environment=candidate.environment,
            idempotency_key=command.idempotency_key,
            correlation_id=command.correlation_id,
            operator_intent=command.operator_intent,
            audit_id=command.audit_id,
            payload_sha256=command.request_sha256,
            product_id=candidate.product_id,
            child_side=candidate.child_side,
            base_size=candidate.base_size,
            limit_price=candidate.limit_price,
            portfolio_id=candidate.portfolio_id,
        )
        result = self.native_repository.prepare_materialization(native_command)
        return self._record(result.attempt)

    def mark_create_invocation_started(
        self,
        *,
        materialization_id: str,
        correlation_id: str,
    ) -> InvocationBoundaryClaim:
        del correlation_id
        transition = self.native_repository.mark_create_invocation_started(
            materialization_id
        )
        return InvocationBoundaryClaim(
            record=self._record(transition.attempt),
            claimed=not bool(transition.replayed),
        )

    def record_create_result(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
    ) -> FollowUpMaterializationRecord:
        outcome = {
            (ExchangeInvocationOutcome.ACCEPTED, ChildExchangeState.ACTIVE): (
                "CREATE_ACCEPTED_NONTERMINAL"
            ),
            (ExchangeInvocationOutcome.ACCEPTED, ChildExchangeState.TERMINAL): (
                "CREATE_ACCEPTED_TERMINAL"
            ),
            (ExchangeInvocationOutcome.REJECTED, ChildExchangeState.UNKNOWN): (
                "CREATE_EXPLICITLY_REJECTED"
            ),
            (ExchangeInvocationOutcome.UNKNOWN, ChildExchangeState.UNKNOWN): (
                "CREATE_UNKNOWN_CONSUMED"
            ),
        }.get((result.outcome, result.child_state))
        if outcome is None:
            raise RuntimeError("create_result_invalid")
        transition = self.native_repository.record_create_result(
            materialization_id,
            outcome=outcome,
            diagnostic_code=result.diagnostic_code,
            exchange_order_id_sha256=result.exchange_order_id_sha256,
        )
        return self._record(transition.attempt)

    def mark_cancel_invocation_started(
        self,
        *,
        materialization_id: str,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        audit_id: str,
    ) -> InvocationBoundaryClaim:
        transition = self.native_repository.mark_cancel_invocation_started(
            materialization_id,
            operation_idempotency_key=idempotency_key,
            actor_id=actor_id,
            roles=roles,
            environment=environment,
            operator_intent=operator_intent,
            correlation_id=correlation_id,
            operation_audit_id=audit_id,
        )
        return InvocationBoundaryClaim(
            record=self._record(transition.attempt),
            claimed=not bool(transition.replayed),
        )

    def record_cancel_result(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
    ) -> FollowUpMaterializationRecord:
        outcome = {
            (ExchangeInvocationOutcome.ACCEPTED, ChildExchangeState.ACTIVE): (
                "CANCEL_ACCEPTED_NONTERMINAL"
            ),
            (ExchangeInvocationOutcome.ACCEPTED, ChildExchangeState.TERMINAL): (
                "CANCEL_ACCEPTED_TERMINAL"
            ),
            (ExchangeInvocationOutcome.REJECTED, ChildExchangeState.ACTIVE): (
                "CANCEL_EXPLICITLY_REJECTED"
            ),
            (ExchangeInvocationOutcome.UNKNOWN, ChildExchangeState.UNKNOWN): (
                "CANCEL_UNKNOWN_CONSUMED"
            ),
        }.get((result.outcome, result.child_state))
        if outcome is None:
            raise RuntimeError("cancel_result_invalid")
        transition = self.native_repository.record_cancel_result(
            materialization_id,
            outcome=outcome,
            diagnostic_code=result.diagnostic_code,
            exchange_order_id_sha256=result.exchange_order_id_sha256,
        )
        return self._record(transition.attempt)

    def record_child_terminal_without_cancel(
        self,
        *,
        materialization_id: str,
        result: PersistedInvocationResult,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        audit_id: str,
    ) -> FollowUpMaterializationRecord:
        if (
            result.outcome is not ExchangeInvocationOutcome.NOT_REQUIRED_TERMINAL
            or result.child_state is not ChildExchangeState.TERMINAL
        ):
            raise RuntimeError("cancel_result_invalid")
        transition = self.native_repository.record_child_terminal_without_cancel(
            materialization_id,
            diagnostic_code=result.diagnostic_code,
            exchange_order_id_sha256=result.exchange_order_id_sha256,
            operation_idempotency_key=idempotency_key,
            actor_id=actor_id,
            roles=roles,
            environment=environment,
            operator_intent=operator_intent,
            correlation_id=result.correlation_id,
            operation_audit_id=audit_id,
        )
        return self._record(transition.attempt)


@dataclass(frozen=True, slots=True)
class _PreparedChildPlan:
    target_movement: Decimal
    target_movement_type: str


@dataclass(frozen=True, slots=True)
class _PendingRawExchangeEvidence:
    """Process-local exact identity awaiting a durable local projection."""

    materialization_id: str
    child_client_order_id: str
    operation_audit_id: str
    operation_idempotency_key_sha256: str
    authoritative_order_status: str
    exchange_order_id: str


def _pending_evidence_key(
    *,
    materialization_id: str,
    child_client_order_id: str,
    operation_audit_id: str,
    operation_idempotency_key_sha256: str,
) -> tuple[str, str, str, str]:
    return (
        _text(materialization_id),
        _text(child_client_order_id),
        _text(operation_audit_id),
        _text(operation_idempotency_key_sha256).lower(),
    )


class ProductionFollowUpMaterializationRuntime:
    """Run one fresh, no-retry eligibility/reconciliation pass."""

    def __init__(
        self,
        *,
        native_repository: Any,
        rest_client: Any | None,
        configured_portfolio_id: str,
        environment: str = "local",
        runtime_authority_check: Callable[[], bool],
        local_order_reader: Callable[[str], Any],
        template_resolver: Callable[[str, str], Any],
        product_reader: Callable[[str], Any],
        portfolio_binding_evaluator: Callable[[Any, str], Any],
        source_order_readback: Callable[..., Mapping[str, Any]],
        source_fill_readback: Callable[..., Mapping[str, Any]],
        market_reference_reader: Callable[[str], Any],
        standing_price_evaluator: Callable[..., Mapping[str, Any]],
        wallet_reader: Callable[[], Any],
        action_guard_evaluator: Callable[..., Any],
        child_persister: Callable[[Mapping[str, Any]], Any],
        local_stealth_reader: Callable[[str], Any],
        local_state_transitioner: Callable[..., Any] | None = None,
        pending_raw_exchange_evidence: (
            dict[tuple[str, str, str, str], _PendingRawExchangeEvidence] | None
        ) = None,
    ) -> None:
        self.native_repository = native_repository
        self.rest_client = rest_client
        self.configured_portfolio_id = _text(configured_portfolio_id)
        self.environment = _text(environment) or "local"
        self.runtime_authority_check = runtime_authority_check
        self.local_order_reader = local_order_reader
        self.template_resolver = template_resolver
        self.product_reader = product_reader
        self.portfolio_binding_evaluator = portfolio_binding_evaluator
        self.source_order_readback = source_order_readback
        self.source_fill_readback = source_fill_readback
        self.market_reference_reader = market_reference_reader
        self.standing_price_evaluator = standing_price_evaluator
        self.wallet_reader = wallet_reader
        self.action_guard_evaluator = action_guard_evaluator
        self.child_persister = child_persister
        self.local_stealth_reader = local_stealth_reader
        self.local_state_transitioner = local_state_transitioner
        self.pending_raw_exchange_evidence = (
            pending_raw_exchange_evidence
            if pending_raw_exchange_evidence is not None
            else {}
        )
        self._prepared_plans: dict[str, _PreparedChildPlan] = {}

    @staticmethod
    def _evidence(
        *,
        candidate: BackendMaterializationCandidate | None,
        blockers: tuple[str, ...] = (),
        ambiguous: bool = False,
        fresh: bool = True,
        coinbase_read_started: bool = False,
    ) -> FreshMaterializationEligibility:
        return FreshMaterializationEligibility(
            candidate=candidate,
            fresh=fresh,
            eligibility_pass_count=1,
            reconciliation_pass_count=1,
            individual_retry_count=0,
            ambiguous=ambiguous,
            blockers=blockers,
            coinbase_read_started=coinbase_read_started,
        )

    def resolve_fresh_materialization_eligibility(
        self,
        *,
        source_client_order_id: str,
    ) -> FreshMaterializationEligibility:
        source_id = _text(source_client_order_id)
        coinbase_read_started = False

        def evidence(**kwargs: Any) -> FreshMaterializationEligibility:
            return self._evidence(
                **kwargs,
                coinbase_read_started=coinbase_read_started,
            )

        try:
            local_readback = self.native_repository.read_materialization(source_id)
            readiness = local_readback.readiness
            attempt = getattr(local_readback, "attempt", None)
            blockers = tuple(getattr(readiness, "blockers", ()) or ())
            resumable_prepared = bool(
                attempt is not None
                and _native_state(attempt.current_state) == "KNOWN_NOT_INVOKED"
                and set(blockers).issubset(
                    {
                        "follow_up_materialization_already_prepared",
                        "source_follow_up_child_already_exists",
                    }
                )
            )
            if blockers and not resumable_prepared:
                return evidence(candidate=None, blockers=blockers)
            if not bool(getattr(readiness, "eligible", False)) and not resumable_prepared:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_local_state_blocked",),
                )
            if self.runtime_authority_check() is not True:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_controlled_live_required",),
                )
            if self.rest_client is None:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_rest_client_unavailable",),
                )
            if not self.configured_portfolio_id:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_test_portfolio_required",),
                )

            source = _mapping(self.local_order_reader(source_id))
            if not source or _text(source.get("client_order_id")) != source_id:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_source_order_unavailable",),
                )
            root_id = _text(getattr(readiness, "root_client_order_id", ""))
            intent_id = _text(getattr(readiness, "follow_up_intent_id", ""))
            child_id = _text(
                getattr(readiness, "deterministic_child_client_order_id", "")
            )
            product_id = _text(getattr(readiness, "product_id", ""))
            source_side = _upper(getattr(readiness, "source_side", ""))
            child_side = _upper(getattr(readiness, "derived_follow_up_side", ""))
            source_size = _decimal(getattr(readiness, "base_size", None))
            exchange_order_id = _text(source.get("exchange_order_id"))
            if not all((root_id, intent_id, child_id, product_id, exchange_order_id)):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_source_identity_incomplete",),
                )

            if (
                resumable_prepared
                and "source_follow_up_child_already_exists" in blockers
            ):
                preclaimed_child = _mapping(self.local_order_reader(child_id))
                if not (
                    _text(preclaimed_child.get("client_order_id")) == child_id
                    and _text(preclaimed_child.get("product_id")) == product_id
                    and _upper(preclaimed_child.get("side")) == child_side
                    and _decimal(preclaimed_child.get("size")) == source_size
                    and _text(preclaimed_child.get("parent_order_id")) == root_id
                    and _text(preclaimed_child.get("retail_portfolio_id"))
                    == self.configured_portfolio_id
                    and not _text(preclaimed_child.get("exchange_order_id"))
                ):
                    return evidence(
                        candidate=None,
                        blockers=(
                            "follow_up_materialization_preclaimed_child_mismatch",
                        ),
                    )
            if (
                _upper(source.get("status")) != "FILLED"
                or _text(source.get("product_id")) != product_id
                or _upper(source.get("side")) != source_side
                or _text(source.get("retail_portfolio_id"))
                != self.configured_portfolio_id
                or source_size is None
                or source_size <= 0
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_source_state_mismatch",),
                )

            coinbase_read_started = True
            binding = self.portfolio_binding_evaluator(
                self.rest_client,
                self.configured_portfolio_id,
            )
            if (
                getattr(binding, "ready", False) is not True
                or _text(getattr(binding, "observed_portfolio_id", ""))
                != self.configured_portfolio_id
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_test_portfolio_required",),
                )

            product = _mapping(self.product_reader(product_id))
            observed_product_id = _text(
                product.get("product_id") or product.get("id")
            )
            product_type = _upper(product.get("product_type"))
            disabled = product.get("trading_disabled") is True or product.get(
                "is_disabled"
            ) is True
            base_increment = _decimal(
                product.get("base_increment") or product.get("base_size_increment")
            )
            quote_increment = _decimal(
                product.get("quote_increment") or product.get("price_increment")
            )
            if (
                observed_product_id != product_id
                or product_type != "SPOT"
                or not is_concrete_usdc_spot_product(product_id)
                or disabled
                or base_increment is None
                or quote_increment is None
                or base_increment <= 0
                or quote_increment <= 0
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_product_policy_blocked",),
                )

            order_readback = dict(
                self.source_order_readback(
                    self.rest_client,
                    client_order_id=source_id,
                    exchange_order_id=exchange_order_id,
                    product_id=product_id,
                    product_type="SPOT",
                    expected_retail_portfolio_id=self.configured_portfolio_id,
                )
            )
            matched_order = _mapping(order_readback.get("matched_order"))
            observed_filled_size = _decimal(
                matched_order.get("filled_size")
                or matched_order.get("filled_quantity")
            )
            if (
                order_readback.get("authoritative") is not True
                or order_readback.get("exact_identity_match") is not True
                or _upper(order_readback.get("authoritative_status")) != "FILLED"
                or order_readback.get("retail_portfolio_id_matches_expected")
                is not True
                or _text(order_readback.get("exchange_order_id"))
                != exchange_order_id
                or _text(matched_order.get("client_order_id")) != source_id
                or _text(matched_order.get("product_id")) != product_id
                or _upper(matched_order.get("side")) != source_side
                or observed_filled_size != source_size
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_authoritative_fill_required",),
                )

            fill_readback = dict(
                self.source_fill_readback(
                    self.rest_client,
                    exchange_order_id=exchange_order_id,
                    product_id=product_id,
                )
            )
            if not (
                fill_readback.get("authoritative") is True
                and fill_readback.get("fill_read_succeeded") is True
                and fill_readback.get("pagination_complete") is True
                and int(fill_readback.get("fill_count") or 0) > 0
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_authoritative_fill_required",),
                )

            template = _mapping(self.template_resolver(source_id, root_id))
            template_size = _decimal(
                template.get("order_base_size") or template.get("base_size")
            )
            limit_price = _decimal(
                template.get("start_price") or template.get("limit_price")
            )
            if (
                _text(template.get("product_id")) != product_id
                or _upper(template.get("side")) != child_side
                or (source_side, child_side) not in {
                    ("BUY", "SELL"),
                    ("SELL", "BUY"),
                }
                or template_size != source_size
                or limit_price is None
                or limit_price <= 0
                or source_size % base_increment != 0
                or limit_price % quote_increment != 0
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_order_tuple_invalid",),
                )
            submitted_notional = source_size * limit_price
            if (
                submitted_notional <= 0
                or submitted_notional > CURRENT_MAX_SUBMITTED_NOTIONAL_USDC
                or submitted_notional > CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC
            ):
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_current_caps_exceeded",),
                )

            market = _mapping(self.market_reference_reader(product_id))
            standing = dict(
                self.standing_price_evaluator(
                    side=child_side,
                    limit_price=limit_price,
                    best_bid=market.get("best_bid"),
                    market_source=market.get("source"),
                    market_observed_at=market.get("observed_at"),
                )
            )
            if standing.get("allowed") is not True:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_standing_price_blocked",),
                )

            wallets = self.wallet_reader()
            wallets_mapping = _mapping(wallets)
            currencies = product_id.split("-")
            if len(currencies) != 2:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_wallet_blocked",),
                )
            required_currency = (
                currencies[0].upper() if child_side == "SELL" else currencies[1].upper()
            )
            required_amount = source_size if child_side == "SELL" else submitted_notional
            if _wallet_available(wallets_mapping.get(required_currency)) < required_amount:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_wallet_blocked",),
                )
            guard_result = self.action_guard_evaluator(
                product_id=product_id,
                side=child_side,
                size=source_size,
                limit_price=limit_price,
                client_order_id=child_id,
                parent_order_id=root_id,
                wallets=wallets,
            )
            guard_allowed = (
                guard_result[0]
                if isinstance(guard_result, tuple) and guard_result
                else guard_result
            )
            if guard_allowed is not True:
                return evidence(
                    candidate=None,
                    blockers=("follow_up_materialization_action_guard_blocked",),
                )

            target_movement = _decimal(template.get("target_movement"))
            if target_movement is None:
                target_movement = _decimal(source.get("target_movement"))
            if target_movement is None:
                target_movement = Decimal("0")
            self._prepared_plans[child_id] = _PreparedChildPlan(
                target_movement=target_movement,
                target_movement_type=(
                    _text(template.get("target_movement_type"))
                    or _text(source.get("target_movement_type"))
                    or "P"
                ),
            )
            candidate = BackendMaterializationCandidate(
                attached_intent_id=intent_id,
                source_client_order_id=source_id,
                root_client_order_id=root_id,
                child_client_order_id=child_id,
                source_status="FILLED",
                source_side=source_side,
                child_side=child_side,
                product_id=product_id,
                product_type="SPOT",
                portfolio_type="TEST",
                portfolio_id=self.configured_portfolio_id,
                portfolio_scope_sha256=_sha256(self.configured_portfolio_id),
                environment=self.environment,
                base_size=source_size,
                limit_price=limit_price,
                submitted_notional_usdc=submitted_notional,
                max_submitted_notional_usdc=CURRENT_MAX_SUBMITTED_NOTIONAL_USDC,
                max_executed_notional_usdc=CURRENT_MAX_EXECUTED_NOTIONAL_USDC,
                effective_notional_cap_usdc=CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC,
                authoritative_source_fill_proven=True,
                source_terminal=True,
                attached_intent_requires_fresh_authorization=True,
                no_existing_follow_up_child=True,
                controlled_live_enabled=True,
                execution_lease_valid=True,
                approved_test_portfolio_verified=True,
                product_policy_allowed=True,
                action_condition_guard_passed=True,
                wallet_check_passed=True,
            )
            return evidence(candidate=candidate)
        except Exception:
            return evidence(
                candidate=None,
                blockers=("follow_up_materialization_eligibility_unavailable",),
                ambiguous=True,
                fresh=False,
            )

    def persist_preclaimed_child(
        self,
        *,
        candidate: BackendMaterializationCandidate,
        materialization_id: str,
    ) -> LocalChildPersistenceEvidence:
        plan = self._prepared_plans.get(candidate.child_client_order_id)
        if plan is None:
            raise RuntimeError("follow_up_materialization_preclaim_plan_missing")
        materialization_binding = _sha256(materialization_id)
        order = {
            "stealth_order_id": candidate.child_client_order_id,
            "product_id": candidate.product_id,
            "side": candidate.child_side,
            "total_size": candidate.base_size,
            # A prepared claim must never be discoverable by an automatic
            # reveal worker before the explicit one-use Create boundary.
            "remaining_size": Decimal("0"),
            "limit_price": candidate.limit_price,
            "status": "HIDDEN",
            "reveal_condition_type": "time_delay",
            "reveal_condition_json": {
                "type": "time_delay",
                "delay_seconds": 315360000,
                "operator_materialization_quarantine": True,
                "materialization_binding_sha256": materialization_binding,
            },
            "sizing_strategy_json": {"type": "fixed"},
            "reason": "operator_follow_up_materialization_preclaim",
            "notes": "Quarantined pending explicit operator Create",
            "parent_order_id": candidate.root_client_order_id,
            "anchor_repricing_policy_json": {"enabled": False},
            "anchor_repricing_state_json": {
                "operator_materialization_quarantine": True,
                "materialization_binding_sha256": materialization_binding,
            },
            "cancel_reentry_policy_json": {"enabled": False},
            "cancel_reentry_state_json": {},
            "post_fill_retreat_policy_json": {"enabled": False},
        }
        result = self.child_persister(order=order)
        if not (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[0], int)
            and result[0] > 0
        ):
            raise RuntimeError("follow_up_materialization_child_persistence_invalid")
        child = _mapping(self.local_order_reader(candidate.child_client_order_id))
        stealth = _mapping(
            self.local_stealth_reader(candidate.child_client_order_id)
        )
        reveal_condition = _json_mapping(stealth.get("reveal_condition_json"))
        anchor_state = _json_mapping(
            stealth.get("anchor_repricing_state_json")
        )
        revealed_orders = stealth.get("revealed_orders")
        if isinstance(revealed_orders, str):
            try:
                revealed_orders = json.loads(revealed_orders)
            except (TypeError, ValueError):
                revealed_orders = ["invalid"]
        if not (
            _text(child.get("client_order_id")) == candidate.child_client_order_id
            and _text(child.get("product_id")) == candidate.product_id
            and _upper(child.get("side")) == candidate.child_side
            and _decimal(child.get("size")) == candidate.base_size
            and _decimal(child.get("price")) == candidate.limit_price
            and _text(child.get("parent_order_id")) == candidate.root_client_order_id
            and _text(child.get("retail_portfolio_id"))
            == candidate.portfolio_id
            and not _text(child.get("exchange_order_id"))
            and _text(stealth.get("stealth_order_id"))
            == candidate.child_client_order_id
            and _text(stealth.get("product_id")) == candidate.product_id
            and _upper(stealth.get("side")) == candidate.child_side
            and _decimal(stealth.get("total_size")) == candidate.base_size
            and _decimal(stealth.get("remaining_size")) == Decimal("0")
            and _decimal(stealth.get("limit_price")) == candidate.limit_price
            and _upper(stealth.get("status")) == "HIDDEN"
            and _text(stealth.get("parent_order_id"))
            == candidate.root_client_order_id
            and reveal_condition.get("operator_materialization_quarantine")
            is True
            and _text(reveal_condition.get("materialization_binding_sha256"))
            == materialization_binding
            and anchor_state.get("operator_materialization_quarantine") is True
            and _text(anchor_state.get("materialization_binding_sha256"))
            == materialization_binding
            and not _text(anchor_state.get("active_placement_client_order_id"))
            and not _text(anchor_state.get("active_exchange_order_id"))
            and not revealed_orders
        ):
            raise RuntimeError("follow_up_materialization_child_persistence_invalid")
        return LocalChildPersistenceEvidence(
            materialization_id=materialization_id,
            child_client_order_id=candidate.child_client_order_id,
            persisted=True,
            exact_replay_safe=True,
            exchange_call_ran=False,
        )

    def read_authoritative_child_state(
        self,
        *,
        child_client_order_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ChildStateEvidence:
        child_id = _text(child_client_order_id)
        coinbase_read_started = False
        try:
            if not (
                _text(materialization_id)
                and _text(operation_audit_id)
                and _is_sha256(operation_idempotency_key_sha256)
            ):
                raise RuntimeError("operation_binding_invalid")
            if self.runtime_authority_check() is not True or self.rest_client is None:
                raise RuntimeError("runtime_unavailable")
            coinbase_read_started = True
            binding = self.portfolio_binding_evaluator(
                self.rest_client,
                self.configured_portfolio_id,
            )
            if getattr(binding, "ready", False) is not True:
                raise RuntimeError("portfolio_unavailable")
            child = _mapping(self.local_order_reader(child_id))
            stored_exchange_order_id = _text(child.get("exchange_order_id"))
            product_id = _text(child.get("product_id"))
            side = _upper(child.get("side"))
            base_size = _decimal(child.get("size"))
            limit_price = _decimal(child.get("price"))
            if not (
                _text(child.get("client_order_id")) == child_id
                and is_concrete_usdc_spot_product(product_id)
                and side in {"BUY", "SELL"}
                and base_size is not None
                and base_size > 0
                and limit_price is not None
                and limit_price > 0
                and _text(child.get("retail_portfolio_id"))
                == self.configured_portfolio_id
            ):
                raise RuntimeError("child_identity_unavailable")
            readback = dict(
                self.source_order_readback(
                    self.rest_client,
                    client_order_id=child_id,
                    exchange_order_id=stored_exchange_order_id or None,
                    product_id=product_id,
                    product_type="SPOT",
                    expected_retail_portfolio_id=self.configured_portfolio_id,
                )
            )
            status = _upper(readback.get("authoritative_status"))
            verified_exchange_order_id = _text(readback.get("exchange_order_id"))
            authoritative, validated_status = _exact_limit_gtc_order_tuple(
                readback,
                client_order_id=child_id,
                exchange_order_id=verified_exchange_order_id,
                product_id=product_id,
                side=side,
                base_size=base_size,
                limit_price=limit_price,
            )
            authoritative = bool(
                authoritative
                and verified_exchange_order_id
                and validated_status == status
                and (
                    not stored_exchange_order_id
                    or verified_exchange_order_id == stored_exchange_order_id
                )
            )
            if status in _ACTIVE_EXCHANGE_STATUSES:
                state = ChildExchangeState.ACTIVE
            elif status in _TERMINAL_EXCHANGE_STATUSES:
                state = ChildExchangeState.TERMINAL
            else:
                state = ChildExchangeState.UNKNOWN
                authoritative = False
            if not authoritative:
                state = ChildExchangeState.UNKNOWN
            if authoritative:
                binding_key = _pending_evidence_key(
                    materialization_id=materialization_id,
                    child_client_order_id=child_id,
                    operation_audit_id=operation_audit_id,
                    operation_idempotency_key_sha256=(
                        operation_idempotency_key_sha256
                    ),
                )
                self.pending_raw_exchange_evidence[binding_key] = (
                    _PendingRawExchangeEvidence(
                        materialization_id=_text(materialization_id),
                        child_client_order_id=child_id,
                        operation_audit_id=_text(operation_audit_id),
                        operation_idempotency_key_sha256=_text(
                            operation_idempotency_key_sha256
                        ).lower(),
                        authoritative_order_status=status,
                        exchange_order_id=verified_exchange_order_id,
                    )
                )
            return ChildStateEvidence(
                child_client_order_id=child_id,
                state=state,
                fresh=True,
                authoritative=authoritative,
                read_count=1,
                individual_retry_count=0,
                ambiguous=not authoritative,
                coinbase_read_started=coinbase_read_started,
                exchange_order_id_sha256=(
                    _sha256(verified_exchange_order_id)
                    if authoritative
                    else None
                ),
            )
        except Exception:
            return ChildStateEvidence(
                child_client_order_id=child_id,
                state=ChildExchangeState.UNKNOWN,
                fresh=False,
                authoritative=False,
                read_count=1,
                individual_retry_count=0,
                ambiguous=True,
                coinbase_read_started=coinbase_read_started,
            )

    def project_persisted_child_state(
        self,
        *,
        record: FollowUpMaterializationRecord,
        operation: Literal[
            "CREATE",
            "CANCEL",
            "TERMINAL_READ",
            "REPLAY_REPAIR",
        ],
        allow_reconciliation_read: bool,
    ) -> LocalChildProjectionEvidence:
        """Project one already-journaled result into both local child rows."""

        if self.local_state_transitioner is None:
            raise RuntimeError("follow_up_materialization_projection_unavailable")
        if operation not in {
            "CREATE",
            "CANCEL",
            "TERMINAL_READ",
            "REPLAY_REPAIR",
        }:
            raise RuntimeError("follow_up_materialization_projection_invalid")
        if not isinstance(allow_reconciliation_read, bool):
            raise RuntimeError("follow_up_materialization_projection_invalid")

        readback = self.native_repository.read_materialization(
            record.source_client_order_id
        )
        attempt = getattr(readback, "attempt", None)
        if attempt is None:
            raise RuntimeError("follow_up_materialization_projection_unavailable")
        native_state = _native_state(getattr(attempt, "current_state", ""))
        projected_state, _child_state, _diagnostic = _native_to_kernel_state(
            native_state
        )
        operation_audit_id = _text(
            getattr(attempt, "current_operation_audit_id", "")
        ) or _text(getattr(attempt, "audit_id", ""))
        operation_key_hash = _text(
            getattr(attempt, "operation_idempotency_key_sha256", "")
        ).lower()
        durable_exchange_hash = _text(
            getattr(attempt, "exchange_order_id_sha256", "")
        ).lower()
        if durable_exchange_hash and not _is_sha256(durable_exchange_hash):
            raise RuntimeError("follow_up_materialization_projection_invalid")
        if not (
            _text(getattr(attempt, "materialization_id", ""))
            == record.materialization_id
            and _text(getattr(attempt, "source_client_order_id", ""))
            == record.source_client_order_id
            and _text(getattr(attempt, "child_client_order_id", ""))
            == record.child_client_order_id
            and projected_state is record.state
            and operation_audit_id == record.audit_id
            and _is_sha256(operation_key_hash)
        ):
            raise RuntimeError("follow_up_materialization_projection_invalid")

        exact_key = _pending_evidence_key(
            materialization_id=record.materialization_id,
            child_client_order_id=record.child_client_order_id,
            operation_audit_id=operation_audit_id,
            operation_idempotency_key_sha256=operation_key_hash,
        )
        pending_key = exact_key
        pending = self.pending_raw_exchange_evidence.get(exact_key)
        if pending is None and operation == "TERMINAL_READ":
            for candidate_key, candidate_evidence in tuple(
                self.pending_raw_exchange_evidence.items()
            ):
                if (
                    candidate_evidence.materialization_id
                    == record.materialization_id
                    and candidate_evidence.child_client_order_id
                    == record.child_client_order_id
                    and (
                        not durable_exchange_hash
                        or _sha256(candidate_evidence.exchange_order_id)
                        == durable_exchange_hash
                    )
                ):
                    pending_key = candidate_key
                    pending = candidate_evidence
                    break

        live_read_count = 0
        child = _mapping(self.local_order_reader(record.child_client_order_id))
        local_exchange_id = _text(child.get("exchange_order_id"))
        local_status = _upper(child.get("status"))
        local_pending = None
        if (
            _text(child.get("client_order_id"))
            == record.child_client_order_id
            and local_exchange_id
            and (
                not durable_exchange_hash
                or _sha256(local_exchange_id) == durable_exchange_hash
            )
        ):
            local_pending = _PendingRawExchangeEvidence(
                materialization_id=record.materialization_id,
                child_client_order_id=record.child_client_order_id,
                operation_audit_id=operation_audit_id,
                operation_idempotency_key_sha256=operation_key_hash,
                authoritative_order_status=local_status,
                exchange_order_id=local_exchange_id,
            )
        if (
            operation == "REPLAY_REPAIR"
            and record.state is MaterializationRecordState.CREATE_ACCEPTED
            and local_pending is not None
        ):
            pending = local_pending
        elif pending is None:
            pending = local_pending

        needs_exact_identity = record.state in {
            MaterializationRecordState.CREATE_ACCEPTED,
            MaterializationRecordState.CANCEL_ACCEPTED,
            MaterializationRecordState.CANCEL_REJECTED,
            MaterializationRecordState.CANCEL_UNKNOWN,
            MaterializationRecordState.CHILD_ALREADY_TERMINAL,
        }
        force_unknown_reconciliation = bool(
            operation == "REPLAY_REPAIR"
            and record.state
            in {
                MaterializationRecordState.CREATE_UNKNOWN,
                MaterializationRecordState.CANCEL_UNKNOWN,
            }
            and allow_reconciliation_read
        )
        if (
            (pending is None and needs_exact_identity)
            or force_unknown_reconciliation
        ) and allow_reconciliation_read:
            child_evidence = self.read_authoritative_child_state(
                child_client_order_id=record.child_client_order_id,
                materialization_id=record.materialization_id,
                operation_audit_id=operation_audit_id,
                operation_idempotency_key_sha256=operation_key_hash,
            )
            live_read_count = 1
            if (
                child_evidence.authoritative is not True
                or child_evidence.ambiguous is True
                or child_evidence.read_count != 1
                or child_evidence.individual_retry_count != 0
                or child_evidence.exchange_order_id_sha256 is None
                or (
                    durable_exchange_hash
                    and child_evidence.exchange_order_id_sha256
                    != durable_exchange_hash
                )
            ):
                raise RuntimeError(
                    "follow_up_materialization_projection_reconciliation_invalid"
                )
            pending_key = exact_key
            pending = self.pending_raw_exchange_evidence.get(exact_key)

        exchange_order_id = pending.exchange_order_id if pending is not None else None
        authoritative_status = (
            pending.authoritative_order_status if pending is not None else ""
        )
        if exchange_order_id and durable_exchange_hash:
            if _sha256(exchange_order_id) != durable_exchange_hash:
                raise RuntimeError("follow_up_materialization_projection_hash_mismatch")
        if durable_exchange_hash and not exchange_order_id:
            raise RuntimeError("follow_up_materialization_projection_identity_missing")

        if operation == "TERMINAL_READ":
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL
            )
        elif record.state is MaterializationRecordState.CREATE_REJECTED:
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED
            )
            authoritative_status = "FAILED"
            exchange_order_id = None
        elif record.state is MaterializationRecordState.CREATE_UNKNOWN:
            if operation == "REPLAY_REPAIR" and pending is not None:
                transition_kind = (
                    FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL
                    if _upper(authoritative_status)
                    in _TERMINAL_EXCHANGE_STATUSES
                    else FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE
                )
            else:
                transition_kind = (
                    FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED
                )
                authoritative_status = "SUBMISSION_UNKNOWN"
                exchange_order_id = None
        elif record.state is MaterializationRecordState.CREATE_ACCEPTED:
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL
                if record.child_state is ChildExchangeState.TERMINAL
                else FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE
            )
        elif record.state is MaterializationRecordState.CANCEL_REJECTED:
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.CANCEL_EXPLICITLY_REJECTED_ACTIVE
            )
        elif record.state is MaterializationRecordState.CANCEL_ACCEPTED:
            if (
                record.child_state is not ChildExchangeState.TERMINAL
                or _upper(authoritative_status) not in _TERMINAL_EXCHANGE_STATUSES
            ):
                raise RuntimeError("follow_up_materialization_projection_invalid")
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL
            )
        elif record.state is MaterializationRecordState.CANCEL_UNKNOWN:
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL
                if operation == "REPLAY_REPAIR"
                and pending is not None
                and _upper(authoritative_status) in _TERMINAL_EXCHANGE_STATUSES
                else FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED
            )
        elif record.state is MaterializationRecordState.CHILD_ALREADY_TERMINAL:
            transition_kind = (
                FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL
            )
        else:
            raise RuntimeError("follow_up_materialization_projection_invalid")

        def apply_local_transition(
            kind: FollowUpMaterializedChildTransitionKind,
            status: str,
            raw_exchange_order_id: str | None,
            *,
            evidence_audit_id: str = operation_audit_id,
            evidence_key_hash: str = operation_key_hash,
        ) -> None:
            if not _text(status):
                raise RuntimeError(
                    "follow_up_materialization_projection_status_missing"
                )
            transition = self.local_state_transitioner(
                materialization_id=record.materialization_id,
                transition_kind=kind.value,
                authoritative_order_status=status,
                exchange_order_id=raw_exchange_order_id,
                operation_audit_id=evidence_audit_id,
                operation_idempotency_key_sha256=evidence_key_hash,
            )
            local_record = getattr(transition, "record", None)
            if not (
                local_record is not None
                and _text(getattr(local_record, "materialization_id", ""))
                == record.materialization_id
                and _text(getattr(local_record, "child_client_order_id", ""))
                == record.child_client_order_id
                and _text(getattr(local_record, "transition_kind", ""))
                == kind.value
                and _upper(
                    getattr(local_record, "authoritative_order_status", "")
                )
                == _upper(status)
                and _text(getattr(local_record, "operation_audit_id", ""))
                == evidence_audit_id
                and _text(
                    getattr(
                        local_record,
                        "operation_idempotency_key_sha256",
                        "",
                    )
                ).lower()
                == evidence_key_hash
                and (
                    _text(
                        getattr(local_record, "exchange_order_id_sha256", "")
                    ).lower()
                    or None
                )
                == (
                    _sha256(raw_exchange_order_id)
                    if raw_exchange_order_id
                    else None
                )
            ):
                raise RuntimeError(
                    "follow_up_materialization_projection_invalid"
                )

        if transition_kind is (
            FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL
        ):
            latest_projection = (
                self.native_repository.read_latest_materialized_child_local_state(
                    record.materialization_id
                )
            )
            if latest_projection is None:
                prior_events = tuple(
                    self.native_repository.list_materialization_events(
                        record.materialization_id
                    )
                )
                predecessor = next(
                    (
                        event
                        for event in reversed(prior_events)
                        if _native_state(getattr(event, "state", ""))
                        in {
                            "CREATE_ACCEPTED_NONTERMINAL",
                            "CREATE_ACCEPTED_TERMINAL",
                            "CREATE_UNKNOWN_CONSUMED",
                        }
                    ),
                    None,
                )
                if predecessor is None:
                    raise RuntimeError(
                        "follow_up_materialization_projection_predecessor_missing"
                    )
                predecessor_state = _native_state(predecessor.state)
                predecessor_audit_id = _text(predecessor.operation_audit_id)
                predecessor_key_hash = _text(
                    predecessor.operation_idempotency_key_sha256
                ).lower()
                if not (
                    predecessor_audit_id and _is_sha256(predecessor_key_hash)
                ):
                    raise RuntimeError(
                        "follow_up_materialization_projection_predecessor_invalid"
                    )
                if predecessor_state == "CREATE_UNKNOWN_CONSUMED":
                    apply_local_transition(
                        FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED,
                        "SUBMISSION_UNKNOWN",
                        None,
                        evidence_audit_id=predecessor_audit_id,
                        evidence_key_hash=predecessor_key_hash,
                    )
                elif predecessor_state == "CREATE_ACCEPTED_NONTERMINAL":
                    apply_local_transition(
                        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE,
                        "PENDING",
                        exchange_order_id,
                        evidence_audit_id=predecessor_audit_id,
                        evidence_key_hash=predecessor_key_hash,
                    )
                else:
                    apply_local_transition(
                        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL,
                        authoritative_status,
                        exchange_order_id,
                        evidence_audit_id=predecessor_audit_id,
                        evidence_key_hash=predecessor_key_hash,
                    )

        if transition_kind in {
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE,
            FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL,
        }:
            latest_projection = (
                self.native_repository.read_latest_materialized_child_local_state(
                    record.materialization_id
                )
            )
            latest_kind = _upper(
                getattr(latest_projection, "transition_kind", "")
            )
            if record.state is MaterializationRecordState.CREATE_UNKNOWN:
                required_predecessor = (
                    FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED
                )
                if not latest_kind:
                    apply_local_transition(
                        required_predecessor,
                        "SUBMISSION_UNKNOWN",
                        None,
                    )
                elif latest_kind not in {
                    required_predecessor.value,
                    transition_kind.value,
                }:
                    raise RuntimeError(
                        "follow_up_materialization_projection_predecessor_invalid"
                    )
            elif record.state is MaterializationRecordState.CANCEL_UNKNOWN:
                if local_pending is None or local_status not in _ACTIVE_EXCHANGE_STATUSES:
                    raise RuntimeError(
                        "follow_up_materialization_projection_predecessor_missing"
                    )
                required_predecessor = (
                    FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED
                )
                if latest_kind != transition_kind.value:
                    if latest_kind not in {
                        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
                        FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value,
                        required_predecessor.value,
                    }:
                        raise RuntimeError(
                            "follow_up_materialization_projection_predecessor_invalid"
                        )
                    if latest_kind != required_predecessor.value:
                        apply_local_transition(
                            required_predecessor,
                            local_status,
                            local_pending.exchange_order_id,
                        )
        apply_local_transition(
            transition_kind,
            authoritative_status,
            exchange_order_id,
        )
        if pending is not None:
            self.pending_raw_exchange_evidence.pop(pending_key, None)
        return LocalChildProjectionEvidence(
            materialization_id=record.materialization_id,
            child_client_order_id=record.child_client_order_id,
            record_state=record.state,
            projected=True,
            exact_replay_safe=True,
            exchange_call_ran=False,
            live_read_count=live_read_count,
            individual_retry_count=0,
        )


class CanonicalFollowUpMaterializationExchange:
    """Make at most one canonical Create or exact-exchange-ID Cancel call."""

    def __init__(
        self,
        *,
        rest_client: Any | None,
        runtime_authority_check: Callable[[], bool],
        local_order_reader: Callable[[str], Any],
        execution_scope_factory: Callable[[str], AbstractContextManager[Any]],
        exact_order_readback: Callable[..., Mapping[str, Any]] | None = None,
        configured_portfolio_id: str = "",
        pending_raw_exchange_evidence: (
            dict[tuple[str, str, str, str], _PendingRawExchangeEvidence] | None
        ) = None,
        inflight_scope_factory: (
            Callable[[str], AbstractContextManager[Any]] | None
        ) = None,
    ) -> None:
        self.rest_client = rest_client
        self.runtime_authority_check = runtime_authority_check
        self.local_order_reader = local_order_reader
        self.execution_scope_factory = execution_scope_factory
        self.exact_order_readback = exact_order_readback
        self.configured_portfolio_id = _text(configured_portfolio_id)
        self.pending_raw_exchange_evidence = (
            pending_raw_exchange_evidence
            if pending_raw_exchange_evidence is not None
            else {}
        )
        self.inflight_scope_factory = inflight_scope_factory or (
            lambda _operation: nullcontext()
        )

    @staticmethod
    def _unknown(
        exchange_order_id: str | None = None,
        *,
        exchange_call_started: bool = False,
    ) -> ExchangeInvocationResult:
        return ExchangeInvocationResult(
            outcome=ExchangeInvocationOutcome.UNKNOWN,
            child_state=ChildExchangeState.UNKNOWN,
            exchange_call_started=exchange_call_started,
            exchange_order_id_sha256=(
                _sha256(exchange_order_id) if exchange_order_id else None
            ),
        )

    def create_follow_up_child(
        self,
        *,
        candidate: BackendMaterializationCandidate,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ExchangeInvocationResult:
        del correlation_id
        if (
            self.rest_client is None
            or self.runtime_authority_check() is not True
            or not _text(materialization_id)
            or not _text(operation_audit_id)
            or not _is_sha256(operation_idempotency_key_sha256)
            or not self.configured_portfolio_id
            or not callable(self.exact_order_readback)
            or (
                candidate.portfolio_id != self.configured_portfolio_id
            )
        ):
            return self._unknown()
        order_configuration = {
            "limit_limit_gtc": {
                "base_size": _decimal_text(candidate.base_size),
                "limit_price": _decimal_text(candidate.limit_price),
                "post_only": False,
            }
        }
        call_started = False
        try:
            from application.admin_api.command_service import (
                coinbase_order_response_order_id,
                coinbase_order_response_success,
                coinbase_order_response_to_dict,
            )
            from core.coinbase_execution_authority import (
                COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
            )

            with self.execution_scope_factory(COINBASE_EXECUTION_SCOPE_SPOT_PLACE):
                with self.inflight_scope_factory("PLACE"):
                    call_started = True
                    response = self.rest_client.create_order(
                        product_id=candidate.product_id,
                        side=candidate.child_side,
                        client_order_id=candidate.child_client_order_id,
                        order_configuration=order_configuration,
                    )
            data = coinbase_order_response_to_dict(response)
            success = coinbase_order_response_success(response, data)
            if success is False:
                return ExchangeInvocationResult(
                    outcome=ExchangeInvocationOutcome.REJECTED,
                    child_state=ChildExchangeState.UNKNOWN,
                    exchange_call_started=True,
                )
            exchange_order_id = coinbase_order_response_order_id(response, data)
            if success is not True or not _text(exchange_order_id):
                return self._unknown(exchange_call_started=True)
            exchange_order_id = _text(exchange_order_id)
            if not _create_response_matches_candidate(
                data,
                candidate,
                exchange_order_id,
            ):
                return self._unknown(
                    exchange_order_id,
                    exchange_call_started=True,
                )
            readback = dict(
                self.exact_order_readback(
                    self.rest_client,
                    client_order_id=candidate.child_client_order_id,
                    exchange_order_id=exchange_order_id,
                    product_id=candidate.product_id,
                    product_type="SPOT",
                    expected_retail_portfolio_id=self.configured_portfolio_id,
                )
            )
            tuple_matches, authoritative_status = _exact_limit_gtc_order_tuple(
                readback,
                client_order_id=candidate.child_client_order_id,
                exchange_order_id=exchange_order_id,
                product_id=candidate.product_id,
                side=candidate.child_side,
                base_size=candidate.base_size,
                limit_price=candidate.limit_price,
            )
            if not tuple_matches:
                return self._unknown(
                    exchange_order_id,
                    exchange_call_started=True,
                )
            pending_key = _pending_evidence_key(
                materialization_id=materialization_id,
                child_client_order_id=candidate.child_client_order_id,
                operation_audit_id=operation_audit_id,
                operation_idempotency_key_sha256=(
                    operation_idempotency_key_sha256
                ),
            )
            self.pending_raw_exchange_evidence[pending_key] = (
                _PendingRawExchangeEvidence(
                    materialization_id=_text(materialization_id),
                    child_client_order_id=candidate.child_client_order_id,
                    operation_audit_id=_text(operation_audit_id),
                    operation_idempotency_key_sha256=_text(
                        operation_idempotency_key_sha256
                    ).lower(),
                    authoritative_order_status=authoritative_status,
                    exchange_order_id=exchange_order_id,
                )
            )
            return ExchangeInvocationResult(
                outcome=ExchangeInvocationOutcome.ACCEPTED,
                child_state=(
                    ChildExchangeState.TERMINAL
                    if authoritative_status in _TERMINAL_EXCHANGE_STATUSES
                    else ChildExchangeState.ACTIVE
                ),
                exchange_call_started=True,
                exchange_order_id_sha256=_sha256(exchange_order_id),
            )
        except Exception:
            return self._unknown(exchange_call_started=call_started)

    def cancel_follow_up_child(
        self,
        *,
        child_client_order_id: str,
        correlation_id: str,
        materialization_id: str,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> ExchangeInvocationResult:
        del correlation_id
        if (
            self.rest_client is None
            or not _text(materialization_id)
            or not _text(operation_audit_id)
            or not _is_sha256(operation_idempotency_key_sha256)
        ):
            return self._unknown()
        child_id = _text(child_client_order_id)
        child = _mapping(self.local_order_reader(child_id))
        stored_exchange_order_id = _text(child.get("exchange_order_id"))
        exchange_order_id = stored_exchange_order_id
        product_id = _text(child.get("product_id"))
        side = _upper(child.get("side"))
        base_size = _decimal(child.get("size"))
        limit_price = _decimal(child.get("price"))
        if not (
            _text(child.get("client_order_id")) == child_id
            and exchange_order_id
            and self.configured_portfolio_id
            and _text(child.get("retail_portfolio_id"))
            == self.configured_portfolio_id
            and is_concrete_usdc_spot_product(product_id)
            and side in {"BUY", "SELL"}
            and base_size is not None
            and base_size > 0
            and limit_price is not None
            and limit_price > 0
            and callable(self.exact_order_readback)
        ):
            return self._unknown()
        pending_key = _pending_evidence_key(
            materialization_id=materialization_id,
            child_client_order_id=child_id,
            operation_audit_id=operation_audit_id,
            operation_idempotency_key_sha256=operation_idempotency_key_sha256,
        )
        self.pending_raw_exchange_evidence[pending_key] = (
            _PendingRawExchangeEvidence(
                materialization_id=_text(materialization_id),
                child_client_order_id=child_id,
                operation_audit_id=_text(operation_audit_id),
                operation_idempotency_key_sha256=_text(
                    operation_idempotency_key_sha256
                ).lower(),
                authoritative_order_status=(
                    _upper(child.get("status")) or "OPEN"
                ),
                exchange_order_id=exchange_order_id,
            )
        )
        if self.runtime_authority_check() is not True:
            return self._unknown(exchange_order_id)
        call_started = False
        try:
            from core.coinbase_execution_authority import (
                COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
            )

            with self.execution_scope_factory(COINBASE_EXECUTION_SCOPE_SPOT_CANCEL):
                with self.inflight_scope_factory("CANCEL"):
                    call_started = True
                    evidence = self.rest_client.cancel_order(
                        child_id,
                        verified_exchange_order_id=exchange_order_id,
                        return_evidence=True,
                    )
            evidence = _mapping(evidence)
            outcome = _text(evidence.get("outcome")).lower()
            identity_match = evidence.get("identity_match") is True
            if outcome == "succeeded" and identity_match:
                readback = dict(
                    self.exact_order_readback(
                        self.rest_client,
                        client_order_id=child_id,
                        exchange_order_id=exchange_order_id,
                        product_id=product_id,
                        product_type="SPOT",
                        expected_retail_portfolio_id=self.configured_portfolio_id,
                    )
                )
                tuple_matches, authoritative_status = _exact_limit_gtc_order_tuple(
                    readback,
                    client_order_id=child_id,
                    exchange_order_id=exchange_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=base_size,
                    limit_price=limit_price,
                )
                if tuple_matches:
                    self.pending_raw_exchange_evidence[pending_key] = (
                        _PendingRawExchangeEvidence(
                            materialization_id=_text(materialization_id),
                            child_client_order_id=child_id,
                            operation_audit_id=_text(operation_audit_id),
                            operation_idempotency_key_sha256=_text(
                                operation_idempotency_key_sha256
                            ).lower(),
                            authoritative_order_status=authoritative_status,
                            exchange_order_id=exchange_order_id,
                        )
                    )
                    if authoritative_status in _TERMINAL_EXCHANGE_STATUSES:
                        return ExchangeInvocationResult(
                            outcome=ExchangeInvocationOutcome.ACCEPTED,
                            child_state=ChildExchangeState.TERMINAL,
                            exchange_call_started=True,
                            exchange_order_id_sha256=_sha256(exchange_order_id),
                        )
                return self._unknown(
                    exchange_order_id,
                    exchange_call_started=True,
                )
            if (
                outcome == "explicitly_rejected"
                and evidence.get("explicit_rejection") is True
                and identity_match
            ):
                return ExchangeInvocationResult(
                    outcome=ExchangeInvocationOutcome.REJECTED,
                    child_state=ChildExchangeState.ACTIVE,
                    exchange_call_started=True,
                    exchange_order_id_sha256=_sha256(exchange_order_id),
                )
            return self._unknown(
                exchange_order_id,
                exchange_call_started=True,
            )
        except Exception:
            return self._unknown(
                exchange_order_id,
                exchange_call_started=call_started,
            )


def _public_state(native_state: str) -> str:
    return (
        "CHILD_ALREADY_TERMINAL_NO_CANCEL"
        if native_state == "CANCEL_NOT_REQUIRED_TERMINAL"
        else native_state
    )


def _public_candidate_from_native(attempt: Any) -> AdminOrderFollowUpMaterializationCandidate:
    base_size = Decimal(str(attempt.base_size))
    limit_price = Decimal(str(attempt.limit_price))
    return AdminOrderFollowUpMaterializationCandidate(
        child_client_order_id=_text(attempt.child_client_order_id),
        product_id=_text(attempt.product_id),
        side=_upper(attempt.child_side),
        base_size=_decimal_text(base_size),
        limit_price=_decimal_text(limit_price),
        submitted_notional_usdc=_decimal_text(base_size * limit_price),
        max_submitted_notional_usdc=_decimal_text(
            CURRENT_MAX_SUBMITTED_NOTIONAL_USDC
        ),
        max_executed_notional_usdc=_decimal_text(
            CURRENT_MAX_EXECUTED_NOTIONAL_USDC
        ),
        effective_notional_cap_usdc=_decimal_text(
            CURRENT_EFFECTIVE_NOTIONAL_CAP_USDC
        ),
    )


def _public_candidate(
    candidate: BackendMaterializationCandidate,
) -> AdminOrderFollowUpMaterializationCandidate:
    return AdminOrderFollowUpMaterializationCandidate(
        child_client_order_id=candidate.child_client_order_id,
        product_id=candidate.product_id,
        side=_upper(candidate.child_side),
        base_size=_decimal_text(candidate.base_size),
        limit_price=_decimal_text(candidate.limit_price),
        submitted_notional_usdc=_decimal_text(candidate.submitted_notional_usdc),
        max_submitted_notional_usdc=_decimal_text(
            candidate.max_submitted_notional_usdc
        ),
        max_executed_notional_usdc=_decimal_text(
            candidate.max_executed_notional_usdc
        ),
        effective_notional_cap_usdc=_decimal_text(
            candidate.effective_notional_cap_usdc
        ),
    )


def _public_attempt(attempt: Any) -> AdminOrderFollowUpMaterializationAttempt:
    native_state = _native_state(attempt.current_state)
    state = _public_state(native_state)
    return AdminOrderFollowUpMaterializationAttempt(
        materialization_id=_text(attempt.materialization_id),
        follow_up_intent_id=_text(attempt.follow_up_intent_id),
        source_client_order_id=_text(attempt.source_client_order_id),
        root_client_order_id=_text(attempt.root_client_order_id),
        child_client_order_id=_text(attempt.child_client_order_id),
        state=state,
        terminal=state in _TERMINAL_PUBLIC_STATES,
        unknown_outcome=state in _UNKNOWN_PUBLIC_STATES,
        exchange_order_id_present=_is_sha256(
            getattr(attempt, "exchange_order_id_sha256", None)
        ),
        correlation_id=(
            _text(getattr(attempt, "current_operation_correlation_id", ""))
            or _text(attempt.correlation_id)
        ),
        audit_id=(
            _text(getattr(attempt, "current_operation_audit_id", ""))
            or _text(attempt.audit_id)
        ),
        recorded_at=_text(attempt.prepared_at),
        updated_at=_text(attempt.state_recorded_at),
    )


def _public_audit_event(event: Any) -> AdminOrderFollowUpMaterializationAuditEvent:
    return AdminOrderFollowUpMaterializationAuditEvent(
        event_id=_text(event.event_id),
        state=_public_state(_native_state(event.state)),
        diagnostic_code=_text(event.diagnostic_code),
        operation_audit_id=_text(event.operation_audit_id),
        environment=_text(event.environment),
        operator_intent=_text(event.operator_intent),
        correlation_id=_text(event.correlation_id),
        exchange_order_id_present=_is_sha256(
            getattr(event, "exchange_order_id_sha256", None)
        ),
        recorded_at=_text(event.recorded_at),
    )


def _public_local_projection(
    projection: Any,
) -> AdminOrderFollowUpMaterializationLocalProjection:
    return AdminOrderFollowUpMaterializationLocalProjection(
        local_state_event_id=_text(projection.local_state_event_id),
        materialization_id=_text(projection.materialization_id),
        child_client_order_id=_text(projection.child_client_order_id),
        transition_kind=_upper(projection.transition_kind),
        authoritative_order_status=_upper(
            projection.authoritative_order_status
        ),
        exchange_order_id_present=_is_sha256(
            getattr(projection, "exchange_order_id_sha256", None)
        ),
        operation_audit_id=_text(projection.operation_audit_id),
        recorded_at=_text(projection.recorded_at),
        order_parent_and_stealth_match=True,
    )


def _call_allowance(attempt: Any | None) -> AdminOrderFollowUpMaterializationCallAllowance:
    state = _native_state(attempt.current_state) if attempt is not None else ""
    create_consumed = state in _CREATE_CONSUMED_NATIVE_STATES
    cancel_consumed = state in _CANCEL_CONSUMED_NATIVE_STATES
    return AdminOrderFollowUpMaterializationCallAllowance(
        create_call_count=1 if create_consumed else 0,
        create_call_consumed=create_consumed,
        cancel_call_count=1 if cancel_consumed else 0,
        cancel_call_consumed=cancel_consumed,
    )


def _safe_closeout_eligibility(
    attempt: Any | None,
) -> AdminOrderFollowUpMaterializationSafeCloseoutEligibility:
    if attempt is None:
        return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
            request_eligible=False,
            backend_decision="blocked",
            blockers=["materialization_not_started"],
        )
    state = _native_state(attempt.current_state)
    if state in {
        "CREATE_INVOCATION_STARTED",
        "CREATE_UNKNOWN_CONSUMED",
        "CREATE_ACCEPTED_NONTERMINAL",
    }:
        return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
            request_eligible=True,
            backend_decision="eligible_for_authoritative_read",
            blockers=[],
        )
    if state == "CREATE_EXPLICITLY_REJECTED":
        return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
            request_eligible=False,
            backend_decision="blocked",
            blockers=["create_rejected"],
        )
    if state in {
        "CREATE_ACCEPTED_TERMINAL",
        "CANCEL_ACCEPTED_TERMINAL",
        "CANCEL_NOT_REQUIRED_TERMINAL",
    }:
        return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
            request_eligible=False,
            backend_decision="terminal",
            blockers=["child_terminal"],
        )
    if state in _CANCEL_CONSUMED_NATIVE_STATES:
        return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
            request_eligible=False,
            backend_decision="consumed",
            blockers=["cancel_allowance_consumed"],
        )
    return AdminOrderFollowUpMaterializationSafeCloseoutEligibility(
        request_eligible=False,
        backend_decision="blocked",
        blockers=["safe_closeout_not_available"],
    )


def _public_eligibility(
    *,
    readiness: Any,
    attempt: Any | None,
    evidence: FreshMaterializationEligibility | None,
) -> AdminOrderFollowUpMaterializationEligibilityEvidence:
    candidate = evidence.candidate if evidence is not None else None
    blockers = list(
        evidence.blockers
        if evidence is not None
        else (getattr(readiness, "blockers", ()) or ())
    )
    if evidence is None:
        blockers = list(dict.fromkeys([*blockers, "fresh_live_authorization_required"]))
    state = _native_state(attempt.current_state) if attempt is not None else ""
    consumed = state in _CREATE_CONSUMED_NATIVE_STATES
    terminal = _public_state(state) in _TERMINAL_PUBLIC_STATES
    ready = bool(candidate is not None and not blockers and not consumed)
    if terminal:
        decision = "terminal"
    elif consumed:
        decision = "consumed"
    elif ready:
        decision = "ready"
    else:
        decision = "blocked"
    return AdminOrderFollowUpMaterializationEligibilityEvidence(
        source_client_order_id=_text(readiness.source_client_order_id),
        root_client_order_id=_text(readiness.root_client_order_id),
        attached_intent_present=bool(
            _text(getattr(readiness, "follow_up_intent_id", ""))
        ),
        source_status=_upper(getattr(readiness, "source_status", "UNKNOWN"))
        or "UNKNOWN",
        source_full_fill_proven=bool(
            getattr(readiness, "full_fill_consistent", False)
        ),
        source_terminal_revalidated=bool(
            candidate is not None and candidate.source_terminal
        ),
        test_portfolio_revalidated=bool(
            candidate is not None and candidate.approved_test_portfolio_verified
        ),
        product_policy_revalidated=bool(
            candidate is not None and candidate.product_policy_allowed
        ),
        wallet_revalidated=bool(candidate is not None and candidate.wallet_check_passed),
        cap_revalidated=bool(
            candidate is not None
            and candidate.submitted_notional_usdc
            <= candidate.effective_notional_cap_usdc
        ),
        reconciliation_revalidated=bool(
            evidence is not None
            and evidence.fresh
            and evidence.reconciliation_pass_count == 1
            and not evidence.ambiguous
        ),
        child_absent=bool(getattr(readiness, "child_absent", False)),
        attempt_unconsumed=not consumed,
        ready=ready,
        backend_decision=decision,
        blockers=blockers,
    )


def _authorization_request_forwardability(
    eligibility: AdminOrderFollowUpMaterializationEligibilityEvidence,
) -> AdminOrderFollowUpMaterializationAuthorizationRequestForwardability:
    blockers = list(eligibility.blockers)
    request_forwardable = blockers == ["fresh_live_authorization_required"]
    return AdminOrderFollowUpMaterializationAuthorizationRequestForwardability(
        request_forwardable=request_forwardable,
        backend_decision=(
            "forward_fresh_acknowledgement_only"
            if request_forwardable
            else "blocked"
        ),
        blockers=[] if request_forwardable else blockers,
    )


def _command_status(*, native_state: str, replayed: bool) -> AdminApiCommandStatus:
    if replayed:
        return AdminApiCommandStatus.REPLAYED
    if native_state in {
        "CREATE_EXPLICITLY_REJECTED",
        "CANCEL_EXPLICITLY_REJECTED",
    }:
        return AdminApiCommandStatus.REJECTED
    if native_state in {
        "CREATE_INVOCATION_STARTED",
        "CREATE_UNKNOWN_CONSUMED",
        "CANCEL_INVOCATION_STARTED",
        "CANCEL_UNKNOWN_CONSUMED",
    }:
        return AdminApiCommandStatus.CONFLICT
    return AdminApiCommandStatus.ACCEPTED


class OperatorFollowUpMaterializationFacade:
    """Map kernel/native evidence into the fixed public OpenAPI contract."""

    def __init__(
        self,
        *,
        service: Any,
        native_repository: Any,
        environment: str | None = None,
    ) -> None:
        self.service = service
        self.native_repository = native_repository
        self.environment = _text(environment) or _text(
            os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT")
        ) or "local"

    def _environment(self, attempt: Any | None) -> str:
        return (
            _text(getattr(attempt, "current_operation_environment", ""))
            or _text(getattr(attempt, "environment", ""))
            or self.environment
        )

    def _native_read(self, source_client_order_id: str) -> Any:
        try:
            return self.native_repository.read_materialization(
                source_client_order_id
            )
        except Exception:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_backend_unavailable", 503
            ) from None

    def read(
        self,
        *,
        source_client_order_id: str,
    ) -> AdminOrderFollowUpMaterializationReadResponse:
        readback = self._native_read(source_client_order_id)
        readiness = readback.readiness
        attempt = readback.attempt
        audit_events: list[AdminOrderFollowUpMaterializationAuditEvent] = []
        local_projection: AdminOrderFollowUpMaterializationLocalProjection | None = (
            None
        )
        if attempt is not None:
            try:
                native_events = tuple(
                    self.native_repository.list_materialization_events(
                        attempt.materialization_id
                    )
                )
                native_projection = (
                    self.native_repository.read_latest_materialized_child_local_state(
                        attempt.materialization_id
                    )
                )
            except Exception:
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_backend_unavailable", 503
                ) from None
            if any(
                _text(getattr(event, "materialization_id", ""))
                != _text(attempt.materialization_id)
                for event in native_events
            ):
                raise OperatorFollowUpMaterializationError(
                    "follow_up_materialization_backend_unavailable", 503
                )
            audit_events = [_public_audit_event(event) for event in native_events]
            if native_projection is not None:
                if (
                    _text(native_projection.materialization_id)
                    != _text(attempt.materialization_id)
                    or _text(native_projection.child_client_order_id)
                    != _text(attempt.child_client_order_id)
                ):
                    raise OperatorFollowUpMaterializationError(
                        "follow_up_materialization_backend_unavailable", 503
                    )
                local_projection = _public_local_projection(native_projection)
        eligibility = _public_eligibility(
            readiness=readiness,
            attempt=attempt,
            evidence=None,
        )
        return AdminOrderFollowUpMaterializationReadResponse(
            source_client_order_id=source_client_order_id,
            root_client_order_id=_text(readiness.root_client_order_id)
            or source_client_order_id,
            follow_up_intent_id=(
                _text(readiness.follow_up_intent_id) or None
            ),
            environment=self._environment(attempt),
            eligibility=eligibility,
            authorization_request_forwardability=(
                _authorization_request_forwardability(eligibility)
            ),
            candidate=(
                _public_candidate_from_native(attempt)
                if attempt is not None
                else None
            ),
            attempt=_public_attempt(attempt) if attempt is not None else None,
            call_allowance=_call_allowance(attempt),
            audit_events=audit_events,
            local_projection=local_projection,
            safe_closeout_eligibility=_safe_closeout_eligibility(attempt),
        )

    def materialize(
        self,
        *,
        source_client_order_id: str,
        request: Any,
        context: Any,
    ) -> AdminOrderFollowUpMaterializationCommandResponse:
        result: MaterializationOperationResult = self.service.materialize(
            source_client_order_id=source_client_order_id,
            request=request,
            context=context,
        )
        readback = self._native_read(source_client_order_id)
        attempt = readback.attempt
        if attempt is None:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable", 503
            )
        candidate = result.candidate
        public_candidate = (
            _public_candidate(candidate)
            if candidate is not None
            else _public_candidate_from_native(attempt)
        )
        native_state = _native_state(attempt.current_state)
        status = _command_status(native_state=native_state, replayed=result.replayed)
        return AdminOrderFollowUpMaterializationCommandResponse(
            status=status,
            message=result.diagnostic_code,
            source_client_order_id=source_client_order_id,
            root_client_order_id=_text(attempt.root_client_order_id),
            child_client_order_id=_text(attempt.child_client_order_id),
            environment=self._environment(attempt),
            operator_intent=AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
            correlation_id=_text(
                getattr(attempt, "current_operation_correlation_id", "")
            )
            or _text(attempt.correlation_id)
            or _text(context.correlation_id),
            idempotency_key=_text(context.idempotency_key),
            audit_id=_text(getattr(attempt, "current_operation_audit_id", ""))
            or _text(attempt.audit_id),
            replayed=result.replayed,
            eligibility=_public_eligibility(
                readiness=readback.readiness,
                attempt=attempt,
                evidence=result.eligibility,
            ),
            candidate=public_candidate,
            attempt=_public_attempt(attempt),
            call_allowance=_call_allowance(attempt),
            live_coinbase_read_ran=result.live_read_ran,
            live_coinbase_create_call_count=1 if result.create_call_ran else 0,
            live_exchange_submitted=result.create_call_ran,
            exchange_state_mutated=bool(
                result.create_call_ran
                and native_state
                in {"CREATE_ACCEPTED_NONTERMINAL", "CREATE_ACCEPTED_TERMINAL"}
            ),
        )

    def safe_closeout(
        self,
        *,
        source_client_order_id: str,
        request: Any,
        context: Any,
    ) -> AdminOrderFollowUpMaterializationCancelResponse:
        result: MaterializationOperationResult = self.service.safe_closeout(
            source_client_order_id=source_client_order_id,
            request=request,
            context=context,
        )
        readback = self._native_read(source_client_order_id)
        attempt = readback.attempt
        if attempt is None:
            raise OperatorFollowUpMaterializationError(
                "follow_up_materialization_result_persistence_unavailable", 503
            )
        native_state = _native_state(attempt.current_state)
        return AdminOrderFollowUpMaterializationCancelResponse(
            status=_command_status(
                native_state=native_state,
                replayed=result.replayed,
            ),
            message=result.diagnostic_code,
            source_client_order_id=source_client_order_id,
            root_client_order_id=_text(attempt.root_client_order_id),
            child_client_order_id=_text(attempt.child_client_order_id),
            environment=self._environment(attempt),
            operator_intent=SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
            correlation_id=_text(
                getattr(attempt, "current_operation_correlation_id", "")
            )
            or _text(context.correlation_id),
            idempotency_key=_text(context.idempotency_key),
            audit_id=_text(getattr(attempt, "current_operation_audit_id", ""))
            or _text(attempt.audit_id),
            replayed=result.replayed,
            attempt=_public_attempt(attempt),
            call_allowance=_call_allowance(attempt),
            live_coinbase_read_ran=result.live_read_ran,
            live_coinbase_cancel_call_count=1 if result.cancel_call_ran else 0,
            live_exchange_cancel_submitted=result.cancel_call_ran,
            exchange_state_mutated=bool(
                result.cancel_call_ran
                and native_state
                in {"CANCEL_ACCEPTED_NONTERMINAL", "CANCEL_ACCEPTED_TERMINAL"}
            ),
        )


def _default_template_resolver(source_id: str, root_id: str) -> dict[str, Any]:
    import dashboard_server

    bridge = getattr(dashboard_server, "stealth_order_bridge", None)
    engine = getattr(bridge, "order_engine", None) if bridge is not None else None
    if engine is None:
        raise RuntimeError("follow_up_materialization_order_engine_unavailable")
    target = engine.resolve_parent_target_movement(root_id)
    template = engine.compute_order_template(source_id, target_movement=target)
    template = _mapping(template)
    if isinstance(target, Mapping):
        template.setdefault("target_movement", target.get("movement"))
        template.setdefault("target_movement_type", target.get("type"))
    return template


def _default_action_guard_evaluator(**kwargs: Any) -> bool:
    from core.action_condition_guard import ActionConditionGuard
    from core.enums import ActionGuardPhase

    wallets = kwargs.pop("wallets")
    allowed, _failure = ActionConditionGuard(
        wallet_fetcher=lambda: wallets,
    ).evaluate(
        phase=ActionGuardPhase.PLANNING,
        **kwargs,
    )
    return allowed


def build_default_operator_follow_up_materialization_service(
) -> OperatorFollowUpMaterializationFacade:
    """Compose production adapters without making a Coinbase API call."""

    from application.admin_api.command_runtime import (
        admin_api_live_runtime_enabled,
        get_admin_api_spot_market_reference,
        load_admin_api_rest_client,
    )
    from application.admin_api.command_service import (
        exact_coinbase_fill_readback,
        exact_coinbase_order_readback,
    )
    from application.admin_api.spot_portfolio_binding import (
        DEFAULT_SPOT_PORTFOLIO_LABEL,
        SPOT_PORTFOLIO_LABEL_ENV,
        evaluate_spot_test_portfolio_binding,
    )
    from core.action_condition_guard import evaluate_spot_standing_price_limit
    from core.coinbase_execution_authority import (
        canonical_coinbase_execution_scope,
    )
    from core.runtime_controller import (
        INFLIGHT_REST_CANCEL,
        INFLIGHT_REST_PLACE,
        get_runtime_controller,
    )
    from database import order as order_db
    from database.order_follow_up_intent import get_default_repository

    native_repository = get_default_repository()
    binding = load_admin_api_rest_client()
    rest_client = binding.client if binding.available else None
    portfolio_id = _text(os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID"))
    portfolio_label = (
        _text(os.environ.get(SPOT_PORTFOLIO_LABEL_ENV))
        or DEFAULT_SPOT_PORTFOLIO_LABEL
    )

    def product_reader(product_id: str) -> Any:
        if rest_client is None:
            return None
        method = getattr(rest_client, "get_product_dict", None)
        if not callable(method):
            method = getattr(rest_client, "get_product", None)
        if not callable(method):
            return None
        return method(product_id)

    def portfolio_binding(client: Any, expected_id: str) -> Any:
        return evaluate_spot_test_portfolio_binding(
            rest_client=client,
            expected_portfolio_id=expected_id,
            expected_portfolio_label=portfolio_label,
        )

    def market_reader(product_id: str) -> Any:
        return get_admin_api_spot_market_reference(
            product_id,
            rest_client=rest_client,
        )

    def wallet_reader() -> Any:
        if rest_client is None:
            raise RuntimeError("follow_up_materialization_wallet_unavailable")
        method = getattr(rest_client, "get_account_wallets", None)
        if not callable(method):
            raise RuntimeError("follow_up_materialization_wallet_unavailable")
        return method()

    pending_raw_exchange_evidence: dict[
        tuple[str, str, str, str], _PendingRawExchangeEvidence
    ] = {}
    runtime = ProductionFollowUpMaterializationRuntime(
        native_repository=native_repository,
        rest_client=rest_client,
        configured_portfolio_id=portfolio_id,
        environment=_configured_admin_environment(),
        runtime_authority_check=admin_api_live_runtime_enabled,
        local_order_reader=order_db.get_parent_order,
        template_resolver=_default_template_resolver,
        product_reader=product_reader,
        portfolio_binding_evaluator=portfolio_binding,
        source_order_readback=exact_coinbase_order_readback,
        source_fill_readback=exact_coinbase_fill_readback,
        market_reference_reader=market_reader,
        standing_price_evaluator=evaluate_spot_standing_price_limit,
        wallet_reader=wallet_reader,
        action_guard_evaluator=_default_action_guard_evaluator,
        child_persister=order_db.persist_filled_follow_up_atomic,
        local_stealth_reader=order_db.get_stealth_order_by_id,
        local_state_transitioner=(
            native_repository.transition_materialized_child_local_state
        ),
        pending_raw_exchange_evidence=pending_raw_exchange_evidence,
    )
    exchange = CanonicalFollowUpMaterializationExchange(
        rest_client=rest_client,
        runtime_authority_check=admin_api_live_runtime_enabled,
        local_order_reader=order_db.get_parent_order,
        execution_scope_factory=canonical_coinbase_execution_scope,
        exact_order_readback=exact_coinbase_order_readback,
        configured_portfolio_id=portfolio_id,
        pending_raw_exchange_evidence=pending_raw_exchange_evidence,
        inflight_scope_factory=lambda operation: get_runtime_controller().track_inflight(
            INFLIGHT_REST_PLACE if operation == "PLACE" else INFLIGHT_REST_CANCEL
        ),
    )
    kernel_repository = NativeFollowUpMaterializationRepositoryAdapter(
        native_repository
    )
    service = OperatorFollowUpMaterializationService(
        repository=kernel_repository,
        runtime=runtime,
        exchange=exchange,
    )
    return OperatorFollowUpMaterializationFacade(
        service=service,
        native_repository=native_repository,
        environment=_configured_admin_environment(),
    )
