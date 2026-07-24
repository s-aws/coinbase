"""PostgreSQL authority for one reviewed revealed-order movement."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from typing import Any, Mapping

from psycopg2.extras import Json

from application.admin_api.operator_revealed_order_movement_service import (
    GOAL_ID,
    OperatorRevealedOrderMovementConflict,
    OperatorRevealedOrderMovementError,
)
from database.database import PostgresDB


_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_DIAGNOSTIC = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_READ_CATEGORIES = frozenset(
    {
        "SOURCE_PRE_CANCEL",
        "SOURCE_POST_CANCEL",
        "WALLET_PRE_CREATE",
        "REPLACEMENT_POST_CREATE",
    }
)
_READ_RESULTS = frozenset(
    {
        "OPEN",
        "PENDING",
        "CANCEL_QUEUED",
        "CANCELLED",
        "FILLED",
        "RETURNED",
        "UNKNOWN",
    }
)


class OperatorRevealedOrderMovementRepository:
    """One non-transferable goal, ten cycles, and two ordered calls."""

    def __init__(self, database: PostgresDB, *, schema: str = "public") -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorRevealedOrderMovementError(
                "operator_move_schema_invalid"
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
                    {self.prefix}operator_revealed_order_movement_goal (
                    goal_id TEXT PRIMARY KEY CHECK (
                        goal_id =
                        'operator_revealed_order_movement_and_repricing_v1'
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'PLANNED', 'CANCEL_CLAIMED',
                            'SOURCE_CANCELLED', 'SOURCE_FILLED',
                            'CANCEL_REJECTED', 'CANCEL_UNKNOWN',
                            'CREATE_CLAIMED', 'REPLACED',
                            'CREATE_REJECTED', 'CREATE_UNKNOWN'
                        )
                    ),
                    stealth_order_id UUID NOT NULL UNIQUE,
                    plan_json JSONB NOT NULL,
                    plan_sha256 CHAR(64) NOT NULL CHECK (
                        plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    source_client_order_id UUID NOT NULL,
                    replacement_client_order_id UUID NOT NULL UNIQUE,
                    source_exchange_order_id_sha256 CHAR(64) NOT NULL CHECK (
                        source_exchange_order_id_sha256
                            ~ '^[0-9a-f]{{64}}$'
                    ),
                    replacement_exchange_order_id_sha256 CHAR(64) CHECK (
                        replacement_exchange_order_id_sha256 IS NULL OR
                        replacement_exchange_order_id_sha256
                            ~ '^[0-9a-f]{{64}}$'
                    ),
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    create_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        cancel_call_count BETWEEN 0 AND 1
                    ),
                    create_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        create_call_count BETWEEN 0 AND 1
                    ),
                    read_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        read_call_count BETWEEN 0 AND 30
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~ '^[a-z][a-z0-9_]{{0,95}}$'
                    ),
                    plan_actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        plan_actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    plan_correlation_id TEXT NOT NULL,
                    plan_idempotency_key TEXT NOT NULL UNIQUE,
                    plan_payload_sha256 CHAR(64) NOT NULL CHECK (
                        plan_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    execute_actor_id_sha256 CHAR(64),
                    execute_correlation_id TEXT,
                    execute_idempotency_key TEXT UNIQUE,
                    execute_payload_sha256 CHAR(64) CHECK (
                        execute_payload_sha256 IS NULL OR
                        execute_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_revealed_order_movement_cycle (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_revealed_order_movement_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    cycle_number INTEGER NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND 10
                    ),
                    phase TEXT NOT NULL CHECK (
                        phase IN ('PLAN', 'EXECUTE')
                    ),
                    completion_status TEXT NOT NULL CHECK (
                        completion_status IN ('IN_FLIGHT', 'COMPLETED')
                    ),
                    actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    correlation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    terminal_goal_state TEXT,
                    terminal_diagnostic_code TEXT,
                    cancel_call_count INTEGER,
                    create_call_count INTEGER,
                    read_call_count INTEGER,
                    evidence_sha256 CHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    PRIMARY KEY (goal_id, cycle_number)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_revealed_order_movement_read_call (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_revealed_order_movement_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    category TEXT NOT NULL CHECK (
                        category IN (
                            'SOURCE_PRE_CANCEL',
                            'SOURCE_POST_CANCEL',
                            'WALLET_PRE_CREATE',
                            'REPLACEMENT_POST_CREATE'
                        )
                    ),
                    correlation_id TEXT NOT NULL,
                    call_state TEXT NOT NULL CHECK (
                        call_state IN ('STARTED', 'RETURNED', 'UNKNOWN')
                    ),
                    result_code TEXT CHECK (
                        result_code IS NULL OR
                        result_code IN (
                            'OPEN', 'PENDING', 'CANCEL_QUEUED',
                            'CANCELLED', 'FILLED', 'RETURNED', 'UNKNOWN'
                        )
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (goal_id, category, correlation_id)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_revealed_order_movement_read_call
                DROP CONSTRAINT IF EXISTS
                    operator_revealed_order_movement_read_call_category_check,
                DROP CONSTRAINT IF EXISTS
                    operator_revealed_order_movement_read_call_result_code_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_revealed_order_movement_read_call
                ADD CONSTRAINT
                    operator_revealed_order_movement_read_call_category_check
                    CHECK (
                        category IN (
                            'SOURCE_PRE_CANCEL',
                            'SOURCE_POST_CANCEL',
                            'WALLET_PRE_CREATE',
                            'REPLACEMENT_POST_CREATE'
                        )
                    ),
                ADD CONSTRAINT
                    operator_revealed_order_movement_read_call_result_code_check
                    CHECK (
                        result_code IS NULL OR
                        result_code IN (
                            'OPEN', 'PENDING', 'CANCEL_QUEUED',
                            'CANCELLED', 'FILLED', 'RETURNED', 'UNKNOWN'
                        )
                    )
                """
            )
            self._recover_interrupted(cursor)

    def get_goal(self, stealth_order_id: str) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_goal
                WHERE goal_id = %s AND stealth_order_id = %s::uuid
                """,
                (GOAL_ID, stealth_order_id),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            return self._project(cursor, rows[0])

    def replay_plan(
        self,
        *,
        stealth_order_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_goal
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            row = rows[0]
            if row["plan_idempotency_key"] != idempotency_key:
                return None
            if (
                str(row["stealth_order_id"]) != stealth_order_id
                or row["plan_payload_sha256"] != payload_sha256
            ):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_plan_idempotency_conflict"
                )
            return self._project(cursor, row, command_replayed=True)

    def replay_execute(
        self,
        *,
        stealth_order_id: str,
        expected_plan_sha256: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s AND idempotency_key = %s
                """,
                (GOAL_ID, idempotency_key),
            )
            cycles = _rows(cursor)
            if not cycles:
                return None
            cycle = cycles[0]
            row = self._locked_goal(cursor, stealth_order_id)
            if (
                cycle["phase"] != "EXECUTE"
                or cycle["correlation_id"] != correlation_id
                or cycle["payload_sha256"] != payload_sha256
                or row["plan_sha256"] != expected_plan_sha256
            ):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_execute_idempotency_conflict"
                )
            return self._project(
                cursor,
                row,
                command_replayed=True,
                cycle=cycle,
            )

    def create_plan(
        self,
        *,
        plan: Mapping[str, Any],
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        self._require_plan(plan)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            if rows:
                row = rows[0]
                if (
                    str(row["stealth_order_id"])
                    == str(plan["stealth_order_id"])
                    and row["plan_idempotency_key"] == idempotency_key
                    and row["plan_payload_sha256"] == payload_sha256
                    and row["plan_sha256"] == plan["plan_sha256"]
                ):
                    return self._project(
                        cursor, row, command_replayed=True
                    )
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_goal_allowance_unavailable"
                )
            actor_hash = _sha(actor_id)
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_revealed_order_movement_goal (
                    goal_id, state, stealth_order_id, plan_json,
                    plan_sha256, source_client_order_id,
                    replacement_client_order_id,
                    source_exchange_order_id_sha256,
                    diagnostic_code, plan_actor_id_sha256,
                    plan_correlation_id, plan_idempotency_key,
                    plan_payload_sha256
                ) VALUES (
                    %s, 'PLANNED', %s::uuid, %s, %s,
                    %s::uuid, %s::uuid, %s,
                    'operator_move_plan_ready', %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    GOAL_ID,
                    plan["stealth_order_id"],
                    Json(dict(plan)),
                    plan["plan_sha256"],
                    plan["source_client_order_id"],
                    plan["replacement_client_order_id"],
                    plan["source_exchange_order_id_sha256"],
                    actor_hash,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                ),
            )
            row = _one(cursor, "operator_move_goal_insert_failed")
            evidence = self._cycle_evidence(
                phase="PLAN",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                state="PLANNED",
                diagnostic_code="operator_move_plan_ready",
                cancel_call_count=0,
                create_call_count=0,
                read_call_count=0,
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_revealed_order_movement_cycle (
                    goal_id, cycle_number, phase, completion_status,
                    actor_id_sha256, correlation_id, idempotency_key,
                    payload_sha256, terminal_goal_state,
                    terminal_diagnostic_code, cancel_call_count,
                    create_call_count, read_call_count, evidence_sha256,
                    completed_at
                ) VALUES (
                    %s, 1, 'PLAN', 'COMPLETED', %s, %s, %s, %s,
                    'PLANNED', 'operator_move_plan_ready', 0, 0, 0,
                    %s, NOW()
                )
                """,
                (
                    GOAL_ID,
                    actor_hash,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                    evidence,
                ),
            )
            return self._project(cursor, row)

    def begin_execute(
        self,
        *,
        stealth_order_id: str,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            if row["plan_sha256"] != expected_plan_sha256:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_plan_binding_conflict"
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (GOAL_ID, idempotency_key),
            )
            cycles = _rows(cursor)
            if cycles:
                cycle = cycles[0]
                if (
                    cycle["phase"] == "EXECUTE"
                    and cycle["correlation_id"] == correlation_id
                    and cycle["payload_sha256"] == payload_sha256
                ):
                    return self._project(
                        cursor,
                        row,
                        command_replayed=True,
                        cycle=cycle,
                    )
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_execute_idempotency_conflict"
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s AND completion_status = 'IN_FLIGHT'
                LIMIT 1
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            if _rows(cursor):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_execute_in_flight"
                )
            if row["state"] not in {"PLANNED", "SOURCE_CANCELLED"}:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_execute_not_available"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            cycle_number = int(cursor.fetchone()[0]) + 1
            if cycle_number > 10:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_cycle_allowance_unavailable"
                )
            actor_hash = _sha(actor_id)
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_revealed_order_movement_cycle (
                    goal_id, cycle_number, phase, completion_status,
                    actor_id_sha256, correlation_id, idempotency_key,
                    payload_sha256
                ) VALUES (
                    %s, %s, 'EXECUTE', 'IN_FLIGHT',
                    %s, %s, %s, %s
                )
                """,
                (
                    GOAL_ID,
                    cycle_number,
                    actor_hash,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                ),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_goal
                SET execute_actor_id_sha256 = %s,
                    execute_correlation_id = %s,
                    execute_idempotency_key = %s,
                    execute_payload_sha256 = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (
                    actor_hash,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                    GOAL_ID,
                ),
            )
            return self._project(
                cursor,
                _one(cursor, "operator_move_goal_missing"),
            )

    def claim_read(
        self,
        *,
        stealth_order_id: str,
        category: str,
        correlation_id: str,
    ) -> None:
        self._require_read_identity(category, correlation_id)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            self._require_active_execute_cycle(cursor, correlation_id)
            cursor.execute(
                f"""
                SELECT call_state
                FROM {self.prefix}operator_revealed_order_movement_read_call
                WHERE goal_id = %s AND category = %s
                  AND correlation_id = %s
                FOR UPDATE
                """,
                (GOAL_ID, category, correlation_id),
            )
            if _rows(cursor):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_read_allowance_unavailable"
                )
            if int(row["read_call_count"]) >= 30:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_read_allowance_unavailable"
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_revealed_order_movement_read_call (
                    goal_id, category, correlation_id, call_state
                ) VALUES (%s, %s, %s, 'STARTED')
                """,
                (GOAL_ID, category, correlation_id),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_goal
                SET read_call_count = read_call_count + 1,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )

    def record_read(
        self,
        *,
        stealth_order_id: str,
        category: str,
        correlation_id: str,
        result_code: str,
    ) -> None:
        self._require_read_identity(category, correlation_id)
        if result_code not in _READ_RESULTS:
            result_code = "UNKNOWN"
        with self.database.get_cursor() as cursor:
            self._locked_goal(cursor, stealth_order_id)
            cursor.execute(
                f"""
                UPDATE
                    {self.prefix}operator_revealed_order_movement_read_call
                SET call_state = 'RETURNED', result_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s AND category = %s
                  AND correlation_id = %s AND call_state = 'STARTED'
                RETURNING goal_id
                """,
                (result_code, GOAL_ID, category, correlation_id),
            )
            if not _rows(cursor):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_read_outcome_conflict"
                )

    def claim_cancel(
        self,
        *,
        stealth_order_id: str,
        correlation_id: str,
    ) -> None:
        self._claim_call(
            stealth_order_id=stealth_order_id,
            correlation_id=correlation_id,
            expected_state="PLANNED",
            state="CANCEL_CLAIMED",
            allowance_column="cancel_allowance_consumed",
            count_column="cancel_call_count",
            diagnostic_code="operator_move_cancel_invocation_started",
        )

    def record_cancel_outcome(
        self,
        *,
        stealth_order_id: str,
        outcome: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        if outcome not in {"CANCELLED", "FILLED", "REJECTED", "UNKNOWN"}:
            raise OperatorRevealedOrderMovementError(
                "operator_move_cancel_outcome_invalid"
            )
        self._require_diagnostic(diagnostic_code)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            allowed = (
                outcome in {"FILLED", "REJECTED", "UNKNOWN"}
                if row["state"] == "PLANNED"
                else (
                    outcome in {"CANCELLED", "REJECTED", "UNKNOWN"}
                    if row["state"] == "CANCEL_CLAIMED"
                    else False
                )
            )
            if not allowed:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_cancel_outcome_conflict"
                )
            state = {
                "CANCELLED": "SOURCE_CANCELLED",
                "FILLED": "SOURCE_FILLED",
                "REJECTED": "CANCEL_REJECTED",
                "UNKNOWN": "CANCEL_UNKNOWN",
            }[outcome]
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_goal
                SET state = %s, diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic_code, GOAL_ID),
            )
            return self._project(
                cursor, _one(cursor, "operator_move_goal_missing")
            )

    def claim_create(
        self,
        *,
        stealth_order_id: str,
        correlation_id: str,
    ) -> None:
        self._claim_call(
            stealth_order_id=stealth_order_id,
            correlation_id=correlation_id,
            expected_state="SOURCE_CANCELLED",
            state="CREATE_CLAIMED",
            allowance_column="create_allowance_consumed",
            count_column="create_call_count",
            diagnostic_code="operator_move_create_invocation_started",
            required_read_category="WALLET_PRE_CREATE",
            required_read_result="RETURNED",
        )

    def record_create_outcome(
        self,
        *,
        stealth_order_id: str,
        outcome: str,
        diagnostic_code: str,
        replacement_exchange_order_id_sha256: str | None,
    ) -> dict[str, Any]:
        if outcome not in {"ACCEPTED", "REJECTED", "UNKNOWN"}:
            raise OperatorRevealedOrderMovementError(
                "operator_move_create_outcome_invalid"
            )
        self._require_diagnostic(diagnostic_code)
        if outcome == "ACCEPTED":
            self._require_sha(replacement_exchange_order_id_sha256)
        elif replacement_exchange_order_id_sha256 is not None:
            raise OperatorRevealedOrderMovementError(
                "operator_move_exchange_identity_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            claimed = bool(row["create_allowance_consumed"]) or int(
                row["create_call_count"]
            ) != 0
            allowed = bool(
                (row["state"] == "CREATE_CLAIMED" and claimed)
                or (
                    row["state"] == "SOURCE_CANCELLED"
                    and not claimed
                    and outcome in {"REJECTED", "UNKNOWN"}
                )
            )
            if not allowed:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_create_outcome_conflict"
                )
            state = {
                "ACCEPTED": "REPLACED",
                "REJECTED": "CREATE_REJECTED",
                "UNKNOWN": "CREATE_UNKNOWN",
            }[outcome]
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_goal
                SET state = %s, diagnostic_code = %s,
                    replacement_exchange_order_id_sha256 = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (
                    state,
                    diagnostic_code,
                    replacement_exchange_order_id_sha256,
                    GOAL_ID,
                ),
            )
            return self._project(
                cursor, _one(cursor, "operator_move_goal_missing")
            )

    def complete_command(
        self,
        *,
        stealth_order_id: str,
        phase: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if phase != "EXECUTE":
            raise OperatorRevealedOrderMovementError(
                "operator_move_cycle_phase_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s AND phase = %s
                  AND correlation_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (GOAL_ID, phase, correlation_id, idempotency_key),
            )
            cycle = _one(cursor, "operator_move_cycle_not_found")
            if cycle["completion_status"] == "COMPLETED":
                return self._project(cursor, row, cycle=cycle)
            if row["state"] in {"CANCEL_CLAIMED", "CREATE_CLAIMED"}:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_command_completion_unavailable"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_revealed_order_movement_read_call
                WHERE goal_id = %s AND correlation_id = %s
                  AND call_state = 'STARTED'
                """,
                (GOAL_ID, correlation_id),
            )
            if int(cursor.fetchone()[0]) != 0:
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_command_completion_unavailable"
                )
            evidence = self._cycle_evidence(
                phase=phase,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=cycle["payload_sha256"],
                state=row["state"],
                diagnostic_code=row["diagnostic_code"],
                cancel_call_count=int(row["cancel_call_count"]),
                create_call_count=int(row["create_call_count"]),
                read_call_count=int(row["read_call_count"]),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    cancel_call_count = %s,
                    create_call_count = %s,
                    read_call_count = %s,
                    evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                RETURNING *
                """,
                (
                    row["state"],
                    row["diagnostic_code"],
                    row["cancel_call_count"],
                    row["create_call_count"],
                    row["read_call_count"],
                    evidence,
                    GOAL_ID,
                    cycle["cycle_number"],
                ),
            )
            completed = _one(cursor, "operator_move_cycle_missing")
            return self._project(cursor, row, cycle=completed)

    def _claim_call(
        self,
        *,
        stealth_order_id: str,
        correlation_id: str,
        expected_state: str,
        state: str,
        allowance_column: str,
        count_column: str,
        diagnostic_code: str,
        required_read_category: str | None = None,
        required_read_result: str | None = None,
    ) -> None:
        if _EVIDENCE_ID.fullmatch(correlation_id) is None:
            raise OperatorRevealedOrderMovementError(
                "operator_move_command_identity_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, stealth_order_id)
            self._require_active_execute_cycle(cursor, correlation_id)
            if required_read_category is not None:
                cursor.execute(
                    f"""
                    SELECT call_state, result_code
                    FROM
                      {self.prefix}operator_revealed_order_movement_read_call
                    WHERE goal_id = %s AND category = %s
                      AND correlation_id = %s
                    FOR UPDATE
                    """,
                    (
                        GOAL_ID,
                        required_read_category,
                        correlation_id,
                    ),
                )
                reads = _rows(cursor)
                if not (
                    len(reads) == 1
                    and reads[0]["call_state"] == "RETURNED"
                    and reads[0]["result_code"]
                    == required_read_result
                ):
                    raise OperatorRevealedOrderMovementConflict(
                        "operator_move_required_read_unavailable"
                    )
            if (
                row["state"] != expected_state
                or row[allowance_column]
                or int(row[count_column]) != 0
            ):
                raise OperatorRevealedOrderMovementConflict(
                    "operator_move_call_allowance_unavailable"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_goal
                SET state = %s, {allowance_column} = TRUE,
                    {count_column} = 1, diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (state, diagnostic_code, GOAL_ID),
            )

    def _recover_interrupted(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_revealed_order_movement_goal AS g
            SET state = 'CANCEL_UNKNOWN',
                diagnostic_code =
                    'operator_move_pre_cancel_read_unknown',
                updated_at = NOW()
            WHERE g.goal_id = %s AND g.state = 'PLANNED'
              AND EXISTS (
                  SELECT 1
                  FROM
                    {self.prefix}operator_revealed_order_movement_read_call r
                  WHERE r.goal_id = g.goal_id
                    AND r.category = 'SOURCE_PRE_CANCEL'
                    AND r.call_state = 'STARTED'
              )
            """,
            (GOAL_ID,),
        )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_revealed_order_movement_goal AS g
            SET state = 'CREATE_UNKNOWN',
                diagnostic_code =
                    'operator_move_wallet_read_unknown',
                updated_at = NOW()
            WHERE g.goal_id = %s AND g.state = 'SOURCE_CANCELLED'
              AND EXISTS (
                  SELECT 1
                  FROM
                    {self.prefix}operator_revealed_order_movement_read_call r
                  WHERE r.goal_id = g.goal_id
                    AND r.category = 'WALLET_PRE_CREATE'
                    AND r.call_state = 'STARTED'
              )
            """,
            (GOAL_ID,),
        )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_revealed_order_movement_read_call
            SET call_state = 'UNKNOWN', result_code = 'UNKNOWN',
                updated_at = NOW()
            WHERE call_state = 'STARTED'
            """
        )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_revealed_order_movement_goal
            SET state = CASE
                    WHEN state = 'CANCEL_CLAIMED'
                        THEN 'CANCEL_UNKNOWN'
                    WHEN state = 'CREATE_CLAIMED'
                        THEN 'CREATE_UNKNOWN'
                    ELSE state
                END,
                diagnostic_code = CASE
                    WHEN state = 'CANCEL_CLAIMED'
                        THEN 'operator_move_cancel_unknown'
                    WHEN state = 'CREATE_CLAIMED'
                        THEN 'operator_move_replacement_unknown'
                    ELSE diagnostic_code
                END,
                updated_at = NOW()
            WHERE state IN ('CANCEL_CLAIMED', 'CREATE_CLAIMED')
            """
        )
        cursor.execute(
            f"""
            SELECT
                g.state AS goal_state,
                g.diagnostic_code AS goal_diagnostic_code,
                g.cancel_call_count AS goal_cancel_call_count,
                g.create_call_count AS goal_create_call_count,
                g.read_call_count AS goal_read_call_count,
                c.phase,
                c.correlation_id,
                c.idempotency_key,
                c.payload_sha256,
                c.cycle_number
            FROM {self.prefix}operator_revealed_order_movement_goal g
            JOIN {self.prefix}operator_revealed_order_movement_cycle c
              ON c.goal_id = g.goal_id
            WHERE c.completion_status = 'IN_FLIGHT'
            ORDER BY c.cycle_number
            FOR UPDATE OF g, c
            """
        )
        for combined in _rows(cursor):
            evidence = self._cycle_evidence(
                phase=str(combined["phase"]),
                correlation_id=str(combined["correlation_id"]),
                idempotency_key=str(combined["idempotency_key"]),
                payload_sha256=str(combined["payload_sha256"]),
                state=str(combined["goal_state"]),
                diagnostic_code=str(combined["goal_diagnostic_code"]),
                cancel_call_count=int(combined["goal_cancel_call_count"]),
                create_call_count=int(combined["goal_create_call_count"]),
                read_call_count=int(combined["goal_read_call_count"]),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_revealed_order_movement_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    cancel_call_count = %s,
                    create_call_count = %s,
                    read_call_count = %s,
                    evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                """,
                (
                    combined["goal_state"],
                    combined["goal_diagnostic_code"],
                    combined["goal_cancel_call_count"],
                    combined["goal_create_call_count"],
                    combined["goal_read_call_count"],
                    evidence,
                    GOAL_ID,
                    combined["cycle_number"],
                ),
            )

    def _locked_goal(
        self, cursor: Any, stealth_order_id: str
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_revealed_order_movement_goal
            WHERE goal_id = %s AND stealth_order_id = %s::uuid
            FOR UPDATE
            """,
            (GOAL_ID, stealth_order_id),
        )
        return _one(cursor, "operator_move_goal_not_found")

    def _require_active_execute_cycle(
        self, cursor: Any, correlation_id: str
    ) -> None:
        cursor.execute(
            f"""
            SELECT cycle_number
            FROM {self.prefix}operator_revealed_order_movement_cycle
            WHERE goal_id = %s AND phase = 'EXECUTE'
              AND correlation_id = %s
              AND completion_status = 'IN_FLIGHT'
            """,
            (GOAL_ID, correlation_id),
        )
        if not _rows(cursor):
            raise OperatorRevealedOrderMovementConflict(
                "operator_move_active_cycle_required"
            )

    def _project(
        self,
        cursor: Any,
        row: Mapping[str, Any],
        *,
        command_replayed: bool = False,
        cycle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if cycle is None:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_revealed_order_movement_cycle
                WHERE goal_id = %s
                ORDER BY cycle_number DESC
                LIMIT 1
                """,
                (GOAL_ID,),
            )
            cycles = _rows(cursor)
            cycle = cycles[0] if cycles else None
        plan = dict(row.get("plan_json") or {})
        return {
            **plan,
            "goal_id": row["goal_id"],
            "state": row["state"],
            "plan": plan,
            "plan_sha256": row["plan_sha256"],
            "replacement_exchange_order_id_sha256": row.get(
                "replacement_exchange_order_id_sha256"
            ),
            "cancel_allowance_consumed": bool(
                row["cancel_allowance_consumed"]
            ),
            "create_allowance_consumed": bool(
                row["create_allowance_consumed"]
            ),
            "cancel_call_count": int(row["cancel_call_count"]),
            "create_call_count": int(row["create_call_count"]),
            "read_call_count": int(row["read_call_count"]),
            "diagnostic_code": row["diagnostic_code"],
            "correlation_id": (
                row.get("execute_correlation_id")
                or row["plan_correlation_id"]
            ),
            "plan_idempotency_key_sha256": _sha(
                row["plan_idempotency_key"]
            ),
            "execute_idempotency_key_sha256": (
                _sha(row["execute_idempotency_key"])
                if row.get("execute_idempotency_key")
                else None
            ),
            "command_cycle_status": (
                cycle.get("completion_status") if cycle else None
            ),
            "command_cycle_phase": (
                cycle.get("phase") if cycle else None
            ),
            "command_cycle_number": (
                int(cycle["cycle_number"]) if cycle else None
            ),
            "command_cycle_correlation_id": (
                cycle.get("correlation_id") if cycle else None
            ),
            "command_cycle_evidence_sha256": (
                cycle.get("evidence_sha256") if cycle else None
            ),
            "command_replayed": command_replayed,
        }

    @staticmethod
    def _cycle_evidence(
        *,
        phase: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
        state: str,
        diagnostic_code: str,
        cancel_call_count: int,
        create_call_count: int,
        read_call_count: int,
    ) -> str:
        return _sha(
            json.dumps(
                {
                    "goal_id": GOAL_ID,
                    "phase": phase,
                    "correlation_id": correlation_id,
                    "idempotency_key_sha256": _sha(idempotency_key),
                    "payload_sha256": payload_sha256,
                    "state": state,
                    "diagnostic_code": diagnostic_code,
                    "cancel_call_count": cancel_call_count,
                    "create_call_count": create_call_count,
                    "read_call_count": read_call_count,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _require_identity(
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> None:
        if (
            not actor_id
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
            or _SHA256.fullmatch(payload_sha256) is None
        ):
            raise OperatorRevealedOrderMovementError(
                "operator_move_command_identity_invalid"
            )

    @staticmethod
    def _require_plan(plan: Mapping[str, Any]) -> None:
        required = {
            "stealth_order_id",
            "plan_sha256",
            "source_client_order_id",
            "replacement_client_order_id",
            "source_exchange_order_id_sha256",
        }
        if not required <= set(plan):
            raise OperatorRevealedOrderMovementError(
                "operator_move_plan_shape_invalid"
            )
        for field in ("plan_sha256", "source_exchange_order_id_sha256"):
            if _SHA256.fullmatch(str(plan[field])) is None:
                raise OperatorRevealedOrderMovementError(
                    "operator_move_plan_hash_invalid"
                )

    @staticmethod
    def _require_read_identity(
        category: str, correlation_id: str
    ) -> None:
        if (
            category not in _READ_CATEGORIES
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
        ):
            raise OperatorRevealedOrderMovementError(
                "operator_move_read_identity_invalid"
            )

    @staticmethod
    def _require_diagnostic(code: str) -> None:
        if _DIAGNOSTIC.fullmatch(code) is None:
            raise OperatorRevealedOrderMovementError(
                "operator_move_diagnostic_invalid"
            )

    @staticmethod
    def _require_sha(value: str | None) -> None:
        if value is None or _SHA256.fullmatch(value) is None:
            raise OperatorRevealedOrderMovementError(
                "operator_move_hash_invalid"
            )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _rows(cursor: Any) -> list[dict[str, Any]]:
    description = cursor.description
    rows = cursor.fetchall()
    if not description:
        return []
    columns = [item.name for item in description]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorRevealedOrderMovementError(code)
    return rows[0]


@lru_cache(maxsize=1)
def get_default_operator_revealed_order_movement_repository(
) -> OperatorRevealedOrderMovementRepository:
    repository = OperatorRevealedOrderMovementRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def initialize_operator_revealed_order_movement_schema() -> None:
    get_default_operator_revealed_order_movement_repository().ensure_schema()
