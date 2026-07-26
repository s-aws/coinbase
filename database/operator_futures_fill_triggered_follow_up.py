"""PostgreSQL authority for Goal 5 Futures full-fill activation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    FuturesFillTriggeredActivationRecord,
    FuturesFillTriggeredControlAction,
    FuturesFillTriggeredControlState,
    FuturesFillTriggeredTriggerState,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualGoalRecord,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((column[0] for column in cursor.description), value))


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    text = str(value or "").strip()
    if not text:
        raise ValueError(
            "operator_futures_fill_triggered_timestamp_invalid"
        )
    return text


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "operator_futures_fill_triggered_fill_schema_invalid"
        ) from None
    if not result.is_finite():
        raise ValueError(
            "operator_futures_fill_triggered_fill_schema_invalid"
        )
    return result


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


class OperatorFuturesFillTriggeredFollowUpRepository:
    """Serialize operator controls and one immutable full-fill claim."""

    def __init__(
        self,
        db: Any,
        *,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError(
                "operator_futures_fill_triggered_schema_invalid"
            )
        self.db = db
        self.schema = str(schema)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
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
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_fill_triggered_follow_up'
                        )} (
                        source_client_order_id VARCHAR(128) PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        follow_up_intent_id UUID NOT NULL UNIQUE REFERENCES
                            {self._table(
                                'operator_futures_follow_up_intent'
                            )}(follow_up_intent_id) ON DELETE RESTRICT,
                        control_state VARCHAR(16) NOT NULL CHECK (
                            control_state IN (
                                'DISABLED', 'ENABLED', 'PAUSED',
                                'DRAINING', 'DRAINED'
                            )
                        ),
                        trigger_state VARCHAR(16) NOT NULL CHECK (
                            trigger_state IN (
                                'UNCLAIMED', 'CLAIMED', 'COMPLETED',
                                'BLOCKED', 'UNKNOWN'
                            )
                        ),
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        delegated_live_authority BOOLEAN NOT NULL,
                        trigger_claim_id UUID UNIQUE,
                        trigger_evidence_sha256 CHAR(64),
                        lifecycle_revision INTEGER NOT NULL DEFAULT 0
                            CHECK (lifecycle_revision >= 0),
                        child_client_order_id VARCHAR(128),
                        preview_outcome VARCHAR(16) NOT NULL
                            DEFAULT 'NOT_RUN',
                        create_outcome VARCHAR(16) NOT NULL
                            DEFAULT 'NOT_RUN',
                        reconciliation_outcome VARCHAR(16) NOT NULL
                            DEFAULT 'NOT_RUN',
                        cancel_outcome VARCHAR(16) NOT NULL
                            DEFAULT 'NOT_RUN',
                        diagnostic_code VARCHAR(128) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        CHECK (
                            (
                                trigger_state = 'UNCLAIMED'
                                AND trigger_claim_id IS NULL
                                AND trigger_evidence_sha256 IS NULL
                            )
                            OR (
                                trigger_state <> 'UNCLAIMED'
                                AND trigger_claim_id IS NOT NULL
                                AND trigger_evidence_sha256 IS NOT NULL
                            )
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_fill_triggered_control_command'
                        )} (
                        command_id UUID PRIMARY KEY,
                        source_client_order_id VARCHAR(128) NOT NULL
                            REFERENCES {self._table(
                                'operator_futures_fill_triggered_follow_up'
                            )}(source_client_order_id) ON DELETE RESTRICT,
                        action VARCHAR(16) NOT NULL CHECK (
                            action IN (
                                'ENABLE', 'DISABLE', 'PAUSE',
                                'RESUME', 'DRAIN'
                            )
                        ),
                        expected_revision INTEGER NOT NULL,
                        result_revision INTEGER NOT NULL,
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        result_json JSONB,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._table(
                        'operator_futures_fill_triggered_control_command'
                    )}
                    ADD COLUMN IF NOT EXISTS result_json JSONB
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        "{self.schema}".
                        operator_futures_fill_triggered_command_immutable()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION
                            'operator_futures_fill_triggered_command_immutable';
                    END;
                    $$
                    """
                )
                cursor.execute(
                    f"""
                    DROP TRIGGER IF EXISTS
                        operator_futures_fill_triggered_command_immutable
                    ON {self._table(
                        'operator_futures_fill_triggered_control_command'
                    )}
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER
                        operator_futures_fill_triggered_command_immutable
                    BEFORE UPDATE OR DELETE
                    ON {self._table(
                        'operator_futures_fill_triggered_control_command'
                    )}
                    FOR EACH ROW EXECUTE FUNCTION
                        "{self.schema}".
                        operator_futures_fill_triggered_command_immutable()
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        operator_futures_fill_triggered_one_authority
                    ON {self._table(
                        'operator_futures_fill_triggered_follow_up'
                    )} (goal_id)
                    WHERE delegated_live_authority IS TRUE
                    """
                )
                self._recover_locked(cursor)
            self._schema_ready = True

    def _recover_locked(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            UPDATE {self._table(
                'operator_futures_fill_triggered_follow_up'
            )}
            SET trigger_state = 'UNKNOWN',
                diagnostic_code =
                    'operator_futures_fill_triggered_restart_unknown',
                updated_at = NOW()
            WHERE trigger_state = 'CLAIMED'
            """
        )

    @staticmethod
    def _record(
        row: Mapping[str, Any],
    ) -> FuturesFillTriggeredActivationRecord:
        roles_value = row.get("roles_json")
        if isinstance(roles_value, str):
            roles_value = json.loads(roles_value)
        return FuturesFillTriggeredActivationRecord(
            goal_id=str(row["goal_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            control_state=FuturesFillTriggeredControlState(
                str(row["control_state"])
            ),
            trigger_state=FuturesFillTriggeredTriggerState(
                str(row["trigger_state"])
            ),
            revision=int(row["revision"]),
            delegated_live_authority=(
                row.get("delegated_live_authority") is True
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
            lifecycle_revision=int(row.get("lifecycle_revision") or 0),
            child_client_order_id=(
                str(row["child_client_order_id"])
                if row.get("child_client_order_id")
                else None
            ),
            preview_outcome=str(row.get("preview_outcome") or "NOT_RUN"),
            create_outcome=str(row.get("create_outcome") or "NOT_RUN"),
            reconciliation_outcome=str(
                row.get("reconciliation_outcome") or "NOT_RUN"
            ),
            cancel_outcome=str(row.get("cancel_outcome") or "NOT_RUN"),
            diagnostic_code=str(row["diagnostic_code"]),
            actor_id=str(row["actor_id"]),
            roles=tuple(
                str(role)
                for role in (
                    roles_value if isinstance(roles_value, list) else []
                )
            ),
            correlation_id=str(row["correlation_id"]),
            audit_id=str(row["audit_id"]),
            recorded_at=_iso(row["recorded_at"]),
            updated_at=_iso(row["updated_at"]),
        )

    def _intent(
        self, cursor: Any, source_id: str, *, lock: bool
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_futures_follow_up_intent')}
            WHERE source_client_order_id = %s
              AND state = 'ATTACHED'
            {"FOR UPDATE" if lock else ""}
            """,
            (source_id,),
        )
        row = _row(cursor)
        if row is None:
            raise ValueError(
                "operator_futures_fill_triggered_intent_not_attached"
            )
        return row

    def _activation(
        self, cursor: Any, source_id: str, *, lock: bool
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table(
                'operator_futures_fill_triggered_follow_up'
            )}
            WHERE source_client_order_id = %s
            {"FOR UPDATE" if lock else ""}
            """,
            (source_id,),
        )
        return _row(cursor)

    def _synthetic(
        self, intent: Mapping[str, Any]
    ) -> FuturesFillTriggeredActivationRecord:
        roles_value = intent.get("roles_json")
        if isinstance(roles_value, str):
            roles_value = json.loads(roles_value)
        recorded = _iso(intent["created_at"])
        return FuturesFillTriggeredActivationRecord(
            goal_id=FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            source_client_order_id=str(
                intent["source_client_order_id"]
            ),
            follow_up_intent_id=str(intent["follow_up_intent_id"]),
            control_state=FuturesFillTriggeredControlState.DISABLED,
            trigger_state=FuturesFillTriggeredTriggerState.UNCLAIMED,
            revision=0,
            delegated_live_authority=False,
            trigger_claim_id=None,
            trigger_evidence_sha256=None,
            lifecycle_revision=0,
            child_client_order_id=None,
            preview_outcome="NOT_RUN",
            create_outcome="NOT_RUN",
            reconciliation_outcome="NOT_RUN",
            cancel_outcome="NOT_RUN",
            diagnostic_code=(
                "operator_futures_fill_triggered_follow_up_disabled"
            ),
            actor_id=str(intent["actor_id"]),
            roles=tuple(
                str(role)
                for role in (
                    roles_value if isinstance(roles_value, list) else []
                )
            ),
            correlation_id=str(intent["correlation_id"]),
            audit_id=str(intent["audit_id"]),
            recorded_at=recorded,
            updated_at=recorded,
        )

    def read(
        self, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if not source_id or len(source_id) > 128:
            raise ValueError(
                "operator_futures_fill_triggered_source_invalid"
            )
        with self._cursor() as cursor:
            intent = self._intent(cursor, source_id, lock=False)
            activation = self._activation(
                cursor, source_id, lock=False
            )
        return (
            self._record(activation)
            if activation is not None
            else self._synthetic(intent)
        )

    @staticmethod
    def _target(
        action: FuturesFillTriggeredControlAction,
        current: FuturesFillTriggeredActivationRecord,
    ) -> FuturesFillTriggeredControlState:
        if (
            current.trigger_state
            is FuturesFillTriggeredTriggerState.CLAIMED
        ):
            if action is FuturesFillTriggeredControlAction.DRAIN:
                return FuturesFillTriggeredControlState.DRAINING
            raise ValueError(
                "operator_futures_fill_triggered_control_inflight"
            )
        if current.trigger_state.terminal:
            if action is FuturesFillTriggeredControlAction.DRAIN:
                return FuturesFillTriggeredControlState.DRAINED
            raise ValueError(
                "operator_futures_fill_triggered_control_terminal"
            )
        if action is FuturesFillTriggeredControlAction.ENABLE:
            if current.control_state not in {
                FuturesFillTriggeredControlState.DISABLED,
                FuturesFillTriggeredControlState.DRAINED,
            }:
                raise ValueError(
                    "operator_futures_fill_triggered_transition_invalid"
                )
            return FuturesFillTriggeredControlState.ENABLED
        if action is FuturesFillTriggeredControlAction.RESUME:
            if (
                current.control_state
                is not FuturesFillTriggeredControlState.PAUSED
            ):
                raise ValueError(
                    "operator_futures_fill_triggered_transition_invalid"
                )
            return FuturesFillTriggeredControlState.ENABLED
        if action is FuturesFillTriggeredControlAction.PAUSE:
            if (
                current.control_state
                is not FuturesFillTriggeredControlState.ENABLED
            ):
                raise ValueError(
                    "operator_futures_fill_triggered_transition_invalid"
                )
            return FuturesFillTriggeredControlState.PAUSED
        if action is FuturesFillTriggeredControlAction.DISABLE:
            return FuturesFillTriggeredControlState.DISABLED
        if action is FuturesFillTriggeredControlAction.DRAIN:
            return FuturesFillTriggeredControlState.DRAINED
        raise ValueError(
            "operator_futures_fill_triggered_action_invalid"
        )

    def transition_control(
        self,
        *,
        source_client_order_id: str,
        action: FuturesFillTriggeredControlAction,
        expected_revision: int,
        authorize_one_preview_create_and_safe_closeout: bool = False,
        acknowledge_unknown_outcome_consumes_allowance: bool = False,
        acknowledge_child_terms_are_backend_derived: bool = False,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        correlation_id: str,
        audit_id: str,
    ) -> FuturesFillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if (
            not source_id
            or not isinstance(action, FuturesFillTriggeredControlAction)
            or type(expected_revision) is not int
            or expected_revision < 0
            or not str(idempotency_key or "").strip()
            or not str(actor_id or "").strip()
            or not roles
            or not str(correlation_id or "").strip()
        ):
            raise ValueError(
                "operator_futures_fill_triggered_control_invalid"
            )
        normalized_audit = str(uuid.UUID(str(audit_id)))
        delegated = action in {
            FuturesFillTriggeredControlAction.ENABLE,
            FuturesFillTriggeredControlAction.RESUME,
        } and (
            authorize_one_preview_create_and_safe_closeout is True
            and acknowledge_unknown_outcome_consumes_allowance is True
            and acknowledge_child_terms_are_backend_derived is True
        )
        if action in {
            FuturesFillTriggeredControlAction.ENABLE,
            FuturesFillTriggeredControlAction.RESUME,
        } and not delegated:
            raise ValueError(
                "operator_futures_fill_triggered_confirmation_required"
            )
        payload = {
            "goal_id": FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            "source_client_order_id": source_id,
            "action": action.value,
            "expected_revision": expected_revision,
            "delegated_live_authority": delegated,
            "actor_id": actor_id,
            "roles": sorted(set(roles)),
            "correlation_id": correlation_id,
        }
        key_hash = hashlib.sha256(
            str(idempotency_key).encode("utf-8")
        ).hexdigest()
        payload_hash = _sha256(payload)
        now = self.clock()
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(34993, hashtext(%s))",
                (FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,),
            )
            cursor.execute(
                "SELECT pg_advisory_xact_lock(34994, hashtext(%s))",
                (source_id,),
            )
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table(
                    'operator_futures_fill_triggered_control_command'
                )}
                WHERE idempotency_key_sha256 = %s
                """,
                (key_hash,),
            )
            replay = _row(cursor)
            if replay is not None:
                if (
                    str(replay["payload_sha256"]) != payload_hash
                    or str(replay["source_client_order_id"])
                    != source_id
                ):
                    raise ValueError(
                        "operator_futures_fill_triggered_"
                        "idempotency_conflict"
                    )
                replay_snapshot = replay.get("result_json")
                if isinstance(replay_snapshot, str):
                    replay_snapshot = json.loads(replay_snapshot)
                if isinstance(replay_snapshot, Mapping):
                    return self._record(replay_snapshot)
                current = self._activation(
                    cursor, source_id, lock=False
                )
                if (
                    current is None
                    or int(current["revision"])
                    != int(replay["result_revision"])
                ):
                    raise ValueError(
                        "operator_futures_fill_triggered_replay_invalid"
                    )
                return self._record(current)
            intent = self._intent(cursor, source_id, lock=True)
            activation = self._activation(
                cursor, source_id, lock=True
            )
            current = (
                self._record(activation)
                if activation is not None
                else self._synthetic(intent)
            )
            persisted_delegated = (
                current.delegated_live_authority
                if current.trigger_state
                is not FuturesFillTriggeredTriggerState.UNCLAIMED
                else delegated
            )
            if delegated:
                cursor.execute(
                    f"""
                    SELECT source_client_order_id
                    FROM {self._table(
                        'operator_futures_fill_triggered_follow_up'
                    )}
                    WHERE delegated_live_authority IS TRUE
                      AND source_client_order_id <> %s
                    LIMIT 1
                    """,
                    (source_id,),
                )
                if _row(cursor) is not None:
                    raise ValueError(
                        "operator_futures_fill_triggered_"
                        "live_authority_already_delegated"
                    )
            if current.revision != expected_revision:
                raise ValueError(
                    "operator_futures_fill_triggered_revision_conflict"
                )
            target = self._target(action, current)
            result_revision = current.revision + 1
            diagnostic = (
                "operator_futures_fill_triggered_follow_up_"
                f"{target.value.lower()}"
            )
            if activation is None:
                cursor.execute(
                    f"""
                    INSERT INTO {self._table(
                        'operator_futures_fill_triggered_follow_up'
                    )} (
                        source_client_order_id, goal_id,
                        follow_up_intent_id, control_state,
                        trigger_state, revision,
                        delegated_live_authority, diagnostic_code,
                        actor_id, roles_json, correlation_id, audit_id,
                        recorded_at, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, 'UNCLAIMED', %s, %s, %s,
                        %s, %s::jsonb, %s, %s, %s, %s
                    )
                    """,
                    (
                        source_id,
                        FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                        current.follow_up_intent_id,
                        target.value,
                        result_revision,
                        persisted_delegated,
                        diagnostic,
                        actor_id,
                        json.dumps(sorted(set(roles))),
                        correlation_id,
                        normalized_audit,
                        now,
                        now,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._table(
                        'operator_futures_fill_triggered_follow_up'
                    )}
                    SET control_state = %s,
                        revision = %s,
                        delegated_live_authority = %s,
                        diagnostic_code = %s,
                        actor_id = %s,
                        roles_json = %s::jsonb,
                        correlation_id = %s,
                        audit_id = %s,
                        updated_at = %s
                    WHERE source_client_order_id = %s
                      AND revision = %s
                    """,
                    (
                        target.value,
                        result_revision,
                        persisted_delegated,
                        diagnostic,
                        actor_id,
                        json.dumps(sorted(set(roles))),
                        correlation_id,
                        normalized_audit,
                        now,
                        source_id,
                        current.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "operator_futures_fill_triggered_revision_conflict"
                    )
            stored = self._activation(
                cursor, source_id, lock=False
            )
            if stored is None:
                raise ValueError(
                    "operator_futures_fill_triggered_persistence_unknown"
                )
            result_snapshot = dict(stored)
            for timestamp_field in ("recorded_at", "updated_at"):
                result_snapshot[timestamp_field] = _iso(
                    result_snapshot[timestamp_field]
                )
            cursor.execute(
                f"""
                INSERT INTO {self._table(
                    'operator_futures_fill_triggered_control_command'
                )} (
                    command_id, source_client_order_id, action,
                    expected_revision, result_revision,
                    idempotency_key_sha256, payload_sha256, result_json,
                    actor_id, roles_json, correlation_id, audit_id,
                    recorded_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                    %s::jsonb, %s, %s, %s
                )
                """,
                (
                    str(uuid.uuid4()),
                    source_id,
                    action.value,
                    expected_revision,
                    result_revision,
                    key_hash,
                    payload_hash,
                    json.dumps(result_snapshot, default=str),
                    actor_id,
                    json.dumps(sorted(set(roles))),
                    correlation_id,
                    normalized_audit,
                    now,
                ),
            )
            return self._record(stored)

    def _full_fill_evidence(
        self,
        cursor: Any,
        source_id: str,
        intent: Mapping[str, Any],
    ) -> str | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_futures_order_projection')}
            WHERE client_order_id = %s
            FOR UPDATE
            """,
            (source_id,),
        )
        projection = _row(cursor)
        if projection is None:
            return None
        try:
            size = _decimal(projection.get("size"))
            filled = _decimal(projection.get("filled_size"))
        except ValueError:
            return None
        if (
            str(projection.get("status") or "").upper() != "FILLED"
            or size != Decimal("1")
            or filled != size
            or projection.get("authoritatively_nonterminal") is True
            or projection.get("cancel_eligible") is True
            or str(projection.get("product_id") or "")
            != str(intent.get("product_id") or "")
            or str(projection.get("side") or "").upper()
            != str(intent.get("source_side") or "").upper()
            or not _SHA256_RE.fullmatch(
                str(
                    projection.get("exchange_order_id_sha256")
                    or ""
                )
            )
        ):
            return None
        return _sha256(
            {
                "goal_id": FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                "follow_up_intent_id": str(
                    intent["follow_up_intent_id"]
                ),
                "source_client_order_id": source_id,
                "root_client_order_id": str(
                    intent["root_client_order_id"]
                ),
                "product_id": str(projection["product_id"]),
                "side": str(projection["side"]),
                "status": "FILLED",
                "size": "1",
                "filled_size": "1",
                "exchange_order_id_sha256": str(
                    projection["exchange_order_id_sha256"]
                ),
                "observed_at": _iso(projection["observed_at"]),
            }
        )

    def claim_full_fill_trigger(
        self, *, source_client_order_id: str
    ) -> FuturesFillTriggeredActivationRecord | None:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        if not source_id:
            raise ValueError(
                "operator_futures_fill_triggered_source_invalid"
            )
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(34995, hashtext(%s))",
                (source_id,),
            )
            try:
                intent = self._intent(cursor, source_id, lock=True)
            except ValueError as exc:
                if (
                    len(exc.args) == 1
                    and exc.args[0]
                    == "operator_futures_fill_triggered_intent_not_attached"
                ):
                    return None
                raise
            activation = self._activation(
                cursor, source_id, lock=True
            )
            if activation is None:
                return None
            current = self._record(activation)
            if (
                current.control_state
                is not FuturesFillTriggeredControlState.ENABLED
                or current.delegated_live_authority is not True
                or current.trigger_state
                is not FuturesFillTriggeredTriggerState.UNCLAIMED
            ):
                return None
            evidence_hash = self._full_fill_evidence(
                cursor, source_id, intent
            )
            if evidence_hash is None:
                return None
            claim_id = str(uuid.uuid4())
            cursor.execute(
                f"""
                UPDATE {self._table(
                    'operator_futures_fill_triggered_follow_up'
                )}
                SET trigger_state = 'CLAIMED',
                    trigger_claim_id = %s,
                    trigger_evidence_sha256 = %s,
                    diagnostic_code =
                        'operator_futures_fill_triggered_claimed',
                    updated_at = %s
                WHERE source_client_order_id = %s
                  AND control_state = 'ENABLED'
                  AND delegated_live_authority IS TRUE
                  AND trigger_state = 'UNCLAIMED'
                """,
                (claim_id, evidence_hash, self.clock(), source_id),
            )
            if cursor.rowcount != 1:
                return None
            stored = self._activation(
                cursor, source_id, lock=False
            )
            if stored is None:
                raise ValueError(
                    "operator_futures_fill_triggered_claim_unknown"
                )
            return self._record(stored)

    def read_intent(
        self, source_client_order_id: str
    ) -> dict[str, Any]:
        self.ensure_schema()
        with self._cursor() as cursor:
            return self._intent(
                cursor,
                str(source_client_order_id or "").strip(),
                lock=False,
            )

    def list_claimed(
        self,
    ) -> tuple[FuturesFillTriggeredActivationRecord, ...]:
        """Return the sole in-flight Goal 5 claim without mutating state."""

        self.ensure_schema()
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table(
                    'operator_futures_fill_triggered_follow_up'
                )}
                WHERE trigger_state = 'CLAIMED'
                ORDER BY recorded_at ASC
                """
            )
            rows: list[dict[str, Any]] = []
            while (row := _row(cursor)) is not None:
                rows.append(row)
        return tuple(self._record(row) for row in rows)

    def finalize_trigger(
        self,
        *,
        source_client_order_id: str,
        trigger_claim_id: str | None,
        trigger_state: FuturesFillTriggeredTriggerState,
        lifecycle: FuturesManualGoalRecord | None,
        diagnostic_code: str,
    ) -> FuturesFillTriggeredActivationRecord:
        self.ensure_schema()
        source_id = str(source_client_order_id or "").strip()
        claim_id = str(uuid.UUID(str(trigger_claim_id)))
        if trigger_state not in {
            FuturesFillTriggeredTriggerState.COMPLETED,
            FuturesFillTriggeredTriggerState.BLOCKED,
            FuturesFillTriggeredTriggerState.UNKNOWN,
        }:
            raise ValueError(
                "operator_futures_fill_triggered_terminal_invalid"
            )
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(34995, hashtext(%s))",
                (source_id,),
            )
            activation = self._activation(
                cursor, source_id, lock=True
            )
            if activation is None:
                raise ValueError(
                    "operator_futures_fill_triggered_not_found"
                )
            current = self._record(activation)
            if current.trigger_state.terminal:
                if (
                    current.trigger_claim_id == claim_id
                    and current.trigger_state is trigger_state
                ):
                    return current
                raise ValueError(
                    "operator_futures_fill_triggered_terminal_conflict"
                )
            if (
                current.trigger_state
                is not FuturesFillTriggeredTriggerState.CLAIMED
                or current.trigger_claim_id != claim_id
            ):
                raise ValueError(
                    "operator_futures_fill_triggered_claim_conflict"
                )
            target_control = (
                FuturesFillTriggeredControlState.DRAINED
                if current.control_state
                is FuturesFillTriggeredControlState.DRAINING
                else current.control_state
            )
            cursor.execute(
                f"""
                UPDATE {self._table(
                    'operator_futures_fill_triggered_follow_up'
                )}
                SET trigger_state = %s,
                    control_state = %s,
                    lifecycle_revision = %s,
                    child_client_order_id = %s,
                    preview_outcome = %s,
                    create_outcome = %s,
                    reconciliation_outcome = %s,
                    cancel_outcome = %s,
                    diagnostic_code = %s,
                    updated_at = %s
                WHERE source_client_order_id = %s
                  AND trigger_state = 'CLAIMED'
                  AND trigger_claim_id = %s
                """,
                (
                    trigger_state.value,
                    target_control.value,
                    lifecycle.revision if lifecycle else 0,
                    lifecycle.client_order_id if lifecycle else None,
                    (
                        lifecycle.preview_outcome.value
                        if lifecycle
                        else "NOT_RUN"
                    ),
                    (
                        lifecycle.create_outcome.value
                        if lifecycle
                        else "NOT_RUN"
                    ),
                    (
                        lifecycle.reconciliation_outcome.value
                        if lifecycle
                        else "NOT_RUN"
                    ),
                    (
                        lifecycle.cancel_outcome.value
                        if lifecycle
                        else "NOT_RUN"
                    ),
                    diagnostic_code,
                    self.clock(),
                    source_id,
                    claim_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_futures_fill_triggered_terminal_unknown"
                )
            stored = self._activation(
                cursor, source_id, lock=False
            )
            if stored is None:
                raise ValueError(
                    "operator_futures_fill_triggered_terminal_unknown"
                )
            return self._record(stored)


_DEFAULT_REPOSITORY: (
    OperatorFuturesFillTriggeredFollowUpRepository | None
) = None
_DEFAULT_LOCK = threading.Lock()


def get_default_operator_futures_fill_triggered_follow_up_repository(
) -> OperatorFuturesFillTriggeredFollowUpRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_REPOSITORY is None:
                from database import order as order_db
                from database.operator_futures_follow_up_intent import (
                    get_default_operator_futures_follow_up_intent_repository,
                )

                get_default_operator_futures_follow_up_intent_repository()
                _DEFAULT_REPOSITORY = (
                    OperatorFuturesFillTriggeredFollowUpRepository(
                        order_db.DB_CLIENT
                    )
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def reset_operator_futures_fill_triggered_follow_up_repository_for_tests(
) -> None:
    global _DEFAULT_REPOSITORY
    with _DEFAULT_LOCK:
        _DEFAULT_REPOSITORY = None


__all__ = [
    "OperatorFuturesFillTriggeredFollowUpRepository",
    "get_default_operator_futures_fill_triggered_follow_up_repository",
    "reset_operator_futures_fill_triggered_follow_up_repository_for_tests",
]
