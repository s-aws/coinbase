"""PostgreSQL goal ledger for one operator stealth reveal and closeout."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from database.database import PostgresDB


GOAL_ID = "operator_stealth_reveal_and_exact_closeout_v1"
_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_IDENTITY_LOCK_NAMESPACE = 31873
_PLAN_FIELDS = frozenset(
    {
        "product_id",
        "side",
        "base_size",
        "limit_price",
        "configured_limit_price",
        "submitted_limit_price",
        "reveal_pricing_policy",
        "reveal_price_source",
        "fallback_used",
        "market_source",
        "market_bid",
        "market_ask",
        "target_movement",
        "target_movement_type",
        "target_movement_source",
        "post_only",
    }
)
_READ_CATEGORIES = frozenset(
    {
        "REVEAL_PORTFOLIO_BINDING",
        "REVEAL_API_KEY_PERMISSIONS",
        "REVEAL_PORTFOLIO_CATALOG",
        "REVEAL_WALLET_ADMISSION",
        "CLOSEOUT_PORTFOLIO_BINDING",
        "CLOSEOUT_API_KEY_PERMISSIONS",
        "CLOSEOUT_PORTFOLIO_CATALOG",
        "EXACT_PRE_CANCEL_READBACK",
        "EXACT_POST_CANCEL_READBACK",
    }
)
_READ_RESULT_CODES = frozenset(
    {
        "READY",
        "NOT_READY",
        "AUTHORITATIVE",
        "NOT_AUTHORITATIVE",
        "UNKNOWN",
    }
)
_AUTHORITATIVE_STATUSES = frozenset(
    {"OPEN", "PENDING", "CANCEL_QUEUED", "FILLED", "CANCELLED"}
)
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


class OperatorStealthRevealError(ValueError):
    """Fixed-code reveal repository failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OperatorStealthRevealConflict(OperatorStealthRevealError):
    """A durable state or single-use allowance conflicts with the request."""


class OperatorStealthRevealRepository:
    """Single-goal, revision-bound reveal and exact-closeout ledger."""

    def __init__(self, database: PostgresDB, *, schema: str = "public") -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_reveal_schema_invalid"
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
                    {self.prefix}operator_stealth_reveal_goal (
                    goal_id TEXT PRIMARY KEY CHECK (
                        goal_id =
                        'operator_stealth_reveal_and_exact_closeout_v1'
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'MATERIALIZING', 'MATERIALIZED',
                            'PREVIEW_CLAIMED', 'PREVIEW_ACCEPTED',
                            'PREVIEW_REJECTED', 'PREVIEW_UNKNOWN',
                            'CREATE_CLAIMED', 'REVEALED',
                            'CREATE_REJECTED', 'CREATE_UNKNOWN',
                            'CANCEL_CLAIMED', 'CANCELLED',
                            'FILLED', 'CANCEL_UNKNOWN'
                        )
                    ),
                    definition_id UUID NOT NULL UNIQUE,
                    definition_revision INTEGER NOT NULL CHECK (
                        definition_revision >= 1
                    ),
                    definition_sha256 CHAR(64) NOT NULL CHECK (
                        definition_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    portfolio_scope_sha256 CHAR(64) NOT NULL CHECK (
                        portfolio_scope_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    client_order_id UUID NOT NULL UNIQUE,
                    plan_json JSONB,
                    plan_sha256 CHAR(64) CHECK (
                        plan_sha256 IS NULL OR
                        plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    preview_claim_id UUID,
                    preview_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    create_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    preview_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        preview_call_count BETWEEN 0 AND 1
                    ),
                    create_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        create_call_count BETWEEN 0 AND 1
                    ),
                    cancel_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        cancel_call_count BETWEEN 0 AND 1
                    ),
                    read_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        read_call_count BETWEEN 0 AND 31
                    ),
                    prepreview_admission_sha256 CHAR(64) CHECK (
                        prepreview_admission_sha256 IS NULL OR
                        prepreview_admission_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    preview_outcome TEXT CHECK (
                        preview_outcome IS NULL OR
                        preview_outcome IN ('ACCEPTED', 'REJECTED', 'UNKNOWN')
                    ),
                    create_outcome TEXT CHECK (
                        create_outcome IS NULL OR
                        create_outcome IN ('ACCEPTED', 'REJECTED', 'UNKNOWN')
                    ),
                    cancel_outcome TEXT CHECK (
                        cancel_outcome IS NULL OR
                        cancel_outcome IN (
                            'CANCELLED', 'FILLED', 'UNKNOWN'
                        )
                    ),
                    exchange_order_id_sha256 CHAR(64) CHECK (
                        exchange_order_id_sha256 IS NULL OR
                        exchange_order_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~ '^[a-z][a-z0-9_]{{0,95}}$'
                    ),
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    reveal_idempotency_key TEXT NOT NULL UNIQUE,
                    reveal_payload_sha256 CHAR(64) NOT NULL CHECK (
                        reveal_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    reveal_result_json JSONB,
                    resume_idempotency_key TEXT UNIQUE,
                    resume_payload_sha256 CHAR(64) CHECK (
                        resume_payload_sha256 IS NULL OR
                        resume_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    resume_actor_id TEXT,
                    resume_correlation_id TEXT,
                    cancel_idempotency_key TEXT UNIQUE,
                    cancel_payload_sha256 CHAR(64) CHECK (
                        cancel_payload_sha256 IS NULL OR
                        cancel_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    cancel_actor_id TEXT,
                    cancel_correlation_id TEXT,
                    cancel_result_json JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS resume_idempotency_key TEXT UNIQUE
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS resume_payload_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS resume_actor_id TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS resume_correlation_id TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_goal_resume_payload_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD CONSTRAINT
                    operator_stealth_reveal_goal_resume_payload_check
                CHECK (
                    resume_payload_sha256 IS NULL OR
                    resume_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS cancel_actor_id TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS cancel_correlation_id TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD COLUMN IF NOT EXISTS prepreview_admission_sha256
                    CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_goal_prepreview_admission_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD CONSTRAINT
                    operator_stealth_reveal_goal_prepreview_admission_check
                CHECK (
                    prepreview_admission_sha256 IS NULL OR
                    prepreview_admission_sha256 ~ '^[0-9a-f]{{64}}$'
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_goal_read_call_count_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_stealth_reveal_goal
                ADD CONSTRAINT
                    operator_stealth_reveal_goal_read_call_count_check
                CHECK (read_call_count BETWEEN 0 AND 31)
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_stealth_reveal_read_call (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_stealth_reveal_goal(goal_id)
                        ON DELETE RESTRICT,
                    category TEXT NOT NULL CHECK (
                        category IN (
                            'REVEAL_PORTFOLIO_BINDING',
                            'REVEAL_API_KEY_PERMISSIONS',
                            'REVEAL_PORTFOLIO_CATALOG',
                            'REVEAL_WALLET_ADMISSION',
                            'CLOSEOUT_PORTFOLIO_BINDING',
                            'CLOSEOUT_API_KEY_PERMISSIONS',
                            'CLOSEOUT_PORTFOLIO_CATALOG',
                            'EXACT_PRE_CANCEL_READBACK',
                            'EXACT_POST_CANCEL_READBACK'
                        )
                    ),
                    correlation_id TEXT NOT NULL,
                    call_state TEXT NOT NULL CHECK (
                        call_state IN ('STARTED', 'RETURNED', 'UNKNOWN')
                    ),
                    result_code TEXT CHECK (
                        result_code IS NULL OR
                        result_code IN (
                            'READY', 'NOT_READY', 'AUTHORITATIVE',
                            'NOT_AUTHORITATIVE', 'UNKNOWN'
                        )
                    ),
                    authoritative_status TEXT CHECK (
                        authoritative_status IS NULL OR
                        authoritative_status IN (
                            'OPEN', 'PENDING', 'CANCEL_QUEUED',
                            'FILLED', 'CANCELLED'
                        )
                    ),
                    wire_call_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        wire_call_count BETWEEN 0 AND 1
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
                    {self.prefix}operator_stealth_reveal_read_call
                ADD COLUMN IF NOT EXISTS wire_call_count INTEGER
                    NOT NULL DEFAULT 0
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_read_call
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_read_call_wire_call_count_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_read_call
                ADD CONSTRAINT
                    operator_stealth_reveal_read_call_wire_call_count_check
                CHECK (wire_call_count BETWEEN 0 AND 1)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_read_call
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_read_call_category_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_read_call
                ADD CONSTRAINT
                    operator_stealth_reveal_read_call_category_check
                CHECK (
                    category IN (
                        'REVEAL_PORTFOLIO_BINDING',
                        'REVEAL_API_KEY_PERMISSIONS',
                        'REVEAL_PORTFOLIO_CATALOG',
                        'REVEAL_WALLET_ADMISSION',
                        'CLOSEOUT_PORTFOLIO_BINDING',
                        'CLOSEOUT_API_KEY_PERMISSIONS',
                        'CLOSEOUT_PORTFOLIO_CATALOG',
                        'EXACT_PRE_CANCEL_READBACK',
                        'EXACT_POST_CANCEL_READBACK'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_stealth_reveal_command_cycle (
                    goal_id TEXT NOT NULL REFERENCES
                        {self.prefix}operator_stealth_reveal_goal(goal_id)
                        ON DELETE RESTRICT,
                    cycle_number INTEGER NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND 10
                    ),
                    phase TEXT NOT NULL CHECK (
                        phase IN (
                            'REVEAL', 'RESUME_CREATE', 'CLOSEOUT'
                        )
                    ),
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    completion_status TEXT NOT NULL DEFAULT 'IN_FLIGHT'
                        CHECK (
                            completion_status IN (
                                'IN_FLIGHT', 'COMPLETED'
                            )
                        ),
                    terminal_goal_state TEXT,
                    terminal_diagnostic_code TEXT,
                    preview_call_count INTEGER,
                    create_call_count INTEGER,
                    cancel_call_count INTEGER,
                    read_call_count INTEGER,
                    completion_evidence_sha256 CHAR(64) CHECK (
                        completion_evidence_sha256 IS NULL OR
                        completion_evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (goal_id, cycle_number),
                    UNIQUE (goal_id, correlation_id),
                    UNIQUE (goal_id, idempotency_key)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_command_cycle
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_command_cycle_phase_check
                """
            )
            for column, ddl in (
                (
                    "completion_status",
                    "TEXT NOT NULL DEFAULT 'IN_FLIGHT'",
                ),
                ("terminal_goal_state", "TEXT"),
                ("terminal_diagnostic_code", "TEXT"),
                ("preview_call_count", "INTEGER"),
                ("create_call_count", "INTEGER"),
                ("cancel_call_count", "INTEGER"),
                ("read_call_count", "INTEGER"),
                ("completion_evidence_sha256", "CHAR(64)"),
                ("completed_at", "TIMESTAMPTZ"),
            ):
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self.prefix}operator_stealth_reveal_command_cycle
                    ADD COLUMN IF NOT EXISTS {column} {ddl}
                    """
                )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_command_cycle
                DROP CONSTRAINT IF EXISTS
                    operator_stealth_reveal_command_cycle_completion_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_command_cycle
                ADD CONSTRAINT
                    operator_stealth_reveal_command_cycle_completion_check
                CHECK (
                    completion_status IN ('IN_FLIGHT', 'COMPLETED')
                    AND (
                        preview_call_count IS NULL
                        OR preview_call_count BETWEEN 0 AND 1
                    )
                    AND (
                        create_call_count IS NULL
                        OR create_call_count BETWEEN 0 AND 1
                    )
                    AND (
                        cancel_call_count IS NULL
                        OR cancel_call_count BETWEEN 0 AND 1
                    )
                    AND (
                        read_call_count IS NULL
                        OR read_call_count BETWEEN 0 AND 31
                    )
                    AND (
                        (
                            completion_status = 'IN_FLIGHT'
                            AND terminal_goal_state IS NULL
                            AND terminal_diagnostic_code IS NULL
                            AND completion_evidence_sha256 IS NULL
                            AND completed_at IS NULL
                        )
                        OR (
                            completion_status = 'COMPLETED'
                            AND terminal_goal_state IS NOT NULL
                            AND terminal_diagnostic_code IS NOT NULL
                            AND preview_call_count IS NOT NULL
                            AND create_call_count IS NOT NULL
                            AND cancel_call_count IS NOT NULL
                            AND read_call_count IS NOT NULL
                            AND completion_evidence_sha256 IS NOT NULL
                            AND completed_at IS NOT NULL
                        )
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_stealth_reveal_command_cycle
                ADD CONSTRAINT
                    operator_stealth_reveal_command_cycle_phase_check
                CHECK (
                    phase IN (
                        'REVEAL', 'RESUME_CREATE', 'CLOSEOUT'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION
                    {self.prefix}operator_stealth_runtime_identity_guard()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $operator_stealth_runtime_identity_guard$
                DECLARE
                    claimed RECORD;
                BEGIN
                    PERFORM pg_advisory_xact_lock(
                        {_RUNTIME_IDENTITY_LOCK_NAMESPACE},
                        hashtext(NEW.stealth_order_id::text)
                    );
                    IF EXISTS (
                        SELECT 1
                        FROM {self.prefix}operator_stealth_definition
                        WHERE definition_id = NEW.stealth_order_id
                    ) THEN
                        SELECT state, definition_revision,
                               definition_sha256, definition_id
                        INTO claimed
                        FROM {self.prefix}operator_stealth_reveal_goal
                        WHERE goal_id = '{GOAL_ID}'
                          AND definition_id = NEW.stealth_order_id;
                        IF claimed IS NULL
                           OR claimed.state <> 'MATERIALIZING'
                           OR NOT EXISTS (
                               SELECT 1
                               FROM {self.prefix}operator_stealth_definition d
                               WHERE d.definition_id = claimed.definition_id
                                 AND d.lifecycle_state = 'DRAFT'
                                 AND d.revision =
                                     claimed.definition_revision
                                 AND d.definition_sha256 =
                                     claimed.definition_sha256
                           )
                        THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23505',
                                MESSAGE =
                                    'stealth_runtime_identity_reserved';
                        END IF;
                    END IF;
                    RETURN NEW;
                END
                $operator_stealth_runtime_identity_guard$
                """
            )
            cursor.execute(
                f"""
                DROP TRIGGER IF EXISTS
                    operator_stealth_runtime_identity_guard
                ON {self.prefix}stealth_orders
                """
            )
            cursor.execute(
                f"""
                CREATE TRIGGER
                    operator_stealth_runtime_identity_guard
                BEFORE INSERT OR UPDATE OF stealth_order_id
                ON {self.prefix}stealth_orders
                FOR EACH ROW
                EXECUTE FUNCTION
                    {self.prefix}operator_stealth_runtime_identity_guard()
                """
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET state = CASE
                        WHEN state = 'PREVIEW_CLAIMED'
                            THEN 'PREVIEW_UNKNOWN'
                        WHEN state = 'CREATE_CLAIMED'
                            THEN 'CREATE_UNKNOWN'
                        WHEN state = 'CANCEL_CLAIMED'
                            THEN 'CANCEL_UNKNOWN'
                        ELSE state
                    END,
                    preview_outcome = CASE
                        WHEN state = 'PREVIEW_CLAIMED' THEN 'UNKNOWN'
                        ELSE preview_outcome
                    END,
                    create_outcome = CASE
                        WHEN state = 'CREATE_CLAIMED' THEN 'UNKNOWN'
                        ELSE create_outcome
                    END,
                    cancel_outcome = CASE
                        WHEN state = 'CANCEL_CLAIMED' THEN 'UNKNOWN'
                        ELSE cancel_outcome
                    END,
                    diagnostic_code = CASE
                        WHEN state IN (
                            'PREVIEW_CLAIMED', 'CREATE_CLAIMED',
                            'CANCEL_CLAIMED'
                        ) THEN 'operator_stealth_interrupted_unknown'
                        ELSE diagnostic_code
                    END,
                    updated_at = NOW()
                WHERE state IN (
                    'PREVIEW_CLAIMED', 'CREATE_CLAIMED', 'CANCEL_CLAIMED'
                )
                """
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_read_call
                SET call_state = 'UNKNOWN',
                    result_code = 'UNKNOWN',
                    authoritative_status = NULL,
                    updated_at = NOW()
                WHERE call_state = 'STARTED'
                """
            )

    def begin_materialization(
        self,
        *,
        definition_id: str,
        expected_revision: int,
        expected_definition_sha256: str,
        expected_portfolio_scope_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_sha(expected_definition_sha256)
        self._require_sha(expected_portfolio_scope_sha256)
        self._require_sha(payload_sha256)
        normalized_id = self._uuid(definition_id)
        with self.database.get_cursor() as cursor:
            self._goal_lock(cursor)
            existing = self._goal(cursor)
            if existing:
                if (
                    str(existing["definition_id"]) == normalized_id
                    and existing["reveal_idempotency_key"]
                    == idempotency_key
                    and existing["reveal_payload_sha256"]
                    == payload_sha256
                ):
                    return self._project(existing, command_replayed=True)
                raise OperatorStealthRevealConflict(
                    "operator_stealth_reveal_allowance_unavailable"
                )
            cursor.execute(
                f"""
                SELECT definition_id, portfolio_scope_sha256,
                       lifecycle_state, revision, definition_sha256
                FROM {self.prefix}operator_stealth_definition
                WHERE definition_id = %s::uuid
                FOR UPDATE
                """,
                (normalized_id,),
            )
            definition = self._one(
                cursor,
                "operator_stealth_definition_not_found",
            )
            if (
                definition["lifecycle_state"] != "DRAFT"
                or int(definition["revision"]) != expected_revision
                or definition["definition_sha256"]
                != expected_definition_sha256
                or definition["portfolio_scope_sha256"]
                != expected_portfolio_scope_sha256
            ):
                raise OperatorStealthRevealConflict(
                    "operator_stealth_definition_binding_conflict"
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self.prefix}stealth_orders
                WHERE stealth_order_id = %s::uuid
                """,
                (normalized_id,),
            )
            if cursor.fetchone() is not None:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_runtime_identity_conflict"
                )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_stealth_reveal_goal (
                    goal_id, state, definition_id, definition_revision,
                    definition_sha256, portfolio_scope_sha256,
                    client_order_id, diagnostic_code, actor_id,
                    correlation_id, reveal_idempotency_key,
                    reveal_payload_sha256
                ) VALUES (
                    %s, 'MATERIALIZING', %s::uuid, %s, %s, %s,
                    %s::uuid, 'operator_stealth_materializing',
                    %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    GOAL_ID,
                    normalized_id,
                    expected_revision,
                    expected_definition_sha256,
                    expected_portfolio_scope_sha256,
                    normalized_id,
                    actor_id,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                ),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def record_materialized(self, definition_id: str) -> dict[str, Any]:
        return self._transition(
            definition_id,
            expected_state="MATERIALIZING",
            state="MATERIALIZED",
            diagnostic_code="operator_stealth_materialized",
            require_runtime=True,
        )

    def record_prepreview_admission(
        self,
        definition_id: str,
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        admission_sha256: str,
    ) -> dict[str, Any]:
        self._require_plan(plan, plan_sha256)
        self._require_sha(admission_sha256)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if (
                row["state"] != "MATERIALIZED"
                or row["preview_allowance_consumed"]
                or int(row["preview_call_count"]) != 0
            ):
                raise OperatorStealthRevealConflict(
                    "operator_stealth_prepreview_admission_conflict"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET plan_json = %s,
                    plan_sha256 = %s,
                    prepreview_admission_sha256 = %s,
                    diagnostic_code =
                        'operator_stealth_prepreview_admission_ready',
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (
                    Json(plan),
                    plan_sha256,
                    admission_sha256,
                    GOAL_ID,
                ),
            )
            return self._project(
                self._one(cursor, "operator_stealth_goal_missing")
            )

    def record_prepreview_cap_blocked(
        self,
        definition_id: str,
        *,
        plan: dict[str, Any],
        plan_sha256: str,
    ) -> dict[str, Any]:
        self._require_plan(plan, plan_sha256)
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if (
                row["state"] != "MATERIALIZED"
                or row["preview_allowance_consumed"]
                or int(row["preview_call_count"]) != 0
                or row["create_allowance_consumed"]
                or int(row["create_call_count"]) != 0
            ):
                raise OperatorStealthRevealConflict(
                    "operator_stealth_prepreview_cap_conflict"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET plan_json = %s,
                    plan_sha256 = %s,
                    prepreview_admission_sha256 = NULL,
                    diagnostic_code =
                        'operator_stealth_prepreview_cap_blocked',
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (Json(plan), plan_sha256, GOAL_ID),
            )
            return self._project(
                self._one(cursor, "operator_stealth_goal_missing")
            )

    def claim_preview(
        self,
        definition_id: str,
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        admission_sha256: str,
    ) -> dict[str, Any]:
        self._require_plan(plan, plan_sha256)
        self._require_sha(admission_sha256)
        claim_id = str(uuid.uuid4())
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if (
                row["state"] != "MATERIALIZED"
                or row["preview_allowance_consumed"]
                or int(row["preview_call_count"]) != 0
                or dict(row.get("plan_json") or {}) != plan
                or row.get("plan_sha256") != plan_sha256
                or row.get("prepreview_admission_sha256")
                != admission_sha256
            ):
                raise OperatorStealthRevealConflict(
                    "operator_stealth_preview_allowance_unavailable"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET state = 'PREVIEW_CLAIMED',
                    plan_json = %s,
                    plan_sha256 = %s,
                    preview_claim_id = %s::uuid,
                    preview_allowance_consumed = TRUE,
                    preview_call_count = 1,
                    diagnostic_code =
                        'operator_stealth_preview_invocation_started',
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (Json(plan), plan_sha256, claim_id, GOAL_ID),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def record_preview_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        states = {
            "ACCEPTED": "PREVIEW_ACCEPTED",
            "REJECTED": "PREVIEW_REJECTED",
            "UNKNOWN": "PREVIEW_UNKNOWN",
        }
        if outcome not in states:
            raise OperatorStealthRevealError(
                "operator_stealth_preview_outcome_invalid"
            )
        return self._transition(
            definition_id,
            expected_state="PREVIEW_CLAIMED",
            state=states[outcome],
            diagnostic_code=diagnostic_code,
            assignments={"preview_outcome": outcome},
        )

    def record_preview_preflight_rejection(
        self,
        definition_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            definition_id,
            expected_state="MATERIALIZED",
            state="PREVIEW_REJECTED",
            diagnostic_code="operator_stealth_preview_preflight_rejected",
            assignments={"preview_outcome": "REJECTED"},
        )

    def claim_create(self, definition_id: str) -> dict[str, Any]:
        return self._claim_call(
            definition_id,
            expected_state="PREVIEW_ACCEPTED",
            state="CREATE_CLAIMED",
            allowance_field="create_allowance_consumed",
            count_field="create_call_count",
            diagnostic_code="operator_stealth_create_invocation_started",
        )

    def record_create_preflight_rejection(
        self,
        definition_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            definition_id,
            expected_state="PREVIEW_ACCEPTED",
            state="CREATE_REJECTED",
            diagnostic_code="operator_stealth_create_preflight_rejected",
            assignments={"create_outcome": "REJECTED"},
        )

    def record_create_cap_rejection(
        self,
        definition_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            definition_id,
            expected_state="PREVIEW_ACCEPTED",
            state="CREATE_REJECTED",
            diagnostic_code="operator_stealth_create_cap_blocked",
            assignments={"create_outcome": "REJECTED"},
        )

    def record_create_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
    ) -> dict[str, Any]:
        states = {
            "ACCEPTED": "REVEALED",
            "REJECTED": "CREATE_REJECTED",
            "UNKNOWN": "CREATE_UNKNOWN",
        }
        if outcome not in states:
            raise OperatorStealthRevealError(
                "operator_stealth_create_outcome_invalid"
            )
        if outcome == "ACCEPTED":
            self._require_sha(exchange_order_id_sha256)
        elif exchange_order_id_sha256 is not None:
            raise OperatorStealthRevealError(
                "operator_stealth_exchange_identity_invalid"
            )
        return self._transition(
            definition_id,
            expected_state="CREATE_CLAIMED",
            state=states[outcome],
            diagnostic_code=diagnostic_code,
            assignments={
                "create_outcome": outcome,
                "exchange_order_id_sha256": exchange_order_id_sha256,
            },
        )

    def claim_cancel(self, definition_id: str) -> dict[str, Any]:
        return self._claim_call(
            definition_id,
            expected_state="REVEALED",
            state="CANCEL_CLAIMED",
            allowance_field="cancel_allowance_consumed",
            count_field="cancel_call_count",
            diagnostic_code="operator_stealth_cancel_invocation_started",
        )

    def record_cancel_preflight_rejection(
        self,
        definition_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            definition_id,
            expected_state="REVEALED",
            state="REVEALED",
            diagnostic_code="operator_stealth_cancel_preflight_rejected",
            assignments={},
        )

    def record_terminal_without_cancel(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        if outcome not in {"CANCELLED", "FILLED"}:
            raise OperatorStealthRevealError(
                "operator_stealth_terminal_outcome_invalid"
            )
        return self._transition(
            definition_id,
            expected_state="REVEALED",
            state=outcome,
            diagnostic_code=diagnostic_code,
            assignments={"cancel_outcome": outcome},
        )

    def record_cancel_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        states = {
            "CANCELLED": "CANCELLED",
            "FILLED": "FILLED",
            "UNKNOWN": "CANCEL_UNKNOWN",
        }
        if outcome not in states:
            raise OperatorStealthRevealError(
                "operator_stealth_cancel_outcome_invalid"
            )
        return self._transition(
            definition_id,
            expected_state="CANCEL_CLAIMED",
            state=states[outcome],
            diagnostic_code=diagnostic_code,
            assignments={"cancel_outcome": outcome},
        )

    def begin_closeout(
        self,
        definition_id: str,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._require_sha(payload_sha256)
        if not actor_id or _EVIDENCE_ID.fullmatch(correlation_id) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_identity_invalid"
            )
        if _EVIDENCE_ID.fullmatch(idempotency_key) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_idempotency_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            existing_key = row.get("cancel_idempotency_key")
            if existing_key is not None:
                if (
                    existing_key == idempotency_key
                    and row.get("cancel_payload_sha256") == payload_sha256
                ):
                    return self._project(row, command_replayed=True)
                if (
                    row["state"] == "REVEALED"
                    and not row["cancel_allowance_consumed"]
                    and row.get("cancel_payload_sha256") == payload_sha256
                ):
                    return self._project(row)
                raise OperatorStealthRevealConflict(
                    "operator_stealth_closeout_idempotency_conflict"
                )
            if row["state"] not in {
                "REVEALED",
                "CANCEL_CLAIMED",
                "CANCELLED",
                "FILLED",
                "CANCEL_UNKNOWN",
            }:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_closeout_not_available"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET cancel_idempotency_key = %s,
                    cancel_payload_sha256 = %s,
                    cancel_actor_id = %s,
                    cancel_correlation_id = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (
                    idempotency_key,
                    payload_sha256,
                    actor_id,
                    correlation_id,
                    GOAL_ID,
                ),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def begin_command_cycle(
        self,
        definition_id: str,
        *,
        phase: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        if phase not in {"REVEAL", "RESUME_CREATE", "CLOSEOUT"}:
            raise OperatorStealthRevealError(
                "operator_stealth_cycle_phase_invalid"
            )
        self._require_sha(payload_sha256)
        if (
            not actor_id
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_cycle_identity_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            cursor.execute(
                f"""
                SELECT cycle_number, phase, correlation_id,
                       idempotency_key, payload_sha256
                FROM {self.prefix}operator_stealth_reveal_command_cycle
                WHERE goal_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (GOAL_ID, idempotency_key),
            )
            rows = self._rows(cursor)
            if rows:
                existing = rows[0]
                if (
                    existing["phase"] == phase
                    and existing["correlation_id"] == correlation_id
                    and existing["payload_sha256"] == payload_sha256
                ):
                    return {
                        "cycle_number": int(existing["cycle_number"]),
                        "command_replayed": True,
                    }
                raise OperatorStealthRevealConflict(
                    "operator_stealth_cycle_idempotency_conflict"
                )
            if phase == "REVEAL":
                expected_payload = row["reveal_payload_sha256"]
                expected_states = {"MATERIALIZING", "MATERIALIZED"}
            elif phase == "RESUME_CREATE":
                # A process may stop after persisting a resume command but
                # before the Create claim. A later explicit operator command
                # gets its own cycle/key while the durable PREVIEW_ACCEPTED
                # state still proves that no Create call was claimed.
                expected_payload = payload_sha256
                expected_states = {"PREVIEW_ACCEPTED"}
            else:
                expected_payload = row.get("cancel_payload_sha256")
                expected_states = {"REVEALED"}
            if (
                expected_payload != payload_sha256
                or row["state"] not in expected_states
            ):
                raise OperatorStealthRevealConflict(
                    "operator_stealth_cycle_binding_conflict"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_reveal_command_cycle
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            cycle_count = int(cursor.fetchone()[0])
            if cycle_count >= 10:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_cycle_allowance_unavailable"
                )
            cycle_number = cycle_count + 1
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_stealth_reveal_command_cycle (
                    goal_id, cycle_number, phase, actor_id,
                    correlation_id, idempotency_key, payload_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    GOAL_ID,
                    cycle_number,
                    phase,
                    actor_id,
                    correlation_id,
                    idempotency_key,
                    payload_sha256,
                ),
            )
            if phase == "RESUME_CREATE":
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_stealth_reveal_goal
                    SET resume_actor_id = %s,
                        resume_correlation_id = %s,
                        resume_idempotency_key = %s,
                        resume_payload_sha256 = %s,
                        updated_at = NOW()
                    WHERE goal_id = %s
                    """,
                    (
                        actor_id,
                        correlation_id,
                        idempotency_key,
                        payload_sha256,
                        GOAL_ID,
                    ),
                )
            else:
                correlation_column = (
                    "correlation_id"
                    if phase == "REVEAL"
                    else "cancel_correlation_id"
                )
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_stealth_reveal_goal
                    SET {correlation_column} = %s, updated_at = NOW()
                    WHERE goal_id = %s
                    """,
                    (correlation_id, GOAL_ID),
                )
            return {
                "cycle_number": cycle_number,
                "command_replayed": False,
            }

    def record_command_completion(
        self,
        definition_id: str,
        *,
        phase: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if phase not in {"REVEAL", "RESUME_CREATE", "CLOSEOUT"}:
            raise OperatorStealthRevealError(
                "operator_stealth_cycle_phase_invalid"
            )
        if (
            _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_cycle_identity_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_reveal_command_cycle
                WHERE goal_id = %s
                  AND phase = %s
                  AND correlation_id = %s
                  AND idempotency_key = %s
                FOR UPDATE
                """,
                (
                    GOAL_ID,
                    phase,
                    correlation_id,
                    idempotency_key,
                ),
            )
            cycle = self._one(
                cursor,
                "operator_stealth_command_cycle_not_found",
            )
            if cycle["completion_status"] == "COMPLETED":
                return self._project(row, command_cycle=cycle)
            if row["state"] in {
                "PREVIEW_CLAIMED",
                "CREATE_CLAIMED",
                "CANCEL_CLAIMED",
            }:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_command_completion_unavailable"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_reveal_read_call
                WHERE goal_id = %s
                  AND correlation_id = %s
                  AND call_state = 'STARTED'
                """,
                (GOAL_ID, correlation_id),
            )
            if int(cursor.fetchone()[0]) != 0:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_command_completion_unavailable"
                )
            evidence = {
                "goal_id": GOAL_ID,
                "cycle_number": int(cycle["cycle_number"]),
                "phase": phase,
                "correlation_id": correlation_id,
                "idempotency_key_sha256": hashlib.sha256(
                    idempotency_key.encode()
                ).hexdigest(),
                "payload_sha256": cycle["payload_sha256"],
                "terminal_goal_state": row["state"],
                "terminal_diagnostic_code": row["diagnostic_code"],
                "preview_call_count": int(row["preview_call_count"]),
                "create_call_count": int(row["create_call_count"]),
                "cancel_call_count": int(row["cancel_call_count"]),
                "read_call_count": int(row["read_call_count"]),
            }
            completion_evidence_sha256 = hashlib.sha256(
                json.dumps(
                    evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_command_cycle
                SET completion_status = 'COMPLETED',
                    terminal_goal_state = %s,
                    terminal_diagnostic_code = %s,
                    preview_call_count = %s,
                    create_call_count = %s,
                    cancel_call_count = %s,
                    read_call_count = %s,
                    completion_evidence_sha256 = %s,
                    completed_at = NOW()
                WHERE goal_id = %s AND cycle_number = %s
                  AND completion_status = 'IN_FLIGHT'
                RETURNING *
                """,
                (
                    row["state"],
                    row["diagnostic_code"],
                    int(row["preview_call_count"]),
                    int(row["create_call_count"]),
                    int(row["cancel_call_count"]),
                    int(row["read_call_count"]),
                    completion_evidence_sha256,
                    GOAL_ID,
                    int(cycle["cycle_number"]),
                ),
            )
            completed = self._one(
                cursor,
                "operator_stealth_command_completion_missing",
            )
            return self._project(row, command_cycle=completed)

    def record_condition_not_ready(
        self,
        definition_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if row["state"] != "MATERIALIZED":
                raise OperatorStealthRevealConflict(
                    "operator_stealth_transition_conflict"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET diagnostic_code =
                        'operator_stealth_condition_not_ready',
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (GOAL_ID,),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def claim_read_call(
        self,
        definition_id: str,
        *,
        category: str,
        correlation_id: str,
        wire_call: bool = True,
    ) -> dict[str, Any]:
        if category not in _READ_CATEGORIES:
            raise OperatorStealthRevealError(
                "operator_stealth_read_category_invalid"
            )
        if _EVIDENCE_ID.fullmatch(correlation_id) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_read_correlation_invalid"
            )
        with self.database.get_cursor() as cursor:
            self._locked_goal_for_definition(cursor, definition_id)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_reveal_read_call
                WHERE goal_id = %s AND category = %s
                  AND correlation_id = %s
                FOR UPDATE
                """,
                (GOAL_ID, category, correlation_id),
            )
            rows = self._rows(cursor)
            if rows:
                return self._project_read(rows[0], invoke_required=False)
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_reveal_read_call
                WHERE goal_id = %s AND category = %s
                """,
                (GOAL_ID, category),
            )
            if int(cursor.fetchone()[0]) >= 10:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_read_cycle_allowance_unavailable"
                )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_stealth_reveal_read_call (
                    goal_id, category, correlation_id, call_state,
                    wire_call_count
                ) VALUES (%s, %s, %s, 'STARTED', %s)
                RETURNING *
                """,
                (
                    GOAL_ID,
                    category,
                    correlation_id,
                    1 if wire_call else 0,
                ),
            )
            read_row = self._one(
                cursor,
                "operator_stealth_read_claim_missing",
            )
            if wire_call:
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_stealth_reveal_goal
                    SET read_call_count = read_call_count + 1,
                        updated_at = NOW()
                    WHERE goal_id = %s AND read_call_count < 31
                    RETURNING goal_id
                    """,
                    (GOAL_ID,),
                )
                if cursor.fetchone() is None:
                    raise OperatorStealthRevealConflict(
                        "operator_stealth_read_allowance_unavailable"
                    )
            return self._project_read(read_row, invoke_required=True)

    def record_read_call_outcome(
        self,
        definition_id: str,
        *,
        category: str,
        correlation_id: str,
        result_code: str,
        authoritative_status: str | None = None,
    ) -> dict[str, Any]:
        if category not in _READ_CATEGORIES:
            raise OperatorStealthRevealError(
                "operator_stealth_read_category_invalid"
            )
        if result_code not in _READ_RESULT_CODES:
            raise OperatorStealthRevealError(
                "operator_stealth_read_result_invalid"
            )
        if (
            authoritative_status is not None
            and authoritative_status not in _AUTHORITATIVE_STATUSES
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_read_status_invalid"
            )
        if (
            result_code != "AUTHORITATIVE"
            and authoritative_status is not None
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_read_status_unexpected"
            )
        with self.database.get_cursor() as cursor:
            self._locked_goal_for_definition(cursor, definition_id)
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_reveal_read_call
                WHERE goal_id = %s AND category = %s
                  AND correlation_id = %s
                FOR UPDATE
                """,
                (GOAL_ID, category, correlation_id),
            )
            row = self._one(cursor, "operator_stealth_read_claim_not_found")
            if row["call_state"] != "STARTED":
                raise OperatorStealthRevealConflict(
                    "operator_stealth_read_outcome_already_recorded"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_read_call
                SET call_state = %s,
                    result_code = %s,
                    authoritative_status = %s,
                    updated_at = NOW()
                WHERE goal_id = %s AND category = %s
                  AND correlation_id = %s
                RETURNING *
                """,
                (
                    "UNKNOWN" if result_code == "UNKNOWN" else "RETURNED",
                    result_code,
                    authoritative_status,
                    GOAL_ID,
                    category,
                    correlation_id,
                ),
            )
            result = self._one(
                cursor,
                "operator_stealth_read_outcome_missing",
            )
            diagnostic_code = {
                "NOT_READY": "operator_stealth_portfolio_binding_not_ready",
                "NOT_AUTHORITATIVE": (
                    "operator_stealth_closeout_identity_unproven"
                ),
                "UNKNOWN": "operator_stealth_read_unknown",
            }.get(result_code)
            if diagnostic_code is not None:
                cursor.execute(
                    f"""
                    UPDATE {self.prefix}operator_stealth_reveal_goal
                    SET diagnostic_code = %s, updated_at = NOW()
                    WHERE goal_id = %s
                    """,
                    (diagnostic_code, GOAL_ID),
                )
            return self._project_read(result, invoke_required=False)

    def get_goal(self, definition_id: str | None = None) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            row = self._goal(cursor)
            if row is None:
                return None
            if definition_id is not None and str(row["definition_id"]) != self._uuid(
                definition_id
            ):
                return None
            return self._project(
                row,
                command_cycle=self._latest_command_cycle(cursor),
            )

    def _claim_call(
        self,
        definition_id: str,
        *,
        expected_state: str,
        state: str,
        allowance_field: str,
        count_field: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if (
                row["state"] != expected_state
                or row[allowance_field]
                or int(row[count_field]) != 0
            ):
                raise OperatorStealthRevealConflict(
                    f"{diagnostic_code.removesuffix('_invocation_started')}"
                    "_allowance_unavailable"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET state = %s,
                    {allowance_field} = TRUE,
                    {count_field} = 1,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                (state, diagnostic_code, GOAL_ID),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def _transition(
        self,
        definition_id: str,
        *,
        expected_state: str,
        state: str,
        diagnostic_code: str,
        assignments: dict[str, Any] | None = None,
        require_runtime: bool = False,
    ) -> dict[str, Any]:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", diagnostic_code) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_diagnostic_invalid"
            )
        assignments = dict(assignments or {})
        allowed = {
            "preview_outcome",
            "create_outcome",
            "cancel_outcome",
            "exchange_order_id_sha256",
        }
        if set(assignments) - allowed:
            raise OperatorStealthRevealError(
                "operator_stealth_assignment_invalid"
            )
        with self.database.get_cursor() as cursor:
            row = self._locked_goal_for_definition(cursor, definition_id)
            if row["state"] != expected_state:
                raise OperatorStealthRevealConflict(
                    "operator_stealth_transition_conflict"
                )
            if require_runtime:
                cursor.execute(
                    f"""
                    SELECT status
                    FROM {self.prefix}stealth_orders
                    WHERE stealth_order_id = %s::uuid
                    """,
                    (str(row["definition_id"]),),
                )
                runtime = cursor.fetchone()
                if runtime is None:
                    raise OperatorStealthRevealConflict(
                        "operator_stealth_runtime_missing"
                    )
            columns = ["state = %s", "diagnostic_code = %s"]
            values: list[Any] = [state, diagnostic_code]
            for key, value in assignments.items():
                columns.append(f"{key} = %s")
                values.append(value)
            values.append(GOAL_ID)
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_stealth_reveal_goal
                SET {", ".join(columns)}, updated_at = NOW()
                WHERE goal_id = %s
                RETURNING *
                """,
                tuple(values),
            )
            return self._project(self._one(cursor, "operator_stealth_goal_missing"))

    def _locked_goal_for_definition(
        self,
        cursor: Any,
        definition_id: str,
    ) -> dict[str, Any]:
        normalized_id = self._uuid(definition_id)
        self._goal_lock(cursor)
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_reveal_goal
            WHERE goal_id = %s AND definition_id = %s::uuid
            FOR UPDATE
            """,
            (GOAL_ID, normalized_id),
        )
        return self._one(cursor, "operator_stealth_goal_not_found")

    def _goal(self, cursor: Any) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_reveal_goal
            WHERE goal_id = %s
            """,
            (GOAL_ID,),
        )
        rows = self._rows(cursor)
        return rows[0] if rows else None

    def _latest_command_cycle(
        self,
        cursor: Any,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_reveal_command_cycle
            WHERE goal_id = %s
            ORDER BY cycle_number DESC
            LIMIT 1
            """,
            (GOAL_ID,),
        )
        rows = self._rows(cursor)
        return rows[0] if rows else None

    @staticmethod
    def _goal_lock(cursor: Any) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (31874, GOAL_ID),
        )

    @staticmethod
    def _rows(cursor: Any) -> list[dict[str, Any]]:
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def _one(self, cursor: Any, code: str) -> dict[str, Any]:
        rows = self._rows(cursor)
        if len(rows) != 1:
            raise OperatorStealthRevealError(code)
        return rows[0]

    @staticmethod
    def _project_read(
        row: dict[str, Any],
        *,
        invoke_required: bool,
    ) -> dict[str, Any]:
        return {
            "category": row["category"],
            "correlation_id": row["correlation_id"],
            "call_state": row["call_state"],
            "result_code": row.get("result_code"),
            "authoritative_status": row.get("authoritative_status"),
            "wire_call_count": int(row.get("wire_call_count") or 0),
            "invoke_required": invoke_required,
        }

    @staticmethod
    def _uuid(value: Any) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (AttributeError, TypeError, ValueError):
            raise OperatorStealthRevealError(
                "operator_stealth_identity_invalid"
            ) from None

    @staticmethod
    def _require_sha(value: Any) -> None:
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_hash_invalid"
            )

    @classmethod
    def _require_plan(cls, plan: dict[str, Any], plan_sha256: str) -> None:
        cls._require_sha(plan_sha256)
        if (
            not isinstance(plan, dict)
            or set(plan) != _PLAN_FIELDS
            or not all(
                isinstance(plan.get(field), str) and plan[field]
                for field in (
                    "product_id",
                    "side",
                    "base_size",
                    "limit_price",
                    "configured_limit_price",
                    "submitted_limit_price",
                    "reveal_pricing_policy",
                    "reveal_price_source",
                    "market_source",
                    "target_movement",
                    "target_movement_type",
                    "target_movement_source",
                )
            )
            or plan.get("fallback_used") is not False
            or any(
                plan.get(field) is not None
                and not isinstance(plan[field], str)
                for field in ("market_bid", "market_ask")
            )
            or type(plan.get("post_only")) is not bool
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_plan_invalid"
            )
        canonical = json.dumps(
            plan,
            sort_keys=True,
            separators=(",", ":"),
        )
        if hashlib.sha256(canonical.encode()).hexdigest() != plan_sha256:
            raise OperatorStealthRevealError(
                "operator_stealth_plan_hash_mismatch"
            )

    @staticmethod
    def _project(
        row: dict[str, Any],
        *,
        command_replayed: bool = False,
        command_cycle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cycle_idempotency_key_sha256 = (
            hashlib.sha256(
                str(command_cycle["idempotency_key"]).encode()
            ).hexdigest()
            if command_cycle is not None
            else None
        )
        return {
            "goal_id": row["goal_id"],
            "state": row["state"],
            "definition_id": str(row["definition_id"]),
            "definition_revision": int(row["definition_revision"]),
            "definition_sha256": row["definition_sha256"],
            "portfolio_scope_sha256": row["portfolio_scope_sha256"],
            "client_order_id": str(row["client_order_id"]),
            "plan": dict(row["plan_json"]) if row.get("plan_json") else None,
            "plan_sha256": row.get("plan_sha256"),
            "prepreview_admission_sha256": row.get(
                "prepreview_admission_sha256"
            ),
            "preview_claim_id": (
                str(row["preview_claim_id"])
                if row.get("preview_claim_id")
                else None
            ),
            "preview_allowance_consumed": bool(
                row["preview_allowance_consumed"]
            ),
            "create_allowance_consumed": bool(
                row["create_allowance_consumed"]
            ),
            "cancel_allowance_consumed": bool(
                row["cancel_allowance_consumed"]
            ),
            "preview_call_count": int(row["preview_call_count"]),
            "create_call_count": int(row["create_call_count"]),
            "cancel_call_count": int(row["cancel_call_count"]),
            "read_call_count": int(row["read_call_count"]),
            "preview_outcome": row.get("preview_outcome"),
            "create_outcome": row.get("create_outcome"),
            "cancel_outcome": row.get("cancel_outcome"),
            "exchange_order_id_sha256": row.get(
                "exchange_order_id_sha256"
            ),
            "diagnostic_code": row["diagnostic_code"],
            "correlation_id": (
                row.get("cancel_correlation_id")
                or row.get("resume_correlation_id")
                or row["correlation_id"]
            ),
            "command_idempotency_key_sha256": hashlib.sha256(
                str(
                    row.get("cancel_idempotency_key")
                    or row.get("resume_idempotency_key")
                    or row["reveal_idempotency_key"]
                ).encode()
            ).hexdigest(),
            "command_identity_bound": bool(
                (
                    row.get("cancel_idempotency_key")
                    or row.get("resume_idempotency_key")
                    or row["reveal_idempotency_key"]
                )
                == (
                    row.get("cancel_correlation_id")
                    or row.get("resume_correlation_id")
                    or row["correlation_id"]
                )
            ),
            "command_cycle_status": (
                command_cycle["completion_status"]
                if command_cycle is not None
                else None
            ),
            "command_cycle_phase": (
                command_cycle["phase"]
                if command_cycle is not None
                else None
            ),
            "command_cycle_number": (
                int(command_cycle["cycle_number"])
                if command_cycle is not None
                else None
            ),
            "command_cycle_correlation_id": (
                command_cycle["correlation_id"]
                if command_cycle is not None
                else None
            ),
            "command_cycle_idempotency_key_sha256": (
                cycle_idempotency_key_sha256
            ),
            "command_cycle_payload_sha256": (
                command_cycle["payload_sha256"]
                if command_cycle is not None
                else None
            ),
            "command_cycle_terminal_goal_state": (
                command_cycle.get("terminal_goal_state")
                if command_cycle is not None
                else None
            ),
            "command_cycle_terminal_diagnostic_code": (
                command_cycle.get("terminal_diagnostic_code")
                if command_cycle is not None
                else None
            ),
            "command_cycle_preview_call_count": (
                int(command_cycle["preview_call_count"])
                if command_cycle is not None
                and command_cycle.get("preview_call_count") is not None
                else None
            ),
            "command_cycle_create_call_count": (
                int(command_cycle["create_call_count"])
                if command_cycle is not None
                and command_cycle.get("create_call_count") is not None
                else None
            ),
            "command_cycle_cancel_call_count": (
                int(command_cycle["cancel_call_count"])
                if command_cycle is not None
                and command_cycle.get("cancel_call_count") is not None
                else None
            ),
            "command_cycle_read_call_count": (
                int(command_cycle["read_call_count"])
                if command_cycle is not None
                and command_cycle.get("read_call_count") is not None
                else None
            ),
            "command_cycle_evidence_sha256": (
                command_cycle.get("completion_evidence_sha256")
                if command_cycle is not None
                else None
            ),
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "command_replayed": command_replayed,
        }


@lru_cache(maxsize=1)
def get_default_operator_stealth_reveal_repository(
) -> OperatorStealthRevealRepository:
    from database.order import DB_CLIENT

    repository = OperatorStealthRevealRepository(DB_CLIENT)
    repository.ensure_schema()
    return repository
