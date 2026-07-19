"""Durable single-slot follow-up intent and automatic-claim persistence.

This module is deliberately local-state only.  It never imports an exchange
client and every decision is made from the existing PostgreSQL order/fill
evidence plus the canonical intent, claim, and audit-outbox tables owned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    FollowUpMaterializationState,
    FollowUpMaterializedChildTransitionKind,
    FollowUpSemanticClaimKind,
    FollowUpSemanticClaimState,
    OrderOwnershipProvenance,
    OrderStatus,
)
from core.operator_follow_up_intent import (
    evaluate_operator_follow_up_intent_policy,
    operator_follow_up_intent_scope_applies,
    operator_follow_up_intent_enabled,
)
from core.product_capability import resolve_product_context
from core.spot_follow_up_policy import evaluate_spot_follow_up_policy


FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = operator_follow_up_intent_enabled
FOLLOW_UP_INTENT_AUDIT_ENDPOINT = (
    "/api/v1/orders/{source_client_order_id}/follow-up-intent"
)
FOLLOW_UP_INTENT_AUDIT_MESSAGE = "follow_up_intent_attached"

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AUTOMATIC_CLAIM_KINDS = {
    FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
    FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
}
_POSITIVE_FILL_EVIDENCE_TABLES = (
    "fill_ledger",
    "order_match_audit",
    "order_event_stream",
    "partial_fill_progress",
)
_MATERIALIZATION_STATES = tuple(state.value for state in FollowUpMaterializationState)
_MATERIALIZATION_STATE_SQL = ", ".join(
    "'" + state.replace("'", "''") + "'" for state in _MATERIALIZATION_STATES
)
_MATERIALIZED_CHILD_TRANSITIONS = tuple(
    transition.value for transition in FollowUpMaterializedChildTransitionKind
)
_MATERIALIZED_CHILD_TRANSITION_SQL = ", ".join(
    "'" + transition.replace("'", "''") + "'"
    for transition in _MATERIALIZED_CHILD_TRANSITIONS
)
_CREATE_RESULT_STATES = {
    FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
    FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
    FollowUpMaterializationState.CREATE_ACCEPTED_TERMINAL.value,
    FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
}
_CANCEL_RESULT_STATES = {
    FollowUpMaterializationState.CANCEL_EXPLICITLY_REJECTED.value,
    FollowUpMaterializationState.CANCEL_ACCEPTED_NONTERMINAL.value,
    FollowUpMaterializationState.CANCEL_ACCEPTED_TERMINAL.value,
    FollowUpMaterializationState.CANCEL_UNKNOWN_CONSUMED.value,
}
_MATERIALIZED_CHILD_ACTIVE_STATUSES = frozenset(
    {
        OrderStatus.PENDING.value,
        OrderStatus.OPEN.value,
        OrderStatus.QUEUED.value,
    }
)
_MATERIALIZED_CHILD_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FILLED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.EXPIRED.value,
        OrderStatus.FAILED.value,
    }
)
_MATERIALIZED_CHILD_TRANSITION_EVENT_STATES = {
    FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value: (
        FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
    ),
    FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value: (
        FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
    ),
    FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL.value: (
        FollowUpMaterializationState.CREATE_ACCEPTED_TERMINAL.value,
    ),
    FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value: (
        FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
    ),
    FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value: (
        FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
    ),
    FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL.value: (
        FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
        FollowUpMaterializationState.CANCEL_UNKNOWN_CONSUMED.value,
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_EXPLICITLY_REJECTED_ACTIVE.value: (
        FollowUpMaterializationState.CANCEL_EXPLICITLY_REJECTED.value,
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value: (
        FollowUpMaterializationState.CANCEL_ACCEPTED_TERMINAL.value,
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value: (
        FollowUpMaterializationState.CANCEL_UNKNOWN_CONSUMED.value,
    ),
    FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL.value: (
        FollowUpMaterializationState.CANCEL_NOT_REQUIRED_TERMINAL.value,
    ),
}
_MATERIALIZED_CHILD_INITIAL_TRANSITIONS = frozenset(
    {
        FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value,
        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL.value,
        FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value,
    }
)
_MATERIALIZED_CHILD_TRANSITION_PREDECESSORS = {
    FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value,
        }
    ),
    FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value,
            FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value,
        }
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_EXPLICITLY_REJECTED_ACTIVE.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value,
        }
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value,
        }
    ),
    FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value,
        }
    ),
    FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL.value: frozenset(
        {
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value,
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.CANCEL_EXPLICITLY_REJECTED_ACTIVE.value,
            FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value,
        }
    ),
}
_MATERIALIZED_CHILD_TERMINAL_TRANSITIONS = frozenset(
    {
        FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value,
        FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL.value,
        FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL.value,
        FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value,
        FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL.value,
    }
)


class FollowUpIntentStoreError(RuntimeError):
    """Value-blind base error raised by the persistence boundary."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


class FollowUpIntentStoreConflict(FollowUpIntentStoreError):
    """A stable state or idempotency conflict."""


class FollowUpIntentStoreUnavailable(FollowUpIntentStoreError):
    """Authoritative persistence evidence could not be established."""


@dataclass(frozen=True)
class FollowUpIntentCommand:
    source_client_order_id: str
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    payload_sha256: str


@dataclass(frozen=True)
class FollowUpMaterializationCommand:
    """Backend-derived exact plan for one durable materialization claim."""

    source_client_order_id: str
    root_client_order_id: str
    follow_up_intent_id: str
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    audit_id: str
    payload_sha256: str
    product_id: str
    child_side: str
    base_size: Decimal
    limit_price: Decimal
    portfolio_id: str


@dataclass(frozen=True)
class FollowUpMaterializationReadiness:
    source_client_order_id: str
    root_client_order_id: str
    follow_up_intent_id: str | None
    deterministic_child_client_order_id: str | None
    eligible: bool
    eligibility_status: str
    blockers: tuple[str, ...]
    source_status: str
    source_ownership_provenance: str
    product_id: str
    source_side: str
    derived_follow_up_side: str | None
    base_size: str | None
    full_fill_consistent: bool
    flat_lineage_valid: bool
    child_absent: bool
    conflicting_claim_absent: bool
    portfolio_scope_sha256: str


@dataclass(frozen=True)
class FollowUpMaterializationAttemptRecord:
    materialization_id: str
    audit_id: str
    follow_up_intent_id: str
    source_client_order_id: str
    root_client_order_id: str
    child_client_order_id: str
    product_id: str
    child_side: str
    base_size: str
    limit_price: str
    portfolio_scope_sha256: str
    idempotency_key: str
    payload_sha256: str
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    correlation_id: str
    operator_intent: str
    prepared_at: str
    current_state: str
    current_diagnostic_code: str
    exchange_order_id_sha256: str | None
    operation_idempotency_key_sha256: str | None
    current_operation_audit_id: str
    current_operation_actor_id: str
    current_operation_roles: tuple[str, ...]
    current_operation_environment: str
    current_operation_operator_intent: str
    current_operation_correlation_id: str
    state_recorded_at: str


@dataclass(frozen=True)
class FollowUpMaterializationEventRecord:
    event_id: str
    materialization_id: str
    state: str
    diagnostic_code: str
    exchange_order_id_sha256: str | None
    operation_idempotency_key_sha256: str | None
    operation_audit_id: str
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    operator_intent: str
    correlation_id: str
    recorded_at: str


@dataclass(frozen=True)
class _FollowUpMaterializationOperationBinding:
    operation_audit_id: str | None
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    operator_intent: str
    correlation_id: str
    idempotency_key_sha256: str


@dataclass(frozen=True)
class FollowUpMaterializationReadback:
    readiness: FollowUpMaterializationReadiness
    attempt: FollowUpMaterializationAttemptRecord | None


@dataclass(frozen=True)
class FollowUpMaterializationPrepareResult:
    readiness: FollowUpMaterializationReadiness
    attempt: FollowUpMaterializationAttemptRecord
    replayed: bool


@dataclass(frozen=True)
class FollowUpMaterializationTransitionResult:
    attempt: FollowUpMaterializationAttemptRecord
    event: FollowUpMaterializationEventRecord
    replayed: bool


@dataclass(frozen=True)
class FollowUpMaterializedChildLocalStateRecord:
    local_state_event_id: str
    materialization_id: str
    child_client_order_id: str
    transition_kind: str
    authoritative_order_status: str
    exchange_order_id_sha256: str | None
    operation_audit_id: str
    operation_idempotency_key_sha256: str
    recorded_at: str


@dataclass(frozen=True)
class FollowUpMaterializedChildLocalStateTransitionResult:
    record: FollowUpMaterializedChildLocalStateRecord
    replayed: bool


@dataclass(frozen=True)
class FollowUpIntentEligibility:
    source_client_order_id: str
    root_client_order_id: str
    source_found: bool
    eligible: bool
    eligibility_status: str
    blockers: tuple[str, ...]
    source_status: str
    source_ownership_provenance: str
    product_id: str
    product_type: str
    source_is_child: bool
    source_authoritative_zero_fill: bool
    source_follow_up_child_absent: bool
    automatic_semantic_claim_absent: bool
    portfolio_scope_sha256: str
    slot_used: int
    semantic_intent: str | None = None
    derived_follow_up_side: str | None = None


@dataclass(frozen=True)
class FollowUpIntentRecord:
    follow_up_intent_id: str
    claim_id: str
    source_client_order_id: str
    root_client_order_id: str
    semantic_intent: str
    derived_follow_up_side: str
    intent_sha256: str
    audit_id: str
    correlation_id: str
    actor_id: str
    environment: str
    portfolio_scope_sha256: str
    idempotency_key: str
    payload_sha256: str
    recorded_at: str


@dataclass(frozen=True)
class FollowUpIntentReadback:
    eligibility: FollowUpIntentEligibility
    record: FollowUpIntentRecord | None


@dataclass(frozen=True)
class FollowUpIntentAttachResult:
    eligibility: FollowUpIntentEligibility
    record: FollowUpIntentRecord
    replayed: bool


@dataclass(frozen=True)
class FollowUpIntentAuditOutboxRecord:
    audit_id: str
    follow_up_intent_id: str
    source_client_order_id: str
    event: dict[str, Any]
    event_sha256: str
    recorded_at: str
    projected_at: str | None


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _canonical_audit_event(
    *,
    audit_id: str,
    recorded_at: str,
    actor_id: str,
    correlation_id: str,
    operator_intent: str,
    idempotency_key: str,
    source_client_order_id: str,
) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "recorded_at": recorded_at,
        "actor_id": actor_id,
        "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION.value,
        "permission": AdminApiPermission.ORDER_CREATE.value,
        "endpoint": FOLLOW_UP_INTENT_AUDIT_ENDPOINT,
        "request_id": correlation_id,
        "operator_intent": operator_intent,
        "idempotency_key": idempotency_key,
        "approval_id": None,
        "client_order_id": source_client_order_id,
        "stealth_order_id": None,
        "coinbase_order_id": None,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "live_coinbase_read_ran": False,
        "live_command_runtime_enabled": None,
        "live_command_rest_client_available": None,
        "live_command_runtime_ready": None,
        "live_command_runtime_missing_reason": None,
        "live_command_runtime_source": None,
        "status": AdminApiCommandStatus.ACCEPTED.value,
        "failure_stage": None,
        "message": FOLLOW_UP_INTENT_AUDIT_MESSAGE,
        "admission_decision": None,
        "approval_cap_guard_decision_ref": None,
        "approval_reconciliation_plan_ref": None,
        "live_execution_intent_ref": None,
    }


def _portfolio_sha256(portfolio_id: str) -> str:
    return hashlib.sha256(str(portfolio_id).encode("utf-8")).hexdigest()


def _require_source_uuid(source_client_order_id: str) -> str:
    value = str(source_client_order_id or "").strip()
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise FollowUpIntentStoreConflict(
            "source_client_order_id_invalid"
        ) from None
    if str(parsed) != value:
        raise FollowUpIntentStoreConflict(
            "source_client_order_id_invalid"
        )
    return str(parsed)


def _require_uuid(value: str, *, code: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = uuid.UUID(normalized)
    except (ValueError, AttributeError, TypeError):
        raise FollowUpIntentStoreConflict(code) from None
    if str(parsed) != normalized:
        raise FollowUpIntentStoreConflict(code)
    return normalized


def _decimal(value: Any, *, code: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except Exception:
        raise FollowUpIntentStoreConflict(code) from None
    if not normalized.is_finite():
        raise FollowUpIntentStoreConflict(code)
    return normalized


def _decimal_text(value: Any) -> str:
    normalized = Decimal(str(value))
    return format(normalized, "f")


def derive_operator_follow_up_materialization_child_id(
    *,
    root_client_order_id: str,
    source_client_order_id: str,
) -> str:
    """Use the canonical restart-stable FILLED follow-up identity formula."""

    root_id = _require_uuid(
        root_client_order_id,
        code="materialization_root_client_order_id_invalid",
    )
    source_id = _require_uuid(
        source_client_order_id,
        code="source_client_order_id_invalid",
    )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coinbase://filled-follow-up/{root_id}/{source_id}",
        )
    )


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, value))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], Mapping):
        return [dict(value) for value in values]
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, value)) for value in values]


class OperatorFollowUpIntentRepository:
    """PostgreSQL repository with one transaction and lock per source action."""

    def __init__(
        self,
        db: Any,
        *,
        configured_spot_portfolio_id: str,
        schema: str = "public",
        product_context_resolver: Callable[[str], Mapping[str, Any]] = (
            resolve_product_context
        ),
        spot_policy_evaluator: Callable[..., Any] = evaluate_spot_follow_up_policy,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("invalid_follow_up_intent_schema")
        self.db = db
        self.schema = str(schema)
        self.configured_spot_portfolio_id = str(
            configured_spot_portfolio_id or ""
        ).strip()
        self.product_context_resolver = product_context_resolver
        self.spot_policy_evaluator = spot_policy_evaluator
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('order_follow_up_semantic_claim')} (
                            claim_id UUID PRIMARY KEY,
                            source_client_order_id VARCHAR(128) NOT NULL,
                            claim_kind VARCHAR(40) NOT NULL,
                            trigger VARCHAR(20),
                            state VARCHAR(20) NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (source_client_order_id, claim_kind)
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS order_follow_up_semantic_claim_source_idx
                        ON {self._table('order_follow_up_semantic_claim')}
                        (source_client_order_id, state)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_intent_audit_outbox')} (
                            audit_id UUID PRIMARY KEY,
                            follow_up_intent_id UUID NOT NULL UNIQUE,
                            source_client_order_id VARCHAR(128) NOT NULL UNIQUE,
                            event_json JSONB NOT NULL,
                            event_sha256 CHAR(64) NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL,
                            projected_at TIMESTAMPTZ
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS operator_follow_up_intent_audit_pending_idx
                        ON {self._table('operator_follow_up_intent_audit_outbox')}
                        (recorded_at ASC, audit_id ASC)
                        WHERE projected_at IS NULL
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_intent')} (
                            follow_up_intent_id UUID PRIMARY KEY,
                            claim_id UUID NOT NULL UNIQUE,
                            source_client_order_id VARCHAR(128) NOT NULL UNIQUE,
                            root_client_order_id VARCHAR(128) NOT NULL,
                            product_id VARCHAR(255) NOT NULL,
                            source_side VARCHAR(10) NOT NULL,
                            derived_follow_up_side VARCHAR(10) NOT NULL,
                            semantic_intent VARCHAR(40) NOT NULL,
                            intent_sha256 CHAR(64) NOT NULL,
                            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                            payload_sha256 CHAR(64) NOT NULL,
                            actor_id VARCHAR(255) NOT NULL,
                            roles_json JSONB NOT NULL,
                            environment VARCHAR(64) NOT NULL,
                            portfolio_scope_sha256 CHAR(64) NOT NULL,
                            correlation_id VARCHAR(255) NOT NULL,
                            operator_intent VARCHAR(255) NOT NULL,
                            audit_id UUID NOT NULL UNIQUE,
                            terminal_result VARCHAR(20) NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (claim_id)
                                REFERENCES {self._table('order_follow_up_semantic_claim')}(claim_id)
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_materialization_attempt')} (
                            materialization_id UUID PRIMARY KEY,
                            audit_id UUID NOT NULL UNIQUE,
                            follow_up_intent_id UUID NOT NULL UNIQUE,
                            source_client_order_id VARCHAR(128) NOT NULL UNIQUE,
                            root_client_order_id VARCHAR(128) NOT NULL,
                            child_client_order_id UUID NOT NULL UNIQUE,
                            product_id VARCHAR(255) NOT NULL,
                            child_side VARCHAR(10) NOT NULL
                                CHECK (child_side IN ('BUY', 'SELL')),
                            base_size NUMERIC(36, 18) NOT NULL
                                CHECK (base_size > 0),
                            limit_price NUMERIC(36, 18) NOT NULL
                                CHECK (limit_price > 0),
                            portfolio_id UUID NOT NULL,
                            portfolio_scope_sha256 CHAR(64) NOT NULL,
                            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                            payload_sha256 CHAR(64) NOT NULL,
                            actor_id VARCHAR(255) NOT NULL,
                            roles_json JSONB NOT NULL,
                            environment VARCHAR(64) NOT NULL,
                            correlation_id VARCHAR(255) NOT NULL,
                            operator_intent VARCHAR(255) NOT NULL,
                            prepared_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (follow_up_intent_id)
                                REFERENCES {self._table('operator_follow_up_intent')}(follow_up_intent_id)
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS operator_follow_up_materialization_lineage_idx
                        ON {self._table('operator_follow_up_materialization_attempt')}
                        (root_client_order_id, child_client_order_id)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_materialization_event')} (
                            event_sequence BIGSERIAL PRIMARY KEY,
                            event_id UUID NOT NULL UNIQUE,
                            materialization_id UUID NOT NULL,
                            state VARCHAR(48) NOT NULL
                                CHECK (state IN ({_MATERIALIZATION_STATE_SQL})),
                            diagnostic_code VARCHAR(96) NOT NULL,
                            exchange_order_id_sha256 CHAR(64),
                            operation_idempotency_key_sha256 CHAR(64) NOT NULL,
                            operation_audit_id UUID NOT NULL,
                            operation_actor_id VARCHAR(255) NOT NULL,
                            operation_roles_json JSONB NOT NULL,
                            operation_environment VARCHAR(64) NOT NULL,
                            operation_operator_intent VARCHAR(255) NOT NULL,
                            operation_correlation_id VARCHAR(255) NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (materialization_id, state),
                            FOREIGN KEY (materialization_id)
                                REFERENCES {self._table('operator_follow_up_materialization_attempt')}(materialization_id)
                        )
                        """
                    )
                    cursor.execute(
                        f"DROP TRIGGER IF EXISTS "
                        "operator_follow_up_materialization_event_append_only "
                        f"ON {self._table('operator_follow_up_materialization_event')}"
                    )
                    cursor.execute(
                        f"ALTER TABLE {self._table('operator_follow_up_materialization_event')} "
                        "DROP CONSTRAINT IF EXISTS "
                        "operator_follow_up_materialization_event_state_check"
                    )
                    cursor.execute(
                        f"ALTER TABLE {self._table('operator_follow_up_materialization_event')} "
                        "ADD CONSTRAINT "
                        "operator_follow_up_materialization_event_state_check "
                        f"CHECK (state IN ({_MATERIALIZATION_STATE_SQL}))"
                    )
                    for column_name, column_type in (
                        ("operation_idempotency_key_sha256", "CHAR(64)"),
                        ("operation_audit_id", "UUID"),
                        ("operation_actor_id", "VARCHAR(255)"),
                        ("operation_roles_json", "JSONB"),
                        ("operation_environment", "VARCHAR(64)"),
                        ("operation_operator_intent", "VARCHAR(255)"),
                        ("operation_correlation_id", "VARCHAR(255)"),
                    ):
                        cursor.execute(
                            f"ALTER TABLE {self._table('operator_follow_up_materialization_event')} "
                            f"ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                        )
                    self._backfill_materialization_operation_bindings(cursor)
                    for column_name in (
                        "operation_idempotency_key_sha256",
                        "operation_audit_id",
                        "operation_actor_id",
                        "operation_roles_json",
                        "operation_environment",
                        "operation_operator_intent",
                        "operation_correlation_id",
                    ):
                        cursor.execute(
                            f"ALTER TABLE {self._table('operator_follow_up_materialization_event')} "
                            f"ALTER COLUMN {column_name} SET NOT NULL"
                        )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS operator_follow_up_materialization_event_latest_idx
                        ON {self._table('operator_follow_up_materialization_event')}
                        (materialization_id, event_sequence DESC)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS operator_follow_up_materialization_event_audit_idx
                        ON {self._table('operator_follow_up_materialization_event')}
                        (operation_audit_id, event_sequence ASC)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_materialized_child_state_event')} (
                            local_state_sequence BIGSERIAL NOT NULL UNIQUE,
                            local_state_event_id UUID PRIMARY KEY,
                            materialization_id UUID NOT NULL,
                            child_client_order_id UUID NOT NULL,
                            transition_kind VARCHAR(48) NOT NULL
                                CHECK (transition_kind IN ({_MATERIALIZED_CHILD_TRANSITION_SQL})),
                            authoritative_order_status VARCHAR(32) NOT NULL,
                            exchange_order_id_sha256 CHAR(64),
                            operation_audit_id UUID NOT NULL,
                            operation_idempotency_key_sha256 CHAR(64) NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (materialization_id, transition_kind),
                            FOREIGN KEY (materialization_id)
                                REFERENCES {self._table('operator_follow_up_materialization_attempt')}(materialization_id)
                        )
                        """
                    )
                    cursor.execute(
                        f"ALTER TABLE {self._table('operator_follow_up_materialized_child_state_event')} "
                        "ADD COLUMN IF NOT EXISTS local_state_sequence BIGSERIAL"
                    )
                    cursor.execute(
                        f"ALTER TABLE {self._table('operator_follow_up_materialized_child_state_event')} "
                        "ALTER COLUMN local_state_sequence SET NOT NULL"
                    )
                    cursor.execute(
                        f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS
                            operator_follow_up_materialized_child_state_sequence_idx
                        ON {self._table('operator_follow_up_materialized_child_state_event')}
                        (local_state_sequence)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS operator_follow_up_materialized_child_state_audit_idx
                        ON {self._table('operator_follow_up_materialized_child_state_event')}
                        (operation_audit_id, recorded_at ASC)
                        """
                    )
                    self._backfill_audit_outbox(cursor)
                    self._install_audit_outbox_constraints(cursor)
                    cursor.execute(
                        f"""
                        CREATE OR REPLACE FUNCTION {self._table('lock_operator_follow_up_source')}()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $$
                        BEGIN
                            IF NEW.client_order_id IS NOT NULL THEN
                                PERFORM pg_advisory_xact_lock(
                                    17291,
                                    hashtext(NEW.client_order_id::text)
                                );
                            END IF;
                            RETURN NEW;
                        END;
                        $$
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE OR REPLACE FUNCTION {self._table('guard_operator_follow_up_lineage')}()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $$
                        BEGIN
                            IF NEW.parent_order_id IS NOT NULL THEN
                                PERFORM pg_advisory_xact_lock(
                                    17291,
                                    hashtext(NEW.parent_order_id::text)
                                );
                                IF EXISTS (
                                    SELECT 1
                                      FROM {self._table('operator_follow_up_intent')}
                                     WHERE source_client_order_id = NEW.parent_order_id::text
                                        OR root_client_order_id = NEW.parent_order_id::text
                                ) AND NOT EXISTS (
                                    SELECT 1
                                      FROM {self._table('operator_follow_up_materialization_attempt')} AS attempt
                                      JOIN {self._table('operator_follow_up_intent')} AS intent
                                        ON intent.follow_up_intent_id = attempt.follow_up_intent_id
                                     WHERE attempt.child_client_order_id::text = NEW.client_order_id::text
                                       AND attempt.root_client_order_id = NEW.parent_order_id::text
                                       AND attempt.source_client_order_id = intent.source_client_order_id
                                       AND attempt.product_id = NEW.product_id::text
                                       AND attempt.child_side = UPPER(NEW.side::text)
                                       AND attempt.base_size = NEW.size
                                       AND attempt.limit_price = NEW.price
                                       AND attempt.portfolio_id = NEW.retail_portfolio_id
                                       AND NEW.status::text = 'PENDING'
                                       AND NEW.ownership_provenance::text = 'ADMIN_FILL_FOLLOW_UP'
                                       AND (
                                           SELECT event.state
                                             FROM {self._table('operator_follow_up_materialization_event')} AS event
                                            WHERE event.materialization_id = attempt.materialization_id
                                            ORDER BY event.event_sequence DESC
                                            LIMIT 1
                                       ) = 'KNOWN_NOT_INVOKED'
                                ) THEN
                                    RAISE EXCEPTION USING
                                        ERRCODE = 'P0001',
                                        MESSAGE = 'operator_follow_up_intent_lineage_locked';
                                END IF;
                            END IF;
                            RETURN NEW;
                        END;
                        $$
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE OR REPLACE FUNCTION {self._table('guard_operator_follow_up_materialization_append_only')}()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $$
                        BEGIN
                            RAISE EXCEPTION USING
                                ERRCODE = 'P0001',
                                MESSAGE = 'operator_follow_up_materialization_append_only';
                        END;
                        $$
                        """
                    )
                    for table_name in (
                        "operator_follow_up_materialization_attempt",
                        "operator_follow_up_materialization_event",
                        "operator_follow_up_materialized_child_state_event",
                    ):
                        trigger_name = f"{table_name}_append_only"
                        cursor.execute(
                            f"DROP TRIGGER IF EXISTS {trigger_name} "
                            f"ON {self._table(table_name)}"
                        )
                        cursor.execute(
                            f"""
                            CREATE TRIGGER {trigger_name}
                            BEFORE UPDATE OR DELETE ON {self._table(table_name)}
                            FOR EACH ROW
                            EXECUTE FUNCTION {self._table('guard_operator_follow_up_materialization_append_only')}()
                            """
                        )
                    self._install_lineage_lock_trigger(cursor)
                    for table_name in _POSITIVE_FILL_EVIDENCE_TABLES:
                        self._install_source_lock_trigger(cursor, table_name)
            except Exception as exc:
                raise FollowUpIntentStoreUnavailable(
                    "follow_up_intent_store_unavailable"
                ) from None
            self._schema_ready = True

    def _backfill_materialization_operation_bindings(self, cursor: Any) -> None:
        """Upgrade pre-binding journals without changing their state history."""

        cursor.execute(
            f"""
            SELECT materialization_id, audit_id, idempotency_key, actor_id,
                   roles_json, environment, operator_intent, correlation_id
              FROM {self._table('operator_follow_up_materialization_attempt')}
             ORDER BY prepared_at ASC, materialization_id ASC
            """
        )
        for attempt in _rows(cursor):
            materialization_id = str(attempt["materialization_id"])
            cursor.execute(
                f"""
                SELECT event_sequence, state,
                       operation_idempotency_key_sha256,
                       operation_audit_id, operation_actor_id,
                       operation_roles_json, operation_environment,
                       operation_operator_intent, operation_correlation_id
                  FROM {self._table('operator_follow_up_materialization_event')}
                 WHERE materialization_id = %s
                 ORDER BY event_sequence ASC
                """,
                (materialization_id,),
            )
            events = _rows(cursor)
            groups: dict[str, list[dict[str, Any]]] = {
                "create": [],
                "cancel": [],
                "terminal_without_cancel": [],
            }
            for event in events:
                state = str(event.get("state") or "")
                if state == FollowUpMaterializationState.CANCEL_NOT_REQUIRED_TERMINAL.value:
                    groups["terminal_without_cancel"].append(event)
                elif state.startswith("CANCEL_"):
                    groups["cancel"].append(event)
                else:
                    groups["create"].append(event)

            attempt_roles = attempt.get("roles_json")
            if isinstance(attempt_roles, str):
                attempt_roles = json.loads(attempt_roles)
            if not isinstance(attempt_roles, list):
                raise ValueError("follow_up_materialization_roles_invalid")
            prepare_binding = {
                "operation_idempotency_key_sha256": hashlib.sha256(
                    str(attempt["idempotency_key"]).encode("utf-8")
                ).hexdigest(),
                "operation_audit_id": str(attempt["audit_id"]),
                "operation_actor_id": str(attempt["actor_id"]),
                "operation_roles_json": list(attempt_roles),
                "operation_environment": str(attempt["environment"]),
                "operation_operator_intent": str(attempt["operator_intent"]),
                "operation_correlation_id": str(attempt["correlation_id"]),
            }

            for group_name, group_events in groups.items():
                if not group_events:
                    continue
                if group_name == "create":
                    binding = dict(prepare_binding)
                else:
                    binding = {}
                    defaults = {
                        **prepare_binding,
                        "operation_idempotency_key_sha256": hashlib.sha256(
                            (
                                "legacy-operator-follow-up-materialization/"
                                f"{materialization_id}/{group_name}"
                            ).encode("utf-8")
                        ).hexdigest(),
                        "operation_audit_id": str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                (
                                    "coinbase://operator-follow-up-materialization/"
                                    f"{materialization_id}/{group_name}-audit"
                                ),
                            )
                        ),
                    }
                    for field_name, default in defaults.items():
                        present = [
                            event.get(field_name)
                            for event in group_events
                            if event.get(field_name) is not None
                        ]
                        if field_name == "operation_roles_json":
                            present = [
                                json.loads(value) if isinstance(value, str) else value
                                for value in present
                            ]
                        if present and any(value != present[0] for value in present[1:]):
                            raise ValueError(
                                "follow_up_materialization_operation_binding_mismatch"
                            )
                        binding[field_name] = present[0] if present else default

                for event in group_events:
                    needs_update = False
                    for field_name, expected in binding.items():
                        current = event.get(field_name)
                        if field_name == "operation_roles_json" and isinstance(
                            current, str
                        ):
                            current = json.loads(current)
                        if current is not None and current != expected:
                            raise ValueError(
                                "follow_up_materialization_operation_binding_mismatch"
                            )
                        if current is None:
                            needs_update = True
                    if not needs_update:
                        continue
                    cursor.execute(
                        f"""
                        UPDATE {self._table('operator_follow_up_materialization_event')}
                           SET operation_idempotency_key_sha256 = %s,
                               operation_audit_id = %s,
                               operation_actor_id = %s,
                               operation_roles_json = %s::jsonb,
                               operation_environment = %s,
                               operation_operator_intent = %s,
                               operation_correlation_id = %s
                         WHERE event_sequence = %s
                        """,
                        (
                            binding["operation_idempotency_key_sha256"],
                            binding["operation_audit_id"],
                            binding["operation_actor_id"],
                            json.dumps(
                                binding["operation_roles_json"],
                                separators=(",", ":"),
                            ),
                            binding["operation_environment"],
                            binding["operation_operator_intent"],
                            binding["operation_correlation_id"],
                            event["event_sequence"],
                        ),
                    )

    def _backfill_audit_outbox(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            SELECT intent.follow_up_intent_id, intent.source_client_order_id,
                   intent.audit_id, intent.recorded_at, intent.actor_id,
                   intent.correlation_id, intent.operator_intent,
                   intent.idempotency_key, intent.terminal_result
              FROM {self._table('operator_follow_up_intent')} AS intent
              LEFT JOIN {self._table('operator_follow_up_intent_audit_outbox')} AS outbox
                ON outbox.audit_id = intent.audit_id
             WHERE outbox.audit_id IS NULL
             ORDER BY intent.recorded_at ASC, intent.audit_id ASC
            """
        )
        for row in _rows(cursor):
            if str(row.get("terminal_result") or "") != "ATTACHED":
                raise ValueError("follow_up_intent_audit_outbox_backfill_mismatch")
            recorded_at = _utc_iso(row["recorded_at"])
            event = _canonical_audit_event(
                audit_id=str(row["audit_id"]),
                recorded_at=recorded_at,
                actor_id=str(row["actor_id"]),
                correlation_id=str(row["correlation_id"]),
                operator_intent=str(row["operator_intent"]),
                idempotency_key=str(row["idempotency_key"]),
                source_client_order_id=str(row["source_client_order_id"]),
            )
            cursor.execute(
                f"""
                INSERT INTO {self._table('operator_follow_up_intent_audit_outbox')} (
                    audit_id, follow_up_intent_id, source_client_order_id,
                    event_json, event_sha256, recorded_at
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (audit_id) DO NOTHING
                """,
                (
                    str(row["audit_id"]),
                    str(row["follow_up_intent_id"]),
                    str(row["source_client_order_id"]),
                    json.dumps(event, sort_keys=True, separators=(",", ":")),
                    _canonical_sha256(event),
                    row["recorded_at"],
                ),
            )

        cursor.execute(
            f"""
            SELECT intent.follow_up_intent_id, intent.source_client_order_id,
                   intent.audit_id, intent.recorded_at, intent.actor_id,
                   intent.correlation_id, intent.operator_intent,
                   intent.idempotency_key, intent.terminal_result,
                   outbox.follow_up_intent_id AS outbox_follow_up_intent_id,
                   outbox.source_client_order_id AS outbox_source_client_order_id,
                   outbox.event_json, outbox.event_sha256,
                   outbox.recorded_at AS outbox_recorded_at
              FROM {self._table('operator_follow_up_intent')} AS intent
              LEFT JOIN {self._table('operator_follow_up_intent_audit_outbox')} AS outbox
                ON outbox.audit_id = intent.audit_id
             ORDER BY intent.recorded_at ASC, intent.audit_id ASC
            """
        )
        for row in _rows(cursor):
            recorded_at = _utc_iso(row["recorded_at"])
            event = _canonical_audit_event(
                audit_id=str(row["audit_id"]),
                recorded_at=recorded_at,
                actor_id=str(row["actor_id"]),
                correlation_id=str(row["correlation_id"]),
                operator_intent=str(row["operator_intent"]),
                idempotency_key=str(row["idempotency_key"]),
                source_client_order_id=str(row["source_client_order_id"]),
            )
            if (
                str(row.get("terminal_result") or "") != "ATTACHED"
                or str(row.get("outbox_follow_up_intent_id") or "")
                != str(row["follow_up_intent_id"])
                or str(row.get("outbox_source_client_order_id") or "")
                != str(row["source_client_order_id"])
                or row.get("event_json") != event
                or str(row.get("event_sha256") or "")
                != _canonical_sha256(event)
                or _utc_iso(row.get("outbox_recorded_at")) != recorded_at
            ):
                raise ValueError("follow_up_intent_audit_outbox_backfill_mismatch")

    def _install_audit_outbox_constraints(self, cursor: Any) -> None:
        constraints = (
            (
                "operator_follow_up_intent",
                "operator_follow_up_intent_audit_outbox_fk",
                (
                    f"ALTER TABLE {self._table('operator_follow_up_intent')} "
                    "ADD CONSTRAINT operator_follow_up_intent_audit_outbox_fk "
                    f"FOREIGN KEY (audit_id) REFERENCES "
                    f"{self._table('operator_follow_up_intent_audit_outbox')}(audit_id) "
                    "DEFERRABLE INITIALLY DEFERRED"
                ),
            ),
            (
                "operator_follow_up_intent_audit_outbox",
                "operator_follow_up_intent_outbox_intent_fk",
                (
                    f"ALTER TABLE {self._table('operator_follow_up_intent_audit_outbox')} "
                    "ADD CONSTRAINT operator_follow_up_intent_outbox_intent_fk "
                    f"FOREIGN KEY (follow_up_intent_id) REFERENCES "
                    f"{self._table('operator_follow_up_intent')}(follow_up_intent_id) "
                    "DEFERRABLE INITIALLY DEFERRED"
                ),
            ),
        )
        for table_name, constraint_name, statement in constraints:
            cursor.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_constraint "
                "WHERE conrelid = to_regclass(%s) AND conname = %s"
                ")",
                (f"{self.schema}.{table_name}", constraint_name),
            )
            row = cursor.fetchone()
            exists = (
                bool(next(iter(row.values()), False))
                if isinstance(row, Mapping)
                else bool(row and row[0])
            )
            if not exists:
                cursor.execute(statement)

    def _install_lineage_lock_trigger(self, cursor: Any) -> None:
        cursor.execute(
            "SELECT to_regclass(%s)",
            (f"{self.schema}.order_parent",),
        )
        row = cursor.fetchone()
        relation = (
            next(iter(row.values()), None)
            if isinstance(row, Mapping)
            else (row[0] if row else None)
        )
        if relation is None:
            return
        trigger_name = "operator_follow_up_lineage_lock"
        cursor.execute(
            f"DROP TRIGGER IF EXISTS {trigger_name} ON {self._table('order_parent')}"
        )
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT OR UPDATE OF parent_order_id
            ON {self._table('order_parent')}
            FOR EACH ROW
            EXECUTE FUNCTION {self._table('guard_operator_follow_up_lineage')}()
            """
        )

    def _install_source_lock_trigger(self, cursor: Any, table_name: str) -> None:
        if table_name not in _POSITIVE_FILL_EVIDENCE_TABLES:
            raise ValueError("unsupported_follow_up_source_lock_table")
        cursor.execute("SELECT to_regclass(%s)", (f"{self.schema}.{table_name}",))
        row = cursor.fetchone()
        relation = (
            next(iter(row.values()), None)
            if isinstance(row, Mapping)
            else (row[0] if row else None)
        )
        if relation is None:
            return
        trigger_name = "operator_follow_up_source_lock"
        cursor.execute(
            f"DROP TRIGGER IF EXISTS {trigger_name} ON {self._table(table_name)}"
        )
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT OR UPDATE ON {self._table(table_name)}
            FOR EACH ROW
            EXECUTE FUNCTION {self._table('lock_operator_follow_up_source')}()
            """
        )

    def install_source_lock_trigger(self, table_name: str) -> None:
        """Install the source advisory-lock trigger on a newly created table."""

        if not self._schema_ready:
            return
        try:
            with self.db.get_cursor() as cursor:
                self._install_source_lock_trigger(cursor, table_name)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_source_lock_unavailable"
            ) from None

    def install_lineage_lock_trigger(self) -> None:
        """Install the lineage interlock after ``order_parent`` is created."""

        if not self._schema_ready:
            return
        try:
            with self.db.get_cursor() as cursor:
                self._install_lineage_lock_trigger(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_lineage_lock_unavailable"
            ) from None

    @staticmethod
    def _lock_source(cursor: Any, source_client_order_id: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (17291, source_client_order_id),
        )

    def _read_intent(self, cursor: Any, source_client_order_id: str) -> FollowUpIntentRecord | None:
        cursor.execute(
            f"""
            SELECT follow_up_intent_id, claim_id, source_client_order_id,
                   root_client_order_id, semantic_intent,
                   derived_follow_up_side, intent_sha256, audit_id,
                   correlation_id, actor_id, environment,
                   portfolio_scope_sha256, idempotency_key, payload_sha256,
                   recorded_at
              FROM {self._table('operator_follow_up_intent')}
             WHERE source_client_order_id = %s
            """,
            (source_client_order_id,),
        )
        row = _row(cursor)
        return self._record(row) if row else None

    def _read_intent_by_idempotency(self, cursor: Any, key: str) -> FollowUpIntentRecord | None:
        cursor.execute(
            f"""
            SELECT follow_up_intent_id, claim_id, source_client_order_id,
                   root_client_order_id, semantic_intent,
                   derived_follow_up_side, intent_sha256, audit_id,
                   correlation_id, actor_id, environment,
                   portfolio_scope_sha256, idempotency_key, payload_sha256,
                   recorded_at
              FROM {self._table('operator_follow_up_intent')}
             WHERE idempotency_key = %s
            """,
            (key,),
        )
        row = _row(cursor)
        return self._record(row) if row else None

    @staticmethod
    def _record(row: Mapping[str, Any]) -> FollowUpIntentRecord:
        recorded_at = row["recorded_at"]
        if isinstance(recorded_at, datetime):
            recorded_at = recorded_at.astimezone(timezone.utc).isoformat()
        return FollowUpIntentRecord(
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            claim_id=str(row["claim_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            root_client_order_id=str(row["root_client_order_id"]),
            semantic_intent=str(row["semantic_intent"]),
            derived_follow_up_side=str(row["derived_follow_up_side"]),
            intent_sha256=str(row["intent_sha256"]),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            actor_id=str(row["actor_id"]),
            environment=str(row["environment"]),
            portfolio_scope_sha256=str(row["portfolio_scope_sha256"]),
            idempotency_key=str(row["idempotency_key"]),
            payload_sha256=str(row["payload_sha256"]),
            recorded_at=str(recorded_at),
        )

    @staticmethod
    def _audit_outbox_record(
        row: Mapping[str, Any],
    ) -> FollowUpIntentAuditOutboxRecord:
        event = row.get("event_json")
        if isinstance(event, str):
            event = json.loads(event)
        if not isinstance(event, Mapping):
            raise ValueError("follow_up_intent_audit_outbox_invalid")
        projected_at = row.get("projected_at")
        return FollowUpIntentAuditOutboxRecord(
            audit_id=str(row["audit_id"]),
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            event=dict(event),
            event_sha256=str(row["event_sha256"]),
            recorded_at=_utc_iso(row["recorded_at"]),
            projected_at=(
                _utc_iso(projected_at) if projected_at is not None else None
            ),
        )

    def read_audit_outbox(
        self,
        audit_id: str,
    ) -> FollowUpIntentAuditOutboxRecord:
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT audit_id, follow_up_intent_id,
                           source_client_order_id, event_json,
                           event_sha256, recorded_at, projected_at
                      FROM {self._table('operator_follow_up_intent_audit_outbox')}
                     WHERE audit_id = %s
                    """,
                    (audit_id,),
                )
                row = _row(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_audit_outbox_unavailable"
            ) from None
        if row is None:
            raise FollowUpIntentStoreConflict(
                "follow_up_intent_audit_outbox_missing"
            )
        try:
            return self._audit_outbox_record(row)
        except Exception:
            raise FollowUpIntentStoreConflict(
                "follow_up_intent_audit_outbox_mismatch"
            ) from None

    def list_unprojected_audit_outbox(
        self,
        *,
        limit: int,
    ) -> tuple[FollowUpIntentAuditOutboxRecord, ...]:
        bounded_limit = max(1, min(int(limit), 100))
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT audit_id, follow_up_intent_id,
                           source_client_order_id, event_json,
                           event_sha256, recorded_at, projected_at
                      FROM {self._table('operator_follow_up_intent_audit_outbox')}
                     WHERE projected_at IS NULL
                     ORDER BY recorded_at ASC, audit_id ASC
                     LIMIT %s
                    """,
                    (bounded_limit,),
                )
                rows = _rows(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_audit_outbox_unavailable"
            ) from None
        try:
            return tuple(self._audit_outbox_record(row) for row in rows)
        except Exception:
            raise FollowUpIntentStoreConflict(
                "follow_up_intent_audit_outbox_mismatch"
            ) from None

    def mark_audit_projected(
        self,
        *,
        audit_id: str,
        event_sha256: str,
    ) -> FollowUpIntentAuditOutboxRecord:
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_follow_up_intent_audit_outbox')}
                       SET projected_at = COALESCE(projected_at, CURRENT_TIMESTAMP)
                     WHERE audit_id = %s AND event_sha256 = %s
                    RETURNING audit_id, follow_up_intent_id,
                              source_client_order_id, event_json,
                              event_sha256, recorded_at, projected_at
                    """,
                    (audit_id, event_sha256),
                )
                row = _row(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_audit_outbox_unavailable"
            ) from None
        if row is None:
            raise FollowUpIntentStoreConflict(
                "follow_up_intent_audit_outbox_mismatch"
            )
        try:
            return self._audit_outbox_record(row)
        except Exception:
            raise FollowUpIntentStoreConflict(
                "follow_up_intent_audit_outbox_mismatch"
            ) from None

    def _exists(self, cursor: Any, query: str, params: tuple[Any, ...]) -> bool:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return False
        if isinstance(row, Mapping):
            return bool(next(iter(row.values()), False))
        return bool(row[0])

    @staticmethod
    def _materialization_event_record(
        row: Mapping[str, Any],
    ) -> FollowUpMaterializationEventRecord:
        roles = row.get("operation_roles_json")
        if isinstance(roles, str):
            roles = json.loads(roles)
        if not isinstance(roles, list):
            raise ValueError("follow_up_materialization_operation_roles_invalid")
        return FollowUpMaterializationEventRecord(
            event_id=str(row["event_id"]),
            materialization_id=str(row["materialization_id"]),
            state=str(row["state"]),
            diagnostic_code=str(row["diagnostic_code"]),
            exchange_order_id_sha256=(
                str(row["exchange_order_id_sha256"])
                if row.get("exchange_order_id_sha256")
                else None
            ),
            operation_idempotency_key_sha256=(
                str(row["operation_idempotency_key_sha256"])
                if row.get("operation_idempotency_key_sha256")
                else None
            ),
            operation_audit_id=str(row["operation_audit_id"]),
            actor_id=str(row["operation_actor_id"]),
            roles=tuple(str(role) for role in roles),
            environment=str(row["operation_environment"]),
            operator_intent=str(row["operation_operator_intent"]),
            correlation_id=str(row["operation_correlation_id"]),
            recorded_at=_utc_iso(row["recorded_at"]),
        )

    @staticmethod
    def _materialized_child_local_state_record(
        row: Mapping[str, Any],
    ) -> FollowUpMaterializedChildLocalStateRecord:
        return FollowUpMaterializedChildLocalStateRecord(
            local_state_event_id=str(row["local_state_event_id"]),
            materialization_id=str(row["materialization_id"]),
            child_client_order_id=str(row["child_client_order_id"]),
            transition_kind=str(row["transition_kind"]),
            authoritative_order_status=str(row["authoritative_order_status"]),
            exchange_order_id_sha256=(
                str(row["exchange_order_id_sha256"])
                if row.get("exchange_order_id_sha256")
                else None
            ),
            operation_audit_id=str(row["operation_audit_id"]),
            operation_idempotency_key_sha256=str(
                row["operation_idempotency_key_sha256"]
            ),
            recorded_at=_utc_iso(row["recorded_at"]),
        )

    @staticmethod
    def _materialization_attempt_record(
        row: Mapping[str, Any],
    ) -> FollowUpMaterializationAttemptRecord:
        roles = row.get("roles_json")
        if isinstance(roles, str):
            roles = json.loads(roles)
        if not isinstance(roles, list):
            raise ValueError("follow_up_materialization_roles_invalid")
        operation_roles = row.get("operation_roles_json")
        if isinstance(operation_roles, str):
            operation_roles = json.loads(operation_roles)
        if not isinstance(operation_roles, list):
            raise ValueError("follow_up_materialization_operation_roles_invalid")
        return FollowUpMaterializationAttemptRecord(
            materialization_id=str(row["materialization_id"]),
            audit_id=str(row["audit_id"]),
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            root_client_order_id=str(row["root_client_order_id"]),
            child_client_order_id=str(row["child_client_order_id"]),
            product_id=str(row["product_id"]),
            child_side=str(row["child_side"]),
            base_size=_decimal_text(row["base_size"]),
            limit_price=_decimal_text(row["limit_price"]),
            portfolio_scope_sha256=str(row["portfolio_scope_sha256"]),
            idempotency_key=str(row["idempotency_key"]),
            payload_sha256=str(row["payload_sha256"]),
            actor_id=str(row["actor_id"]),
            roles=tuple(str(role) for role in roles),
            environment=str(row["environment"]),
            correlation_id=str(row["correlation_id"]),
            operator_intent=str(row["operator_intent"]),
            prepared_at=_utc_iso(row["prepared_at"]),
            current_state=str(row["state"]),
            current_diagnostic_code=str(row["diagnostic_code"]),
            exchange_order_id_sha256=(
                str(row["exchange_order_id_sha256"])
                if row.get("exchange_order_id_sha256")
                else None
            ),
            operation_idempotency_key_sha256=(
                str(row["operation_idempotency_key_sha256"])
                if row.get("operation_idempotency_key_sha256")
                else None
            ),
            current_operation_audit_id=str(row["operation_audit_id"]),
            current_operation_actor_id=str(row["operation_actor_id"]),
            current_operation_roles=tuple(
                str(role) for role in operation_roles
            ),
            current_operation_environment=str(row["operation_environment"]),
            current_operation_operator_intent=str(
                row["operation_operator_intent"]
            ),
            current_operation_correlation_id=str(
                row["operation_correlation_id"]
            ),
            state_recorded_at=_utc_iso(row["state_recorded_at"]),
        )

    def _read_materialization_attempt_locked(
        self,
        cursor: Any,
        *,
        source_client_order_id: str | None = None,
        idempotency_key: str | None = None,
        materialization_id: str | None = None,
    ) -> FollowUpMaterializationAttemptRecord | None:
        selectors = [
            source_client_order_id is not None,
            idempotency_key is not None,
            materialization_id is not None,
        ]
        if sum(selectors) != 1:
            raise ValueError("materialization_attempt_selector_invalid")
        if source_client_order_id is not None:
            predicate = "attempt.source_client_order_id = %s"
            parameter = source_client_order_id
        elif idempotency_key is not None:
            predicate = "attempt.idempotency_key = %s"
            parameter = idempotency_key
        else:
            predicate = "attempt.materialization_id = %s"
            parameter = materialization_id
        cursor.execute(
            f"""
            SELECT attempt.materialization_id, attempt.audit_id,
                   attempt.follow_up_intent_id,
                   attempt.source_client_order_id, attempt.root_client_order_id,
                   attempt.child_client_order_id, attempt.product_id,
                   attempt.child_side, attempt.base_size, attempt.limit_price,
                   attempt.portfolio_scope_sha256, attempt.idempotency_key,
                   attempt.payload_sha256, attempt.actor_id, attempt.roles_json,
                   attempt.environment, attempt.correlation_id,
                   attempt.operator_intent, attempt.prepared_at,
                   latest.state, latest.diagnostic_code,
                   latest.exchange_order_id_sha256,
                   latest.operation_idempotency_key_sha256,
                   latest.operation_audit_id, latest.operation_actor_id,
                   latest.operation_roles_json,
                   latest.operation_environment,
                   latest.operation_operator_intent,
                   latest.operation_correlation_id,
                   latest.recorded_at AS state_recorded_at
              FROM {self._table('operator_follow_up_materialization_attempt')} AS attempt
              JOIN LATERAL (
                    SELECT event.state, event.diagnostic_code,
                           event.exchange_order_id_sha256,
                           event.operation_idempotency_key_sha256,
                           event.operation_audit_id,
                           event.operation_actor_id,
                           event.operation_roles_json,
                           event.operation_environment,
                           event.operation_operator_intent,
                           event.operation_correlation_id,
                           event.recorded_at
                      FROM {self._table('operator_follow_up_materialization_event')} AS event
                     WHERE event.materialization_id = attempt.materialization_id
                     ORDER BY event.event_sequence DESC
                     LIMIT 1
              ) AS latest ON TRUE
             WHERE {predicate}
            """,
            (parameter,),
        )
        row = _row(cursor)
        return self._materialization_attempt_record(row) if row else None

    def _read_materialization_event_locked(
        self,
        cursor: Any,
        *,
        materialization_id: str,
        state: str,
    ) -> FollowUpMaterializationEventRecord | None:
        cursor.execute(
            f"""
            SELECT event_id, materialization_id, state, diagnostic_code,
                   exchange_order_id_sha256,
                   operation_idempotency_key_sha256, operation_audit_id,
                   operation_actor_id, operation_roles_json,
                   operation_environment, operation_operator_intent,
                   operation_correlation_id, recorded_at
              FROM {self._table('operator_follow_up_materialization_event')}
             WHERE materialization_id = %s AND state = %s
            """,
            (materialization_id, state),
        )
        row = _row(cursor)
        return self._materialization_event_record(row) if row else None

    def _evaluate_materialization_locked(
        self,
        cursor: Any,
        source_client_order_id: str,
        *,
        existing_attempt: FollowUpMaterializationAttemptRecord | None,
    ) -> FollowUpMaterializationReadiness:
        blockers: list[str] = []
        portfolio_hash = _portfolio_sha256(self.configured_spot_portfolio_id)
        cursor.execute(
            f"""
            SELECT source.client_order_id, source.product_id, source.side,
                   source.size, source.status, source.parent_order_id,
                   source.ownership_provenance, source.retail_portfolio_id,
                   intent.follow_up_intent_id, intent.claim_id,
                   intent.root_client_order_id AS intent_root_client_order_id,
                   intent.product_id AS intent_product_id,
                   intent.source_side AS intent_source_side,
                   intent.derived_follow_up_side, intent.terminal_result
              FROM {self._table('order_parent')} AS source
              LEFT JOIN {self._table('operator_follow_up_intent')} AS intent
                ON intent.source_client_order_id = source.client_order_id
             WHERE source.client_order_id = %s
             FOR UPDATE OF source
            """,
            (source_client_order_id,),
        )
        source = _row(cursor)
        if source is None:
            return FollowUpMaterializationReadiness(
                source_client_order_id=source_client_order_id,
                root_client_order_id=source_client_order_id,
                follow_up_intent_id=None,
                deterministic_child_client_order_id=None,
                eligible=False,
                eligibility_status="blocked",
                blockers=("source_order_not_found",),
                source_status="UNKNOWN",
                source_ownership_provenance="UNKNOWN",
                product_id="UNKNOWN",
                source_side="UNKNOWN",
                derived_follow_up_side=None,
                base_size=None,
                full_fill_consistent=False,
                flat_lineage_valid=False,
                child_absent=False,
                conflicting_claim_absent=False,
                portfolio_scope_sha256=portfolio_hash,
            )

        source_status = str(source.get("status") or "UNKNOWN").upper()
        provenance = str(source.get("ownership_provenance") or "UNKNOWN")
        product_id = str(source.get("product_id") or "UNKNOWN")
        source_side = str(source.get("side") or "UNKNOWN").upper()
        source_size = _decimal(source.get("size"), code="source_size_invalid")
        parent_id = str(source.get("parent_order_id") or "").strip()
        root_id = parent_id or source_client_order_id
        intent_id = (
            str(source["follow_up_intent_id"])
            if source.get("follow_up_intent_id")
            else None
        )
        derived_side = (
            str(source["derived_follow_up_side"]).upper()
            if source.get("derived_follow_up_side")
            else None
        )

        if intent_id is None:
            blockers.append("follow_up_intent_not_attached")
        else:
            if str(source.get("terminal_result") or "") != "ATTACHED":
                blockers.append("follow_up_intent_not_attached")
            if str(source.get("intent_root_client_order_id") or "") != root_id:
                blockers.append("materialization_root_mismatch")
            if str(source.get("intent_product_id") or "") != product_id:
                blockers.append("materialization_product_mismatch")
            if str(source.get("intent_source_side") or "").upper() != source_side:
                blockers.append("materialization_source_side_mismatch")

        if source_status != OrderStatus.FILLED.value:
            blockers.append("source_status_not_filled")
        if provenance not in {
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
        }:
            blockers.append("source_not_system_owned")
        if not self.configured_spot_portfolio_id:
            blockers.append("spot_portfolio_scope_unconfigured")
        elif (
            str(source.get("retail_portfolio_id") or "")
            != self.configured_spot_portfolio_id
        ):
            blockers.append("source_portfolio_scope_mismatch")
        if source_size <= 0:
            blockers.append("source_size_invalid")

        root_lineage_valid = False
        if parent_id:
            self._lock_source(cursor, root_id)
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, status, parent_order_id,
                       ownership_provenance, retail_portfolio_id
                  FROM {self._table('order_parent')}
                 WHERE client_order_id = %s
                 FOR UPDATE
                """,
                (root_id,),
            )
            root = _row(cursor)
            root_lineage_valid = not (
                root is None
                or root.get("parent_order_id")
                or str(root.get("ownership_provenance") or "")
                != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                or str(root.get("retail_portfolio_id") or "")
                != self.configured_spot_portfolio_id
                or str(root.get("product_id") or "") != product_id
                or str(root.get("status") or "").upper()
                not in {OrderStatus.FILLED.value, OrderStatus.CANCELLED.value}
            )
        else:
            root_lineage_valid = (
                provenance == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            )
        if not root_lineage_valid:
            blockers.append("source_root_lineage_invalid")

        catalog_found = False
        product_type = "UNKNOWN"
        try:
            context = dict(self.product_context_resolver(product_id))
            catalog_found = context.get("catalog_found") is True
            product_type = str(context.get("product_type") or "UNKNOWN").upper()
        except Exception:
            catalog_found = False
        if not catalog_found:
            blockers.append("source_product_unknown")
        elif product_type != "SPOT":
            blockers.append("source_product_not_spot")
        if derived_side not in {"BUY", "SELL"} or derived_side == source_side:
            blockers.append("materialization_side_mismatch")
        elif catalog_found and product_type == "SPOT":
            try:
                policy = self.spot_policy_evaluator(
                    product_id=product_id,
                    source_side=source_side,
                    follow_up_side=derived_side,
                    trigger="filled",
                )
                if getattr(policy, "allowed", False) is not True:
                    blockers.append("source_follow_up_policy_not_allowed")
            except Exception:
                blockers.append("source_follow_up_policy_not_allowed")

        cursor.execute(
            f"""
            SELECT COALESCE(SUM(quantity), 0) AS filled_size,
                   COUNT(*) FILTER (WHERE quantity > 0) AS positive_rows,
                   COUNT(*) FILTER (WHERE quantity < 0) AS negative_rows
              FROM {self._table('fill_ledger')}
             WHERE client_order_id = %s
            """,
            (source_client_order_id,),
        )
        ledger = _row(cursor) or {}
        full_fill_consistent = (
            int(ledger.get("positive_rows") or 0) > 0
            and int(ledger.get("negative_rows") or 0) == 0
            and _decimal(
                ledger.get("filled_size") or 0,
                code="source_fill_evidence_invalid",
            )
            == source_size
        )

        cursor.execute(
            f"""
            SELECT MAX(cumulative_quantity) AS cumulative_quantity,
                   MAX(number_of_fills) AS number_of_fills
              FROM {self._table('order_match_audit')}
             WHERE client_order_id = %s
            """,
            (source_client_order_id,),
        )
        match = _row(cursor) or {}
        match_quantity = _decimal(
            match.get("cumulative_quantity") or 0,
            code="source_fill_evidence_invalid",
        )
        if match_quantity > 0 and (
            match_quantity != source_size
            or int(match.get("number_of_fills") or 0) <= 0
        ):
            full_fill_consistent = False

        cursor.execute(
            f"""
            SELECT MAX(cumulative_filled_size) AS cumulative_filled_size
              FROM {self._table('order_event_stream')}
             WHERE client_order_id = %s
            """,
            (source_client_order_id,),
        )
        stream = _row(cursor) or {}
        stream_quantity = _decimal(
            stream.get("cumulative_filled_size") or 0,
            code="source_fill_evidence_invalid",
        )
        if stream_quantity > 0 and stream_quantity != source_size:
            full_fill_consistent = False

        cursor.execute(
            f"""
            SELECT MAX(last_cumulative_qty_processed) AS cumulative_quantity,
                   MAX(carry_remainder_qty) AS carry_remainder_qty,
                   MAX(last_number_of_fills_seen) AS number_of_fills,
                   MAX(last_completion_pct_seen) AS completion_pct,
                   MAX(partial_follow_ups_created) AS partial_follow_ups_created
              FROM {self._table('partial_fill_progress')}
             WHERE client_order_id = %s
            """,
            (source_client_order_id,),
        )
        progress = _row(cursor) or {}
        progress_quantity = _decimal(
            progress.get("cumulative_quantity") or 0,
            code="source_fill_evidence_invalid",
        )
        if progress_quantity > 0 and (
            progress_quantity != source_size
            or _decimal(
                progress.get("carry_remainder_qty") or 0,
                code="source_fill_evidence_invalid",
            )
            != 0
            or int(progress.get("number_of_fills") or 0) <= 0
            or _decimal(
                progress.get("completion_pct") or 0,
                code="source_fill_evidence_invalid",
            )
            != 100
            or int(progress.get("partial_follow_ups_created") or 0) != 0
        ):
            full_fill_consistent = False
        if not full_fill_consistent:
            blockers.append("source_full_fill_inconsistent")

        cursor.execute(
            f"""
            SELECT client_order_id
              FROM {self._table('order_parent')}
             WHERE parent_order_id = %s
               AND client_order_id <> %s
             LIMIT 1
            """,
            (root_id, source_client_order_id if parent_id else ""),
        )
        related_child = cursor.fetchone() is not None
        nested_child = False
        if parent_id:
            cursor.execute(
                f"""
                SELECT 1 FROM {self._table('order_parent')}
                 WHERE parent_order_id = %s LIMIT 1
                """,
                (source_client_order_id,),
            )
            nested_child = cursor.fetchone() is not None
        child_absent = not related_child and not nested_child
        if not child_absent:
            blockers.append("source_follow_up_child_already_exists")

        conflicting_claim_absent = True
        cursor.execute(
            f"""
            SELECT claim_id, claim_kind, state
              FROM {self._table('order_follow_up_semantic_claim')}
             WHERE source_client_order_id = %s AND state <> %s
            """,
            (
                source_client_order_id,
                FollowUpSemanticClaimState.RELEASED.value,
            ),
        )
        for claim in _rows(cursor):
            if (
                intent_id is not None
                and str(claim.get("claim_id") or "")
                == str(source.get("claim_id") or "")
                and str(claim.get("claim_kind") or "")
                == FollowUpSemanticClaimKind.OPERATOR_INTENT.value
                and str(claim.get("state") or "")
                == FollowUpSemanticClaimState.COMPLETED.value
            ):
                continue
            conflicting_claim_absent = False
            blockers.append("follow_up_semantic_claim_present")
        if parent_id:
            cursor.execute(
                f"""
                SELECT claim_kind, state
                  FROM {self._table('order_follow_up_semantic_claim')}
                 WHERE source_client_order_id = %s AND state <> %s
                """,
                (root_id, FollowUpSemanticClaimState.RELEASED.value),
            )
            for claim in _rows(cursor):
                if (
                    str(claim.get("state") or "")
                    == FollowUpSemanticClaimState.COMPLETED.value
                    and str(claim.get("claim_kind") or "")
                    in {
                        *_AUTOMATIC_CLAIM_KINDS,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                    }
                ):
                    continue
                conflicting_claim_absent = False
                blockers.append("follow_up_semantic_claim_present")

        deterministic_child_id = None
        if root_id and source_client_order_id:
            deterministic_child_id = (
                derive_operator_follow_up_materialization_child_id(
                    root_client_order_id=root_id,
                    source_client_order_id=source_client_order_id,
                )
            )
        if existing_attempt is not None:
            blockers.append("follow_up_materialization_already_prepared")

        blockers = list(dict.fromkeys(blockers))
        return FollowUpMaterializationReadiness(
            source_client_order_id=source_client_order_id,
            root_client_order_id=root_id,
            follow_up_intent_id=intent_id,
            deterministic_child_client_order_id=deterministic_child_id,
            eligible=not blockers,
            eligibility_status=(
                "prepared" if existing_attempt is not None else (
                    "eligible" if not blockers else "blocked"
                )
            ),
            blockers=tuple(blockers),
            source_status=source_status,
            source_ownership_provenance=provenance,
            product_id=product_id,
            source_side=source_side,
            derived_follow_up_side=derived_side,
            base_size=_decimal_text(source_size),
            full_fill_consistent=full_fill_consistent,
            flat_lineage_valid=root_lineage_valid,
            child_absent=child_absent,
            conflicting_claim_absent=conflicting_claim_absent,
            portfolio_scope_sha256=portfolio_hash,
        )

    def _evaluate_locked(
        self,
        cursor: Any,
        source_client_order_id: str,
        *,
        existing_intent: FollowUpIntentRecord | None = None,
    ) -> FollowUpIntentEligibility:
        blockers: list[str] = []
        portfolio_hash = _portfolio_sha256(self.configured_spot_portfolio_id)
        cursor.execute(
            f"""
            SELECT client_order_id, product_id, side, status, parent_order_id,
                   ownership_provenance, retail_portfolio_id
              FROM {self._table('order_parent')}
             WHERE client_order_id = %s
             FOR UPDATE
            """,
            (source_client_order_id,),
        )
        source = _row(cursor)
        if source is None:
            return FollowUpIntentEligibility(
                source_client_order_id=source_client_order_id,
                root_client_order_id=source_client_order_id,
                source_found=False,
                eligible=False,
                eligibility_status="blocked",
                blockers=("source_order_not_found",),
                source_status="UNKNOWN",
                source_ownership_provenance="UNKNOWN",
                product_id="UNKNOWN",
                product_type="UNKNOWN",
                source_is_child=False,
                source_authoritative_zero_fill=False,
                source_follow_up_child_absent=False,
                automatic_semantic_claim_absent=False,
                portfolio_scope_sha256=portfolio_hash,
                slot_used=1 if existing_intent else 0,
            )

        source_status = str(source.get("status") or "UNKNOWN").upper()
        provenance = str(source.get("ownership_provenance") or "UNKNOWN")
        product_id = str(source.get("product_id") or "UNKNOWN")
        source_side = str(source.get("side") or "").upper()
        parent_id = str(source.get("parent_order_id") or "").strip()
        root_id = parent_id or source_client_order_id
        source_is_child = bool(parent_id)

        root_lineage_valid = False
        if source_is_child:
            # Source and root advisory locks close the sibling-insert race.
            # The order_parent trigger takes the same lock before any child
            # lineage write and rejects it once an intent is durable.
            self._lock_source(cursor, root_id)
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, status, parent_order_id,
                       ownership_provenance, retail_portfolio_id
                  FROM {self._table('order_parent')}
                 WHERE client_order_id = %s
                 FOR UPDATE
                """,
                (root_id,),
            )
            root = _row(cursor)
            root_lineage_valid = not (
                root is None
                or root.get("parent_order_id")
                or str(root.get("ownership_provenance") or "")
                != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                or str(root.get("retail_portfolio_id") or "")
                != self.configured_spot_portfolio_id
                or str(root.get("product_id") or "") != product_id
                or str(root.get("status") or "").upper()
                not in {
                    OrderStatus.FILLED.value,
                    OrderStatus.CANCELLED.value,
                }
            )
        else:
            root_lineage_valid = (
                provenance == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            )

        policy = evaluate_operator_follow_up_intent_policy(
            source_status=source_status,
            source_ownership_provenance=provenance,
            spot_portfolio_configured=bool(self.configured_spot_portfolio_id),
            source_portfolio_matches=(
                str(source.get("retail_portfolio_id") or "")
                == self.configured_spot_portfolio_id
            ),
            root_lineage_valid=root_lineage_valid,
            product_id=product_id,
            source_side=source_side,
            product_context_resolver=self.product_context_resolver,
            spot_policy_evaluator=self.spot_policy_evaluator,
        )
        blockers.extend(policy.blockers)
        product_type = policy.product_type
        follow_up_side = policy.derived_follow_up_side
        semantic_intent = policy.semantic_intent

        fill_present = any(
            (
                self._exists(
                    cursor,
                    f"SELECT EXISTS (SELECT 1 FROM {self._table(table)} " + predicate + ")",
                    (source_client_order_id,),
                )
            )
            for table, predicate in (
                ("fill_ledger", "WHERE client_order_id = %s AND COALESCE(quantity, 0) > 0"),
                (
                    "order_match_audit",
                    "WHERE client_order_id = %s AND (COALESCE(cumulative_quantity, 0) > 0 OR COALESCE(derived_size_delta, 0) > 0 OR COALESCE(number_of_fills, 0) > 0)",
                ),
                (
                    "order_event_stream",
                    "WHERE client_order_id = %s AND COALESCE(cumulative_filled_size, 0) > 0",
                ),
                (
                    "partial_fill_progress",
                    "WHERE client_order_id = %s AND (COALESCE(last_cumulative_qty_processed, 0) > 0 OR COALESCE(carry_remainder_qty, 0) > 0 OR COALESCE(last_number_of_fills_seen, 0) > 0 OR COALESCE(last_completion_pct_seen, 0) > 0 OR COALESCE(partial_follow_ups_created, 0) > 0)",
                ),
            )
        )
        if fill_present:
            blockers.append("source_has_positive_fill_evidence")

        cursor.execute(
            f"""
            SELECT client_order_id
              FROM {self._table('order_parent')}
             WHERE parent_order_id = %s AND client_order_id <> %s
             ORDER BY created_at ASC, id ASC
            """,
            (root_id, source_client_order_id if source_is_child else ""),
        )
        related_children = cursor.fetchall()
        nested_children = []
        if source_is_child:
            cursor.execute(
                f"""
                SELECT client_order_id
                  FROM {self._table('order_parent')}
                 WHERE parent_order_id = %s
                 ORDER BY created_at ASC, id ASC
                """,
                (source_client_order_id,),
            )
            nested_children = cursor.fetchall()
        child_absent = not related_children and not nested_children
        if related_children:
            blockers.append(
                "source_follow_up_child_attribution_ambiguous"
                if source_is_child
                else "source_follow_up_child_already_exists"
            )
        if nested_children:
            blockers.append("source_nested_follow_up_child_present")

        cursor.execute(
            f"""
            SELECT claim_kind, state
              FROM {self._table('order_follow_up_semantic_claim')}
             WHERE source_client_order_id = %s AND state <> %s
            """,
            (
                source_client_order_id,
                FollowUpSemanticClaimState.RELEASED.value,
            ),
        )
        claim_rows = cursor.fetchall()
        automatic_claim_absent = True
        for claim_row in claim_rows:
            if isinstance(claim_row, Mapping):
                claim_kind = claim_row.get("claim_kind")
            else:
                claim_kind = claim_row[0]
            kind = str(claim_kind)
            if kind in _AUTOMATIC_CLAIM_KINDS:
                automatic_claim_absent = False
                blockers.append("automatic_follow_up_claim_present")
            elif kind == FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value:
                blockers.append("source_has_positive_fill_activity")
            elif (
                kind == FollowUpSemanticClaimKind.OPERATOR_INTENT.value
                and existing_intent is not None
            ):
                continue
            else:
                if kind != FollowUpSemanticClaimKind.OPERATOR_INTENT.value:
                    automatic_claim_absent = False
                blockers.append("follow_up_semantic_claim_present")

        if source_is_child:
            cursor.execute(
                f"""
                SELECT claim_kind, state
                  FROM {self._table('order_follow_up_semantic_claim')}
                 WHERE source_client_order_id = %s AND state <> %s
                """,
                (
                    root_id,
                    FollowUpSemanticClaimState.RELEASED.value,
                ),
            )
            for claim_row in cursor.fetchall():
                if isinstance(claim_row, Mapping):
                    claim_kind = claim_row.get("claim_kind")
                    claim_state = claim_row.get("state")
                else:
                    claim_kind, claim_state = claim_row[:2]
                kind = str(claim_kind)
                state = str(claim_state)
                if (
                    state == FollowUpSemanticClaimState.COMPLETED.value
                    and kind
                    in {
                        *_AUTOMATIC_CLAIM_KINDS,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                    }
                ):
                    # Historical root evidence produced the current child and
                    # does not consume that child's next semantic slot.
                    continue
                if kind in _AUTOMATIC_CLAIM_KINDS:
                    automatic_claim_absent = False
                    blockers.append("automatic_follow_up_claim_present")
                else:
                    blockers.append("follow_up_semantic_claim_present")

        if existing_intent is not None:
            blockers.append("follow_up_intent_already_attached")

        blockers = list(dict.fromkeys(blockers))
        return FollowUpIntentEligibility(
            source_client_order_id=source_client_order_id,
            root_client_order_id=root_id,
            source_found=True,
            eligible=not blockers,
            eligibility_status=(
                "attached" if existing_intent is not None else (
                    "eligible" if not blockers else "blocked"
                )
            ),
            blockers=tuple(blockers),
            source_status=source_status,
            source_ownership_provenance=provenance,
            product_id=product_id,
            product_type=product_type,
            source_is_child=source_is_child,
            source_authoritative_zero_fill=not fill_present,
            source_follow_up_child_absent=child_absent,
            automatic_semantic_claim_absent=automatic_claim_absent,
            portfolio_scope_sha256=portfolio_hash,
            slot_used=1 if existing_intent else 0,
            semantic_intent=semantic_intent,
            derived_follow_up_side=follow_up_side,
        )

    def read(self, source_client_order_id: str) -> FollowUpIntentReadback:
        source_client_order_id = _require_source_uuid(source_client_order_id)
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                intent = self._read_intent(cursor, source_client_order_id)
                eligibility = self._evaluate_locked(
                    cursor,
                    source_client_order_id,
                    existing_intent=intent,
                )
                return FollowUpIntentReadback(eligibility=eligibility, record=intent)
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_evidence_unavailable"
            ) from None

    def read_materialization(
        self,
        source_client_order_id: str,
    ) -> FollowUpMaterializationReadback:
        """Read durable readiness/state without running schema initialization."""

        source_client_order_id = _require_source_uuid(source_client_order_id)
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                attempt = self._read_materialization_attempt_locked(
                    cursor,
                    source_client_order_id=source_client_order_id,
                )
                readiness = self._evaluate_materialization_locked(
                    cursor,
                    source_client_order_id,
                    existing_attempt=attempt,
                )
                return FollowUpMaterializationReadback(
                    readiness=readiness,
                    attempt=attempt,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_evidence_unavailable"
            ) from None

    def list_materialization_events(
        self,
        materialization_id: str,
    ) -> tuple[FollowUpMaterializationEventRecord, ...]:
        """Return the immutable, sanitized audit journal in commit order."""

        materialization_id = _require_uuid(
            materialization_id,
            code="materialization_id_invalid",
        )
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT event_id, materialization_id, state,
                           diagnostic_code, exchange_order_id_sha256,
                           operation_idempotency_key_sha256,
                           operation_audit_id, operation_actor_id,
                           operation_roles_json, operation_environment,
                           operation_operator_intent,
                           operation_correlation_id, recorded_at
                      FROM {self._table('operator_follow_up_materialization_event')}
                     WHERE materialization_id = %s
                     ORDER BY event_sequence ASC
                    """,
                    (materialization_id,),
                )
                rows = _rows(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_evidence_unavailable"
            ) from None
        return tuple(self._materialization_event_record(row) for row in rows)

    def list_materialization_events_by_operation_audit_id(
        self,
        operation_audit_id: str,
    ) -> tuple[FollowUpMaterializationEventRecord, ...]:
        """Read one operation's immutable audit events without running DDL."""

        operation_audit_id = _require_uuid(
            operation_audit_id,
            code="materialization_operation_audit_id_invalid",
        )
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT event_id, materialization_id, state,
                           diagnostic_code, exchange_order_id_sha256,
                           operation_idempotency_key_sha256,
                           operation_audit_id, operation_actor_id,
                           operation_roles_json, operation_environment,
                           operation_operator_intent,
                           operation_correlation_id, recorded_at
                      FROM {self._table('operator_follow_up_materialization_event')}
                     WHERE operation_audit_id = %s
                     ORDER BY event_sequence ASC
                    """,
                    (operation_audit_id,),
                )
                rows = _rows(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_evidence_unavailable"
            ) from None
        return tuple(self._materialization_event_record(row) for row in rows)

    @staticmethod
    def _validate_materialization_sha256(value: str, *, code: str) -> str:
        normalized = str(value or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise FollowUpIntentStoreConflict(code)
        return normalized

    def prepare_materialization(
        self,
        command: FollowUpMaterializationCommand,
    ) -> FollowUpMaterializationPrepareResult:
        """Reserve one exact child plan before any exchange-call boundary."""

        source_id = _require_source_uuid(command.source_client_order_id)
        root_id = _require_uuid(
            command.root_client_order_id,
            code="materialization_root_client_order_id_invalid",
        )
        intent_id = _require_uuid(
            command.follow_up_intent_id,
            code="materialization_follow_up_intent_id_invalid",
        )
        portfolio_id = _require_uuid(
            command.portfolio_id,
            code="materialization_portfolio_id_invalid",
        )
        payload_sha256 = self._validate_materialization_sha256(
            command.payload_sha256,
            code="materialization_payload_sha256_invalid",
        )
        audit_id = _require_uuid(
            command.audit_id,
            code="materialization_audit_id_invalid",
        )
        base_size = _decimal(
            command.base_size,
            code="materialization_size_invalid",
        )
        limit_price = _decimal(
            command.limit_price,
            code="materialization_limit_price_invalid",
        )
        if base_size <= 0:
            raise FollowUpIntentStoreConflict("materialization_size_invalid")
        if limit_price <= 0:
            raise FollowUpIntentStoreConflict("materialization_limit_price_invalid")
        child_side = str(command.child_side or "").upper()
        if child_side not in {"BUY", "SELL"}:
            raise FollowUpIntentStoreConflict("materialization_side_mismatch")
        idempotency_key = str(command.idempotency_key or "").strip()
        if not idempotency_key:
            raise FollowUpIntentStoreConflict("idempotency_key_invalid")

        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_id)
                replay = self._read_materialization_attempt_locked(
                    cursor,
                    idempotency_key=idempotency_key,
                )
                if replay is not None:
                    exact_replay = all(
                        (
                            replay.source_client_order_id == source_id,
                            replay.root_client_order_id == root_id,
                            replay.follow_up_intent_id == intent_id,
                            replay.payload_sha256 == payload_sha256,
                            replay.product_id == str(command.product_id),
                            replay.child_side == child_side,
                            Decimal(replay.base_size) == base_size,
                            Decimal(replay.limit_price) == limit_price,
                            replay.portfolio_scope_sha256
                            == _portfolio_sha256(portfolio_id),
                            replay.actor_id == str(command.actor_id),
                            replay.environment == str(command.environment),
                            replay.operator_intent == str(command.operator_intent),
                            replay.audit_id == audit_id,
                        )
                    )
                    if not exact_replay:
                        raise FollowUpIntentStoreConflict("idempotency_conflict")
                    readiness = self._evaluate_materialization_locked(
                        cursor,
                        source_id,
                        existing_attempt=replay,
                    )
                    return FollowUpMaterializationPrepareResult(
                        readiness=readiness,
                        attempt=replay,
                        replayed=True,
                    )

                existing = self._read_materialization_attempt_locked(
                    cursor,
                    source_client_order_id=source_id,
                )
                if existing is not None:
                    raise FollowUpIntentStoreConflict(
                        "follow_up_materialization_already_prepared"
                    )
                readiness = self._evaluate_materialization_locked(
                    cursor,
                    source_id,
                    existing_attempt=None,
                )
                if not readiness.eligible:
                    raise FollowUpIntentStoreConflict(readiness.blockers[0])
                if readiness.root_client_order_id != root_id:
                    raise FollowUpIntentStoreConflict("materialization_root_mismatch")
                if readiness.follow_up_intent_id != intent_id:
                    raise FollowUpIntentStoreConflict("materialization_intent_mismatch")
                if readiness.product_id != str(command.product_id):
                    raise FollowUpIntentStoreConflict("materialization_product_mismatch")
                if readiness.derived_follow_up_side != child_side:
                    raise FollowUpIntentStoreConflict("materialization_side_mismatch")
                if Decimal(str(readiness.base_size)) != base_size:
                    raise FollowUpIntentStoreConflict("materialization_size_mismatch")
                if portfolio_id != self.configured_spot_portfolio_id:
                    raise FollowUpIntentStoreConflict(
                        "materialization_portfolio_mismatch"
                    )

                child_id = derive_operator_follow_up_materialization_child_id(
                    root_client_order_id=root_id,
                    source_client_order_id=source_id,
                )
                if readiness.deterministic_child_client_order_id != child_id:
                    raise FollowUpIntentStoreConflict(
                        "materialization_child_identity_mismatch"
                )
                materialization_id = str(uuid.uuid4())
                prepared_at = datetime.now(timezone.utc)
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_materialization_attempt')} (
                        materialization_id, audit_id, follow_up_intent_id,
                        source_client_order_id, root_client_order_id,
                        child_client_order_id, product_id, child_side,
                        base_size, limit_price, portfolio_id,
                        portfolio_scope_sha256, idempotency_key,
                        payload_sha256, actor_id, roles_json, environment,
                        correlation_id, operator_intent, prepared_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
                    )
                    """,
                    (
                        materialization_id,
                        audit_id,
                        intent_id,
                        source_id,
                        root_id,
                        child_id,
                        str(command.product_id),
                        child_side,
                        base_size,
                        limit_price,
                        portfolio_id,
                        _portfolio_sha256(portfolio_id),
                        idempotency_key,
                        payload_sha256,
                        str(command.actor_id),
                        json.dumps(list(command.roles), separators=(",", ":")),
                        str(command.environment),
                        str(command.correlation_id),
                        str(command.operator_intent),
                        prepared_at,
                    ),
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_materialization_event')} (
                        event_id, materialization_id, state,
                        diagnostic_code, operation_idempotency_key_sha256,
                        operation_audit_id, operation_actor_id,
                        operation_roles_json, operation_environment,
                        operation_operator_intent,
                        operation_correlation_id, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        str(uuid.uuid4()),
                        materialization_id,
                        FollowUpMaterializationState.KNOWN_NOT_INVOKED.value,
                        "known_not_invoked",
                        hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
                        audit_id,
                        str(command.actor_id),
                        json.dumps(list(command.roles), separators=(",", ":")),
                        str(command.environment),
                        str(command.operator_intent),
                        str(command.correlation_id),
                        prepared_at,
                    ),
                )
                attempt = self._read_materialization_attempt_locked(
                    cursor,
                    materialization_id=materialization_id,
                )
                if attempt is None:
                    raise FollowUpIntentStoreUnavailable(
                        "follow_up_materialization_persistence_unknown"
                    )
                return FollowUpMaterializationPrepareResult(
                    readiness=readiness,
                    attempt=attempt,
                    replayed=False,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_persistence_unknown"
            ) from None

    def _append_materialization_event_locked(
        self,
        cursor: Any,
        *,
        materialization_id: str,
        state: str,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None,
        operation_binding: _FollowUpMaterializationOperationBinding,
    ) -> FollowUpMaterializationEventRecord:
        cursor.execute(
            f"""
            INSERT INTO {self._table('operator_follow_up_materialization_event')} (
                event_id, materialization_id, state, diagnostic_code,
                exchange_order_id_sha256, operation_idempotency_key_sha256,
                operation_audit_id, operation_actor_id,
                operation_roles_json, operation_environment,
                operation_operator_intent, operation_correlation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s, %s, %s
            )
            RETURNING event_id, materialization_id, state, diagnostic_code,
                      exchange_order_id_sha256,
                      operation_idempotency_key_sha256,
                      operation_audit_id, operation_actor_id,
                      operation_roles_json, operation_environment,
                      operation_operator_intent,
                      operation_correlation_id, recorded_at
            """,
            (
                str(uuid.uuid4()),
                materialization_id,
                state,
                diagnostic_code,
                exchange_order_id_sha256,
                operation_binding.idempotency_key_sha256,
                operation_binding.operation_audit_id,
                operation_binding.actor_id,
                json.dumps(list(operation_binding.roles), separators=(",", ":")),
                operation_binding.environment,
                operation_binding.operator_intent,
                operation_binding.correlation_id,
            ),
        )
        row = _row(cursor)
        if row is None:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_transition_unknown"
            )
        return self._materialization_event_record(row)

    def _load_and_lock_materialization(
        self,
        cursor: Any,
        materialization_id: str,
    ) -> FollowUpMaterializationAttemptRecord:
        attempt = self._read_materialization_attempt_locked(
            cursor,
            materialization_id=materialization_id,
        )
        if attempt is None:
            raise FollowUpIntentStoreConflict("follow_up_materialization_not_found")
        self._lock_source(cursor, attempt.source_client_order_id)
        if attempt.root_client_order_id != attempt.source_client_order_id:
            self._lock_source(cursor, attempt.root_client_order_id)
        refreshed = self._read_materialization_attempt_locked(
            cursor,
            materialization_id=materialization_id,
        )
        if refreshed is None:
            raise FollowUpIntentStoreConflict("follow_up_materialization_not_found")
        return refreshed

    @staticmethod
    def _prepare_operation_binding(
        attempt: FollowUpMaterializationAttemptRecord,
    ) -> _FollowUpMaterializationOperationBinding:
        return _FollowUpMaterializationOperationBinding(
            operation_audit_id=attempt.audit_id,
            actor_id=attempt.actor_id,
            roles=attempt.roles,
            environment=attempt.environment,
            operator_intent=attempt.operator_intent,
            correlation_id=attempt.correlation_id,
            idempotency_key_sha256=hashlib.sha256(
                attempt.idempotency_key.encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _event_operation_binding(
        event: FollowUpMaterializationEventRecord,
    ) -> _FollowUpMaterializationOperationBinding:
        if not event.operation_idempotency_key_sha256:
            raise FollowUpIntentStoreConflict(
                "materialization_operation_binding_missing"
            )
        return _FollowUpMaterializationOperationBinding(
            operation_audit_id=event.operation_audit_id,
            actor_id=event.actor_id,
            roles=event.roles,
            environment=event.environment,
            operator_intent=event.operator_intent,
            correlation_id=event.correlation_id,
            idempotency_key_sha256=event.operation_idempotency_key_sha256,
        )

    @staticmethod
    def _requested_operation_binding(
        *,
        operation_idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        operation_audit_id: str | None = None,
    ) -> _FollowUpMaterializationOperationBinding:
        operation_key = str(operation_idempotency_key or "").strip()
        normalized_actor = str(actor_id or "").strip()
        normalized_roles = tuple(str(role or "").strip() for role in roles)
        normalized_environment = str(environment or "").strip()
        normalized_intent = str(operator_intent or "").strip()
        normalized_correlation = str(correlation_id or "").strip()
        if not operation_key:
            raise FollowUpIntentStoreConflict("operation_idempotency_key_invalid")
        if not normalized_actor or len(normalized_actor) > 255:
            raise FollowUpIntentStoreConflict("operation_actor_invalid")
        if (
            not normalized_roles
            or any(not role for role in normalized_roles)
            or len(set(normalized_roles)) != len(normalized_roles)
        ):
            raise FollowUpIntentStoreConflict("operation_roles_invalid")
        if not normalized_environment or len(normalized_environment) > 64:
            raise FollowUpIntentStoreConflict("operation_environment_invalid")
        if not normalized_intent or len(normalized_intent) > 255:
            raise FollowUpIntentStoreConflict("operation_intent_invalid")
        if not normalized_correlation or len(normalized_correlation) > 255:
            raise FollowUpIntentStoreConflict("operation_correlation_invalid")
        normalized_audit_id = (
            _require_uuid(
                operation_audit_id,
                code="materialization_operation_audit_id_invalid",
            )
            if operation_audit_id is not None
            else None
        )
        return _FollowUpMaterializationOperationBinding(
            operation_audit_id=normalized_audit_id,
            actor_id=normalized_actor,
            roles=normalized_roles,
            environment=normalized_environment,
            operator_intent=normalized_intent,
            correlation_id=normalized_correlation,
            idempotency_key_sha256=hashlib.sha256(
                operation_key.encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _operation_binding_matches_event(
        requested: _FollowUpMaterializationOperationBinding,
        event: FollowUpMaterializationEventRecord,
    ) -> bool:
        return all(
            (
                requested.idempotency_key_sha256
                == event.operation_idempotency_key_sha256,
                requested.actor_id == event.actor_id,
                requested.roles == event.roles,
                requested.environment == event.environment,
                requested.operator_intent == event.operator_intent,
                requested.correlation_id == event.correlation_id,
                requested.operation_audit_id in {
                    None,
                    event.operation_audit_id,
                },
            )
        )

    def _transition_materialization(
        self,
        *,
        materialization_id: str,
        target_state: str,
        expected_state: str | tuple[str, ...],
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
        operation_binding: _FollowUpMaterializationOperationBinding | None = None,
        use_prepare_operation_binding: bool = False,
        consumed_code: str,
        replay_after_progress: bool,
    ) -> FollowUpMaterializationTransitionResult:
        materialization_id = _require_uuid(
            materialization_id,
            code="materialization_id_invalid",
        )
        normalized_diagnostic = str(diagnostic_code or "").strip()
        if not re.fullmatch(r"[a-z0-9_]{1,96}", normalized_diagnostic):
            raise FollowUpIntentStoreConflict(
                "materialization_diagnostic_code_invalid"
            )
        exchange_hash = None
        if exchange_order_id_sha256 is not None:
            exchange_hash = self._validate_materialization_sha256(
                exchange_order_id_sha256,
                code="exchange_order_id_sha256_invalid",
            )
        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                attempt = self._load_and_lock_materialization(
                    cursor,
                    materialization_id,
                )
                effective_binding = (
                    self._prepare_operation_binding(attempt)
                    if use_prepare_operation_binding
                    else operation_binding
                )
                if effective_binding is None:
                    raise FollowUpIntentStoreConflict(
                        "materialization_operation_binding_missing"
                    )
                existing_event = self._read_materialization_event_locked(
                    cursor,
                    materialization_id=materialization_id,
                    state=target_state,
                )
                if existing_event is not None:
                    if (
                        existing_event.diagnostic_code != normalized_diagnostic
                        or existing_event.exchange_order_id_sha256 != exchange_hash
                        or not self._operation_binding_matches_event(
                            effective_binding,
                            existing_event,
                        )
                    ):
                        raise FollowUpIntentStoreConflict("idempotency_conflict")
                    if not replay_after_progress and attempt.current_state != target_state:
                        raise FollowUpIntentStoreConflict(consumed_code)
                    return FollowUpMaterializationTransitionResult(
                        attempt=attempt,
                        event=existing_event,
                        replayed=True,
                    )
                expected_states = (
                    (expected_state,)
                    if isinstance(expected_state, str)
                    else expected_state
                )
                if attempt.current_state not in expected_states:
                    raise FollowUpIntentStoreConflict(consumed_code)
                if effective_binding.operation_audit_id is None:
                    effective_binding = _FollowUpMaterializationOperationBinding(
                        operation_audit_id=str(uuid.uuid4()),
                        actor_id=effective_binding.actor_id,
                        roles=effective_binding.roles,
                        environment=effective_binding.environment,
                        operator_intent=effective_binding.operator_intent,
                        correlation_id=effective_binding.correlation_id,
                        idempotency_key_sha256=(
                            effective_binding.idempotency_key_sha256
                        ),
                    )
                event = self._append_materialization_event_locked(
                    cursor,
                    materialization_id=materialization_id,
                    state=target_state,
                    diagnostic_code=normalized_diagnostic,
                    exchange_order_id_sha256=exchange_hash,
                    operation_binding=effective_binding,
                )
                transitioned = self._read_materialization_attempt_locked(
                    cursor,
                    materialization_id=materialization_id,
                )
                if transitioned is None:
                    raise FollowUpIntentStoreUnavailable(
                        "follow_up_materialization_transition_unknown"
                    )
                return FollowUpMaterializationTransitionResult(
                    attempt=transitioned,
                    event=event,
                    replayed=False,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_transition_unknown"
            ) from None

    def mark_create_invocation_started(
        self,
        materialization_id: str,
    ) -> FollowUpMaterializationTransitionResult:
        return self._transition_materialization(
            materialization_id=materialization_id,
            target_state=FollowUpMaterializationState.CREATE_INVOCATION_STARTED.value,
            expected_state=FollowUpMaterializationState.KNOWN_NOT_INVOKED.value,
            diagnostic_code="create_invocation_started",
            use_prepare_operation_binding=True,
            consumed_code="create_boundary_consumed",
            replay_after_progress=True,
        )

    def record_create_result(
        self,
        materialization_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
    ) -> FollowUpMaterializationTransitionResult:
        normalized = str(outcome or "").upper()
        if normalized not in _CREATE_RESULT_STATES:
            raise FollowUpIntentStoreConflict("create_result_invalid")
        return self._transition_materialization(
            materialization_id=materialization_id,
            target_state=normalized,
            expected_state=FollowUpMaterializationState.CREATE_INVOCATION_STARTED.value,
            diagnostic_code=diagnostic_code,
            exchange_order_id_sha256=exchange_order_id_sha256,
            use_prepare_operation_binding=True,
            consumed_code="create_boundary_consumed",
            replay_after_progress=True,
        )

    def mark_cancel_invocation_started(
        self,
        materialization_id: str,
        *,
        operation_idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        operation_audit_id: str | None = None,
    ) -> FollowUpMaterializationTransitionResult:
        operation_binding = self._requested_operation_binding(
            operation_idempotency_key=operation_idempotency_key,
            actor_id=actor_id,
            roles=roles,
            environment=environment,
            operator_intent=operator_intent,
            correlation_id=correlation_id,
            operation_audit_id=operation_audit_id,
        )
        return self._transition_materialization(
            materialization_id=materialization_id,
            target_state=FollowUpMaterializationState.CANCEL_INVOCATION_STARTED.value,
            expected_state=(
                FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
                FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
            ),
            diagnostic_code="cancel_invocation_started",
            operation_binding=operation_binding,
            consumed_code=(
                "cancel_boundary_consumed"
                if self._materialization_has_cancel_boundary(materialization_id)
                else "cancel_not_eligible"
            ),
            replay_after_progress=False,
        )

    def record_child_terminal_without_cancel(
        self,
        materialization_id: str,
        *,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
        operation_idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        environment: str,
        operator_intent: str,
        correlation_id: str,
        operation_audit_id: str | None = None,
    ) -> FollowUpMaterializationTransitionResult:
        """Append reconciled terminal proof without crossing Cancel."""

        operation_binding = self._requested_operation_binding(
            operation_idempotency_key=operation_idempotency_key,
            actor_id=actor_id,
            roles=roles,
            environment=environment,
            operator_intent=operator_intent,
            correlation_id=correlation_id,
            operation_audit_id=operation_audit_id,
        )
        return self._transition_materialization(
            materialization_id=materialization_id,
            target_state=(
                FollowUpMaterializationState.CANCEL_NOT_REQUIRED_TERMINAL.value
            ),
            expected_state=(
                FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
                FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
            ),
            diagnostic_code=diagnostic_code,
            exchange_order_id_sha256=exchange_order_id_sha256,
            operation_binding=operation_binding,
            consumed_code="cancel_not_eligible",
            replay_after_progress=True,
        )

    def _materialization_has_cancel_boundary(self, materialization_id: str) -> bool:
        """Classify prior cancel start without mutating or initializing schema."""

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT 1
                      FROM {self._table('operator_follow_up_materialization_event')}
                     WHERE materialization_id = %s AND state = %s
                    """,
                    (
                        materialization_id,
                        FollowUpMaterializationState.CANCEL_INVOCATION_STARTED.value,
                    ),
                )
                return cursor.fetchone() is not None
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_evidence_unavailable"
            ) from None

    def record_cancel_result(
        self,
        materialization_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
    ) -> FollowUpMaterializationTransitionResult:
        normalized = str(outcome or "").upper()
        if normalized not in _CANCEL_RESULT_STATES:
            raise FollowUpIntentStoreConflict("cancel_result_invalid")
        operation_binding = self._cancel_operation_binding(
            materialization_id
        )
        return self._transition_materialization(
            materialization_id=materialization_id,
            target_state=normalized,
            expected_state=FollowUpMaterializationState.CANCEL_INVOCATION_STARTED.value,
            diagnostic_code=diagnostic_code,
            exchange_order_id_sha256=exchange_order_id_sha256,
            operation_binding=operation_binding,
            consumed_code="cancel_boundary_consumed",
            replay_after_progress=True,
        )

    def _cancel_operation_binding(
        self,
        materialization_id: str,
    ) -> _FollowUpMaterializationOperationBinding:
        try:
            with self.db.get_cursor() as cursor:
                event = self._read_materialization_event_locked(
                    cursor,
                    materialization_id=materialization_id,
                    state=(
                        FollowUpMaterializationState.CANCEL_INVOCATION_STARTED.value
                    ),
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_materialization_evidence_unavailable"
            ) from None
        if event is None:
            raise FollowUpIntentStoreConflict("cancel_not_started")
        return self._event_operation_binding(event)

    @staticmethod
    def _materialized_child_json_mapping(
        value: Any,
        *,
        code: str,
    ) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                raise FollowUpIntentStoreConflict(code) from None
            if isinstance(parsed, Mapping):
                return dict(parsed)
        raise FollowUpIntentStoreConflict(code)

    @staticmethod
    def _materialized_child_json_list(
        value: Any,
        *,
        code: str,
    ) -> list[Any]:
        if isinstance(value, list):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                raise FollowUpIntentStoreConflict(code) from None
            if isinstance(parsed, list):
                return list(parsed)
        raise FollowUpIntentStoreConflict(code)

    @staticmethod
    def _materialized_child_projection_matches(
        *,
        record: FollowUpMaterializedChildLocalStateRecord,
        child: Mapping[str, Any],
        stealth: Mapping[str, Any],
    ) -> bool:
        child_status = str(child.get("status") or "").upper()
        child_exchange_id = str(child.get("exchange_order_id") or "").strip()
        child_exchange_hash = (
            hashlib.sha256(child_exchange_id.encode("utf-8")).hexdigest()
            if child_exchange_id
            else None
        )
        if (
            child_status != record.authoritative_order_status
            or child_exchange_hash != record.exchange_order_id_sha256
            or _decimal(
                stealth.get("remaining_size"),
                code="materialized_child_identity_mismatch",
            )
            != 0
        ):
            return False
        transition = record.transition_kind
        stealth_status = str(stealth.get("status") or "").upper()
        try:
            revealed_orders = (
                OperatorFollowUpIntentRepository._materialized_child_json_list(
                    stealth.get("revealed_orders"),
                    code="materialized_child_identity_mismatch",
                )
            )
            anchor = (
                OperatorFollowUpIntentRepository._materialized_child_json_mapping(
                    stealth.get("anchor_repricing_state_json"),
                    code="materialized_child_identity_mismatch",
                )
            )
        except FollowUpIntentStoreError:
            return False
        if transition == (
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value
        ):
            return (
                stealth_status == "HIDDEN"
                and not revealed_orders
                and not anchor.get("active_placement_client_order_id")
                and not anchor.get("active_exchange_order_id")
            )
        if transition == (
            FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value
        ):
            return (
                stealth_status == "CANCELLED"
                and not revealed_orders
                and not anchor.get("active_placement_client_order_id")
                and not anchor.get("active_exchange_order_id")
            )
        if transition in _MATERIALIZED_CHILD_TERMINAL_TRANSITIONS:
            expected_stealth_status = (
                "EXECUTED"
                if record.authoritative_order_status == OrderStatus.FILLED.value
                else "CANCELLED"
            )
            return (
                stealth_status == expected_stealth_status
                and bool(child_exchange_id)
                and len(revealed_orders) == 1
                and isinstance(revealed_orders[0], Mapping)
                and str(revealed_orders[0].get("placed_order_id") or "")
                == record.child_client_order_id
                and str(revealed_orders[0].get("exchange_order_id") or "")
                == child_exchange_id
                and not anchor.get("active_placement_client_order_id")
                and not anchor.get("active_exchange_order_id")
            )
        return (
            stealth_status == "REVEALED"
            and bool(child_exchange_id)
            and len(revealed_orders) == 1
            and isinstance(revealed_orders[0], Mapping)
            and str(revealed_orders[0].get("placed_order_id") or "")
            == record.child_client_order_id
            and str(revealed_orders[0].get("exchange_order_id") or "")
            == child_exchange_id
            and str(anchor.get("active_placement_client_order_id") or "")
            == record.child_client_order_id
            and str(anchor.get("active_exchange_order_id") or "")
            == child_exchange_id
        )

    def transition_materialized_child_local_state(
        self,
        *,
        materialization_id: str,
        transition_kind: str,
        authoritative_order_status: str,
        exchange_order_id: str | None,
        operation_audit_id: str,
        operation_idempotency_key_sha256: str,
    ) -> FollowUpMaterializedChildLocalStateTransitionResult:
        """Atomically project one durable exchange result into local child state.

        The raw exchange identifier is accepted only at this backend persistence
        boundary.  It is stored in the authoritative local order/stealth rows,
        while the immutable projection journal and returned record contain only
        its SHA-256 digest.
        """

        materialization_id = _require_uuid(
            materialization_id,
            code="materialization_id_invalid",
        )
        normalized_transition = str(transition_kind or "").strip().upper()
        if normalized_transition not in _MATERIALIZED_CHILD_TRANSITIONS:
            raise FollowUpIntentStoreConflict(
                "materialized_child_transition_invalid"
            )
        normalized_status = str(authoritative_order_status or "").strip().upper()
        operation_audit_id = _require_uuid(
            operation_audit_id,
            code="materialization_operation_audit_id_invalid",
        )
        operation_key_hash = self._validate_materialization_sha256(
            operation_idempotency_key_sha256,
            code="materialization_operation_idempotency_sha256_invalid",
        )
        raw_exchange_id = None
        if exchange_order_id is not None:
            candidate_exchange_id = str(exchange_order_id).strip()
            if (
                not candidate_exchange_id
                or len(candidate_exchange_id) > 64
                or any(
                    ord(character) < 33 or ord(character) > 126
                    for character in candidate_exchange_id
                )
            ):
                raise FollowUpIntentStoreConflict(
                    "materialized_child_exchange_order_id_invalid"
                )
            raw_exchange_id = candidate_exchange_id
        exchange_hash = (
            hashlib.sha256(raw_exchange_id.encode("utf-8")).hexdigest()
            if raw_exchange_id is not None
            else None
        )

        if normalized_transition == (
            FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value
        ):
            valid_status = normalized_status == OrderStatus.FAILED.value
            requires_exchange_id = False
        elif normalized_transition == (
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value
        ):
            valid_status = normalized_status == OrderStatus.SUBMISSION_UNKNOWN.value
            requires_exchange_id = False
        elif normalized_transition == (
            FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value
        ):
            valid_status = normalized_status == OrderStatus.CANCELLED.value
            requires_exchange_id = True
        elif normalized_transition in _MATERIALIZED_CHILD_TERMINAL_TRANSITIONS:
            valid_status = normalized_status in _MATERIALIZED_CHILD_TERMINAL_STATUSES
            requires_exchange_id = True
        elif normalized_transition == (
            FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value
        ):
            valid_status = normalized_status in {
                *_MATERIALIZED_CHILD_ACTIVE_STATUSES,
                OrderStatus.CANCEL_QUEUED.value,
            }
            requires_exchange_id = True
        else:
            valid_status = normalized_status in _MATERIALIZED_CHILD_ACTIVE_STATUSES
            requires_exchange_id = True
        if (
            not valid_status
            or requires_exchange_id is not (raw_exchange_id is not None)
        ):
            raise FollowUpIntentStoreConflict(
                "materialized_child_local_state_invalid"
            )

        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                attempt = self._load_and_lock_materialization(
                    cursor,
                    materialization_id,
                )
                cursor.execute(
                    f"""
                    SELECT portfolio_id
                      FROM {self._table('operator_follow_up_materialization_attempt')}
                     WHERE materialization_id = %s
                     FOR SHARE
                    """,
                    (materialization_id,),
                )
                attempt_row = _row(cursor)
                if attempt_row is None:
                    raise FollowUpIntentStoreConflict(
                        "follow_up_materialization_not_found"
                    )
                portfolio_id = str(attempt_row.get("portfolio_id") or "")
                if (
                    not self.configured_spot_portfolio_id
                    or portfolio_id != self.configured_spot_portfolio_id
                    or attempt.portfolio_scope_sha256
                    != _portfolio_sha256(portfolio_id)
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )

                event_states = _MATERIALIZED_CHILD_TRANSITION_EVENT_STATES[
                    normalized_transition
                ]
                placeholders = ", ".join("%s" for _ in event_states)
                cursor.execute(
                    f"""
                    SELECT event_id, materialization_id, state, diagnostic_code,
                           exchange_order_id_sha256,
                           operation_idempotency_key_sha256,
                           operation_audit_id, operation_actor_id,
                           operation_roles_json, operation_environment,
                           operation_operator_intent,
                           operation_correlation_id, recorded_at
                      FROM {self._table('operator_follow_up_materialization_event')}
                     WHERE materialization_id = %s
                       AND operation_audit_id = %s
                       AND operation_idempotency_key_sha256 = %s
                       AND state IN ({placeholders})
                     ORDER BY event_sequence DESC
                     LIMIT 1
                     FOR SHARE
                    """,
                    (
                        materialization_id,
                        operation_audit_id,
                        operation_key_hash,
                        *event_states,
                    ),
                )
                materialization_event_row = _row(cursor)
                if materialization_event_row is None:
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_operation_evidence_mismatch"
                    )
                materialization_event = self._materialization_event_record(
                    materialization_event_row
                )
                event_exchange_hash = (
                    materialization_event.exchange_order_id_sha256
                )
                strict_event_hash_transitions = {
                    FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value,
                    FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL.value,
                    FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value,
                    FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL.value,
                }
                if (
                    event_exchange_hash is not None
                    and event_exchange_hash != exchange_hash
                ) or (
                    normalized_transition in strict_event_hash_transitions
                    and event_exchange_hash != exchange_hash
                ):
                    cursor.execute(
                        f"""
                        SELECT 1
                          FROM {self._table('operator_follow_up_materialized_child_state_event')}
                         WHERE materialization_id = %s
                           AND transition_kind = %s
                         LIMIT 1
                        """,
                        (materialization_id, normalized_transition),
                    )
                    if cursor.fetchone() is not None:
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_operation_evidence_mismatch"
                    )

                cursor.execute(
                    f"""
                    SELECT local_state_sequence, local_state_event_id,
                           materialization_id, child_client_order_id,
                           transition_kind, authoritative_order_status,
                           exchange_order_id_sha256, operation_audit_id,
                           operation_idempotency_key_sha256, recorded_at
                      FROM {self._table('operator_follow_up_materialized_child_state_event')}
                     WHERE materialization_id = %s
                     ORDER BY local_state_sequence ASC
                     FOR SHARE
                    """,
                    (materialization_id,),
                )
                local_rows = _rows(cursor)
                local_records = [
                    self._materialized_child_local_state_record(row)
                    for row in local_rows
                ]
                existing_index = next(
                    (
                        index
                        for index, record in enumerate(local_records)
                        if record.transition_kind == normalized_transition
                    ),
                    None,
                )
                existing_record = (
                    local_records[existing_index]
                    if existing_index is not None
                    else None
                )
                if existing_record is not None and (
                    existing_record.authoritative_order_status != normalized_status
                    or existing_record.exchange_order_id_sha256 != exchange_hash
                    or existing_record.operation_audit_id != operation_audit_id
                    or existing_record.operation_idempotency_key_sha256
                    != operation_key_hash
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_local_state_conflict"
                    )

                ids = {
                    attempt.root_client_order_id,
                    attempt.source_client_order_id,
                    attempt.child_client_order_id,
                }
                order_placeholders = ", ".join("%s" for _ in ids)
                cursor.execute(
                    f"""
                    SELECT client_order_id, product_id, side, size, price,
                           status, parent_order_id, ownership_provenance,
                           retail_portfolio_id, exchange_order_id
                      FROM {self._table('order_parent')}
                     WHERE client_order_id IN ({order_placeholders})
                     FOR UPDATE
                    """,
                    tuple(ids),
                )
                order_rows = {
                    str(row.get("client_order_id") or ""): row
                    for row in _rows(cursor)
                }
                root = order_rows.get(attempt.root_client_order_id)
                source = order_rows.get(attempt.source_client_order_id)
                child = order_rows.get(attempt.child_client_order_id)
                if root is None or source is None or child is None:
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )
                if (
                    str(root.get("client_order_id") or "")
                    != attempt.root_client_order_id
                    or root.get("parent_order_id")
                    or str(root.get("product_id") or "") != attempt.product_id
                    or str(root.get("ownership_provenance") or "")
                    != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                    or str(root.get("retail_portfolio_id") or "") != portfolio_id
                    or str(root.get("status") or "").upper()
                    not in {OrderStatus.FILLED.value, OrderStatus.CANCELLED.value}
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )
                expected_source_parent = (
                    None
                    if attempt.source_client_order_id
                    == attempt.root_client_order_id
                    else attempt.root_client_order_id
                )
                if (
                    str(source.get("product_id") or "") != attempt.product_id
                    or str(source.get("status") or "").upper()
                    != OrderStatus.FILLED.value
                    or str(source.get("retail_portfolio_id") or "") != portfolio_id
                    or (
                        str(source.get("parent_order_id") or "") or None
                    )
                    != expected_source_parent
                    or str(source.get("ownership_provenance") or "")
                    not in {
                        OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
                        OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
                    }
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )
                if (
                    str(child.get("client_order_id") or "")
                    != attempt.child_client_order_id
                    or str(child.get("parent_order_id") or "")
                    != attempt.root_client_order_id
                    or str(child.get("product_id") or "") != attempt.product_id
                    or str(child.get("side") or "").upper() != attempt.child_side
                    or _decimal(
                        child.get("size"),
                        code="materialized_child_identity_mismatch",
                    )
                    != Decimal(attempt.base_size)
                    or _decimal(
                        child.get("price"),
                        code="materialized_child_identity_mismatch",
                    )
                    != Decimal(attempt.limit_price)
                    or str(child.get("ownership_provenance") or "")
                    != OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
                    or str(child.get("retail_portfolio_id") or "") != portfolio_id
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )

                cursor.execute(
                    f"""
                    SELECT client_order_id, parent_order_id
                      FROM {self._table('order_parent')}
                     WHERE parent_order_id = %s
                     FOR UPDATE
                    """,
                    (attempt.root_client_order_id,),
                )
                expected_children = {attempt.child_client_order_id}
                if attempt.source_client_order_id != attempt.root_client_order_id:
                    expected_children.add(attempt.source_client_order_id)
                lineage_children = {
                    str(row.get("client_order_id") or "")
                    for row in _rows(cursor)
                }
                if lineage_children != expected_children:
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )
                nested_parent_ids = [attempt.child_client_order_id]
                if attempt.source_client_order_id != attempt.root_client_order_id:
                    nested_parent_ids.append(attempt.source_client_order_id)
                nested_placeholders = ", ".join(
                    "%s" for _ in nested_parent_ids
                )
                cursor.execute(
                    f"""
                    SELECT 1
                      FROM {self._table('order_parent')}
                     WHERE parent_order_id IN ({nested_placeholders})
                     LIMIT 1
                     FOR UPDATE
                    """,
                    tuple(nested_parent_ids),
                )
                if cursor.fetchone() is not None:
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )

                cursor.execute(
                    f"""
                    SELECT stealth_order_id, parent_order_id, product_id, side,
                           total_size, remaining_size, revealed_size,
                           executed_size, limit_price, status,
                           reveal_condition_json, anchor_repricing_state_json,
                           revealed_orders, last_placement_at
                      FROM {self._table('stealth_orders')}
                     WHERE stealth_order_id = %s
                     FOR UPDATE
                    """,
                    (attempt.child_client_order_id,),
                )
                stealth = _row(cursor)
                if stealth is None:
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )
                reveal_condition = self._materialized_child_json_mapping(
                    stealth.get("reveal_condition_json"),
                    code="materialized_child_identity_mismatch",
                )
                anchor = self._materialized_child_json_mapping(
                    stealth.get("anchor_repricing_state_json"),
                    code="materialized_child_identity_mismatch",
                )
                revealed_orders = self._materialized_child_json_list(
                    stealth.get("revealed_orders"),
                    code="materialized_child_identity_mismatch",
                )
                materialization_binding = hashlib.sha256(
                    materialization_id.encode("utf-8")
                ).hexdigest()
                if (
                    str(stealth.get("stealth_order_id") or "")
                    != attempt.child_client_order_id
                    or str(stealth.get("parent_order_id") or "")
                    != attempt.root_client_order_id
                    or str(stealth.get("product_id") or "") != attempt.product_id
                    or str(stealth.get("side") or "").upper()
                    != attempt.child_side
                    or _decimal(
                        stealth.get("total_size"),
                        code="materialized_child_identity_mismatch",
                    )
                    != Decimal(attempt.base_size)
                    or _decimal(
                        stealth.get("remaining_size"),
                        code="materialized_child_identity_mismatch",
                    )
                    != 0
                    or _decimal(
                        stealth.get("limit_price"),
                        code="materialized_child_identity_mismatch",
                    )
                    != Decimal(attempt.limit_price)
                    or reveal_condition.get("operator_materialization_quarantine")
                    is not True
                    or str(
                        reveal_condition.get("materialization_binding_sha256")
                        or ""
                    )
                    != materialization_binding
                    or anchor.get("operator_materialization_quarantine") is not True
                    or str(anchor.get("materialization_binding_sha256") or "")
                    != materialization_binding
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_identity_mismatch"
                    )

                child_exchange_id = str(
                    child.get("exchange_order_id") or ""
                ).strip()
                observed_exchange_ids = {
                    child_exchange_id,
                    str(anchor.get("active_exchange_order_id") or "").strip(),
                    str(anchor.get("last_exchange_order_id") or "").strip(),
                }
                for revealed_order in revealed_orders:
                    if not isinstance(revealed_order, Mapping):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_identity_mismatch"
                        )
                    if str(revealed_order.get("placed_order_id") or "") != (
                        attempt.child_client_order_id
                    ):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_identity_mismatch"
                        )
                    observed_exchange_ids.add(
                        str(revealed_order.get("exchange_order_id") or "").strip()
                    )
                observed_exchange_ids.discard("")
                if len(observed_exchange_ids) > 1 or (
                    observed_exchange_ids
                    and raw_exchange_id not in observed_exchange_ids
                ):
                    raise FollowUpIntentStoreConflict(
                        "materialized_child_exchange_identity_conflict"
                    )

                if existing_record is not None:
                    if existing_index != len(local_records) - 1:
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )
                    if not self._materialized_child_projection_matches(
                        record=existing_record,
                        child=child,
                        stealth=stealth,
                    ):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )
                    return FollowUpMaterializedChildLocalStateTransitionResult(
                        record=existing_record,
                        replayed=True,
                    )

                if normalized_transition in _MATERIALIZED_CHILD_INITIAL_TRANSITIONS:
                    if local_records:
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )
                    if (
                        str(child.get("status") or "").upper()
                        != OrderStatus.PENDING.value
                        or child_exchange_id
                        or str(stealth.get("status") or "").upper() != "HIDDEN"
                        or revealed_orders
                        or anchor.get("active_placement_client_order_id")
                        or anchor.get("active_exchange_order_id")
                    ):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )
                else:
                    allowed_predecessors = (
                        _MATERIALIZED_CHILD_TRANSITION_PREDECESSORS.get(
                            normalized_transition,
                            frozenset(),
                        )
                    )
                    if (
                        not local_records
                        or local_records[-1].transition_kind
                        not in allowed_predecessors
                        or local_records[-1].transition_kind
                        in _MATERIALIZED_CHILD_TERMINAL_TRANSITIONS
                        or not self._materialized_child_projection_matches(
                            record=local_records[-1],
                            child=child,
                            stealth=stealth,
                        )
                    ):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_conflict"
                        )

                is_create_unknown = normalized_transition == (
                    FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value
                )
                is_create_rejected = normalized_transition == (
                    FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value
                )
                is_terminal = (
                    normalized_transition in _MATERIALIZED_CHILD_TERMINAL_TRANSITIONS
                    and not is_create_rejected
                )
                needs_reveal_evidence = not (
                    is_create_unknown or is_create_rejected
                )
                projected_revealed_orders = list(revealed_orders)
                if needs_reveal_evidence and not projected_revealed_orders:
                    projected_revealed_orders = [
                        {
                            "placed_order_id": attempt.child_client_order_id,
                            "exchange_order_id": raw_exchange_id,
                            "operator_materialization": True,
                            "operation_audit_id": operation_audit_id,
                        }
                    ]
                projected_anchor = dict(anchor)
                if needs_reveal_evidence and not is_terminal:
                    projected_anchor.update(
                        {
                            "active_placement_client_order_id": (
                                attempt.child_client_order_id
                            ),
                            "active_exchange_order_id": raw_exchange_id,
                            "active_placement_operation_audit_id": (
                                operation_audit_id
                            ),
                        }
                    )
                else:
                    active_placement_id = projected_anchor.pop(
                        "active_placement_client_order_id",
                        None,
                    )
                    active_exchange_id = projected_anchor.pop(
                        "active_exchange_order_id",
                        None,
                    )
                    projected_anchor.pop(
                        "active_placement_operation_audit_id",
                        None,
                    )
                    if needs_reveal_evidence:
                        projected_anchor["last_placement_client_order_id"] = (
                            active_placement_id or attempt.child_client_order_id
                        )
                        projected_anchor["last_exchange_order_id"] = (
                            active_exchange_id or raw_exchange_id
                        )
                        projected_anchor["terminal_operation_audit_id"] = (
                            operation_audit_id
                        )

                if is_create_unknown:
                    stealth_status = "HIDDEN"
                elif is_create_rejected:
                    stealth_status = "CANCELLED"
                elif is_terminal:
                    stealth_status = (
                        "EXECUTED"
                        if normalized_status == OrderStatus.FILLED.value
                        else "CANCELLED"
                    )
                else:
                    stealth_status = "REVEALED"
                revealed_size = (
                    Decimal(attempt.base_size)
                    if needs_reveal_evidence
                    else Decimal("0")
                )
                executed_size = _decimal(
                    stealth.get("executed_size") or 0,
                    code="materialized_child_identity_mismatch",
                )
                if normalized_status == OrderStatus.FILLED.value:
                    executed_size = Decimal(attempt.base_size)

                cursor.execute(
                    f"""
                    UPDATE {self._table('order_parent')}
                       SET status = %s, exchange_order_id = %s
                     WHERE client_order_id = %s
                    """,
                    (
                        normalized_status,
                        raw_exchange_id,
                        attempt.child_client_order_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise FollowUpIntentStoreUnavailable(
                        "materialized_child_local_state_unknown"
                    )
                cursor.execute(
                    f"""
                    UPDATE {self._table('stealth_orders')}
                       SET status = %s,
                           remaining_size = 0,
                           revealed_size = %s,
                           executed_size = %s,
                           revealed_orders = %s::jsonb,
                           anchor_repricing_state_json = %s::jsonb,
                           last_placement_at = CASE
                               WHEN %s AND last_placement_at IS NULL
                               THEN CURRENT_TIMESTAMP
                               ELSE last_placement_at
                           END,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE stealth_order_id = %s
                    """,
                    (
                        stealth_status,
                        revealed_size,
                        executed_size,
                        json.dumps(
                            projected_revealed_orders,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            projected_anchor,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        needs_reveal_evidence,
                        attempt.child_client_order_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise FollowUpIntentStoreUnavailable(
                        "materialized_child_local_state_unknown"
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_materialized_child_state_event')} (
                        local_state_event_id, materialization_id,
                        child_client_order_id, transition_kind,
                        authoritative_order_status, exchange_order_id_sha256,
                        operation_audit_id,
                        operation_idempotency_key_sha256
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING local_state_event_id, materialization_id,
                              child_client_order_id, transition_kind,
                              authoritative_order_status,
                              exchange_order_id_sha256, operation_audit_id,
                              operation_idempotency_key_sha256, recorded_at
                    """,
                    (
                        str(uuid.uuid4()),
                        materialization_id,
                        attempt.child_client_order_id,
                        normalized_transition,
                        normalized_status,
                        exchange_hash,
                        operation_audit_id,
                        operation_key_hash,
                    ),
                )
                inserted_row = _row(cursor)
                if inserted_row is None:
                    raise FollowUpIntentStoreUnavailable(
                        "materialized_child_local_state_unknown"
                    )
                return FollowUpMaterializedChildLocalStateTransitionResult(
                    record=self._materialized_child_local_state_record(
                        inserted_row
                    ),
                    replayed=False,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "materialized_child_local_state_unknown"
            ) from None

    def read_latest_materialized_child_local_state(
        self,
        materialization_id: str,
    ) -> FollowUpMaterializedChildLocalStateRecord | None:
        """Read the latest sanitized local projection journal without DDL."""

        materialization_id = _require_uuid(
            materialization_id,
            code="materialization_id_invalid",
        )
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT local_state_event_id, materialization_id,
                           child_client_order_id, transition_kind,
                           authoritative_order_status,
                           exchange_order_id_sha256, operation_audit_id,
                           operation_idempotency_key_sha256, recorded_at
                      FROM {self._table('operator_follow_up_materialized_child_state_event')}
                     WHERE materialization_id = %s
                     ORDER BY local_state_sequence DESC
                     LIMIT 1
                    """,
                    (materialization_id,),
                )
                row = _row(cursor)
                if row is not None:
                    record = self._materialized_child_local_state_record(row)
                    cursor.execute(
                        f"""
                        SELECT client_order_id, status, exchange_order_id
                          FROM {self._table('order_parent')}
                         WHERE client_order_id = %s
                        """,
                        (record.child_client_order_id,),
                    )
                    child = _row(cursor)
                    cursor.execute(
                        f"""
                        SELECT stealth_order_id, status, remaining_size,
                               revealed_orders, reveal_condition_json,
                               anchor_repricing_state_json
                          FROM {self._table('stealth_orders')}
                         WHERE stealth_order_id = %s
                        """,
                        (record.child_client_order_id,),
                    )
                    stealth = _row(cursor)
                    if child is None or stealth is None:
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_mismatch"
                        )
                    reveal_condition = self._materialized_child_json_mapping(
                        stealth.get("reveal_condition_json"),
                        code="materialized_child_local_state_mismatch",
                    )
                    anchor = self._materialized_child_json_mapping(
                        stealth.get("anchor_repricing_state_json"),
                        code="materialized_child_local_state_mismatch",
                    )
                    materialization_binding = hashlib.sha256(
                        materialization_id.encode("utf-8")
                    ).hexdigest()
                    if (
                        reveal_condition.get(
                            "operator_materialization_quarantine"
                        )
                        is not True
                        or str(
                            reveal_condition.get(
                                "materialization_binding_sha256"
                            )
                            or ""
                        )
                        != materialization_binding
                        or anchor.get("operator_materialization_quarantine")
                        is not True
                        or str(
                            anchor.get("materialization_binding_sha256") or ""
                        )
                        != materialization_binding
                        or not self._materialized_child_projection_matches(
                            record=record,
                            child=child,
                            stealth=stealth,
                        )
                    ):
                        raise FollowUpIntentStoreConflict(
                            "materialized_child_local_state_mismatch"
                        )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "materialized_child_local_state_unavailable"
            ) from None
        return (
            self._materialized_child_local_state_record(row)
            if row is not None
            else None
        )

    def slot_applies(
        self,
        source_client_order_id: str,
        *,
        include_current_scope: bool = True,
    ) -> bool:
        """Classify whether one engine order needs the durable slot interlock."""

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    "SELECT to_regclass(%s) AS intent_relation, "
                    "to_regclass(%s) AS claim_relation",
                    (
                        f"{self.schema}.operator_follow_up_intent",
                        f"{self.schema}.order_follow_up_semantic_claim",
                    ),
                )
                relations = cursor.fetchone() or (None, None)
                intent_relation = (
                    relations.get("intent_relation")
                    if isinstance(relations, Mapping)
                    else relations[0]
                )
                claim_relation = (
                    relations.get("claim_relation")
                    if isinstance(relations, Mapping)
                    else relations[1]
                )
                if intent_relation is not None:
                    cursor.execute(
                        f"""
                        SELECT 1 FROM {self._table('operator_follow_up_intent')}
                         WHERE source_client_order_id = %s
                            OR root_client_order_id = %s
                         LIMIT 1
                        """,
                        (source_client_order_id, source_client_order_id),
                    )
                    if cursor.fetchone() is not None:
                        return True
                if claim_relation is not None:
                    cursor.execute(
                        f"""
                        SELECT 1
                          FROM {self._table('order_follow_up_semantic_claim')}
                         WHERE source_client_order_id = %s
                           AND state <> %s
                         LIMIT 1
                        """,
                        (
                            source_client_order_id,
                            FollowUpSemanticClaimState.RELEASED.value,
                        ),
                    )
                    if cursor.fetchone() is not None:
                        return True
                if not include_current_scope:
                    return False
                cursor.execute(
                    f"""
                    SELECT product_id, ownership_provenance, retail_portfolio_id
                      FROM {self._table('order_parent')}
                     WHERE client_order_id = %s
                    """,
                    (source_client_order_id,),
                )
                source = _row(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_scope_unavailable"
            ) from None
        if source is None:
            return False
        return operator_follow_up_intent_scope_applies(
            source_ownership_provenance=str(
                source.get("ownership_provenance") or ""
            ),
            spot_portfolio_configured=bool(self.configured_spot_portfolio_id),
            source_portfolio_matches=(
                str(source.get("retail_portfolio_id") or "")
                == self.configured_spot_portfolio_id
            ),
            product_id=str(source.get("product_id") or ""),
            product_context_resolver=self.product_context_resolver,
        )

    def attach(self, command: FollowUpIntentCommand) -> FollowUpIntentAttachResult:
        _require_source_uuid(command.source_client_order_id)
        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, command.source_client_order_id)
                replay = self._read_intent_by_idempotency(
                    cursor,
                    command.idempotency_key,
                )
                if replay is not None:
                    if (
                        replay.source_client_order_id
                        != command.source_client_order_id
                        or replay.payload_sha256 != command.payload_sha256
                    ):
                        raise FollowUpIntentStoreConflict("idempotency_conflict")
                    eligibility = self._evaluate_locked(
                        cursor,
                        command.source_client_order_id,
                        existing_intent=replay,
                    )
                    return FollowUpIntentAttachResult(
                        eligibility=eligibility,
                        record=replay,
                        replayed=True,
                    )

                existing = self._read_intent(cursor, command.source_client_order_id)
                eligibility = self._evaluate_locked(
                    cursor,
                    command.source_client_order_id,
                    existing_intent=existing,
                )
                if not eligibility.eligible:
                    raise FollowUpIntentStoreConflict(eligibility.blockers[0])

                claim_id = str(uuid.uuid4())
                intent_id = str(uuid.uuid4())
                audit_id = str(uuid.uuid4())
                recorded_at = datetime.now(timezone.utc)
                recorded_at_text = recorded_at.isoformat()
                semantic_intent = eligibility.semantic_intent or "EXIT"
                follow_up_side = eligibility.derived_follow_up_side or "SELL"
                intent_sha256 = _canonical_sha256(
                    {
                        "source_client_order_id": command.source_client_order_id,
                        "root_client_order_id": eligibility.root_client_order_id,
                        "trigger": "FILLED",
                        "intent_kind": "single_on_full_fill",
                        "semantic_intent": semantic_intent,
                        "derived_follow_up_side": follow_up_side,
                        "portfolio_scope_sha256": eligibility.portfolio_scope_sha256,
                    }
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        claim_id,
                        command.source_client_order_id,
                        FollowUpSemanticClaimKind.OPERATOR_INTENT.value,
                        "FILLED",
                        FollowUpSemanticClaimState.COMPLETED.value,
                    ),
                )
                audit_event = _canonical_audit_event(
                    audit_id=audit_id,
                    recorded_at=recorded_at_text,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    operator_intent=command.operator_intent,
                    idempotency_key=command.idempotency_key,
                    source_client_order_id=command.source_client_order_id,
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_intent_audit_outbox')} (
                        audit_id, follow_up_intent_id, source_client_order_id,
                        event_json, event_sha256, recorded_at
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        audit_id,
                        intent_id,
                        command.source_client_order_id,
                        json.dumps(
                            audit_event,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        _canonical_sha256(audit_event),
                        recorded_at,
                    ),
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_intent')} (
                        follow_up_intent_id, claim_id, source_client_order_id,
                        root_client_order_id, product_id, source_side,
                        derived_follow_up_side, semantic_intent, intent_sha256,
                        idempotency_key, payload_sha256, actor_id, roles_json,
                        environment, portfolio_scope_sha256, correlation_id,
                        operator_intent, audit_id, terminal_result, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, 'ATTACHED', %s
                    )
                    RETURNING follow_up_intent_id, claim_id,
                              source_client_order_id, root_client_order_id,
                              semantic_intent, derived_follow_up_side,
                              intent_sha256, audit_id, correlation_id, actor_id,
                              environment, portfolio_scope_sha256,
                              idempotency_key, payload_sha256, recorded_at
                    """,
                    (
                        intent_id,
                        claim_id,
                        command.source_client_order_id,
                        eligibility.root_client_order_id,
                        eligibility.product_id,
                        "BUY" if follow_up_side == "SELL" else "SELL",
                        follow_up_side,
                        semantic_intent,
                        intent_sha256,
                        command.idempotency_key,
                        command.payload_sha256,
                        command.actor_id,
                        json.dumps(list(command.roles), separators=(",", ":")),
                        command.environment,
                        eligibility.portfolio_scope_sha256,
                        command.correlation_id,
                        command.operator_intent,
                        audit_id,
                        recorded_at,
                    ),
                )
                record = self._record(_row(cursor) or {})
                attached = FollowUpIntentEligibility(
                    **{
                        **eligibility.__dict__,
                        "eligible": False,
                        "eligibility_status": "attached",
                        "blockers": ("follow_up_intent_already_attached",),
                        "slot_used": 1,
                    }
                )
                return FollowUpIntentAttachResult(
                    eligibility=attached,
                    record=record,
                    replayed=False,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_persistence_unknown"
            ) from None

    def try_claim_automatic(self, *, source_client_order_id: str, trigger: str) -> str | None:
        self.ensure_schema()
        normalized = str(trigger or "").upper()
        kind_by_trigger = {
            "FILLED": FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
            "CANCELLED": FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
        }
        if normalized not in kind_by_trigger:
            return None
        kind = kind_by_trigger[normalized]
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    SELECT 1
                      FROM {self._table('operator_follow_up_intent')}
                     WHERE source_client_order_id = %s
                        OR root_client_order_id = %s
                     LIMIT 1
                    """,
                    (source_client_order_id, source_client_order_id),
                )
                if cursor.fetchone() is not None:
                    return None
                cursor.execute(
                    f"""
                    SELECT claim_kind, state FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND state <> %s
                       AND claim_kind <> %s
                    """,
                    (
                        source_client_order_id,
                        FollowUpSemanticClaimState.RELEASED.value,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                    ),
                )
                if cursor.fetchone() is not None:
                    return None
                claim_id = str(uuid.uuid4())
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_client_order_id, claim_kind) DO UPDATE
                       SET claim_id = EXCLUDED.claim_id,
                           trigger = EXCLUDED.trigger,
                           state = EXCLUDED.state,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE {self._table('order_follow_up_semantic_claim')}.state = %s
                    RETURNING claim_id
                    """,
                    (
                        claim_id,
                        source_client_order_id,
                        kind,
                        normalized,
                        FollowUpSemanticClaimState.CLAIMED.value,
                        FollowUpSemanticClaimState.RELEASED.value,
                    ),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception:
            return None

    def transition_automatic(
        self,
        *,
        source_client_order_id: str,
        trigger: str,
        claim_id: str,
        target_state: str,
    ) -> bool:
        self.ensure_schema()
        normalized = str(trigger or "").upper()
        kind_by_trigger = {
            "FILLED": FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
            "CANCELLED": FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
        }
        if normalized not in kind_by_trigger:
            return False
        kind = kind_by_trigger[normalized]
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    UPDATE {self._table('order_follow_up_semantic_claim')}
                       SET state = %s, updated_at = CURRENT_TIMESTAMP
                     WHERE source_client_order_id = %s
                       AND claim_kind = %s AND claim_id = %s
                       AND state = %s
                    """,
                    (
                        target_state,
                        source_client_order_id,
                        kind,
                        claim_id,
                        FollowUpSemanticClaimState.CLAIMED.value,
                    ),
                )
                if cursor.rowcount == 1:
                    return True
                cursor.execute(
                    f"""
                    SELECT state FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND claim_kind = %s AND claim_id = %s
                    """,
                    (source_client_order_id, kind, claim_id),
                )
                row = cursor.fetchone()
                return bool(row and str(row[0]) == target_state)
        except Exception:
            return False

    def mark_positive_fill_activity(self, *, source_client_order_id: str) -> bool:
        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    SELECT 1
                      FROM {self._table('operator_follow_up_intent')}
                     WHERE source_client_order_id = %s
                        OR root_client_order_id = %s
                     LIMIT 1
                    """,
                    (source_client_order_id, source_client_order_id),
                )
                if cursor.fetchone() is not None:
                    return False
                cursor.execute(
                    f"""
                    SELECT 1 FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND claim_kind <> %s
                       AND state <> %s
                    """,
                    (
                        source_client_order_id,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                        FollowUpSemanticClaimState.RELEASED.value,
                    ),
                )
                if cursor.fetchone() is not None:
                    return False
                marker_id = str(uuid.uuid4())
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_client_order_id, claim_kind) DO NOTHING
                    """,
                    (
                        marker_id,
                        source_client_order_id,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                        "PARTIAL_FILL",
                        FollowUpSemanticClaimState.COMPLETED.value,
                    ),
                )
                return True
        except Exception:
            return False


_DEFAULT_REPOSITORY: OperatorFollowUpIntentRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_repository() -> OperatorFollowUpIntentRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                import os
                from database import order as order_db

                _DEFAULT_REPOSITORY = OperatorFollowUpIntentRepository(
                    order_db.DB_CLIENT,
                    configured_spot_portfolio_id=os.environ.get(
                        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", ""
                    ),
                )
    return _DEFAULT_REPOSITORY


def create_order_follow_up_intent_tables() -> None:
    """Create schema and boundedly drain its canonical audit outbox."""

    if not operator_follow_up_intent_enabled():
        return
    repository = get_default_repository()
    repository.ensure_schema()
    from application.admin_api.operator_follow_up_intent import (
        FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
        project_pending_operator_follow_up_intent_audits,
    )

    project_pending_operator_follow_up_intent_audits(
        repository=repository,
        limit=FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
    )


def try_claim_automatic_order_follow_up(
    *, source_client_order_id: str, trigger: str
) -> str | None:
    return get_default_repository().try_claim_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
    )


def release_automatic_order_follow_up_claim(
    *, source_client_order_id: str, trigger: str, claim_id: str
) -> bool:
    return get_default_repository().transition_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
        claim_id=claim_id,
        target_state=FollowUpSemanticClaimState.RELEASED.value,
    )


def complete_automatic_order_follow_up_claim(
    *, source_client_order_id: str, trigger: str, claim_id: str
) -> bool:
    return get_default_repository().transition_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
        claim_id=claim_id,
        target_state=FollowUpSemanticClaimState.COMPLETED.value,
    )


def mark_order_follow_up_positive_fill_activity(
    *, source_client_order_id: str
) -> bool:
    return get_default_repository().mark_positive_fill_activity(
        source_client_order_id=source_client_order_id
    )


def install_order_follow_up_source_lock_trigger(table_name: str) -> None:
    """Attach the shared source lock to a positive-fill evidence table."""

    if not operator_follow_up_intent_enabled():
        return
    get_default_repository().install_source_lock_trigger(table_name)


def install_order_follow_up_lineage_lock_trigger() -> None:
    """Attach the durable intent interlock to ``order_parent`` lineage writes."""

    if not operator_follow_up_intent_enabled():
        return
    get_default_repository().install_lineage_lock_trigger()


def operator_follow_up_intent_slot_applies(source_client_order_id: str) -> bool:
    """Fail closed on unknown scope evidence, but skip known out-of-scope rows."""

    try:
        return get_default_repository().slot_applies(
            source_client_order_id,
            include_current_scope=operator_follow_up_intent_enabled(),
        )
    except FollowUpIntentStoreError:
        return True


def install_order_module_bindings() -> None:
    """Install the canonical wrappers on ``database.order`` for OrderEngine."""

    from database import order as order_db

    order_db.FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = (
        operator_follow_up_intent_enabled
    )
    order_db.FOLLOW_UP_INTENT_DURABLE_SLOT_APPLIES = (
        operator_follow_up_intent_slot_applies
    )
    order_db.try_claim_automatic_order_follow_up = try_claim_automatic_order_follow_up
    order_db.release_automatic_order_follow_up_claim = (
        release_automatic_order_follow_up_claim
    )
    order_db.complete_automatic_order_follow_up_claim = (
        complete_automatic_order_follow_up_claim
    )
    order_db.mark_order_follow_up_positive_fill_activity = (
        mark_order_follow_up_positive_fill_activity
    )
