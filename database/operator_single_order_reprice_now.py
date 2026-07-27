"""PostgreSQL ledger for one call-free Goal 15 Reprice Now intent."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Mapping
from uuid import UUID, uuid4

from psycopg2.extras import Json

from database.database import PostgresDB


GOAL_ID = "operator_single_order_reprice_now_v1"
MAX_CYCLES = 10
_LOCK_NAMESPACE = 47615
_PROCESS_PREPARE_LOCK = threading.RLock()
_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_DIAGNOSTIC = re.compile(r"^operator_reprice_now_[a-z0-9_]{1,75}$")
_INTENT_KEYS = frozenset(
    {
        "goal_id",
        "policy_revision",
        "stealth_order_id",
        "source_client_order_id",
        "reserved_successor_client_order_id",
        "root_client_order_id",
        "definition_revision",
        "definition_sha256",
        "source_evidence_sha256",
        "source_status",
        "zero_fill_proven",
        "system_owned",
        "direct_parent",
        "intent_sha256",
    }
)
_SELECTION_KEYS = frozenset(
    {
        "stealth_order_id",
        "source_client_order_id",
        "found",
        "eligible",
        "diagnostic_code",
        "definition_revision",
        "definition_sha256",
        "root_client_order_id",
        "source_status",
        "zero_fill_proven",
        "system_owned",
        "direct_parent",
        "source_evidence_sha256",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "body",
        "exception",
        "exception_message",
        "exchange_order_id",
        "exchange_order_id_sha256",
        "message",
        "portfolio_id",
        "preview_id",
        "private_identifier",
        "raw",
        "raw_response",
        "response",
        "response_body",
        "secret",
    }
)


class OperatorSingleOrderRepriceNowError(ValueError):
    """Fixed, value-blind Goal 15 repository rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OperatorSingleOrderRepriceNowConflict(
    OperatorSingleOrderRepriceNowError
):
    """Durable Goal 15 identity or idempotency conflict."""


class OperatorSingleOrderRepriceNowRepository:
    """One immutable intent plus append-only cycle/event evidence."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
    ) -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.prefix = f'"{schema}".'

    def ensure_schema(self) -> None:
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_single_order_reprice_now_goal (
                    goal_id TEXT PRIMARY KEY CHECK (
                        goal_id = '{GOAL_ID}'
                    ),
                    state TEXT NOT NULL CHECK (
                        state = 'INTENT_PREPARED'
                    ),
                    stealth_order_id UUID NOT NULL UNIQUE,
                    source_client_order_id UUID NOT NULL UNIQUE,
                    reserved_successor_client_order_id UUID NOT NULL UNIQUE,
                    intent_json JSONB NOT NULL,
                    intent_sha256 CHAR(64) NOT NULL CHECK (
                        intent_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    source_selection_json JSONB NOT NULL,
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_reprice_now_[a-z0-9_]{{1,75}}$'
                    ),
                    local_cycles_used INTEGER NOT NULL CHECK (
                        local_cycles_used BETWEEN 1 AND {MAX_CYCLES}
                    ),
                    market_terms_bound BOOLEAN NOT NULL DEFAULT FALSE CHECK (
                        NOT market_terms_bound
                    ),
                    cap_policy_bound BOOLEAN NOT NULL DEFAULT FALSE CHECK (
                        NOT cap_policy_bound
                    ),
                    live_authority_terms_complete BOOLEAN NOT NULL
                        DEFAULT FALSE CHECK (
                            NOT live_authority_terms_complete
                        ),
                    source_cancel_allowance_consumed BOOLEAN NOT NULL
                        DEFAULT FALSE CHECK (
                            NOT source_cancel_allowance_consumed
                        ),
                    source_cancel_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        source_cancel_call_count = 0
                    ),
                    replacement_create_allowance_consumed BOOLEAN NOT NULL
                        DEFAULT FALSE CHECK (
                            NOT replacement_create_allowance_consumed
                        ),
                    replacement_create_call_count INTEGER NOT NULL
                        DEFAULT 0 CHECK (
                            replacement_create_call_count = 0
                        ),
                    total_exchange_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        total_exchange_call_count = 0
                    ),
                    actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    correlation_id TEXT NOT NULL CHECK (
                        correlation_id ~
                            '^[A-Za-z0-9._:@|/-]{{1,255}}$'
                    ),
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE CHECK (
                        idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    operator_reason_sha256 CHAR(64) NOT NULL CHECK (
                        operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_single_order_reprice_now_cycle (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_single_order_reprice_now_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    cycle_number INTEGER NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND {MAX_CYCLES}
                    ),
                    phase TEXT NOT NULL CHECK (phase = 'PREPARE'),
                    completion_status TEXT NOT NULL CHECK (
                        completion_status = 'COMPLETED'
                    ),
                    actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    correlation_id TEXT NOT NULL CHECK (
                        correlation_id ~
                            '^[A-Za-z0-9._:@|/-]{{1,255}}$'
                    ),
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE CHECK (
                        idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    evidence_sha256 CHAR(64) NOT NULL CHECK (
                        evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (goal_id, cycle_number)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_single_order_reprice_now_event (
                    event_id UUID PRIMARY KEY,
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_single_order_reprice_now_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    event_type TEXT NOT NULL CHECK (
                        event_type = 'REPRICE_NOW_INTENT_PREPARED'
                    ),
                    cycle_number INTEGER NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND {MAX_CYCLES}
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_reprice_now_[a-z0-9_]{{1,75}}$'
                    ),
                    correlation_id TEXT NOT NULL CHECK (
                        correlation_id ~
                            '^[A-Za-z0-9._:@|/-]{{1,255}}$'
                    ),
                    evidence_sha256 CHAR(64) NOT NULL CHECK (
                        evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION
                    {self.prefix}operator_single_order_reprice_now_reject_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $operator_reprice_now_immutable$
                BEGIN
                    RAISE EXCEPTION
                        'operator_reprice_now_immutable_ledger'
                        USING ERRCODE = 'P0001';
                END;
                $operator_reprice_now_immutable$
                """
            )
            for table_suffix in ("goal", "cycle", "event"):
                table = (
                    f"{self.prefix}operator_single_order_reprice_now_"
                    f"{table_suffix}"
                )
                row_trigger = (
                    "operator_single_order_reprice_now_"
                    f"{table_suffix}_immutable_row"
                )
                truncate_trigger = (
                    "operator_single_order_reprice_now_"
                    f"{table_suffix}_immutable_truncate"
                )
                cursor.execute(
                    f"DROP TRIGGER IF EXISTS {row_trigger} ON {table}"
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER {row_trigger}
                    BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW
                    EXECUTE FUNCTION
                        {self.prefix}operator_single_order_reprice_now_reject_mutation()
                    """
                )
                cursor.execute(
                    f"DROP TRIGGER IF EXISTS {truncate_trigger} ON {table}"
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER {truncate_trigger}
                    BEFORE TRUNCATE ON {table}
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION
                        {self.prefix}operator_single_order_reprice_now_reject_mutation()
                    """
                )

    @contextmanager
    def prepare_lock(self):
        """Serialize replay, local source resolution, and first persistence.

        The process lock prevents same-connection session-lock reentrancy from
        allowing another local thread through. The PostgreSQL session advisory
        lock extends the same boundary across installed worker processes.
        """

        with _PROCESS_PREPARE_LOCK:
            with self.database.get_cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_lock(%s)",
                    (_LOCK_NAMESPACE,),
                )
            try:
                yield
            finally:
                with self.database.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (_LOCK_NAMESPACE,),
                    )
                    rows = _rows(cursor)
                    if not rows or rows[0].get("pg_advisory_unlock") is not True:
                        raise OperatorSingleOrderRepriceNowError(
                            "operator_reprice_now_prepare_lock_failed"
                        )

    def get_intent(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
    ) -> dict[str, Any] | None:
        _canonical_v4(
            stealth_order_id,
            code="operator_reprice_now_source_identity_invalid",
        )
        _canonical_v4(
            source_client_order_id,
            code="operator_reprice_now_source_identity_invalid",
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_single_order_reprice_now_goal
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            row = rows[0]
            if (
                str(row["stealth_order_id"]) != stealth_order_id
                or str(row["source_client_order_id"])
                != source_client_order_id
            ):
                return {
                    "goal_bound_elsewhere": True,
                    "local_cycles_used": int(
                        row["local_cycles_used"]
                    ),
                }
            return self._project(cursor, row)

    def goal_is_bound(self) -> bool:
        """Return only the goal-global allowance state, never its identity."""

        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM
                        {self.prefix}operator_single_order_reprice_now_goal
                    WHERE goal_id = %s
                ) AS goal_is_bound
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            return bool(rows and rows[0]["goal_is_bound"] is True)

    def get_intent_replay(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        self._require_command(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_single_order_reprice_now_goal
                WHERE goal_id = %s
                  AND idempotency_key_sha256 = %s
                """,
                (GOAL_ID, idempotency_hash),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            row = rows[0]
            if (
                str(row["stealth_order_id"]) != stealth_order_id
                or str(row["source_client_order_id"])
                != source_client_order_id
                or row["actor_id_sha256"] != actor_hash
                or row["correlation_id"] != correlation_id
                or row["payload_sha256"] != payload_sha256
            ):
                raise OperatorSingleOrderRepriceNowConflict(
                    "operator_reprice_now_idempotency_conflict"
                )
            return self._project(
                cursor,
                row,
                command_replayed=True,
            )

    def create_intent(
        self,
        *,
        intent: Mapping[str, Any],
        source_selection: Mapping[str, Any],
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
        operator_reason_sha256: str,
    ) -> dict[str, Any]:
        self._require_command(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        self._require_intent(intent, source_selection)
        if _SHA256.fullmatch(operator_reason_sha256) is None:
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_reason_evidence_invalid"
            )
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        intent_json = dict(intent)
        intent_sha256 = str(intent_json["intent_sha256"])
        cycle_evidence = _hash_payload(
            {
                "goal_id": GOAL_ID,
                "cycle_number": 1,
                "phase": "PREPARE",
                "stealth_order_id": intent_json["stealth_order_id"],
                "source_client_order_id": intent_json[
                    "source_client_order_id"
                ],
                "reserved_successor_client_order_id": intent_json[
                    "reserved_successor_client_order_id"
                ],
                "intent_sha256": intent_sha256,
                "payload_sha256": payload_sha256,
                "correlation_id": correlation_id,
            }
        )
        event_id = str(uuid4())
        with self.database.get_cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_LOCK_NAMESPACE,),
            )
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_single_order_reprice_now_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            existing = _rows(cursor)
            if existing:
                row = existing[0]
                exact_replay = bool(
                    str(row["stealth_order_id"])
                    == str(intent_json["stealth_order_id"])
                    and str(row["source_client_order_id"])
                    == str(intent_json["source_client_order_id"])
                    and str(row["reserved_successor_client_order_id"])
                    == str(
                        intent_json[
                            "reserved_successor_client_order_id"
                        ]
                    )
                    and dict(row["intent_json"]) == intent_json
                    and dict(row["source_selection_json"])
                    == dict(source_selection)
                    and row["intent_sha256"] == intent_sha256
                    and row["actor_id_sha256"] == actor_hash
                    and row["correlation_id"] == correlation_id
                    and row["idempotency_key_sha256"]
                    == idempotency_hash
                    and row["payload_sha256"] == payload_sha256
                    and row["operator_reason_sha256"]
                    == operator_reason_sha256
                )
                if exact_replay:
                    return self._project(
                        cursor,
                        row,
                        command_replayed=True,
                    )
                raise OperatorSingleOrderRepriceNowConflict(
                    "operator_reprice_now_goal_already_bound"
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_single_order_reprice_now_goal (
                        goal_id, state, stealth_order_id,
                        source_client_order_id,
                        reserved_successor_client_order_id,
                        intent_json, intent_sha256,
                        source_selection_json, diagnostic_code,
                        local_cycles_used, actor_id_sha256,
                        correlation_id, idempotency_key_sha256,
                        payload_sha256, operator_reason_sha256
                    )
                VALUES (
                    %s, 'INTENT_PREPARED', %s::uuid, %s::uuid, %s::uuid,
                    %s, %s, %s, %s, 1, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    GOAL_ID,
                    intent_json["stealth_order_id"],
                    intent_json["source_client_order_id"],
                    intent_json["reserved_successor_client_order_id"],
                    Json(intent_json),
                    intent_sha256,
                    Json(dict(source_selection)),
                    "operator_reprice_now_intent_prepared",
                    actor_hash,
                    correlation_id,
                    idempotency_hash,
                    payload_sha256,
                    operator_reason_sha256,
                ),
            )
            row = _one(
                cursor,
                "operator_reprice_now_persistence_failed",
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_single_order_reprice_now_cycle (
                        goal_id, cycle_number, phase, completion_status,
                        actor_id_sha256, correlation_id,
                        idempotency_key_sha256, payload_sha256,
                        evidence_sha256
                    )
                VALUES (
                    %s, 1, 'PREPARE', 'COMPLETED',
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    GOAL_ID,
                    actor_hash,
                    correlation_id,
                    idempotency_hash,
                    payload_sha256,
                    cycle_evidence,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_single_order_reprice_now_event (
                        event_id, goal_id, event_type, cycle_number,
                        diagnostic_code, correlation_id, evidence_sha256
                    )
                VALUES (
                    %s::uuid, %s, 'REPRICE_NOW_INTENT_PREPARED', 1,
                    %s, %s, %s
                )
                """,
                (
                    event_id,
                    GOAL_ID,
                    "operator_reprice_now_intent_prepared",
                    correlation_id,
                    cycle_evidence,
                ),
            )
            return self._project(cursor, row)

    def _project(
        self,
        cursor: Any,
        row: Mapping[str, Any],
        *,
        command_replayed: bool = False,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT event_id, event_type, cycle_number, diagnostic_code,
                   correlation_id, evidence_sha256, recorded_at
            FROM {self.prefix}operator_single_order_reprice_now_event
            WHERE goal_id = %s
            ORDER BY cycle_number, recorded_at, event_id
            """,
            (GOAL_ID,),
        )
        events = [
            {
                **event,
                "event_id": str(event["event_id"]),
            }
            for event in _rows(cursor)
        ]
        intent = dict(row["intent_json"])
        return {
            "state": row["state"],
            "diagnostic_code": row["diagnostic_code"],
            "intent": intent,
            "intent_sha256": row["intent_sha256"],
            "source_selection": dict(row["source_selection_json"]),
            "local_cycles_used": row["local_cycles_used"],
            "latest_cycle_idempotency_key_sha256": row[
                "idempotency_key_sha256"
            ],
            "latest_cycle_payload_sha256": row["payload_sha256"],
            "latest_cycle_actor_id_sha256": row["actor_id_sha256"],
            "latest_cycle_evidence_sha256": (
                events[-1]["evidence_sha256"] if events else None
            ),
            "events": events,
            "correlation_id": row["correlation_id"],
            "command_replayed": command_replayed,
        }

    @staticmethod
    def _require_command(
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> None:
        if any(
            _EVIDENCE_ID.fullmatch(str(value or "")) is None
            for value in (actor_id, correlation_id, idempotency_key)
        ) or _SHA256.fullmatch(payload_sha256) is None:
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_command_identity_invalid"
            )

    @staticmethod
    def _require_intent(
        intent: Mapping[str, Any],
        source_selection: Mapping[str, Any],
    ) -> None:
        if (
            set(intent) != _INTENT_KEYS
            or set(source_selection) != _SELECTION_KEYS
            or _contains_forbidden_key(intent)
            or _contains_forbidden_key(source_selection)
        ):
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_persistence_payload_invalid"
            )
        intent_payload = dict(intent)
        intent_sha256 = str(intent_payload.pop("intent_sha256", ""))
        if (
            intent.get("goal_id") != GOAL_ID
            or intent.get("policy_revision")
            != "SINGLE_ORDER_REPRICE_NOW_INTENT_V1"
            or _SHA256.fullmatch(intent_sha256) is None
            or intent_sha256 != _hash_payload(intent_payload)
            or intent.get("stealth_order_id")
            != source_selection.get("stealth_order_id")
            or intent.get("source_client_order_id")
            != source_selection.get("source_client_order_id")
            or intent.get("source_evidence_sha256")
            != source_selection.get("source_evidence_sha256")
            or source_selection.get("eligible") is not True
            or source_selection.get("diagnostic_code")
            != "operator_reprice_now_source_eligible"
        ):
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_persistence_payload_invalid"
            )
        _canonical_v4(
            str(intent["stealth_order_id"]),
            code="operator_reprice_now_source_identity_invalid",
        )
        _canonical_v4(
            str(intent["source_client_order_id"]),
            code="operator_reprice_now_source_identity_invalid",
        )
        _canonical_v5(
            str(intent["reserved_successor_client_order_id"]),
            code="operator_reprice_now_successor_identity_invalid",
        )


def _canonical_v4(value: str, *, code: str) -> str:
    return _canonical_uuid(value, version=4, code=code)


def _canonical_v5(value: str, *, code: str) -> str:
    return _canonical_uuid(value, version=5, code=code)


def _canonical_uuid(value: str, *, version: int, code: str) -> str:
    try:
        parsed = UUID(str(value or "").strip())
    except (AttributeError, TypeError, ValueError):
        raise OperatorSingleOrderRepriceNowError(code) from None
    canonical = str(parsed)
    if canonical != str(value or "").strip() or parsed.version != version:
        raise OperatorSingleOrderRepriceNowError(code)
    return canonical


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if (
                normalized in _FORBIDDEN_KEYS
                or "exchange_order_id" in normalized
                or _contains_forbidden_key(item)
            ):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorSingleOrderRepriceNowConflict(code)
    return rows[0]


@lru_cache(maxsize=1)
def get_default_operator_single_order_reprice_now_repository(
) -> OperatorSingleOrderRepriceNowRepository:
    repository = OperatorSingleOrderRepriceNowRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def initialize_operator_single_order_reprice_now_schema() -> None:
    get_default_operator_single_order_reprice_now_repository().ensure_schema()


__all__ = [
    "GOAL_ID",
    "MAX_CYCLES",
    "OperatorSingleOrderRepriceNowConflict",
    "OperatorSingleOrderRepriceNowError",
    "OperatorSingleOrderRepriceNowRepository",
    "get_default_operator_single_order_reprice_now_repository",
    "initialize_operator_single_order_reprice_now_schema",
]
