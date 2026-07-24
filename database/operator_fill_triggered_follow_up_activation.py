"""PostgreSQL authority for one fill-triggered follow-up activation.

The activation record is intentionally separate from the immutable attached
intent and from earlier materialization proof ledgers.  It stores no Coinbase
response or exchange-native identifier.  The full-fill claim is admitted only
after local canonical order and fill-ledger evidence agree exactly.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import threading
from typing import Any, Mapping
import uuid

from application.admin_api.operator_fill_triggered_follow_up_activation import (
    FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FillTriggeredActivationControlAction,
    FillTriggeredActivationControlState,
    FillTriggeredActivationRecord,
    FillTriggeredActivationTriggerState,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_STATES = tuple(state.value for state in FillTriggeredActivationControlState)
_TRIGGER_STATES = tuple(state.value for state in FillTriggeredActivationTriggerState)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, value))


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("fill_triggered_timestamp_invalid")
    return normalized


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("fill_triggered_fill_evidence_invalid") from None
    if not result.is_finite():
        raise ValueError("fill_triggered_fill_evidence_invalid")
    return result


class OperatorFillTriggeredFollowUpActivationRepository:
    """Serialize controls and the one automatic full-fill trigger claim."""

    def __init__(self, db: Any, *, schema: str = "public") -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("fill_triggered_schema_invalid")
        self.db = db
        self.schema = str(schema)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @contextmanager
    def _cursor(self):
        with self.db.get_cursor() as cursor:
            yield cursor

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table('operator_fill_triggered_follow_up_activation')} (
                        goal_id VARCHAR(128) NOT NULL,
                        source_client_order_id VARCHAR(128) PRIMARY KEY,
                        follow_up_intent_id UUID NOT NULL UNIQUE,
                        control_state VARCHAR(16) NOT NULL
                            CHECK (control_state IN ({_sql_values(_CONTROL_STATES)})),
                        trigger_state VARCHAR(16) NOT NULL
                            CHECK (trigger_state IN ({_sql_values(_TRIGGER_STATES)})),
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        delegated_create_authority BOOLEAN NOT NULL DEFAULT FALSE,
                        trigger_claim_id UUID UNIQUE,
                        trigger_evidence_sha256 CHAR(64),
                        materialization_state VARCHAR(64),
                        child_client_order_id VARCHAR(128),
                        diagnostic_code VARCHAR(96) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CHECK (
                            (trigger_state = 'UNCLAIMED'
                             AND trigger_claim_id IS NULL
                             AND trigger_evidence_sha256 IS NULL)
                            OR
                            (trigger_state <> 'UNCLAIMED'
                             AND trigger_claim_id IS NOT NULL
                             AND trigger_evidence_sha256 IS NOT NULL)
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._table('operator_fill_triggered_follow_up_activation')}
                    ADD COLUMN IF NOT EXISTS delegated_create_authority
                        BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table('operator_fill_triggered_follow_up_control_command')} (
                        command_id UUID PRIMARY KEY,
                        source_client_order_id VARCHAR(128) NOT NULL,
                        action VARCHAR(16) NOT NULL,
                        expected_revision INTEGER NOT NULL,
                        result_revision INTEGER NOT NULL,
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (source_client_order_id)
                            REFERENCES {self._table('operator_fill_triggered_follow_up_activation')}(source_client_order_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION {self._table('guard_fill_triggered_control_command_append_only')}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = '55000',
                            MESSAGE = 'fill_triggered_control_command_append_only';
                    END;
                    $$
                    """
                )
                cursor.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"fill_triggered_control_command_append_only "
                    f"ON {self._table('operator_fill_triggered_follow_up_control_command')}"
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER fill_triggered_control_command_append_only
                    BEFORE UPDATE OR DELETE ON
                        {self._table('operator_fill_triggered_follow_up_control_command')}
                    FOR EACH ROW EXECUTE FUNCTION
                        {self._table('guard_fill_triggered_control_command_append_only')}()
                    """
                )
            self._schema_ready = True

    @staticmethod
    def _record(row: Mapping[str, Any]) -> FillTriggeredActivationRecord:
        roles_value = row.get("roles_json")
        if isinstance(roles_value, str):
            roles_value = json.loads(roles_value)
        roles = tuple(
            str(role)
            for role in (roles_value if isinstance(roles_value, list) else [])
        )
        return FillTriggeredActivationRecord(
            goal_id=str(row["goal_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            control_state=FillTriggeredActivationControlState(
                str(row["control_state"])
            ),
            trigger_state=FillTriggeredActivationTriggerState(
                str(row["trigger_state"])
            ),
            revision=int(row["revision"]),
            delegated_create_authority=(
                row.get("delegated_create_authority") is True
            ),
            trigger_claim_id=(
                str(row["trigger_claim_id"])
                if row.get("trigger_claim_id")
                else None
            ),
            trigger_evidence_sha256=(
                str(row["trigger_evidence_sha256"])
                if row.get("trigger_evidence_sha256")
                else None
            ),
            materialization_state=(
                str(row["materialization_state"])
                if row.get("materialization_state")
                else None
            ),
            child_client_order_id=(
                str(row["child_client_order_id"])
                if row.get("child_client_order_id")
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            actor_id=str(row["actor_id"]),
            roles=roles,
            correlation_id=str(row["correlation_id"]),
            audit_id=str(row["audit_id"]),
            recorded_at=_iso(row["recorded_at"]),
            updated_at=_iso(row["updated_at"]),
        )

    def _intent(self, cursor: Any, source_id: str, *, lock: bool) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT follow_up_intent_id, source_client_order_id,
                   terminal_result, actor_id, roles_json,
                   correlation_id, audit_id, recorded_at
              FROM {self._table('operator_follow_up_intent')}
             WHERE source_client_order_id = %s
               AND terminal_result = 'ATTACHED'
             {"FOR UPDATE" if lock else ""}
            """,
            (source_id,),
        )
        row = _row(cursor)
        if row is None:
            raise ValueError("fill_triggered_follow_up_intent_not_attached")
        return row

    def _activation(
        self,
        cursor: Any,
        source_id: str,
        *,
        lock: bool,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
              FROM {self._table('operator_fill_triggered_follow_up_activation')}
             WHERE source_client_order_id = %s
             {"FOR UPDATE" if lock else ""}
            """,
            (source_id,),
        )
        return _row(cursor)

    def _read_locked(self, cursor: Any, source_id: str) -> FillTriggeredActivationRecord:
        intent = self._intent(cursor, source_id, lock=True)
        activation = self._activation(cursor, source_id, lock=True)
        if activation is not None:
            return self._record(activation)
        roles_value = intent.get("roles_json")
        if isinstance(roles_value, str):
            roles_value = json.loads(roles_value)
        return FillTriggeredActivationRecord(
            goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            source_client_order_id=source_id,
            follow_up_intent_id=str(intent["follow_up_intent_id"]),
            control_state=FillTriggeredActivationControlState.DISABLED,
            trigger_state=FillTriggeredActivationTriggerState.UNCLAIMED,
            revision=0,
            delegated_create_authority=False,
            trigger_claim_id=None,
            trigger_evidence_sha256=None,
            materialization_state=None,
            child_client_order_id=None,
            diagnostic_code="fill_triggered_follow_up_disabled",
            actor_id=str(intent["actor_id"]),
            roles=tuple(str(role) for role in (roles_value or [])),
            correlation_id=str(intent["correlation_id"]),
            audit_id=str(intent["audit_id"]),
            recorded_at=_iso(intent["recorded_at"]),
            updated_at=_iso(intent["recorded_at"]),
        )

    def read(self, source_client_order_id: str) -> FillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if not source_id or len(source_id) > 128:
            raise ValueError("fill_triggered_follow_up_source_invalid")
        with self._cursor() as cursor:
            intent = self._intent(cursor, source_id, lock=False)
            activation = self._activation(cursor, source_id, lock=False)
            if activation is not None:
                return self._record(activation)
            roles_value = intent.get("roles_json")
            if isinstance(roles_value, str):
                roles_value = json.loads(roles_value)
            return FillTriggeredActivationRecord(
                goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                source_client_order_id=source_id,
                follow_up_intent_id=str(intent["follow_up_intent_id"]),
                control_state=FillTriggeredActivationControlState.DISABLED,
                trigger_state=FillTriggeredActivationTriggerState.UNCLAIMED,
                revision=0,
                delegated_create_authority=False,
                trigger_claim_id=None,
                trigger_evidence_sha256=None,
                materialization_state=None,
                child_client_order_id=None,
                diagnostic_code="fill_triggered_follow_up_disabled",
                actor_id=str(intent["actor_id"]),
                roles=tuple(str(role) for role in (roles_value or [])),
                correlation_id=str(intent["correlation_id"]),
                audit_id=str(intent["audit_id"]),
                recorded_at=_iso(intent["recorded_at"]),
                updated_at=_iso(intent["recorded_at"]),
            )

    def has_attached_intent(self, source_client_order_id: str) -> bool:
        """Return local scope without synthesizing or mutating activation state."""

        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if not source_id or len(source_id) > 128:
            return False
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 1
                  FROM {self._table('operator_follow_up_intent')}
                 WHERE source_client_order_id = %s
                   AND terminal_result = 'ATTACHED'
                 LIMIT 1
                """,
                (source_id,),
            )
            return cursor.fetchone() is not None

    def list_claimed(self) -> tuple[FillTriggeredActivationRecord, ...]:
        """Return local stranded-claim candidates for startup recovery."""

        self.ensure_schema()
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                  FROM {self._table('operator_fill_triggered_follow_up_activation')}
                 WHERE trigger_state = 'CLAIMED'
                 ORDER BY recorded_at ASC
                """
            )
            rows: list[dict[str, Any]] = []
            while (row := _row(cursor)) is not None:
                rows.append(row)
        return tuple(self._record(row) for row in rows)

    @staticmethod
    def _control_target(
        action: FillTriggeredActivationControlAction,
        record: FillTriggeredActivationRecord,
    ) -> FillTriggeredActivationControlState:
        if record.trigger_state is FillTriggeredActivationTriggerState.CLAIMED:
            if action is FillTriggeredActivationControlAction.DRAIN:
                return FillTriggeredActivationControlState.DRAINING
            raise ValueError("fill_triggered_control_inflight")
        if record.trigger_state.is_terminal:
            if action is FillTriggeredActivationControlAction.DRAIN:
                return FillTriggeredActivationControlState.DRAINED
            raise ValueError("fill_triggered_control_terminal")
        if action is FillTriggeredActivationControlAction.ENABLE:
            return FillTriggeredActivationControlState.ENABLED
        if action is FillTriggeredActivationControlAction.DISABLE:
            return FillTriggeredActivationControlState.DISABLED
        if action is FillTriggeredActivationControlAction.PAUSE:
            if record.control_state is not FillTriggeredActivationControlState.ENABLED:
                raise ValueError("fill_triggered_control_transition_invalid")
            return FillTriggeredActivationControlState.PAUSED
        if action is FillTriggeredActivationControlAction.DRAIN:
            return FillTriggeredActivationControlState.DRAINED
        raise ValueError("fill_triggered_control_action_invalid")

    def transition_control(
        self,
        *,
        source_client_order_id: str,
        action: FillTriggeredActivationControlAction,
        expected_revision: int,
        authorize_single_fill_triggered_materialization: bool = False,
        acknowledge_unknown_outcome_consumes_create_allowance: bool = False,
        acknowledge_child_terms_are_backend_derived: bool = False,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        correlation_id: str,
        audit_id: str,
    ) -> FillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if (
            not source_id
            or not isinstance(action, FillTriggeredActivationControlAction)
            or type(expected_revision) is not int
            or expected_revision < 0
            or (
                action is FillTriggeredActivationControlAction.ENABLE
                and (
                    authorize_single_fill_triggered_materialization is not True
                    or acknowledge_unknown_outcome_consumes_create_allowance
                    is not True
                    or acknowledge_child_terms_are_backend_derived is not True
                )
            )
        ):
            raise ValueError("fill_triggered_control_invalid")
        delegated_authority = (
            action is FillTriggeredActivationControlAction.ENABLE
            and authorize_single_fill_triggered_materialization is True
            and acknowledge_unknown_outcome_consumes_create_allowance is True
            and acknowledge_child_terms_are_backend_derived is True
        )
        key_hash = hashlib.sha256(str(idempotency_key).encode()).hexdigest()
        payload = {
            "source_client_order_id": source_id,
            "action": action.value,
            "expected_revision": expected_revision,
            "authorize_single_fill_triggered_materialization": (
                authorize_single_fill_triggered_materialization
            ),
            "acknowledge_unknown_outcome_consumes_create_allowance": (
                acknowledge_unknown_outcome_consumes_create_allowance
            ),
            "acknowledge_child_terms_are_backend_derived": (
                acknowledge_child_terms_are_backend_derived
            ),
            "actor_id": str(actor_id),
            "roles": list(roles),
            "correlation_id": str(correlation_id),
            "audit_id": str(audit_id),
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        normalized_audit_id = str(uuid.UUID(str(audit_id)))
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(31881, hashtext(%s))",
                (source_id,),
            )
            cursor.execute(
                f"""
                SELECT payload_sha256, source_client_order_id, result_revision
                  FROM {self._table('operator_fill_triggered_follow_up_control_command')}
                 WHERE idempotency_key_sha256 = %s
                """,
                (key_hash,),
            )
            replay = _row(cursor)
            if replay is not None:
                if (
                    str(replay["payload_sha256"]) != payload_hash
                    or str(replay["source_client_order_id"]) != source_id
                ):
                    raise ValueError("fill_triggered_control_idempotency_conflict")
                record = self._read_locked(cursor, source_id)
                if record.revision != int(replay["result_revision"]):
                    raise ValueError("fill_triggered_control_replay_invalid")
                return record

            current = self._read_locked(cursor, source_id)
            if current.revision != expected_revision:
                raise ValueError("fill_triggered_control_revision_conflict")
            target = self._control_target(action, current)
            result_revision = current.revision + 1
            if current.revision == 0:
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_fill_triggered_follow_up_activation')} (
                        goal_id, source_client_order_id, follow_up_intent_id,
                        control_state, trigger_state, revision,
                        delegated_create_authority,
                        diagnostic_code, actor_id, roles_json,
                        correlation_id, audit_id
                    ) VALUES (%s, %s, %s, %s, 'UNCLAIMED', %s, %s, %s, %s,
                              %s::jsonb, %s, %s)
                    """,
                    (
                        FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                        source_id,
                        current.follow_up_intent_id,
                        target.value,
                        result_revision,
                        delegated_authority,
                        f"fill_triggered_follow_up_{target.value.lower()}",
                        str(actor_id),
                        json.dumps(list(roles), separators=(",", ":")),
                        str(correlation_id),
                        normalized_audit_id,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_fill_triggered_follow_up_activation')}
                           SET control_state = %s,
                               revision = %s,
                               delegated_create_authority = %s,
                               diagnostic_code = %s,
                           actor_id = %s,
                           roles_json = %s::jsonb,
                           correlation_id = %s,
                           audit_id = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE source_client_order_id = %s
                       AND revision = %s
                    """,
                    (
                        target.value,
                        result_revision,
                        delegated_authority,
                        f"fill_triggered_follow_up_{target.value.lower()}",
                        str(actor_id),
                        json.dumps(list(roles), separators=(",", ":")),
                        str(correlation_id),
                        normalized_audit_id,
                        source_id,
                        current.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("fill_triggered_control_revision_conflict")
            cursor.execute(
                f"""
                INSERT INTO {self._table('operator_fill_triggered_follow_up_control_command')} (
                    command_id, source_client_order_id, action,
                    expected_revision, result_revision,
                    idempotency_key_sha256, payload_sha256,
                    correlation_id, audit_id, actor_id, roles_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    source_id,
                    action.value,
                    expected_revision,
                    result_revision,
                    key_hash,
                    payload_hash,
                    str(correlation_id),
                    normalized_audit_id,
                    str(actor_id),
                    json.dumps(list(roles), separators=(",", ":")),
                ),
            )
            activation = self._activation(cursor, source_id, lock=False)
            if activation is None:
                raise ValueError("fill_triggered_control_persistence_unknown")
            return self._record(activation)

    def _full_fill_proven(self, cursor: Any, source_id: str) -> bool:
        cursor.execute(
            f"""
            SELECT status, size
              FROM {self._table('order_parent')}
             WHERE client_order_id = %s
             FOR UPDATE
            """,
            (source_id,),
        )
        source = _row(cursor)
        if source is None or str(source.get("status") or "").upper() != "FILLED":
            return False
        source_size = _decimal(source.get("size"))
        if source_size <= 0:
            return False
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(quantity), 0) AS filled_size,
                   COUNT(*) FILTER (WHERE quantity > 0) AS positive_rows,
                   COUNT(*) FILTER (WHERE quantity < 0) AS negative_rows
              FROM {self._table('fill_ledger')}
             WHERE client_order_id = %s
            """,
            (source_id,),
        )
        ledger = _row(cursor) or {}
        if (
            int(ledger.get("positive_rows") or 0) <= 0
            or int(ledger.get("negative_rows") or 0) != 0
            or _decimal(ledger.get("filled_size") or 0) != source_size
        ):
            return False
        cursor.execute(
            f"""
            SELECT COALESCE(MAX(partial_follow_ups_created), 0) AS created
              FROM {self._table('partial_fill_progress')}
             WHERE client_order_id = %s
            """,
            (source_id,),
        )
        progress = _row(cursor) or {}
        return int(progress.get("created") or 0) == 0

    def claim_full_fill_trigger(
        self,
        *,
        source_client_order_id: str,
        trigger_evidence_sha256: str,
    ) -> FillTriggeredActivationRecord | None:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        evidence_hash = str(trigger_evidence_sha256 or "").lower()
        if not source_id or not _SHA256_RE.fullmatch(evidence_hash):
            raise ValueError("fill_triggered_claim_invalid")
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(31882, hashtext(%s))",
                (source_id,),
            )
            self._intent(cursor, source_id, lock=True)
            activation = self._activation(cursor, source_id, lock=True)
            if activation is None:
                return None
            current = self._record(activation)
            if (
                current.control_state
                is not FillTriggeredActivationControlState.ENABLED
                or current.delegated_create_authority is not True
                or current.trigger_state
                is not FillTriggeredActivationTriggerState.UNCLAIMED
                or not self._full_fill_proven(cursor, source_id)
            ):
                return None
            claim_id = str(uuid.uuid4())
            cursor.execute(
                f"""
                UPDATE {self._table('operator_fill_triggered_follow_up_activation')}
                   SET trigger_state = 'CLAIMED',
                       trigger_claim_id = %s,
                       trigger_evidence_sha256 = %s,
                       diagnostic_code = 'fill_triggered_follow_up_claimed',
                       updated_at = CURRENT_TIMESTAMP
                 WHERE source_client_order_id = %s
                   AND control_state = 'ENABLED'
                   AND delegated_create_authority IS TRUE
                   AND trigger_state = 'UNCLAIMED'
                """,
                (claim_id, evidence_hash, source_id),
            )
            if cursor.rowcount != 1:
                return None
            claimed = self._activation(cursor, source_id, lock=False)
            if claimed is None:
                raise ValueError("fill_triggered_claim_persistence_unknown")
            return self._record(claimed)

    def finalize_trigger(
        self,
        *,
        source_client_order_id: str,
        trigger_claim_id: str,
        trigger_state: FillTriggeredActivationTriggerState,
        materialization_state: str,
        child_client_order_id: str | None,
        diagnostic_code: str,
    ) -> FillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if trigger_state not in {
            FillTriggeredActivationTriggerState.COMPLETED,
            FillTriggeredActivationTriggerState.BLOCKED,
            FillTriggeredActivationTriggerState.UNKNOWN,
        }:
            raise ValueError("fill_triggered_terminal_invalid")
        claim_id = str(uuid.UUID(str(trigger_claim_id)))
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(31882, hashtext(%s))",
                (source_id,),
            )
            activation = self._activation(cursor, source_id, lock=True)
            if activation is None:
                raise ValueError("fill_triggered_activation_not_found")
            current = self._record(activation)
            if current.trigger_state.is_terminal:
                if (
                    current.trigger_claim_id == claim_id
                    and current.trigger_state is trigger_state
                ):
                    return current
                raise ValueError("fill_triggered_terminal_conflict")
            if (
                current.trigger_state
                is not FillTriggeredActivationTriggerState.CLAIMED
                or current.trigger_claim_id != claim_id
            ):
                raise ValueError("fill_triggered_claim_conflict")
            target_control = (
                FillTriggeredActivationControlState.DRAINED
                if current.control_state
                is FillTriggeredActivationControlState.DRAINING
                else current.control_state
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_fill_triggered_follow_up_activation')}
                   SET trigger_state = %s,
                       control_state = %s,
                       materialization_state = %s,
                       child_client_order_id = %s,
                       diagnostic_code = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE source_client_order_id = %s
                   AND trigger_state = 'CLAIMED'
                   AND trigger_claim_id = %s
                """,
                (
                    trigger_state.value,
                    target_control.value,
                    str(materialization_state),
                    child_client_order_id,
                    str(diagnostic_code),
                    source_id,
                    claim_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("fill_triggered_terminal_persistence_unknown")
            finalized = self._activation(cursor, source_id, lock=False)
            if finalized is None:
                raise ValueError("fill_triggered_terminal_persistence_unknown")
            return self._record(finalized)


_DEFAULT_REPOSITORY: OperatorFillTriggeredFollowUpActivationRepository | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_operator_fill_triggered_follow_up_activation_repository(
) -> OperatorFillTriggeredFollowUpActivationRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_REPOSITORY is None:
                from database import order as order_db

                _DEFAULT_REPOSITORY = (
                    OperatorFillTriggeredFollowUpActivationRepository(
                        order_db.DB_CLIENT
                    )
                )
    return _DEFAULT_REPOSITORY


def create_operator_fill_triggered_follow_up_activation_tables() -> None:
    repository = (
        get_default_operator_fill_triggered_follow_up_activation_repository()
    )
    repository.ensure_schema()
    from application.admin_api.operator_fill_triggered_follow_up_activation import (
        recover_stranded_fill_triggered_follow_ups,
    )
    from database.order_follow_up_intent import get_default_repository

    recover_stranded_fill_triggered_follow_ups(
        repository=repository,
        native_repository=get_default_repository(),
    )
