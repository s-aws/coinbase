"""PostgreSQL durability for the local operator Automation control plane.

This module owns records and transitions only.  It imports no Coinbase client
and cannot dispatch a domain job.  Public Admin API projection and RBAC remain
in the application layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from typing import Any, Generic, Mapping, TypeVar
import uuid

from core.enums import (
    OperatorAutomationControlPosture,
    OperatorAutomationDefinitionState,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
    OperatorAutomationScheduleKind,
)
from database.database import PostgresDB


_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_RUN_STATES = (
    OperatorAutomationRunState.CLAIMED,
    OperatorAutomationRunState.PREPARING,
    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
    OperatorAutomationRunState.INVOCATION_STARTED,
    OperatorAutomationRunState.ACTIVE,
)
_PRE_INVOCATION_STATES = (
    OperatorAutomationRunState.CLAIMED,
    OperatorAutomationRunState.PREPARING,
    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
)
_POST_INVOCATION_STATES = (
    OperatorAutomationRunState.INVOCATION_STARTED,
    OperatorAutomationRunState.ACTIVE,
)
_SPOT_JOB_KINDS = {
    OperatorAutomationJobKind.SPOT_CAMPAIGN,
    OperatorAutomationJobKind.SPOT_SWEEP,
    OperatorAutomationJobKind.SPOT_LADDER,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _new_id() -> str:
    return str(uuid.uuid4())


def _validate_id(value: str, *, code: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise AutomationStoreInvalid(code) from None
    canonical = str(parsed)
    if canonical != value:
        raise AutomationStoreInvalid(code)
    return canonical


@dataclass(frozen=True)
class AutomationMutationCommand:
    idempotency_key: str
    payload_sha256: str
    actor_id: str
    correlation_id: str
    operator_intent: str


@dataclass(frozen=True)
class AutomationDefinitionCreateCommand(AutomationMutationCommand):
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    label: str
    product_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutomationControlPlaneRecord:
    posture: OperatorAutomationControlPosture
    updated_at: str


@dataclass(frozen=True)
class AutomationDefinitionRecord:
    definition_id: str
    revision: int
    label: str
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    lifecycle_state: OperatorAutomationDefinitionState
    product_ids: tuple[str, ...]
    schedule_kind: OperatorAutomationScheduleKind
    interval_seconds: int | None
    next_review_at: str | None
    schedule_due: bool
    due_reason: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AutomationRunRecord:
    run_id: str
    definition_id: str
    domain: OperatorAutomationDomain
    job_kind: OperatorAutomationJobKind
    state: OperatorAutomationRunState
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    client_order_id: str | None
    live_attempt_consumed: bool
    coinbase_api_call_count: int
    create_call_count: int
    cancel_call_count: int
    claimed_at: str
    updated_at: str


@dataclass(frozen=True)
class AutomationRunEventRecord:
    event_id: str
    run_id: str
    sequence: int
    from_state: OperatorAutomationRunState | None
    to_state: OperatorAutomationRunState
    diagnostic_code: str
    audit_id: str
    idempotency_key_sha256: str
    correlation_id: str
    recorded_at: str


@dataclass(frozen=True)
class AutomationLifecycleEventRecord:
    event_id: str
    definition_id: str | None
    from_state: str | None
    to_state: str
    diagnostic_code: str
    audit_id: str
    correlation_id: str
    recorded_at: str


T = TypeVar("T")


@dataclass(frozen=True)
class AutomationStorePage(Generic[T]):
    items: tuple[T, ...]
    total_count: int

    @property
    def total(self) -> int:
        return self.total_count


@dataclass(frozen=True)
class AutomationStoreMutation(Generic[T]):
    entity: T
    audit_id: str
    correlation_id: str
    replayed: bool = False


class AutomationStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AutomationStoreConflict(AutomationStoreError):
    pass


class AutomationStoreNotFound(AutomationStoreError):
    pass


class AutomationStoreInvalid(AutomationStoreError):
    pass


class AutomationStoreUnavailable(AutomationStoreError):
    pass


class OperatorAutomationRepository:
    """Typed, transaction-bounded PostgreSQL repository."""

    def __init__(self, database: PostgresDB, *, schema: str = "public") -> None:
        if _SCHEMA_PATTERN.fullmatch(schema) is None:
            raise AutomationStoreInvalid("automation_schema_invalid")
        self.database = database
        self.schema = schema
        self._prefix = f'"{schema}".'

    def ensure_schema(self) -> None:
        """Install the additive schema and immutable event guard idempotently."""

        active_states = ", ".join(f"'{state.value}'" for state in _ACTIVE_RUN_STATES)
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_control_plane_state (
                    singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
                    posture TEXT NOT NULL CHECK (posture IN ('ACTIVE','PAUSED','DRAINING','SHUTDOWN')),
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_control_plane_state
                    (singleton, posture, updated_at)
                VALUES (1, 'ACTIVE', NOW())
                ON CONFLICT (singleton) DO NOTHING
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_definition (
                    definition_id UUID PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    label TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
                    domain TEXT NOT NULL CHECK (domain IN ('SPOT','ORDERS')),
                    job_kind TEXT NOT NULL CHECK (job_kind IN ('SPOT_CAMPAIGN','SPOT_SWEEP','SPOT_LADDER','FOLLOW_UP')),
                    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('DRAFT','ENABLED','DISABLED','PAUSED','DRAINING')),
                    product_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('MANUAL_ONLY','INTERVAL_REVIEW_ONLY')),
                    interval_seconds INTEGER CHECK (interval_seconds IS NULL OR interval_seconds BETWEEN 60 AND 31536000),
                    next_review_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    CHECK (
                        (schedule_kind = 'MANUAL_ONLY' AND interval_seconds IS NULL AND next_review_at IS NULL)
                        OR
                        (schedule_kind = 'INTERVAL_REVIEW_ONLY' AND interval_seconds IS NOT NULL AND next_review_at IS NOT NULL)
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_run (
                    run_id UUID PRIMARY KEY,
                    definition_id UUID NOT NULL REFERENCES {self._prefix}automation_definition(definition_id),
                    domain TEXT NOT NULL CHECK (domain IN ('SPOT','ORDERS')),
                    job_kind TEXT NOT NULL CHECK (job_kind IN ('SPOT_CAMPAIGN','SPOT_SWEEP','SPOT_LADDER','FOLLOW_UP')),
                    state TEXT NOT NULL CHECK (state IN ('CLAIMED','PREPARING','AWAITING_OPERATOR_AUTHORIZATION','BLOCKED','ABORTED','INVOCATION_STARTED','ACTIVE','TERMINAL','UNKNOWN_CONSUMED')),
                    diagnostic_code TEXT NOT NULL CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    client_order_id UUID,
                    live_attempt_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    coinbase_api_call_count INTEGER NOT NULL DEFAULT 0 CHECK (coinbase_api_call_count >= 0),
                    create_call_count INTEGER NOT NULL DEFAULT 0 CHECK (create_call_count >= 0),
                    cancel_call_count INTEGER NOT NULL DEFAULT 0 CHECK (cancel_call_count >= 0),
                    claimed_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS automation_run_one_active_per_definition
                ON {self._prefix}automation_run (definition_id)
                WHERE state IN ({active_states})
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_idempotency (
                    idempotency_key_sha256 CHAR(64) PRIMARY KEY,
                    payload_sha256 CHAR(64) NOT NULL,
                    actor_id_sha256 CHAR(64) NOT NULL,
                    operator_intent_sha256 CHAR(64) NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id UUID NOT NULL,
                    audit_id UUID NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    result_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._prefix}automation_event_outbox (
                    event_id UUID PRIMARY KEY,
                    definition_id UUID REFERENCES {self._prefix}automation_definition(definition_id),
                    run_id UUID REFERENCES {self._prefix}automation_run(run_id),
                    sequence INTEGER,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    diagnostic_code TEXT NOT NULL CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    audit_id UUID NOT NULL,
                    idempotency_key_sha256 CHAR(64) NOT NULL,
                    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    event_json JSONB NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (run_id, sequence)
                )
                """
            )
            function_name = f'"{self.schema}".reject_automation_event_mutation'
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {function_name}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'automation_event_outbox_is_append_only';
                END;
                $$
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_event_outbox_no_update ON {self._prefix}automation_event_outbox"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_event_outbox_no_update
                BEFORE UPDATE ON {self._prefix}automation_event_outbox
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS automation_event_outbox_no_delete ON {self._prefix}automation_event_outbox"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER automation_event_outbox_no_delete
                BEFORE DELETE ON {self._prefix}automation_event_outbox
                FOR EACH ROW EXECUTE FUNCTION {function_name}()
                """
            )

    @staticmethod
    def _validate_command(command: AutomationMutationCommand) -> None:
        if not command.idempotency_key or len(command.idempotency_key) > 255:
            raise AutomationStoreInvalid("automation_idempotency_key_invalid")
        if _SHA256_PATTERN.fullmatch(command.payload_sha256) is None:
            raise AutomationStoreInvalid("automation_payload_hash_invalid")
        if not command.actor_id or len(command.actor_id) > 255:
            raise AutomationStoreInvalid("automation_actor_invalid")
        if not command.correlation_id or len(command.correlation_id) > 255:
            raise AutomationStoreInvalid("automation_correlation_invalid")
        if not command.operator_intent or len(command.operator_intent) > 255:
            raise AutomationStoreInvalid("automation_operator_intent_invalid")

    @staticmethod
    def _rows(cursor: Any) -> list[dict[str, Any]]:
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _row(cursor: Any) -> dict[str, Any] | None:
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def _advisory_key(key_sha256: str) -> int:
        unsigned = int(key_sha256[:16], 16)
        return unsigned if unsigned < 2**63 else unsigned - 2**64

    def _idempotency_replay(
        self,
        cursor: Any,
        *,
        command: AutomationMutationCommand,
        resource_type: str,
    ) -> dict[str, Any] | None:
        self._validate_command(command)
        key_sha256 = _hash(command.idempotency_key)
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (self._advisory_key(key_sha256),))
        cursor.execute(
            f"""
            SELECT payload_sha256, actor_id_sha256, operator_intent_sha256,
                   resource_type, audit_id, correlation_id, result_json
            FROM {self._prefix}automation_idempotency
            WHERE idempotency_key_sha256 = %s
            """,
            (key_sha256,),
        )
        row = self._row(cursor)
        if row is None:
            return None
        if (
            row["payload_sha256"] != command.payload_sha256
            or row["actor_id_sha256"] != _hash(command.actor_id)
            or row["operator_intent_sha256"] != _hash(command.operator_intent)
            or row["resource_type"] != resource_type
        ):
            raise AutomationStoreConflict("automation_idempotency_conflict")
        result = row["result_json"]
        if isinstance(result, str):
            result = json.loads(result)
        return {
            "entity": result,
            "audit_id": str(row["audit_id"]),
            "correlation_id": row["correlation_id"],
        }

    def _store_idempotency(
        self,
        cursor: Any,
        *,
        command: AutomationMutationCommand,
        resource_type: str,
        resource_id: str,
        audit_id: str,
        result: Mapping[str, Any],
        recorded_at: datetime,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_idempotency (
                idempotency_key_sha256, payload_sha256, actor_id_sha256,
                operator_intent_sha256, resource_type, resource_id, audit_id,
                correlation_id, result_json, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,
            (
                _hash(command.idempotency_key),
                command.payload_sha256,
                _hash(command.actor_id),
                _hash(command.operator_intent),
                resource_type,
                resource_id,
                audit_id,
                command.correlation_id,
                json.dumps(result, sort_keys=True, separators=(",", ":")),
                recorded_at,
            ),
        )

    def _control_from_row(self, row: Mapping[str, Any]) -> AutomationControlPlaneRecord:
        return AutomationControlPlaneRecord(
            posture=OperatorAutomationControlPosture(row["posture"]),
            updated_at=_iso(row["updated_at"]) or "",
        )

    def _definition_from_row(
        self,
        row: Mapping[str, Any],
        *,
        control_posture: OperatorAutomationControlPosture,
        now: datetime | None = None,
    ) -> AutomationDefinitionRecord:
        lifecycle = OperatorAutomationDefinitionState(row["lifecycle_state"])
        schedule_kind = OperatorAutomationScheduleKind(row["schedule_kind"])
        next_review = row["next_review_at"]
        current = now or _utc_now()
        if control_posture is not OperatorAutomationControlPosture.ACTIVE:
            due, reason = False, "control_plane_not_active"
        elif schedule_kind is OperatorAutomationScheduleKind.MANUAL_ONLY:
            due, reason = False, "manual_only"
        elif lifecycle is not OperatorAutomationDefinitionState.ENABLED:
            due, reason = False, "definition_inactive"
        elif next_review is not None and next_review <= current:
            due, reason = True, "due"
        else:
            due, reason = False, "not_due"
        product_ids = row["product_ids"]
        if isinstance(product_ids, str):
            product_ids = json.loads(product_ids)
        return AutomationDefinitionRecord(
            definition_id=str(row["definition_id"]),
            revision=int(row["revision"]),
            label=row["label"],
            domain=OperatorAutomationDomain(row["domain"]),
            job_kind=OperatorAutomationJobKind(row["job_kind"]),
            lifecycle_state=lifecycle,
            product_ids=tuple(product_ids or ()),
            schedule_kind=schedule_kind,
            interval_seconds=row["interval_seconds"],
            next_review_at=_iso(next_review),
            schedule_due=due,
            due_reason=reason,
            created_at=_iso(row["created_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _definition_json(record: AutomationDefinitionRecord) -> dict[str, Any]:
        result = asdict(record)
        result["domain"] = record.domain.value
        result["job_kind"] = record.job_kind.value
        result["lifecycle_state"] = record.lifecycle_state.value
        result["schedule_kind"] = record.schedule_kind.value
        result["product_ids"] = list(record.product_ids)
        return result

    def _definition_from_json(self, value: Mapping[str, Any]) -> AutomationDefinitionRecord:
        return AutomationDefinitionRecord(
            definition_id=value["definition_id"],
            revision=int(value["revision"]),
            label=value["label"],
            domain=OperatorAutomationDomain(value["domain"]),
            job_kind=OperatorAutomationJobKind(value["job_kind"]),
            lifecycle_state=OperatorAutomationDefinitionState(value["lifecycle_state"]),
            product_ids=tuple(value.get("product_ids") or ()),
            schedule_kind=OperatorAutomationScheduleKind(value["schedule_kind"]),
            interval_seconds=value.get("interval_seconds"),
            next_review_at=value.get("next_review_at"),
            schedule_due=bool(value["schedule_due"]),
            due_reason=value["due_reason"],
            created_at=value["created_at"],
            updated_at=value["updated_at"],
        )

    def _append_event(
        self,
        cursor: Any,
        *,
        definition_id: str | None,
        run_id: str | None,
        from_state: str | None,
        to_state: str,
        diagnostic_code: str,
        audit_id: str,
        idempotency_key_sha256: str,
        correlation_id: str,
        recorded_at: datetime,
    ) -> None:
        sequence: int | None = None
        if run_id is not None:
            cursor.execute(
                f"SELECT COALESCE(MAX(sequence), 0) + 1 FROM {self._prefix}automation_event_outbox WHERE run_id = %s",
                (run_id,),
            )
            sequence = int(cursor.fetchone()[0])
        event_id = _new_id()
        event_json = {
            "diagnostic_code": diagnostic_code,
            "event_id": event_id,
            "from_state": from_state,
            "run_id": run_id,
            "sequence": sequence,
            "to_state": to_state,
        }
        cursor.execute(
            f"""
            INSERT INTO {self._prefix}automation_event_outbox (
                event_id, definition_id, run_id, sequence, from_state, to_state,
                diagnostic_code, audit_id, idempotency_key_sha256,
                correlation_id, event_json, recorded_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,
            (
                event_id,
                definition_id,
                run_id,
                sequence,
                from_state,
                to_state,
                diagnostic_code,
                audit_id,
                idempotency_key_sha256,
                correlation_id,
                json.dumps(event_json, sort_keys=True, separators=(",", ":")),
                recorded_at,
            ),
        )

    def get_control_posture(self) -> AutomationControlPlaneRecord:
        rows = self.database.execute_query(
            f"SELECT posture, updated_at FROM {self._prefix}automation_control_plane_state WHERE singleton = 1"
        )
        if len(rows) != 1:
            raise AutomationStoreUnavailable("automation_control_plane_unavailable")
        return self._control_from_row(rows[0])

    def create_definition(
        self,
        command: AutomationDefinitionCreateCommand,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        domain = OperatorAutomationDomain(command.domain)
        job_kind = OperatorAutomationJobKind(command.job_kind)
        if (job_kind in _SPOT_JOB_KINDS) is not (domain is OperatorAutomationDomain.SPOT):
            raise AutomationStoreInvalid("automation_definition_domain_kind_mismatch")
        if job_kind is OperatorAutomationJobKind.FOLLOW_UP and domain is not OperatorAutomationDomain.ORDERS:
            raise AutomationStoreInvalid("automation_definition_domain_kind_mismatch")
        label = command.label.strip()
        if not label or len(label) > 120:
            raise AutomationStoreInvalid("automation_definition_label_invalid")
        if len(set(command.product_ids)) != len(command.product_ids):
            raise AutomationStoreInvalid("automation_definition_product_scope_invalid")
        if job_kind is OperatorAutomationJobKind.FOLLOW_UP and command.product_ids:
            raise AutomationStoreInvalid("automation_follow_up_product_scope_forbidden")

        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type="definition_create",
            )
            if replay is not None:
                return AutomationStoreMutation(
                    entity=self._definition_from_json(replay["entity"]),
                    audit_id=replay["audit_id"],
                    correlation_id=replay["correlation_id"],
                    replayed=True,
                )
            now = _utc_now()
            definition_id = _new_id()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_definition (
                    definition_id, revision, label, domain, job_kind,
                    lifecycle_state, product_ids, schedule_kind,
                    interval_seconds, next_review_at, created_at, updated_at
                ) VALUES (%s,1,%s,%s,%s,'DRAFT',%s::jsonb,'MANUAL_ONLY',NULL,NULL,%s,%s)
                RETURNING *
                """,
                (
                    definition_id,
                    label,
                    domain.value,
                    job_kind.value,
                    json.dumps(list(command.product_ids)),
                    now,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._definition_from_row(
                row,
                control_posture=OperatorAutomationControlPosture.ACTIVE,
                now=now,
            )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=None,
                to_state=record.lifecycle_state.value,
                diagnostic_code="automation_definition_created",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type="definition_create",
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def _current_control(self, cursor: Any, *, for_update: bool = False) -> OperatorAutomationControlPosture:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT posture FROM {self._prefix}automation_control_plane_state WHERE singleton = 1{suffix}"
        )
        row = cursor.fetchone()
        if row is None:
            raise AutomationStoreUnavailable("automation_control_plane_unavailable")
        return OperatorAutomationControlPosture(row[0])

    def get_definition(self, definition_id: str) -> AutomationDefinitionRecord | None:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s",
                (definition_id,),
            )
            row = self._row(cursor)
            return (
                self._definition_from_row(row, control_posture=posture)
                if row is not None
                else None
            )

    def list_definitions(
        self,
        *,
        domain: OperatorAutomationDomain | str | None = None,
        job_kind: OperatorAutomationJobKind | str | None = None,
        lifecycle_state: OperatorAutomationDefinitionState | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationDefinitionRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if domain is not None:
            domain_value = OperatorAutomationDomain(domain).value
            conditions.append("domain = %s")
            params.append(domain_value)
        if job_kind is not None:
            job_value = OperatorAutomationJobKind(job_kind).value
            conditions.append("job_kind = %s")
            params.append(job_value)
        if lifecycle_state is not None:
            state_value = OperatorAutomationDefinitionState(lifecycle_state).value
            conditions.append("lifecycle_state = %s")
            params.append(state_value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.get_cursor() as cursor:
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_definition{where}",
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition{where} ORDER BY created_at, definition_id LIMIT %s OFFSET %s",
                tuple([*params, limit, offset]),
            )
            rows = self._rows(cursor)
            return AutomationStorePage(
                items=tuple(
                    self._definition_from_row(row, control_posture=posture)
                    for row in rows
                ),
                total_count=total,
            )

    @staticmethod
    def _definition_target(
        current: OperatorAutomationDefinitionState,
        action: str,
    ) -> OperatorAutomationDefinitionState:
        normalized = action.lower()
        transitions = {
            OperatorAutomationDefinitionState.DRAFT: {
                "enable": OperatorAutomationDefinitionState.ENABLED,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.ENABLED: {
                "pause": OperatorAutomationDefinitionState.PAUSED,
                "drain": OperatorAutomationDefinitionState.DRAINING,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.PAUSED: {
                "resume": OperatorAutomationDefinitionState.ENABLED,
                "drain": OperatorAutomationDefinitionState.DRAINING,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.DRAINING: {
                "resume": OperatorAutomationDefinitionState.ENABLED,
                "disable": OperatorAutomationDefinitionState.DISABLED,
            },
            OperatorAutomationDefinitionState.DISABLED: {
                "enable": OperatorAutomationDefinitionState.ENABLED,
            },
        }
        try:
            return transitions[current][normalized]
        except KeyError:
            raise AutomationStoreConflict("automation_definition_transition_invalid") from None

    def transition_definition(
        self,
        definition_id: str,
        action: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        normalized = _enum_value(action).lower()
        resource_type = f"definition_{normalized}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._definition_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            current = OperatorAutomationDefinitionState(row["lifecycle_state"])
            target = self._definition_target(current, normalized)
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_definition
                SET lifecycle_state = %s, revision = revision + 1, updated_at = %s
                WHERE definition_id = %s
                RETURNING *
                """,
                (target.value, now, definition_id),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._definition_from_row(
                updated,
                control_posture=posture,
                now=now,
            )
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=f"automation_definition_{normalized}",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def set_schedule(
        self,
        definition_id: str,
        schedule_kind: OperatorAutomationScheduleKind | str,
        *,
        interval_seconds: int | None,
        command: AutomationMutationCommand,
        _evidence_kind: str = "set",
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        if _evidence_kind not in {"set", "clear"}:
            raise AutomationStoreInvalid("automation_schedule_evidence_invalid")
        resource_type = f"definition_{_evidence_kind}_schedule"
        diagnostic_code = f"automation_schedule_{'set' if _evidence_kind == 'set' else 'cleared'}"
        kind = OperatorAutomationScheduleKind(schedule_kind)
        if kind is OperatorAutomationScheduleKind.MANUAL_ONLY:
            if interval_seconds is not None:
                raise AutomationStoreInvalid("automation_manual_schedule_interval_forbidden")
        elif type(interval_seconds) is not int or not 60 <= interval_seconds <= 31_536_000:
            raise AutomationStoreInvalid("automation_schedule_interval_invalid")
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._definition_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor)
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            if self._row(cursor) is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            now = _utc_now()
            next_review_at = (
                now + timedelta(seconds=interval_seconds or 0)
                if kind is OperatorAutomationScheduleKind.INTERVAL_REVIEW_ONLY
                else None
            )
            audit_id = _new_id()
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_definition
                SET schedule_kind = %s, interval_seconds = %s,
                    next_review_at = %s, revision = revision + 1, updated_at = %s
                WHERE definition_id = %s RETURNING *
                """,
                (kind.value, interval_seconds, next_review_at, now, definition_id),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._definition_from_row(updated, control_posture=posture, now=now)
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=None,
                from_state=None,
                to_state=kind.value,
                diagnostic_code=diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=definition_id,
                audit_id=audit_id,
                result=self._definition_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def clear_schedule(
        self,
        definition_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationDefinitionRecord]:
        return self.set_schedule(
            definition_id,
            OperatorAutomationScheduleKind.MANUAL_ONLY,
            interval_seconds=None,
            command=AutomationMutationCommand(
                idempotency_key=command.idempotency_key,
                payload_sha256=command.payload_sha256,
                actor_id=command.actor_id,
                correlation_id=command.correlation_id,
                operator_intent=command.operator_intent,
            ),
            _evidence_kind="clear",
        )

    def transition_control_posture(
        self,
        action: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationControlPlaneRecord]:
        normalized = _enum_value(action).lower()
        targets = {
            "pause": OperatorAutomationControlPosture.PAUSED,
            "resume": OperatorAutomationControlPosture.ACTIVE,
            "drain": OperatorAutomationControlPosture.DRAINING,
            "shutdown": OperatorAutomationControlPosture.SHUTDOWN,
        }
        if normalized not in targets:
            raise AutomationStoreInvalid("automation_control_action_invalid")
        resource_type = f"control_{normalized}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                value = replay["entity"]
                record = AutomationControlPlaneRecord(
                    posture=OperatorAutomationControlPosture(value["posture"]),
                    updated_at=value["updated_at"],
                )
                return AutomationStoreMutation(
                    record,
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            current = self._current_control(cursor, for_update=True)
            target = targets[normalized]
            allowed_targets = {
                OperatorAutomationControlPosture.ACTIVE: {
                    OperatorAutomationControlPosture.PAUSED,
                    OperatorAutomationControlPosture.DRAINING,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.PAUSED: {
                    OperatorAutomationControlPosture.ACTIVE,
                    OperatorAutomationControlPosture.DRAINING,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.DRAINING: {
                    OperatorAutomationControlPosture.ACTIVE,
                    OperatorAutomationControlPosture.SHUTDOWN,
                },
                OperatorAutomationControlPosture.SHUTDOWN: {
                    OperatorAutomationControlPosture.ACTIVE,
                },
            }
            if target not in allowed_targets[current]:
                raise AutomationStoreConflict(
                    "automation_control_transition_invalid"
                )
            now = _utc_now()
            audit_id = _new_id()
            cursor.execute(
                f"UPDATE {self._prefix}automation_control_plane_state SET posture = %s, updated_at = %s WHERE singleton = 1 RETURNING posture, updated_at",
                (target.value, now),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._control_from_row(row)
            self._append_event(
                cursor,
                definition_id=None,
                run_id=None,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=f"automation_control_{normalized}",
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            result = {"posture": record.posture.value, "updated_at": record.updated_at}
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=audit_id,
                audit_id=audit_id,
                result=result,
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def _run_from_row(self, row: Mapping[str, Any]) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=str(row["run_id"]),
            definition_id=str(row["definition_id"]),
            domain=OperatorAutomationDomain(row["domain"]),
            job_kind=OperatorAutomationJobKind(row["job_kind"]),
            state=OperatorAutomationRunState(row["state"]),
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            client_order_id=(
                str(row["client_order_id"])
                if row.get("client_order_id") is not None
                else None
            ),
            live_attempt_consumed=bool(row["live_attempt_consumed"]),
            coinbase_api_call_count=int(row["coinbase_api_call_count"]),
            create_call_count=int(row["create_call_count"]),
            cancel_call_count=int(row["cancel_call_count"]),
            claimed_at=_iso(row["claimed_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
        )

    @staticmethod
    def _run_json(record: AutomationRunRecord) -> dict[str, Any]:
        result = asdict(record)
        result["domain"] = record.domain.value
        result["job_kind"] = record.job_kind.value
        result["state"] = record.state.value
        return result

    def _run_from_json(self, value: Mapping[str, Any]) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=value["run_id"],
            definition_id=value["definition_id"],
            domain=OperatorAutomationDomain(value["domain"]),
            job_kind=OperatorAutomationJobKind(value["job_kind"]),
            state=OperatorAutomationRunState(value["state"]),
            diagnostic_code=value["diagnostic_code"],
            audit_id=value["audit_id"],
            correlation_id=value["correlation_id"],
            client_order_id=value.get("client_order_id"),
            live_attempt_consumed=bool(value["live_attempt_consumed"]),
            coinbase_api_call_count=int(value["coinbase_api_call_count"]),
            create_call_count=int(value["create_call_count"]),
            cancel_call_count=int(value["cancel_call_count"]),
            claimed_at=value["claimed_at"],
            updated_at=value["updated_at"],
        )

    def claim_one_shot_run(
        self,
        definition_id: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type="run_claim_one_shot",
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._run_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            posture = self._current_control(cursor, for_update=True)
            if posture is not OperatorAutomationControlPosture.ACTIVE:
                raise AutomationStoreConflict("automation_control_plane_not_active")
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_definition WHERE definition_id = %s FOR UPDATE",
                (definition_id,),
            )
            definition = self._row(cursor)
            if definition is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            if definition["lifecycle_state"] != OperatorAutomationDefinitionState.ENABLED.value:
                raise AutomationStoreConflict("automation_definition_not_enabled")
            cursor.execute(
                f"SELECT run_id FROM {self._prefix}automation_run WHERE definition_id = %s AND state = ANY(%s) LIMIT 1",
                (definition_id, [state.value for state in _ACTIVE_RUN_STATES]),
            )
            if cursor.fetchone() is not None:
                raise AutomationStoreConflict("automation_run_in_progress")
            now = _utc_now()
            run_id = _new_id()
            audit_id = _new_id()
            cursor.execute(
                f"""
                INSERT INTO {self._prefix}automation_run (
                    run_id, definition_id, domain, job_kind, state,
                    diagnostic_code, audit_id, correlation_id, client_order_id,
                    live_attempt_consumed, coinbase_api_call_count,
                    create_call_count, cancel_call_count, claimed_at, updated_at
                ) VALUES (%s,%s,%s,%s,'CLAIMED','one_shot_run_claimed',%s,%s,NULL,FALSE,0,0,0,%s,%s)
                RETURNING *
                """,
                (
                    run_id,
                    definition_id,
                    definition["domain"],
                    definition["job_kind"],
                    audit_id,
                    command.correlation_id,
                    now,
                    now,
                ),
            )
            row = self._row(cursor)
            assert row is not None
            record = self._run_from_row(row)
            self._append_event(
                cursor,
                definition_id=definition_id,
                run_id=run_id,
                from_state=None,
                to_state=record.state.value,
                diagnostic_code=record.diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type="run_claim_one_shot",
                resource_id=run_id,
                audit_id=audit_id,
                result=self._run_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    @staticmethod
    def _run_transition_allowed(
        current: OperatorAutomationRunState,
        target: OperatorAutomationRunState,
    ) -> bool:
        transitions = {
            OperatorAutomationRunState.CLAIMED: {
                OperatorAutomationRunState.PREPARING,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.PREPARING: {
                OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION: {
                OperatorAutomationRunState.INVOCATION_STARTED,
                OperatorAutomationRunState.BLOCKED,
                OperatorAutomationRunState.ABORTED,
            },
            OperatorAutomationRunState.INVOCATION_STARTED: {
                OperatorAutomationRunState.ACTIVE,
                OperatorAutomationRunState.TERMINAL,
                OperatorAutomationRunState.UNKNOWN_CONSUMED,
            },
            OperatorAutomationRunState.ACTIVE: {
                OperatorAutomationRunState.TERMINAL,
                OperatorAutomationRunState.UNKNOWN_CONSUMED,
            },
        }
        return target in transitions.get(current, set())

    def transition_run(
        self,
        run_id: str,
        target_state: OperatorAutomationRunState | str,
        *,
        diagnostic_code: str,
        command: AutomationMutationCommand,
    ) -> AutomationStoreMutation[AutomationRunRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        target = OperatorAutomationRunState(target_state)
        if re.fullmatch(r"[a-z0-9_]{1,96}", diagnostic_code) is None:
            raise AutomationStoreInvalid("automation_run_diagnostic_invalid")
        resource_type = f"run_transition_{target.value.lower()}"
        with self.database.get_cursor() as cursor:
            replay = self._idempotency_replay(
                cursor,
                command=command,
                resource_type=resource_type,
            )
            if replay is not None:
                return AutomationStoreMutation(
                    self._run_from_json(replay["entity"]),
                    replay["audit_id"],
                    replay["correlation_id"],
                    True,
                )
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            row = self._row(cursor)
            if row is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            current = OperatorAutomationRunState(row["state"])
            if not self._run_transition_allowed(current, target):
                raise AutomationStoreConflict("automation_run_transition_invalid")
            now = _utc_now()
            audit_id = _new_id()
            live_consumed = bool(row["live_attempt_consumed"]) or target is OperatorAutomationRunState.UNKNOWN_CONSUMED
            cursor.execute(
                f"""
                UPDATE {self._prefix}automation_run
                SET state = %s, diagnostic_code = %s, audit_id = %s,
                    correlation_id = %s, live_attempt_consumed = %s,
                    updated_at = %s
                WHERE run_id = %s RETURNING *
                """,
                (
                    target.value,
                    diagnostic_code,
                    audit_id,
                    command.correlation_id,
                    live_consumed,
                    now,
                    run_id,
                ),
            )
            updated = self._row(cursor)
            assert updated is not None
            record = self._run_from_row(updated)
            self._append_event(
                cursor,
                definition_id=record.definition_id,
                run_id=run_id,
                from_state=current.value,
                to_state=target.value,
                diagnostic_code=diagnostic_code,
                audit_id=audit_id,
                idempotency_key_sha256=_hash(command.idempotency_key),
                correlation_id=command.correlation_id,
                recorded_at=now,
            )
            self._store_idempotency(
                cursor,
                command=command,
                resource_type=resource_type,
                resource_id=run_id,
                audit_id=audit_id,
                result=self._run_json(record),
                recorded_at=now,
            )
            return AutomationStoreMutation(record, audit_id, command.correlation_id)

    def get_run(self, run_id: str) -> AutomationRunRecord | None:
        _validate_id(run_id, code="automation_run_id_invalid")
        rows = self.database.execute_query(
            f"SELECT * FROM {self._prefix}automation_run WHERE run_id = %s",
            (run_id,),
        )
        return self._run_from_row(rows[0]) if rows else None

    def list_runs(
        self,
        *,
        definition_id: str | None = None,
        state: OperatorAutomationRunState | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationRunRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if definition_id is not None:
            _validate_id(definition_id, code="automation_definition_id_invalid")
            conditions.append("definition_id = %s")
            params.append(definition_id)
        if state is not None:
            conditions.append("state = %s")
            params.append(OperatorAutomationRunState(state).value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_run{where}",
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT * FROM {self._prefix}automation_run{where} ORDER BY claimed_at, run_id LIMIT %s OFFSET %s",
                tuple([*params, limit, offset]),
            )
            return AutomationStorePage(
                tuple(self._run_from_row(row) for row in self._rows(cursor)),
                total,
            )

    def list_run_events(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationRunEventRecord]:
        _validate_id(run_id, code="automation_run_id_invalid")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {self._prefix}automation_run WHERE run_id = %s",
                (run_id,),
            )
            if cursor.fetchone() is None:
                raise AutomationStoreNotFound("automation_run_not_found")
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE run_id = %s",
                (run_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, run_id, sequence, from_state, to_state,
                       diagnostic_code, audit_id, idempotency_key_sha256,
                       correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE run_id = %s ORDER BY sequence LIMIT %s OFFSET %s
                """,
                (run_id, limit, offset),
            )
            records = tuple(
                AutomationRunEventRecord(
                    event_id=str(row["event_id"]),
                    run_id=str(row["run_id"]),
                    sequence=int(row["sequence"]),
                    from_state=(
                        OperatorAutomationRunState(row["from_state"])
                        if row["from_state"] is not None
                        else None
                    ),
                    to_state=OperatorAutomationRunState(row["to_state"]),
                    diagnostic_code=row["diagnostic_code"],
                    audit_id=str(row["audit_id"]),
                    idempotency_key_sha256=row["idempotency_key_sha256"],
                    correlation_id=row["correlation_id"],
                    recorded_at=_iso(row["recorded_at"]) or "",
                )
                for row in self._rows(cursor)
            )
            return AutomationStorePage(records, total)

    def list_definition_events(
        self,
        definition_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationLifecycleEventRecord]:
        _validate_id(definition_id, code="automation_definition_id_invalid")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {self._prefix}automation_definition WHERE definition_id = %s",
                (definition_id,),
            )
            if cursor.fetchone() is None:
                raise AutomationStoreNotFound("automation_definition_not_found")
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE definition_id = %s AND run_id IS NULL",
                (definition_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, definition_id, from_state, to_state,
                       diagnostic_code, audit_id, correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE definition_id = %s AND run_id IS NULL
                ORDER BY recorded_at, event_id LIMIT %s OFFSET %s
                """,
                (definition_id, limit, offset),
            )
            return AutomationStorePage(
                tuple(
                    self._lifecycle_event_from_row(row)
                    for row in self._rows(cursor)
                ),
                total,
            )

    def list_control_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationStorePage[AutomationLifecycleEventRecord]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AutomationStoreInvalid("automation_page_limit_invalid")
        if type(offset) is not int or offset < 0:
            raise AutomationStoreInvalid("automation_page_offset_invalid")
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {self._prefix}automation_event_outbox WHERE definition_id IS NULL AND run_id IS NULL"
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, definition_id, from_state, to_state,
                       diagnostic_code, audit_id, correlation_id, recorded_at
                FROM {self._prefix}automation_event_outbox
                WHERE definition_id IS NULL AND run_id IS NULL
                ORDER BY recorded_at, event_id LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return AutomationStorePage(
                tuple(
                    self._lifecycle_event_from_row(row)
                    for row in self._rows(cursor)
                ),
                total,
            )

    @staticmethod
    def _lifecycle_event_from_row(
        row: Mapping[str, Any],
    ) -> AutomationLifecycleEventRecord:
        return AutomationLifecycleEventRecord(
            event_id=str(row["event_id"]),
            definition_id=(
                str(row["definition_id"])
                if row["definition_id"] is not None
                else None
            ),
            from_state=row["from_state"],
            to_state=row["to_state"],
            diagnostic_code=row["diagnostic_code"],
            audit_id=str(row["audit_id"]),
            correlation_id=row["correlation_id"],
            recorded_at=_iso(row["recorded_at"]) or "",
        )

    def recover_runs_after_restart(self) -> tuple[AutomationRunRecord, ...]:
        """Recover pre-invocation work and quarantine any invoked work once."""

        recovered: list[AutomationRunRecord] = []
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM {self._prefix}automation_run
                WHERE state = ANY(%s)
                ORDER BY claimed_at, run_id
                FOR UPDATE
                """,
                ([state.value for state in _ACTIVE_RUN_STATES],),
            )
            rows = self._rows(cursor)
            for row in rows:
                current = OperatorAutomationRunState(row["state"])
                if current in _POST_INVOCATION_STATES:
                    target = OperatorAutomationRunState.UNKNOWN_CONSUMED
                    diagnostic = "restart_unknown_consumed"
                    live_consumed = True
                elif current in _PRE_INVOCATION_STATES:
                    target = OperatorAutomationRunState.BLOCKED
                    diagnostic = "restart_pre_invocation_blocked"
                    live_consumed = False
                else:  # pragma: no cover - guarded by the query values
                    continue
                now = _utc_now()
                audit_id = _new_id()
                correlation_id = "automation-restart-recovery"
                evidence_key = _hash(
                    f"automation-restart:{row['run_id']}:{current.value}:{diagnostic}"
                )
                cursor.execute(
                    f"""
                    UPDATE {self._prefix}automation_run
                    SET state = %s, diagnostic_code = %s, audit_id = %s,
                        correlation_id = %s, live_attempt_consumed = %s,
                        updated_at = %s
                    WHERE run_id = %s RETURNING *
                    """,
                    (
                        target.value,
                        diagnostic,
                        audit_id,
                        correlation_id,
                        live_consumed,
                        now,
                        str(row["run_id"]),
                    ),
                )
                updated = self._row(cursor)
                assert updated is not None
                record = self._run_from_row(updated)
                self._append_event(
                    cursor,
                    definition_id=record.definition_id,
                    run_id=record.run_id,
                    from_state=current.value,
                    to_state=target.value,
                    diagnostic_code=diagnostic,
                    audit_id=audit_id,
                    idempotency_key_sha256=evidence_key,
                    correlation_id=correlation_id,
                    recorded_at=now,
                )
                recovered.append(record)
        return tuple(recovered)


def get_default_operator_automation_repository() -> OperatorAutomationRepository:
    schema = os.environ.get("COINBASE_OPERATOR_AUTOMATION_DB_SCHEMA", "public")
    return OperatorAutomationRepository(PostgresDB(), schema=schema)


def initialize_operator_automation_schema() -> None:
    repository = get_default_operator_automation_repository()
    repository.ensure_schema()
    repository.recover_runs_after_restart()
