"""PostgreSQL authority for one operator-reviewed parent move premark."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from functools import lru_cache
from typing import Any, Mapping

from psycopg2.extras import Json

from database.database import PostgresDB


GOAL_ID = "operator_parent_move_premark_lifecycle_v1"
MAX_CYCLES = 10

_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_DIAGNOSTIC = re.compile(
    r"^operator_parent_move_[a-z0-9_]{1,75}$"
)
_ALLOWED_PLAN_KEYS = frozenset(
    {
        "goal_id",
        "policy_revision",
        "source_client_order_id",
        "reserved_successor_client_order_id",
        "portfolio_scope_sha256",
        "product_id",
        "side",
        "base_size",
        "source_limit_price",
        "requested_limit_price",
        "replacement_limit_price",
        "price_increment",
        "base_increment",
        "base_min_size",
        "quote_min_size",
        "source_status",
        "source_filled_size",
        "source_order_type",
        "source_time_in_force",
        "source_ownership_provenance",
        "post_only",
        "submitted_notional",
        "possible_execution_notional",
        "submitted_notional_cap",
        "possible_execution_notional_cap",
        "zero_fill_proven",
        "system_owned",
        "source_evidence_sha256",
    }
)
_FORBIDDEN_PLAN_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "body",
        "exception",
        "exception_message",
        "exchange_order_id",
        "message",
        "preview_id",
        "private_identifier",
        "raw",
        "raw_response",
        "response",
        "response_body",
        "secret",
    }
)
_SAFE_SUPPRESSION_FINAL_STATES = frozenset(
    {
        "SOURCE_CANCEL_REJECTED",
    }
)
_SOURCE_CANCEL_EVENT_ACK_STATES = frozenset(
    {
        "SOURCE_CANCEL_BOUNDARY_CROSSED",
        "SOURCE_CANCELLED",
        "SOURCE_CANCEL_UNKNOWN",
        "REPLACEMENT_CREATE_CLAIMED",
        "REPLACEMENT_CREATE_BOUNDARY_CROSSED",
        "REPLACEMENT_CREATED",
        "REPLACEMENT_CREATE_REJECTED",
        "REPLACEMENT_CREATE_UNKNOWN",
        "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED",
        "SUCCESSOR_CLOSEOUT_CANCEL_BOUNDARY_CROSSED",
        "SUCCESSOR_CLOSED",
        "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED",
        "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN",
    }
)


class OperatorParentMovePremarkError(ValueError):
    """Fixed, value-blind repository validation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OperatorParentMovePremarkConflict(
    OperatorParentMovePremarkError
):
    """Durable state, binding, or allowance conflict."""


class OperatorParentMovePremarkRepository:
    """One goal-local plan, ten cycles, and three one-use mutations."""

    def __init__(self, database: PostgresDB, *, schema: str = "public") -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_schema_invalid"
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
                    {self.prefix}operator_parent_move_premark_goal (
                    goal_id TEXT PRIMARY KEY CHECK (
                        goal_id = '{GOAL_ID}'
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'PLANNED',
                            'SOURCE_CANCEL_CLAIMED',
                            'SOURCE_CANCEL_BOUNDARY_CROSSED',
                            'SOURCE_CANCELLED',
                            'SOURCE_CANCEL_REJECTED',
                            'SOURCE_CANCEL_UNKNOWN',
                            'REPLACEMENT_CREATE_CLAIMED',
                            'REPLACEMENT_CREATE_BOUNDARY_CROSSED',
                            'REPLACEMENT_CREATED',
                            'REPLACEMENT_CREATE_REJECTED',
                            'REPLACEMENT_CREATE_UNKNOWN',
                            'SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED',
                            'SUCCESSOR_CLOSEOUT_CANCEL_BOUNDARY_CROSSED',
                            'SUCCESSOR_CLOSED',
                            'SUCCESSOR_CLOSEOUT_CANCEL_REJECTED',
                            'SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN'
                        )
                    ),
                    source_client_order_id UUID NOT NULL UNIQUE,
                    reserved_successor_client_order_id UUID NOT NULL UNIQUE,
                    plan_json JSONB NOT NULL,
                    plan_sha256 CHAR(64) NOT NULL CHECK (
                        plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_parent_move_[a-z0-9_]{{1,75}}$'
                    ),
                    source_follow_up_suppressed BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    source_cancel_event_acknowledged BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    suppression_correlation_id TEXT,
                    source_cancel_allowance_consumed BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    replacement_create_allowance_consumed BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    successor_closeout_cancel_allowance_consumed
                        BOOLEAN NOT NULL DEFAULT FALSE,
                    source_cancel_call_count SMALLINT NOT NULL DEFAULT 0
                        CHECK (source_cancel_call_count BETWEEN 0 AND 1),
                    replacement_create_call_count SMALLINT NOT NULL DEFAULT 0
                        CHECK (
                            replacement_create_call_count BETWEEN 0 AND 1
                        ),
                    successor_closeout_cancel_call_count SMALLINT NOT NULL
                        DEFAULT 0 CHECK (
                            successor_closeout_cancel_call_count
                                BETWEEN 0 AND 1
                        ),
                    plan_actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        plan_actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    plan_correlation_id TEXT NOT NULL,
                    plan_idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (
                            plan_idempotency_key_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    plan_request_sha256 CHAR(64) NOT NULL CHECK (
                        plan_request_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    plan_request_binding_legacy BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    plan_payload_sha256 CHAR(64) NOT NULL CHECK (
                        plan_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_parent_move_premark_cycle (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_parent_move_premark_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    cycle_number SMALLINT NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND {MAX_CYCLES}
                    ),
                    phase TEXT NOT NULL CHECK (
                        phase IN ('PLAN', 'EXECUTE', 'CLOSEOUT')
                    ),
                    completion_status TEXT NOT NULL CHECK (
                        completion_status IN ('IN_FLIGHT', 'COMPLETED')
                    ),
                    actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    correlation_id TEXT NOT NULL,
                    idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE CHECK (
                        idempotency_key_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    terminal_goal_state TEXT,
                    terminal_diagnostic_code TEXT,
                    evidence_sha256 CHAR(64) CHECK (
                        evidence_sha256 IS NULL OR
                        evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    PRIMARY KEY (goal_id, cycle_number)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_parent_move_premark_goal
                ADD COLUMN IF NOT EXISTS
                    source_cancel_event_acknowledged BOOLEAN NOT NULL
                    DEFAULT FALSE
                """
            )
            self._rearm_legacy_source_cancel_fences(cursor)
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_parent_move_premark_goal
                ADD COLUMN IF NOT EXISTS plan_request_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_parent_move_premark_goal
                ADD COLUMN IF NOT EXISTS
                    plan_request_binding_legacy BOOLEAN NOT NULL
                    DEFAULT FALSE
                """
            )
            self._migrate_plan_request_binding(cursor)
            self._migrate_hash_only_idempotency(cursor)
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_parent_move_premark_cycle
                ADD COLUMN IF NOT EXISTS evidence_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    operator_parent_move_premark_one_inflight_cycle
                ON {self.prefix}operator_parent_move_premark_cycle(goal_id)
                WHERE completion_status = 'IN_FLIGHT'
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    operator_parent_move_premark_cycle_correlation_unique
                ON {self.prefix}operator_parent_move_premark_cycle(
                    goal_id, correlation_id
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_parent_move_premark_claim (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_parent_move_premark_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    action TEXT NOT NULL CHECK (
                        action IN (
                            'SOURCE_CANCEL',
                            'REPLACEMENT_CREATE',
                            'SUCCESSOR_CLOSEOUT_CANCEL'
                        )
                    ),
                    cycle_number SMALLINT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    claim_state TEXT NOT NULL CHECK (
                        claim_state IN (
                            'CLAIMED', 'BOUNDARY_CROSSED',
                            'RETURNED', 'UNKNOWN',
                            'ABORTED_PRE_BOUNDARY'
                        )
                    ),
                    allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    outcome_code TEXT,
                    exchange_evidence_sha256 CHAR(64) CHECK (
                        exchange_evidence_sha256 IS NULL OR
                        exchange_evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    boundary_crossed_at TIMESTAMPTZ,
                    resolved_at TIMESTAMPTZ,
                    PRIMARY KEY (goal_id, action),
                    FOREIGN KEY (goal_id, cycle_number) REFERENCES
                        {self.prefix}operator_parent_move_premark_cycle(
                            goal_id, cycle_number
                        ) ON DELETE RESTRICT
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_parent_move_premark_event (
                    event_id BIGSERIAL PRIMARY KEY,
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_parent_move_premark_goal(
                            goal_id
                        ) ON DELETE RESTRICT,
                    source_client_order_id UUID NOT NULL,
                    event_type TEXT NOT NULL CHECK (
                        event_type IN (
                            'PLAN_CREATED', 'CYCLE_STARTED',
                            'CYCLE_COMPLETED',
                            'SOURCE_SUPPRESSION_ACTIVATED',
                            'SOURCE_SUPPRESSION_FINALIZED',
                            'MUTATION_CLAIMED',
                            'MUTATION_BOUNDARY_CROSSED',
                            'MUTATION_RETURNED',
                            'MUTATION_ABORTED_PRE_BOUNDARY',
                            'MUTATION_RECOVERED_UNKNOWN'
                        )
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_parent_move_[a-z0-9_]{{1,75}}$'
                    ),
                    evidence_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION
                    {self.prefix}reject_parent_move_premark_event_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION
                        'operator_parent_move_event_append_only';
                END;
                $$
                """
            )
            cursor.execute(
                f"""
                DROP TRIGGER IF EXISTS
                    operator_parent_move_premark_event_append_only
                ON {self.prefix}operator_parent_move_premark_event
                """
            )
            cursor.execute(
                f"""
                CREATE TRIGGER
                    operator_parent_move_premark_event_append_only
                BEFORE UPDATE OR DELETE
                ON {self.prefix}operator_parent_move_premark_event
                FOR EACH ROW EXECUTE FUNCTION
                    {self.prefix}reject_parent_move_premark_event_mutation()
                """
            )

    def recover_stranded_work(self) -> None:
        """Recover work only after the caller proves exclusive ownership.

        Schema installation is intentionally side-effect free with respect to
        command state.  The application runtime owns the OS-released lifecycle
        lock and calls this method before operator ingress; repository
        construction alone must never reinterpret an active exchange boundary
        as a dead worker.
        """

        with self.database.get_cursor() as cursor:
            self._recover_boundary_crossed(cursor)
            self._recover_pre_boundary_inflight(cursor)

    def _rearm_legacy_source_cancel_fences(self, cursor: Any) -> None:
        """Restore a fail-closed fence for pre-acknowledgement schema rows."""

        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_parent_move_premark_goal
            SET source_follow_up_suppressed = TRUE,
                suppression_correlation_id = NULL,
                updated_at = NOW()
            WHERE source_cancel_event_acknowledged = FALSE
              AND source_follow_up_suppressed = FALSE
              AND source_cancel_allowance_consumed = TRUE
              AND source_cancel_call_count = 1
              AND state = ANY(%s)
            """,
            (list(sorted(_SOURCE_CANCEL_EVENT_ACK_STATES)),),
        )

    def _migrate_plan_request_binding(self, cursor: Any) -> None:
        """Mark unprovable legacy Premark request bindings fail-closed."""

        cursor.execute(
            f"""
            SELECT goal_id, plan_payload_sha256
            FROM {self.prefix}operator_parent_move_premark_goal
            WHERE plan_request_sha256 IS NULL
            FOR UPDATE
            """
        )
        for row in _rows(cursor):
            legacy_marker = _sha(
                (
                    f"{GOAL_ID}:legacy-request-binding:"
                    f"{row['plan_payload_sha256']}"
                )
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET plan_request_sha256 = %s,
                    plan_request_binding_legacy = TRUE,
                    updated_at = NOW()
                WHERE goal_id = %s
                  AND plan_request_sha256 IS NULL
                """,
                (legacy_marker, row["goal_id"]),
            )
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {self.prefix}operator_parent_move_premark_goal
            WHERE plan_request_sha256 IS NULL
               OR plan_request_sha256 !~ '^[0-9a-f]{{64}}$'
            """
        )
        if int(cursor.fetchone()[0]) != 0:
            raise OperatorParentMovePremarkConflict(
                "operator_parent_move_request_binding_migration_invalid"
            )
        cursor.execute(
            f"""
            ALTER TABLE {self.prefix}operator_parent_move_premark_goal
            ALTER COLUMN plan_request_sha256 SET NOT NULL
            """
        )
        constraint_name = (
            "operator_parent_move_premark_goal_"
            "plan_request_sha256_format"
        )
        cursor.execute(
            f"""
            ALTER TABLE
                {self.prefix}operator_parent_move_premark_goal
            DROP CONSTRAINT IF EXISTS {constraint_name}
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE
                {self.prefix}operator_parent_move_premark_goal
            ADD CONSTRAINT {constraint_name}
            CHECK (plan_request_sha256 ~ '^[0-9a-f]{{64}}$')
            """
        )

    def _migrate_hash_only_idempotency(self, cursor: Any) -> None:
        """Replace legacy raw command keys with one-way SHA-256 bindings."""

        migrations = (
            (
                "operator_parent_move_premark_goal",
                "plan_idempotency_key",
                "plan_idempotency_key_sha256",
                ("goal_id",),
            ),
            (
                "operator_parent_move_premark_cycle",
                "idempotency_key",
                "idempotency_key_sha256",
                ("goal_id", "cycle_number"),
            ),
        )
        for table, legacy_column, hash_column, identity_columns in migrations:
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}{table}
                ADD COLUMN IF NOT EXISTS {hash_column} CHAR(64)
                """
            )
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                )
                """,
                (self.schema, table, legacy_column),
            )
            legacy_exists = bool(cursor.fetchone()[0])
            if legacy_exists:
                selected = ", ".join(
                    (*identity_columns, legacy_column, hash_column)
                )
                cursor.execute(
                    f"""
                    SELECT {selected}
                    FROM {self.prefix}{table}
                    WHERE {hash_column} IS NULL
                    FOR UPDATE
                    """
                )
                for row in _rows(cursor):
                    raw_key = str(row[legacy_column]).rstrip()
                    predicates = " AND ".join(
                        f"{column} = %s" for column in identity_columns
                    )
                    cursor.execute(
                        f"""
                        UPDATE {self.prefix}{table}
                        SET {hash_column} = %s
                        WHERE {predicates}
                        """,
                        (
                            _sha(raw_key),
                            *(row[column] for column in identity_columns),
                        ),
                    )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}{table}
                WHERE {hash_column} IS NULL
                   OR {hash_column} !~ '^[0-9a-f]{{64}}$'
                """
            )
            if int(cursor.fetchone()[0]) != 0:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_idempotency_migration_invalid"
                )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}{table}
                ALTER COLUMN {hash_column} SET NOT NULL
                """
            )
            constraint_name = f"{table}_{hash_column}_format"
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}{table}
                DROP CONSTRAINT IF EXISTS {constraint_name}
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}{table}
                ADD CONSTRAINT {constraint_name}
                CHECK ({hash_column} ~ '^[0-9a-f]{{64}}$')
                """
            )
            if legacy_exists:
                cursor.execute(
                    f"""
                    ALTER TABLE {self.prefix}{table}
                    DROP COLUMN {legacy_column}
                    """
                )
            index_name = f"{table}_{hash_column}_unique"
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
                ON {self.prefix}{table} ({hash_column})
                """
            )

    def get_premark_replay(
        self,
        *,
        source_client_order_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        premark_request_sha256: str,
    ) -> dict[str, Any] | None:
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=premark_request_sha256,
        )
        source_id = _uuid(source_client_order_id)
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            row = rows[0]
            if (
                str(row["source_client_order_id"]) != source_id
                or row["plan_idempotency_key_sha256"]
                != idempotency_hash
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_goal_allowance_unavailable"
                )
            if not (
                row["plan_actor_id_sha256"] == actor_hash
                and row["plan_correlation_id"] == correlation_id
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_idempotency_conflict"
                )
            if row["plan_request_binding_legacy"]:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_legacy_request_binding_unavailable"
                )
            if row["plan_request_sha256"] != premark_request_sha256:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_idempotency_conflict"
                )
            return self._project(
                cursor,
                row,
                command_replayed=True,
            )

    def create_plan(
        self,
        *,
        plan: Mapping[str, Any],
        plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        premark_request_sha256: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        _require_sha(premark_request_sha256)
        normalized_plan = self._require_plan(plan, plan_sha256)
        source_id = str(normalized_plan["source_client_order_id"])
        successor_id = str(
            normalized_plan["reserved_successor_client_order_id"]
        )
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            self._lock_goal(cursor)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            goals = _rows(cursor)
            if goals:
                row = goals[0]
                if (
                    row["plan_idempotency_key_sha256"]
                    == idempotency_hash
                ):
                    if row["plan_request_binding_legacy"]:
                        raise OperatorParentMovePremarkConflict(
                            "operator_parent_move_"
                            "legacy_request_binding_unavailable"
                        )
                    if not (
                        row["plan_actor_id_sha256"] == actor_hash
                        and row["plan_correlation_id"] == correlation_id
                        and row["plan_request_sha256"]
                        == premark_request_sha256
                        and row["plan_payload_sha256"] == payload_sha256
                        and row["plan_sha256"] == plan_sha256
                        and str(row["source_client_order_id"]) == source_id
                        and str(
                            row["reserved_successor_client_order_id"]
                        )
                        == successor_id
                    ):
                        raise OperatorParentMovePremarkConflict(
                            "operator_parent_move_idempotency_conflict"
                        )
                    return self._project(
                        cursor,
                        row,
                        command_replayed=True,
                    )
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_goal_allowance_unavailable"
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_parent_move_premark_goal (
                    goal_id, state, source_client_order_id,
                    reserved_successor_client_order_id,
                    plan_json, plan_sha256, diagnostic_code,
                    plan_actor_id_sha256, plan_correlation_id,
                    plan_idempotency_key_sha256, plan_request_sha256,
                    plan_payload_sha256
                ) VALUES (
                    %s, 'PLANNED', %s::uuid, %s::uuid, %s, %s,
                    'operator_parent_move_plan_ready',
                    %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    GOAL_ID,
                    source_id,
                    successor_id,
                    Json(normalized_plan),
                    plan_sha256,
                    actor_hash,
                    correlation_id,
                    idempotency_hash,
                    premark_request_sha256,
                    payload_sha256,
                ),
            )
            row = _one(cursor, "operator_parent_move_goal_insert_failed")
            cycle_evidence = self._cycle_evidence_sha256(
                cycle_number=1,
                phase="PLAN",
                correlation_id=correlation_id,
                idempotency_key_sha256=idempotency_hash,
                payload_sha256=payload_sha256,
                state="PLANNED",
                diagnostic_code="operator_parent_move_plan_ready",
                row=row,
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_parent_move_premark_cycle (
                    goal_id, cycle_number, phase, completion_status,
                    actor_id_sha256, correlation_id,
                    idempotency_key_sha256,
                    payload_sha256, terminal_goal_state,
                    terminal_diagnostic_code, evidence_sha256,
                    completed_at
                ) VALUES (
                    %s, 1, 'PLAN', 'COMPLETED', %s, %s, %s, %s,
                    'PLANNED', 'operator_parent_move_plan_ready',
                    %s, NOW()
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
            self._append_event(
                cursor,
                source_client_order_id=source_id,
                event_type="PLAN_CREATED",
                diagnostic_code="operator_parent_move_plan_ready",
                evidence={
                    "plan_sha256": plan_sha256,
                    "reserved_successor_client_order_id": successor_id,
                },
            )
            return self._project(cursor, row)

    def get_goal(
        self, source_client_order_id: str
    ) -> dict[str, Any] | None:
        try:
            source_id = _uuid(source_client_order_id)
        except OperatorParentMovePremarkError:
            return None
        with self.database.get_cursor() as cursor:
            snapshot = self._projection_snapshot(cursor)
            if snapshot is None:
                return None
            if str(snapshot["source_client_order_id"]) != source_id:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_goal_allowance_unavailable"
                )
            return self._project_snapshot(snapshot)

    def begin_execute(
        self,
        *,
        source_client_order_id: str,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        return self._begin_cycle(
            phase="EXECUTE",
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            expected_plan_sha256=expected_plan_sha256,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )

    def get_execute_replay(
        self,
        *,
        source_client_order_id: str,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        _require_sha(expected_plan_sha256)
        source_id = _uuid(source_client_order_id)
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            goals = _rows(cursor)
            if not goals:
                return None
            row = goals[0]
            if str(row["source_client_order_id"]) != source_id:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_goal_allowance_unavailable"
                )
            if row["plan_sha256"] != expected_plan_sha256:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_plan_binding_conflict"
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_cycle
                WHERE goal_id = %s AND idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (GOAL_ID, idempotency_hash),
            )
            cycles = _rows(cursor)
            if not cycles:
                return None
            cycle = cycles[0]
            if not (
                cycle["phase"] == "EXECUTE"
                and cycle["actor_id_sha256"] == actor_hash
                and cycle["correlation_id"] == correlation_id
                and cycle["payload_sha256"] == payload_sha256
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_idempotency_conflict"
                )
            return self._project(
                cursor,
                row,
                cycle=cycle,
                command_replayed=True,
            )

    def begin_closeout(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        return self._begin_cycle(
            phase="CLOSEOUT",
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=(
                reserved_successor_client_order_id
            ),
            expected_plan_sha256=expected_plan_sha256,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )

    def complete_cycle(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
        idempotency_key: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        self._require_diagnostic(diagnostic_code)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_cycle
                WHERE goal_id = %s AND correlation_id = %s
                  AND idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (GOAL_ID, correlation_id, idempotency_hash),
            )
            cycle = _one(
                cursor,
                "operator_parent_move_cycle_not_found",
            )
            if cycle["completion_status"] == "COMPLETED":
                return self._project(cursor, row, cycle=cycle)
            cursor.execute(
                f"""
                SELECT claim_state
                FROM {self.prefix}operator_parent_move_premark_claim
                WHERE goal_id = %s AND cycle_number = %s
                  AND claim_state IN ('CLAIMED', 'BOUNDARY_CROSSED')
                FOR UPDATE
                """,
                (GOAL_ID, cycle["cycle_number"]),
            )
            if _rows(cursor):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_cycle_completion_unavailable"
                )
            evidence_sha256 = self._cycle_evidence_sha256(
                cycle_number=int(cycle["cycle_number"]),
                phase=str(cycle["phase"]),
                correlation_id=str(cycle["correlation_id"]),
                idempotency_key_sha256=str(
                    cycle["idempotency_key_sha256"]
                ),
                payload_sha256=str(cycle["payload_sha256"]),
                state=str(row["state"]),
                diagnostic_code=diagnostic_code,
                row=row,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                RETURNING *
                """,
                (
                    row["state"],
                    diagnostic_code,
                    evidence_sha256,
                    GOAL_ID,
                    cycle["cycle_number"],
                ),
            )
            completed = _one(
                cursor,
                "operator_parent_move_cycle_not_found",
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (diagnostic_code, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="CYCLE_COMPLETED",
                diagnostic_code=diagnostic_code,
                evidence={
                    "cycle_number": int(completed["cycle_number"]),
                    "phase": str(completed["phase"]),
                    "state": str(row["state"]),
                },
            )
            return self._project(cursor, row, cycle=completed)

    def activate_source_follow_up_suppression(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            self._require_active_cycle(
                cursor,
                correlation_id=correlation_id,
                phase="EXECUTE",
            )
            if row["source_follow_up_suppressed"]:
                if row["suppression_correlation_id"] != correlation_id:
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_source_suppression_conflict"
                    )
                return self._project(
                    cursor,
                    row,
                    command_replayed=True,
                )
            if row["state"] != "PLANNED":
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_source_suppression_unavailable"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET source_follow_up_suppressed = TRUE,
                    suppression_correlation_id = %s,
                    diagnostic_code =
                        'operator_parent_move_source_suppression_active',
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (correlation_id, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="SOURCE_SUPPRESSION_ACTIVATED",
                diagnostic_code=(
                    "operator_parent_move_source_suppression_active"
                ),
                evidence={"active": True},
            )
            return self._project(cursor, row)

    def finalize_source_follow_up_suppression(
        self,
        *,
        source_client_order_id: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        self._require_diagnostic(diagnostic_code)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            if not row["source_follow_up_suppressed"]:
                return self._project(
                    cursor,
                    row,
                    command_replayed=True,
                )
            if row["state"] not in _SAFE_SUPPRESSION_FINAL_STATES:
                if row["state"] in _SOURCE_CANCEL_EVENT_ACK_STATES:
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_source_suppression_ack_required"
                    )
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_source_suppression_finalize_unsafe"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET source_follow_up_suppressed = FALSE,
                    suppression_correlation_id = NULL,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (diagnostic_code, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="SOURCE_SUPPRESSION_FINALIZED",
                diagnostic_code=diagnostic_code,
                evidence={"active": False, "state": str(row["state"])},
            )
            return self._project(cursor, row)

    def acknowledge_source_cancel_event_suppression(
        self,
        client_order_id: str,
    ) -> bool:
        """Seal one observed source-CANCELLED event before releasing its fence."""

        try:
            source_id = _uuid(client_order_id)
        except OperatorParentMovePremarkError:
            return False
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                  AND source_client_order_id = %s::uuid
                FOR UPDATE
                """,
                (GOAL_ID, source_id),
            )
            rows = _rows(cursor)
            if not rows:
                return False
            row = rows[0]
            if row["source_cancel_event_acknowledged"]:
                return True
            if (
                not row["source_follow_up_suppressed"]
                or row["state"] not in _SOURCE_CANCEL_EVENT_ACK_STATES
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_source_cancel_event_ack_unsafe"
                )
            diagnostic = (
                "operator_parent_move_source_cancel_event_acknowledged"
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET source_cancel_event_acknowledged = TRUE,
                    source_follow_up_suppressed = FALSE,
                    suppression_correlation_id = NULL,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (diagnostic, GOAL_ID),
            )
            self._append_event(
                cursor,
                source_client_order_id=source_id,
                event_type="SOURCE_SUPPRESSION_FINALIZED",
                diagnostic_code=diagnostic,
                evidence={
                    "active": False,
                    "cancel_event_acknowledged": True,
                    "state": str(row["state"]),
                },
            )
            return True

    def should_suppress_source_cancel_follow_up(
        self,
        client_order_id: str,
    ) -> bool:
        """Return the effective fence, including an immutable consumed-event seal."""

        try:
            source_id = _uuid(client_order_id)
        except OperatorParentMovePremarkError:
            return False
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT source_follow_up_suppressed,
                       source_cancel_event_acknowledged
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                  AND source_client_order_id = %s::uuid
                """,
                (GOAL_ID, source_id),
            )
            row = cursor.fetchone()
            return bool(row is not None and (row[0] or row[1]))

    def is_source_follow_up_suppressed(
        self, client_order_id: str
    ) -> bool:
        try:
            source_id = _uuid(client_order_id)
        except OperatorParentMovePremarkError:
            return False
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT source_follow_up_suppressed
                FROM {self.prefix}operator_parent_move_premark_goal
                WHERE goal_id = %s
                  AND source_client_order_id = %s::uuid
                """,
                (GOAL_ID, source_id),
            )
            row = cursor.fetchone()
            return bool(row is not None and row[0])

    def claim_source_cancel(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._claim_mutation(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            action="SOURCE_CANCEL",
            phase="EXECUTE",
            expected_state="PLANNED",
        )

    def mark_source_cancel_boundary_crossed(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._mark_mutation_boundary_crossed(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            action="SOURCE_CANCEL",
        )

    def record_source_cancel_outcome(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
        cycle_number: int,
        outcome: str,
        diagnostic_code: str,
        exchange_evidence_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._record_mutation_outcome(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            cycle_number=cycle_number,
            action="SOURCE_CANCEL",
            outcome=outcome,
            diagnostic_code=diagnostic_code,
            exchange_evidence_sha256=exchange_evidence_sha256,
        )

    def abort_source_cancel_before_boundary(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        return self._abort_claim_before_boundary(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            diagnostic_code=diagnostic_code,
            action="SOURCE_CANCEL",
            restored_state="PLANNED",
        )

    def claim_replacement_create(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._claim_mutation(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            action="REPLACEMENT_CREATE",
            phase="EXECUTE",
            expected_state="SOURCE_CANCELLED",
        )

    def mark_replacement_create_boundary_crossed(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._mark_mutation_boundary_crossed(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            action="REPLACEMENT_CREATE",
        )

    def record_replacement_create_outcome(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
        cycle_number: int,
        outcome: str,
        diagnostic_code: str,
        exchange_evidence_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._record_mutation_outcome(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            cycle_number=cycle_number,
            action="REPLACEMENT_CREATE",
            outcome=outcome,
            diagnostic_code=diagnostic_code,
            exchange_evidence_sha256=exchange_evidence_sha256,
        )

    def abort_replacement_create_before_boundary(
        self,
        *,
        source_client_order_id: str,
        correlation_id: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        return self._abort_claim_before_boundary(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=None,
            correlation_id=correlation_id,
            diagnostic_code=diagnostic_code,
            action="REPLACEMENT_CREATE",
            restored_state="SOURCE_CANCELLED",
        )

    def claim_successor_closeout_cancel(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._claim_mutation(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=(
                reserved_successor_client_order_id
            ),
            correlation_id=correlation_id,
            action="SUCCESSOR_CLOSEOUT_CANCEL",
            phase="CLOSEOUT",
            expected_state="REPLACEMENT_CREATED",
        )

    def mark_successor_closeout_cancel_boundary_crossed(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        return self._mark_mutation_boundary_crossed(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=(
                reserved_successor_client_order_id
            ),
            correlation_id=correlation_id,
            action="SUCCESSOR_CLOSEOUT_CANCEL",
        )

    def record_successor_closeout_cancel_outcome(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str,
        correlation_id: str,
        cycle_number: int,
        outcome: str,
        diagnostic_code: str,
        exchange_evidence_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._record_mutation_outcome(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=(
                reserved_successor_client_order_id
            ),
            correlation_id=correlation_id,
            cycle_number=cycle_number,
            action="SUCCESSOR_CLOSEOUT_CANCEL",
            outcome=outcome,
            diagnostic_code=diagnostic_code,
            exchange_evidence_sha256=exchange_evidence_sha256,
        )

    def abort_successor_closeout_cancel_before_boundary(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str,
        correlation_id: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        return self._abort_claim_before_boundary(
            source_client_order_id=source_client_order_id,
            reserved_successor_client_order_id=(
                reserved_successor_client_order_id
            ),
            correlation_id=correlation_id,
            diagnostic_code=diagnostic_code,
            action="SUCCESSOR_CLOSEOUT_CANCEL",
            restored_state="REPLACEMENT_CREATED",
        )

    def list_events(
        self,
        *,
        source_client_order_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        source_id = _uuid(source_client_order_id)
        if limit < 1 or limit > 100 or offset < 0:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_pagination_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_parent_move_premark_event
                WHERE goal_id = %s
                  AND source_client_order_id = %s::uuid
                """,
                (GOAL_ID, source_id),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, event_type, diagnostic_code,
                       evidence_json, created_at
                FROM {self.prefix}operator_parent_move_premark_event
                WHERE goal_id = %s
                  AND source_client_order_id = %s::uuid
                ORDER BY event_id ASC
                LIMIT %s OFFSET %s
                """,
                (GOAL_ID, source_id, limit, offset),
            )
            events = [
                {
                    "event_id": int(row["event_id"]),
                    "event_type": str(row["event_type"]),
                    "diagnostic_code": str(row["diagnostic_code"]),
                    "evidence": dict(row["evidence_json"]),
                    "created_at": row["created_at"].isoformat(),
                }
                for row in _rows(cursor)
            ]
            return events, total

    def _begin_cycle(
        self,
        *,
        phase: str,
        source_client_order_id: str,
        reserved_successor_client_order_id: str | None,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        _require_sha(expected_plan_sha256)
        actor_hash = _sha(actor_id)
        idempotency_hash = _sha(idempotency_key)
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            row = self._locked_goal(cursor, source_client_order_id)
            if row["plan_sha256"] != expected_plan_sha256:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_plan_binding_conflict"
                )
            if reserved_successor_client_order_id is not None:
                self._require_successor_binding(
                    row,
                    reserved_successor_client_order_id,
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_move_premark_cycle
                WHERE goal_id = %s AND idempotency_key_sha256 = %s
                FOR UPDATE
                """,
                (GOAL_ID, idempotency_hash),
            )
            cycles = _rows(cursor)
            if cycles:
                cycle = cycles[0]
                if not (
                    cycle["phase"] == phase
                    and cycle["actor_id_sha256"] == actor_hash
                    and cycle["correlation_id"] == correlation_id
                    and cycle["payload_sha256"] == payload_sha256
                ):
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_idempotency_conflict"
                    )
                return self._project(
                    cursor,
                    row,
                    cycle=cycle,
                    command_replayed=True,
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self.prefix}operator_parent_move_premark_cycle
                WHERE goal_id = %s AND completion_status = 'IN_FLIGHT'
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            if _rows(cursor):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_cycle_in_flight"
                )
            if phase == "EXECUTE":
                execute_available = row["state"] == "PLANNED" or (
                    row["state"] == "SOURCE_CANCELLED"
                    and row["source_cancel_allowance_consumed"] is True
                    and int(row["source_cancel_call_count"]) == 1
                    and row["replacement_create_allowance_consumed"]
                    is False
                    and int(row["replacement_create_call_count"]) == 0
                    and (
                        row["source_follow_up_suppressed"] is True
                        or row[
                            "source_cancel_event_acknowledged"
                        ]
                        is True
                    )
                )
                if not execute_available:
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_execute_unavailable"
                    )
            if (
                phase == "CLOSEOUT"
                and row["state"] != "REPLACEMENT_CREATED"
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_closeout_unavailable"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_parent_move_premark_cycle
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            cycle_number = int(cursor.fetchone()[0]) + 1
            if cycle_number > MAX_CYCLES:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_cycle_allowance_unavailable"
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_parent_move_premark_cycle (
                    goal_id, cycle_number, phase, completion_status,
                    actor_id_sha256, correlation_id,
                    idempotency_key_sha256,
                    payload_sha256
                ) VALUES (
                    %s, %s, %s, 'IN_FLIGHT', %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    GOAL_ID,
                    cycle_number,
                    phase,
                    actor_hash,
                    correlation_id,
                    idempotency_hash,
                    payload_sha256,
                ),
            )
            cycle = _one(cursor, "operator_parent_move_cycle_insert_failed")
            diagnostic = (
                "operator_parent_move_execute_started"
                if phase == "EXECUTE"
                else "operator_parent_move_closeout_started"
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (diagnostic, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="CYCLE_STARTED",
                diagnostic_code=diagnostic,
                evidence={
                    "cycle_number": cycle_number,
                    "phase": phase,
                },
            )
            return self._project(cursor, row, cycle=cycle)

    def _claim_mutation(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str | None,
        correlation_id: str,
        action: str,
        phase: str,
        expected_state: str,
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            if reserved_successor_client_order_id is not None:
                self._require_successor_binding(
                    row,
                    reserved_successor_client_order_id,
                )
            cursor.execute(
                f"""
                SELECT claim_state, allowance_consumed, cycle_number,
                       correlation_id
                FROM {self.prefix}operator_parent_move_premark_claim
                WHERE goal_id = %s AND action = %s
                FOR UPDATE
                """,
                (GOAL_ID, action),
            )
            existing_claims = _rows(cursor)
            reusable_claim = bool(
                len(existing_claims) == 1
                and existing_claims[0]["claim_state"]
                == "ABORTED_PRE_BOUNDARY"
                and existing_claims[0]["allowance_consumed"] is False
            )
            if existing_claims and not reusable_claim:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_allowance_unavailable"
                )
            cycle = self._require_active_cycle(
                cursor,
                correlation_id=correlation_id,
                phase=phase,
            )
            if reusable_claim and (
                int(existing_claims[0]["cycle_number"])
                == int(cycle["cycle_number"])
                or str(existing_claims[0]["correlation_id"])
                == correlation_id
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_allowance_unavailable"
                )
            if action == "SOURCE_CANCEL" and not row[
                "source_follow_up_suppressed"
            ]:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_source_suppression_required"
                )
            if row["state"] != expected_state:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_order_conflict"
                )
            if reusable_claim:
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_parent_move_premark_claim
                    SET cycle_number = %s, correlation_id = %s,
                        claim_state = 'CLAIMED', outcome_code = NULL,
                        exchange_evidence_sha256 = NULL,
                        boundary_crossed_at = NULL, resolved_at = NULL
                    WHERE goal_id = %s AND action = %s
                      AND claim_state = 'ABORTED_PRE_BOUNDARY'
                      AND NOT allowance_consumed
                    """,
                    (
                        cycle["cycle_number"],
                        correlation_id,
                        GOAL_ID,
                        action,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self.prefix}operator_parent_move_premark_claim (
                        goal_id, action, cycle_number, correlation_id,
                        claim_state
                    ) VALUES (%s, %s, %s, %s, 'CLAIMED')
                    """,
                    (
                        GOAL_ID,
                        action,
                        cycle["cycle_number"],
                        correlation_id,
                    ),
                )
            state = f"{action}_CLAIMED"
            diagnostic = _diagnostic_for(action, "claimed")
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET state = %s, diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="MUTATION_CLAIMED",
                diagnostic_code=diagnostic,
                evidence={
                    "action": action,
                    "cycle_number": int(cycle["cycle_number"]),
                },
            )
            return self._project(cursor, row, cycle=cycle)

    def _mark_mutation_boundary_crossed(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str | None,
        correlation_id: str,
        action: str,
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        allowance_column, count_column = _allowance_columns(action)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            if reserved_successor_client_order_id is not None:
                self._require_successor_binding(
                    row,
                    reserved_successor_client_order_id,
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_claim
                SET claim_state = 'BOUNDARY_CROSSED',
                    allowance_consumed = TRUE,
                    boundary_crossed_at = NOW()
                WHERE goal_id = %s AND action = %s
                  AND correlation_id = %s AND claim_state = 'CLAIMED'
                RETURNING cycle_number
                """,
                (GOAL_ID, action, correlation_id),
            )
            claims = _rows(cursor)
            if not claims:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_boundary_conflict"
                )
            state = f"{action}_BOUNDARY_CROSSED"
            diagnostic = _diagnostic_for(action, "invocation_started")
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET state = %s, {allowance_column} = TRUE,
                    {count_column} = 1, diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="MUTATION_BOUNDARY_CROSSED",
                diagnostic_code=diagnostic,
                evidence={"action": action},
            )
            return self._project(cursor, row)

    def _record_mutation_outcome(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str | None,
        correlation_id: str,
        cycle_number: int,
        action: str,
        outcome: str,
        diagnostic_code: str,
        exchange_evidence_sha256: str | None,
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        if (
            not isinstance(cycle_number, int)
            or isinstance(cycle_number, bool)
            or cycle_number < 1
            or cycle_number > MAX_CYCLES
        ):
            raise OperatorParentMovePremarkError(
                "operator_parent_move_cycle_number_invalid"
            )
        self._require_diagnostic(diagnostic_code)
        allowed = {
            "SOURCE_CANCEL": frozenset(
                {"CANCELLED", "REJECTED", "UNKNOWN"}
            ),
            "REPLACEMENT_CREATE": frozenset(
                {"ACCEPTED", "REJECTED", "UNKNOWN"}
            ),
            "SUCCESSOR_CLOSEOUT_CANCEL": frozenset(
                {"CANCELLED", "REJECTED", "UNKNOWN"}
            ),
        }[action]
        if outcome not in allowed:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_mutation_outcome_invalid"
            )
        if exchange_evidence_sha256 is not None:
            _require_sha(exchange_evidence_sha256)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            if reserved_successor_client_order_id is not None:
                self._require_successor_binding(
                    row,
                    reserved_successor_client_order_id,
                )
            cursor.execute(
                f"""
                SELECT c.claim_state, c.allowance_consumed
                FROM {self.prefix}operator_parent_move_premark_claim AS c
                JOIN {self.prefix}operator_parent_move_premark_cycle AS cy
                  ON cy.goal_id = c.goal_id
                 AND cy.cycle_number = c.cycle_number
                WHERE c.goal_id = %s AND c.action = %s
                  AND c.correlation_id = %s
                  AND c.cycle_number = %s
                  AND cy.correlation_id = %s
                  AND cy.completion_status = 'IN_FLIGHT'
                FOR UPDATE OF c, cy
                """,
                (
                    GOAL_ID,
                    action,
                    correlation_id,
                    cycle_number,
                    correlation_id,
                ),
            )
            claims = _rows(cursor)
            if len(claims) != 1:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_outcome_conflict"
                )
            crossed = (
                claims[0]["claim_state"] == "BOUNDARY_CROSSED"
                and claims[0]["allowance_consumed"] is True
            )
            pre_boundary_terminal = (
                claims[0]["claim_state"] == "CLAIMED"
                and claims[0]["allowance_consumed"] is False
                and outcome in {"REJECTED", "UNKNOWN"}
                and exchange_evidence_sha256 is None
            )
            if not (crossed or pre_boundary_terminal):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_outcome_conflict"
                )
            if (
                crossed
                and outcome != "UNKNOWN"
                and exchange_evidence_sha256 is None
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_exchange_evidence_required"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_claim
                SET claim_state = %s, outcome_code = %s,
                    exchange_evidence_sha256 = %s,
                    resolved_at = NOW()
                WHERE goal_id = %s AND action = %s
                  AND correlation_id = %s
                  AND cycle_number = %s
                  AND claim_state = %s
                  AND allowance_consumed = %s
                RETURNING cycle_number
                """,
                (
                    "UNKNOWN" if outcome == "UNKNOWN" else "RETURNED",
                    outcome,
                    exchange_evidence_sha256,
                    GOAL_ID,
                    action,
                    correlation_id,
                    cycle_number,
                    claims[0]["claim_state"],
                    claims[0]["allowance_consumed"],
                ),
            )
            if len(_rows(cursor)) != 1:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_mutation_outcome_conflict"
                )
            state = _outcome_state(action, outcome)
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET state = %s, diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic_code, GOAL_ID),
            )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="MUTATION_RETURNED",
                diagnostic_code=diagnostic_code,
                evidence={
                    "action": action,
                    "outcome": outcome,
                    "exchange_invoked": crossed,
                    "exchange_evidence_sha256": (
                        exchange_evidence_sha256
                    ),
                },
            )
            return self._project(cursor, row)

    def _abort_claim_before_boundary(
        self,
        *,
        source_client_order_id: str,
        reserved_successor_client_order_id: str | None,
        correlation_id: str,
        diagnostic_code: str,
        action: str,
        restored_state: str,
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        self._require_diagnostic(diagnostic_code)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal(cursor, source_client_order_id)
            if reserved_successor_client_order_id is not None:
                self._require_successor_binding(
                    row,
                    reserved_successor_client_order_id,
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_claim
                SET claim_state = 'ABORTED_PRE_BOUNDARY',
                    outcome_code = 'PRE_BOUNDARY_ABORTED',
                    resolved_at = NOW()
                WHERE goal_id = %s AND action = %s
                  AND correlation_id = %s
                  AND claim_state = 'CLAIMED'
                  AND NOT allowance_consumed
                RETURNING cycle_number
                """,
                (GOAL_ID, action, correlation_id),
            )
            claims = _rows(cursor)
            if len(claims) != 1:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_pre_boundary_abort_conflict"
                )
            if action == "SOURCE_CANCEL":
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_parent_move_premark_goal
                    SET state = %s, diagnostic_code = %s,
                        source_follow_up_suppressed = FALSE,
                        suppression_correlation_id = NULL,
                        updated_at = NOW()
                    WHERE goal_id = %s
                    RETURNING *
                    """,
                    (restored_state, diagnostic_code, GOAL_ID),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_parent_move_premark_goal
                    SET state = %s, diagnostic_code = %s,
                        updated_at = NOW()
                    WHERE goal_id = %s
                    RETURNING *
                    """,
                    (restored_state, diagnostic_code, GOAL_ID),
                )
            row = _one(cursor, "operator_parent_move_goal_not_found")
            self._append_event(
                cursor,
                source_client_order_id=source_client_order_id,
                event_type="MUTATION_ABORTED_PRE_BOUNDARY",
                diagnostic_code=diagnostic_code,
                evidence={
                    "action": action,
                    "allowance_consumed": False,
                    "restored_state": restored_state,
                },
            )
            return self._project(cursor, row)

    def _recover_boundary_crossed(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            SELECT c.action, c.cycle_number, g.source_client_order_id,
                   cy.phase, cy.correlation_id,
                   cy.idempotency_key_sha256,
                   cy.payload_sha256
            FROM {self.prefix}operator_parent_move_premark_claim AS c
            JOIN {self.prefix}operator_parent_move_premark_goal AS g
              ON g.goal_id = c.goal_id
            JOIN {self.prefix}operator_parent_move_premark_cycle AS cy
              ON cy.goal_id = c.goal_id
             AND cy.cycle_number = c.cycle_number
            WHERE c.claim_state = 'BOUNDARY_CROSSED'
            ORDER BY c.action
            FOR UPDATE OF c, g
            """
        )
        for claim in _rows(cursor):
            action = str(claim["action"])
            state = _outcome_state(action, "UNKNOWN")
            diagnostic = _diagnostic_for(action, "unknown")
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_claim
                SET claim_state = 'UNKNOWN', outcome_code = 'UNKNOWN',
                    resolved_at = NOW()
                WHERE goal_id = %s AND action = %s
                  AND claim_state = 'BOUNDARY_CROSSED'
                """,
                (GOAL_ID, action),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_goal
                SET state = %s, diagnostic_code = %s, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic, GOAL_ID),
            )
            goal_row = _one(
                cursor,
                "operator_parent_move_goal_not_found",
            )
            evidence_sha256 = self._cycle_evidence_sha256(
                cycle_number=int(claim["cycle_number"]),
                phase=str(claim["phase"]),
                correlation_id=str(claim["correlation_id"]),
                idempotency_key_sha256=str(
                    claim["idempotency_key_sha256"]
                ),
                payload_sha256=str(claim["payload_sha256"]),
                state=state,
                diagnostic_code=diagnostic,
                row=goal_row,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                  AND completion_status = 'IN_FLIGHT'
                """,
                (
                    state,
                    diagnostic,
                    evidence_sha256,
                    GOAL_ID,
                    claim["cycle_number"],
                ),
            )
            self._append_event(
                cursor,
                source_client_order_id=str(
                    claim["source_client_order_id"]
                ),
                event_type="MUTATION_RECOVERED_UNKNOWN",
                diagnostic_code=diagnostic,
                evidence={"action": action, "outcome": "UNKNOWN"},
            )

    def _recover_pre_boundary_inflight(self, cursor: Any) -> None:
        """Abort only unconsumed claims and complete stranded local cycles."""

        cursor.execute(
            f"""
            SELECT cy.*, g.source_client_order_id, g.state,
                   g.diagnostic_code, g.source_follow_up_suppressed,
                   g.suppression_correlation_id,
                   g.source_cancel_allowance_consumed,
                   g.replacement_create_allowance_consumed,
                   g.successor_closeout_cancel_allowance_consumed
            FROM {self.prefix}operator_parent_move_premark_cycle AS cy
            JOIN {self.prefix}operator_parent_move_premark_goal AS g
              ON g.goal_id = cy.goal_id
            WHERE cy.goal_id = %s
              AND cy.completion_status = 'IN_FLIGHT'
            ORDER BY cy.cycle_number
            FOR UPDATE OF cy, g
            """,
            (GOAL_ID,),
        )
        for cycle in _rows(cursor):
            cursor.execute(
                f"""
                SELECT action, claim_state, allowance_consumed
                FROM {self.prefix}operator_parent_move_premark_claim
                WHERE goal_id = %s AND cycle_number = %s
                ORDER BY action
                FOR UPDATE
                """,
                (GOAL_ID, cycle["cycle_number"]),
            )
            claims = _rows(cursor)
            if any(
                claim["claim_state"] == "BOUNDARY_CROSSED"
                for claim in claims
            ):
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_restart_recovery_incomplete"
                )
            active_claims = [
                claim
                for claim in claims
                if claim["claim_state"] == "CLAIMED"
            ]
            if len(active_claims) > 1:
                raise OperatorParentMovePremarkConflict(
                    "operator_parent_move_restart_recovery_invalid"
                )
            source_id = str(cycle["source_client_order_id"])
            state = str(cycle["state"])
            diagnostic = str(cycle["diagnostic_code"])
            if active_claims:
                claim = active_claims[0]
                if claim["allowance_consumed"] is not False:
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_restart_recovery_invalid"
                    )
                action = str(claim["action"])
                state = {
                    "SOURCE_CANCEL": "PLANNED",
                    "REPLACEMENT_CREATE": "SOURCE_CANCELLED",
                    "SUCCESSOR_CLOSEOUT_CANCEL": "REPLACEMENT_CREATED",
                }[action]
                diagnostic = _diagnostic_for(
                    action,
                    "pre_boundary_recovered",
                )
                if action == "SOURCE_CANCEL":
                    if (
                        cycle["source_follow_up_suppressed"] is not True
                        or cycle["suppression_correlation_id"]
                        != cycle["correlation_id"]
                    ):
                        raise OperatorParentMovePremarkConflict(
                            "operator_parent_move_restart_recovery_invalid"
                        )
                    suppression_update = (
                        ", source_follow_up_suppressed = FALSE"
                        ", suppression_correlation_id = NULL"
                    )
                else:
                    suppression_update = ""
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_parent_move_premark_claim
                    SET claim_state = 'ABORTED_PRE_BOUNDARY',
                        outcome_code = 'PRE_BOUNDARY_ABORTED',
                        resolved_at = NOW()
                    WHERE goal_id = %s AND action = %s
                      AND claim_state = 'CLAIMED'
                      AND NOT allowance_consumed
                    """,
                    (GOAL_ID, action),
                )
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_parent_move_premark_goal
                    SET state = %s, diagnostic_code = %s,
                        updated_at = NOW()
                        {suppression_update}
                    WHERE goal_id = %s
                    RETURNING *
                    """,
                    (state, diagnostic, GOAL_ID),
                )
                goal_row = _one(
                    cursor,
                    "operator_parent_move_goal_not_found",
                )
                self._append_event(
                    cursor,
                    source_client_order_id=source_id,
                    event_type="MUTATION_ABORTED_PRE_BOUNDARY",
                    diagnostic_code=diagnostic,
                    evidence={
                        "action": action,
                        "allowance_consumed": False,
                        "restart_recovered": True,
                        "restored_state": state,
                    },
                )
            else:
                allowed_states = {
                    "EXECUTE": frozenset(
                        {
                            "PLANNED",
                            "SOURCE_CANCELLED",
                            "SOURCE_CANCEL_REJECTED",
                            "SOURCE_CANCEL_UNKNOWN",
                            "REPLACEMENT_CREATED",
                            "REPLACEMENT_CREATE_REJECTED",
                            "REPLACEMENT_CREATE_UNKNOWN",
                        }
                    ),
                    "CLOSEOUT": frozenset(
                        {
                            "REPLACEMENT_CREATED",
                            "SUCCESSOR_CLOSED",
                            "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED",
                            "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN",
                        }
                    ),
                }[str(cycle["phase"])]
                if state not in allowed_states:
                    raise OperatorParentMovePremarkConflict(
                        "operator_parent_move_restart_recovery_invalid"
                    )
                clear_safe_suppression = (
                    str(cycle["phase"]) == "EXECUTE"
                    and state in {"PLANNED", *_SAFE_SUPPRESSION_FINAL_STATES}
                    and cycle["source_follow_up_suppressed"] is True
                )
                if clear_safe_suppression:
                    if (
                        cycle["suppression_correlation_id"]
                        != cycle["correlation_id"]
                    ):
                        raise OperatorParentMovePremarkConflict(
                            "operator_parent_move_restart_recovery_invalid"
                        )
                    cursor.execute(
                        f"""
                        UPDATE
                            {self.prefix}operator_parent_move_premark_goal
                        SET source_follow_up_suppressed = FALSE,
                            suppression_correlation_id = NULL,
                            updated_at = NOW()
                        WHERE goal_id = %s
                        RETURNING *
                        """,
                        (GOAL_ID,),
                    )
                    goal_row = _one(
                        cursor,
                        "operator_parent_move_goal_not_found",
                    )
                    if state in _SAFE_SUPPRESSION_FINAL_STATES:
                        self._append_event(
                            cursor,
                            source_client_order_id=source_id,
                            event_type="SOURCE_SUPPRESSION_FINALIZED",
                            diagnostic_code=(
                                "operator_parent_move_source_"
                                "suppression_finalized"
                            ),
                            evidence={
                                "active": False,
                                "restart_recovered": True,
                                "state": state,
                            },
                        )
                else:
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM {self.prefix}operator_parent_move_premark_goal
                        WHERE goal_id = %s
                        """,
                        (GOAL_ID,),
                    )
                    goal_row = _one(
                        cursor,
                        "operator_parent_move_goal_not_found",
                    )
                if not claims:
                    diagnostic = (
                        "operator_parent_move_execute_pre_boundary_recovered"
                        if cycle["phase"] == "EXECUTE"
                        else (
                            "operator_parent_move_closeout_"
                            "pre_boundary_recovered"
                        )
                    )
                    cursor.execute(
                        f"""
                        UPDATE
                            {self.prefix}operator_parent_move_premark_goal
                        SET diagnostic_code = %s, updated_at = NOW()
                        WHERE goal_id = %s
                        RETURNING *
                        """,
                        (diagnostic, GOAL_ID),
                    )
                    goal_row = _one(
                        cursor,
                        "operator_parent_move_goal_not_found",
                    )
            evidence_sha256 = self._cycle_evidence_sha256(
                cycle_number=int(cycle["cycle_number"]),
                phase=str(cycle["phase"]),
                correlation_id=str(cycle["correlation_id"]),
                idempotency_key_sha256=str(
                    cycle["idempotency_key_sha256"]
                ),
                payload_sha256=str(cycle["payload_sha256"]),
                state=state,
                diagnostic_code=diagnostic,
                row=goal_row,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_move_premark_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                  AND completion_status = 'IN_FLIGHT'
                """,
                (
                    state,
                    diagnostic,
                    evidence_sha256,
                    GOAL_ID,
                    cycle["cycle_number"],
                ),
            )
            self._append_event(
                cursor,
                source_client_order_id=source_id,
                event_type="CYCLE_COMPLETED",
                diagnostic_code=diagnostic,
                evidence={
                    "cycle_number": int(cycle["cycle_number"]),
                    "phase": str(cycle["phase"]),
                    "restart_recovered": True,
                    "state": state,
                },
            )

    def _project(
        self,
        cursor: Any,
        row: Mapping[str, Any],
        *,
        cycle: Mapping[str, Any] | None = None,
        command_replayed: bool = False,
    ) -> dict[str, Any]:
        _ = (row, cycle)
        snapshot = self._projection_snapshot(cursor)
        if snapshot is None:
            raise OperatorParentMovePremarkConflict(
                "operator_parent_move_goal_not_found"
            )
        return self._project_snapshot(
            snapshot,
            command_replayed=command_replayed,
        )

    def _projection_snapshot(self, cursor: Any) -> dict[str, Any] | None:
        """Read the goal and cycle summary from one MVCC statement."""

        cursor.execute(
            f"""
            SELECT
                g.*,
                (
                    SELECT COUNT(*)
                    FROM {self.prefix}operator_parent_move_premark_cycle AS cc
                    WHERE cc.goal_id = g.goal_id
                ) AS projection_cycle_count,
                latest.cycle_number AS projection_latest_cycle_number,
                latest.phase AS projection_latest_cycle_phase,
                latest.completion_status
                    AS projection_latest_cycle_status,
                latest.correlation_id
                    AS projection_latest_cycle_correlation_id,
                latest.actor_id_sha256
                    AS projection_latest_cycle_actor_id_sha256,
                latest.idempotency_key_sha256
                    AS projection_latest_cycle_idempotency_key_sha256,
                latest.payload_sha256
                    AS projection_latest_cycle_payload_sha256,
                latest.evidence_sha256
                    AS projection_latest_cycle_evidence_sha256,
                active.cycle_number AS projection_active_cycle_number,
                active.phase AS projection_active_cycle_phase,
                active.completion_status
                    AS projection_active_cycle_status
            FROM {self.prefix}operator_parent_move_premark_goal AS g
            LEFT JOIN LATERAL (
                SELECT cy.*
                FROM {self.prefix}operator_parent_move_premark_cycle AS cy
                WHERE cy.goal_id = g.goal_id
                ORDER BY cy.cycle_number DESC
                LIMIT 1
            ) AS latest ON TRUE
            LEFT JOIN LATERAL (
                SELECT cy.cycle_number, cy.phase, cy.completion_status
                FROM {self.prefix}operator_parent_move_premark_cycle AS cy
                WHERE cy.goal_id = g.goal_id
                  AND cy.completion_status = 'IN_FLIGHT'
                ORDER BY cy.cycle_number DESC
                LIMIT 1
            ) AS active ON TRUE
            WHERE g.goal_id = %s
            """,
            (GOAL_ID,),
        )
        rows = _rows(cursor)
        return rows[0] if rows else None

    @staticmethod
    def _project_snapshot(
        row: Mapping[str, Any],
        *,
        command_replayed: bool = False,
    ) -> dict[str, Any]:
        latest_cycle_number = row["projection_latest_cycle_number"]
        active_cycle_number = row["projection_active_cycle_number"]
        return {
            "goal_id": str(row["goal_id"]),
            "state": str(row["state"]),
            "diagnostic_code": str(row["diagnostic_code"]),
            "source_client_order_id": str(row["source_client_order_id"]),
            "reserved_successor_client_order_id": str(
                row["reserved_successor_client_order_id"]
            ),
            "plan": dict(row["plan_json"]),
            "plan_sha256": str(row["plan_sha256"]),
            "source_follow_up_suppressed": bool(
                row["source_follow_up_suppressed"]
            ),
            "source_cancel_event_acknowledged": bool(
                row["source_cancel_event_acknowledged"]
            ),
            "source_cancel_allowance_consumed": bool(
                row["source_cancel_allowance_consumed"]
            ),
            "replacement_create_allowance_consumed": bool(
                row["replacement_create_allowance_consumed"]
            ),
            "successor_closeout_cancel_allowance_consumed": bool(
                row["successor_closeout_cancel_allowance_consumed"]
            ),
            "source_cancel_call_count": int(
                row["source_cancel_call_count"]
            ),
            "replacement_create_call_count": int(
                row["replacement_create_call_count"]
            ),
            "successor_closeout_cancel_call_count": int(
                row["successor_closeout_cancel_call_count"]
            ),
            "cycle_count": int(row["projection_cycle_count"]),
            "latest_cycle_number": (
                int(latest_cycle_number)
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_phase": (
                str(row["projection_latest_cycle_phase"])
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_status": (
                str(row["projection_latest_cycle_status"])
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_correlation_id": (
                str(row["projection_latest_cycle_correlation_id"])
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_actor_id_sha256": (
                str(row["projection_latest_cycle_actor_id_sha256"])
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_idempotency_key_sha256": (
                str(
                    row[
                        "projection_latest_cycle_idempotency_key_sha256"
                    ]
                )
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_payload_sha256": (
                str(row["projection_latest_cycle_payload_sha256"])
                if latest_cycle_number is not None
                else None
            ),
            "latest_cycle_evidence_sha256": (
                (
                    str(row["projection_latest_cycle_evidence_sha256"])
                    if row["projection_latest_cycle_evidence_sha256"]
                    is not None
                    else None
                )
                if latest_cycle_number is not None
                else None
            ),
            "active_cycle_number": (
                int(active_cycle_number)
                if active_cycle_number is not None
                else None
            ),
            "active_cycle_phase": (
                str(row["projection_active_cycle_phase"])
                if active_cycle_number is not None
                else None
            ),
            "active_cycle_status": (
                str(row["projection_active_cycle_status"])
                if active_cycle_number is not None
                else None
            ),
            "command_replayed": command_replayed,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    def _locked_goal(
        self,
        cursor: Any,
        source_client_order_id: str,
    ) -> dict[str, Any]:
        source_id = _uuid(source_client_order_id)
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_parent_move_premark_goal
            WHERE goal_id = %s AND source_client_order_id = %s::uuid
            FOR UPDATE
            """,
            (GOAL_ID, source_id),
        )
        return _one(cursor, "operator_parent_move_goal_not_found")

    def _require_active_cycle(
        self,
        cursor: Any,
        *,
        correlation_id: str,
        phase: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_parent_move_premark_cycle
            WHERE goal_id = %s AND phase = %s
              AND correlation_id = %s
              AND completion_status = 'IN_FLIGHT'
            FOR UPDATE
            """,
            (GOAL_ID, phase, correlation_id),
        )
        return _one(cursor, "operator_parent_move_active_cycle_required")

    @staticmethod
    def _require_successor_binding(
        row: Mapping[str, Any],
        reserved_successor_client_order_id: str,
    ) -> None:
        if str(row["reserved_successor_client_order_id"]) != _uuid(
            reserved_successor_client_order_id
        ):
            raise OperatorParentMovePremarkConflict(
                "operator_parent_move_successor_binding_conflict"
            )

    @staticmethod
    def _require_plan(
        plan: Mapping[str, Any],
        plan_sha256: str,
    ) -> dict[str, Any]:
        _require_sha(plan_sha256)
        if not isinstance(plan, Mapping):
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_invalid"
            )
        normalized = dict(plan)
        if not set(normalized).issubset(_ALLOWED_PLAN_KEYS):
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_not_sanitized"
            )
        if normalized.get("goal_id") != GOAL_ID:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_invalid"
            )
        source_id = _uuid(
            str(normalized.get("source_client_order_id", ""))
        )
        successor_id = _uuid(
            str(
                normalized.get(
                    "reserved_successor_client_order_id",
                    "",
                )
            )
        )
        if source_id == successor_id:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_invalid"
            )
        normalized["source_client_order_id"] = source_id
        normalized["reserved_successor_client_order_id"] = successor_id
        _require_sanitized_json(normalized)
        if _canonical_sha(normalized) != plan_sha256:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_hash_invalid"
            )
        return normalized

    @staticmethod
    def _require_command_identity(
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> None:
        for value in (actor_id, correlation_id, idempotency_key):
            if not isinstance(value, str) or _EVIDENCE_ID.fullmatch(value) is None:
                raise OperatorParentMovePremarkError(
                    "operator_parent_move_command_identity_invalid"
                )
        _require_sha(payload_sha256)

    @staticmethod
    def _require_evidence_id(value: str) -> None:
        if not isinstance(value, str) or _EVIDENCE_ID.fullmatch(value) is None:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_command_identity_invalid"
            )

    @staticmethod
    def _require_diagnostic(value: str) -> None:
        if not isinstance(value, str) or _DIAGNOSTIC.fullmatch(value) is None:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_diagnostic_invalid"
            )

    @staticmethod
    def _cycle_evidence_sha256(
        *,
        cycle_number: int,
        phase: str,
        correlation_id: str,
        idempotency_key_sha256: str,
        payload_sha256: str,
        state: str,
        diagnostic_code: str,
        row: Mapping[str, Any],
    ) -> str:
        return _canonical_sha(
            {
                "goal_id": GOAL_ID,
                "cycle_number": cycle_number,
                "phase": phase,
                "correlation_id": correlation_id,
                "idempotency_key_sha256": idempotency_key_sha256,
                "payload_sha256": payload_sha256,
                "state": state,
                "diagnostic_code": diagnostic_code,
                "plan_sha256": str(row["plan_sha256"]),
                "source_client_order_id": str(
                    row["source_client_order_id"]
                ),
                "reserved_successor_client_order_id": str(
                    row["reserved_successor_client_order_id"]
                ),
                "source_cancel_call_count": int(
                    row["source_cancel_call_count"]
                ),
                "replacement_create_call_count": int(
                    row["replacement_create_call_count"]
                ),
                "successor_closeout_cancel_call_count": int(
                    row["successor_closeout_cancel_call_count"]
                ),
            }
        )

    def _append_event(
        self,
        cursor: Any,
        *,
        source_client_order_id: str,
        event_type: str,
        diagnostic_code: str,
        evidence: Mapping[str, Any],
    ) -> None:
        self._require_diagnostic(diagnostic_code)
        _require_sanitized_json(evidence)
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_parent_move_premark_event (
                goal_id, source_client_order_id, event_type,
                diagnostic_code, evidence_json
            ) VALUES (%s, %s::uuid, %s, %s, %s)
            """,
            (
                GOAL_ID,
                _uuid(source_client_order_id),
                event_type,
                diagnostic_code,
                Json(dict(evidence)),
            ),
        )

    @staticmethod
    def _lock_idempotency(cursor: Any, key: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"{GOAL_ID}:{_sha(key)}",),
        )

    @staticmethod
    def _lock_goal(cursor: Any) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (GOAL_ID,),
        )


def _diagnostic_for(action: str, suffix: str) -> str:
    return {
        "SOURCE_CANCEL": f"operator_parent_move_source_cancel_{suffix}",
        "REPLACEMENT_CREATE": (
            f"operator_parent_move_replacement_create_{suffix}"
        ),
        "SUCCESSOR_CLOSEOUT_CANCEL": (
            f"operator_parent_move_successor_closeout_cancel_{suffix}"
        ),
    }[action]


def _allowance_columns(action: str) -> tuple[str, str]:
    return {
        "SOURCE_CANCEL": (
            "source_cancel_allowance_consumed",
            "source_cancel_call_count",
        ),
        "REPLACEMENT_CREATE": (
            "replacement_create_allowance_consumed",
            "replacement_create_call_count",
        ),
        "SUCCESSOR_CLOSEOUT_CANCEL": (
            "successor_closeout_cancel_allowance_consumed",
            "successor_closeout_cancel_call_count",
        ),
    }[action]


def _outcome_state(action: str, outcome: str) -> str:
    return {
        ("SOURCE_CANCEL", "CANCELLED"): "SOURCE_CANCELLED",
        ("SOURCE_CANCEL", "REJECTED"): "SOURCE_CANCEL_REJECTED",
        ("SOURCE_CANCEL", "UNKNOWN"): "SOURCE_CANCEL_UNKNOWN",
        ("REPLACEMENT_CREATE", "ACCEPTED"): "REPLACEMENT_CREATED",
        (
            "REPLACEMENT_CREATE",
            "REJECTED",
        ): "REPLACEMENT_CREATE_REJECTED",
        (
            "REPLACEMENT_CREATE",
            "UNKNOWN",
        ): "REPLACEMENT_CREATE_UNKNOWN",
        (
            "SUCCESSOR_CLOSEOUT_CANCEL",
            "CANCELLED",
        ): "SUCCESSOR_CLOSED",
        (
            "SUCCESSOR_CLOSEOUT_CANCEL",
            "REJECTED",
        ): "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED",
        (
            "SUCCESSOR_CLOSEOUT_CANCEL",
            "UNKNOWN",
        ): "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN",
    }[(action, outcome)]


def _require_sanitized_json(value: Any, *, key: str | None = None) -> None:
    if key is not None:
        normalized_key = key.lower()
        if (
            normalized_key in _FORBIDDEN_PLAN_KEYS
            or normalized_key.startswith("raw_")
            or normalized_key.endswith("_message")
            or normalized_key.endswith("_secret")
            or normalized_key.endswith("_response")
        ):
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_not_sanitized"
            )
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 255:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_not_sanitized"
            )
        if key is not None and key.lower().endswith("_sha256"):
            _require_sha(value)
        return
    if isinstance(value, Mapping):
        for nested_key, nested_value in value.items():
            if not isinstance(nested_key, str):
                raise OperatorParentMovePremarkError(
                    "operator_parent_move_plan_not_sanitized"
                )
            _require_sanitized_json(nested_value, key=nested_key)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 100:
            raise OperatorParentMovePremarkError(
                "operator_parent_move_plan_not_sanitized"
            )
        for nested in value:
            _require_sanitized_json(nested)
        return
    raise OperatorParentMovePremarkError(
        "operator_parent_move_plan_not_sanitized"
    )


def _uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OperatorParentMovePremarkError(
            "operator_parent_move_identity_invalid"
        ) from exc
    if parsed.version != 4:
        raise OperatorParentMovePremarkError(
            "operator_parent_move_identity_invalid"
        )
    return str(parsed)


def _require_sha(value: str | None) -> None:
    if value is None or _SHA256.fullmatch(str(value)) is None:
        raise OperatorParentMovePremarkError(
            "operator_parent_move_sha256_invalid"
        )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorParentMovePremarkConflict(code)
    return rows[0]


@lru_cache(maxsize=1)
def get_default_operator_parent_move_premark_repository(
) -> OperatorParentMovePremarkRepository:
    repository = OperatorParentMovePremarkRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def initialize_operator_parent_move_premark_schema() -> None:
    """Install Goal 14 schema only; application runtime owns recovery."""

    get_default_operator_parent_move_premark_repository().ensure_schema()


__all__ = [
    "GOAL_ID",
    "MAX_CYCLES",
    "OperatorParentMovePremarkConflict",
    "OperatorParentMovePremarkError",
    "OperatorParentMovePremarkRepository",
    "get_default_operator_parent_move_premark_repository",
    "initialize_operator_parent_move_premark_schema",
]
