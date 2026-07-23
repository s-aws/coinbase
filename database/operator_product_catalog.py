"""PostgreSQL durability for operator Product Catalog administration."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from application.admin_api.operator_product_catalog import (
    OperatorProductCatalogError,
    ProductCatalogDiff,
    ProductCatalogLifecycle,
    ProductCatalogNormalizedItem,
    ProductCatalogReadResult,
    build_product_catalog_diff,
)
from database.database import PostgresDB


_GOAL_ID = "operator_product_catalog_administration_v1"
_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_DIAGNOSTIC_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_ACTIONS = frozenset({"ENABLE", "DISABLE", "RETIRE"})
_REVISION_STATES = (
    "PROPOSED",
    "APPROVED",
    "APPLIED",
    "ROLLED_BACK",
)
_CYCLE_STATES = ("CLAIMED", "READING", "PROPOSED", "FAILED", "UNKNOWN")
_READ_STATES = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "RETURNED",
    "RETURNED_INCOMPLETE",
    "NOT_RETURNED",
    "UNKNOWN_AFTER_PAGE_CLAIM",
)
_CHANGE_TYPES = (
    "ADDED",
    "CHANGED",
    "REMOVED",
    "UNCHANGED",
    "LIFECYCLE_CHANGED",
    "ROLLBACK_RESTORED",
)
_DIAGNOSTIC_CODES = frozenset(
    {
        "product_catalog_refresh_claimed",
        "product_catalog_refresh_proposed",
        "product_catalog_read_failed",
        "product_catalog_refresh_unknown",
        "product_catalog_refresh_interrupted_before_call",
        "product_catalog_refresh_interrupted_unknown",
        "product_catalog_refresh_interrupted_after_return",
        "product_catalog_revision_approved",
        "product_catalog_product_enabled",
        "product_catalog_product_disabled",
        "product_catalog_product_retired",
        "product_catalog_revision_rolled_back",
    }
)


class OperatorProductCatalogRepository:
    """Transaction-bounded catalog revisions, claims, and audit history."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
    ) -> None:
        if _SCHEMA_PATTERN.fullmatch(schema) is None:
            raise OperatorProductCatalogError(
                "product_catalog_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.prefix = f'"{schema}".'

    def ensure_schema(self) -> None:
        revision_states = ", ".join(
            f"'{value}'" for value in _REVISION_STATES
        )
        cycle_states = ", ".join(f"'{value}'" for value in _CYCLE_STATES)
        read_states = ", ".join(f"'{value}'" for value in _READ_STATES)
        change_types = ", ".join(
            f"'{value}'" for value in _CHANGE_TYPES
        )
        lifecycles = ", ".join(
            f"'{value.value}'" for value in ProductCatalogLifecycle
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_goal (
                    goal_id TEXT PRIMARY KEY,
                    cycle_count INTEGER NOT NULL DEFAULT 0
                        CHECK (cycle_count BETWEEN 0 AND 10),
                    logical_read_count INTEGER NOT NULL DEFAULT 0
                        CHECK (logical_read_count BETWEEN 0 AND 10),
                    page_count INTEGER NOT NULL DEFAULT 0
                        CHECK (page_count BETWEEN 0 AND 1000),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_goal (
                    goal_id
                )
                VALUES (%s)
                ON CONFLICT (goal_id) DO NOTHING
                """,
                (_GOAL_ID,),
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_cycle (
                    cycle_id UUID PRIMARY KEY,
                    cycle_number INTEGER NOT NULL
                        CHECK (cycle_number BETWEEN 1 AND 10),
                    state TEXT NOT NULL CHECK (state IN ({cycle_states})),
                    read_state TEXT NOT NULL
                        CHECK (read_state IN ({read_states})),
                    expected_active_revision_id UUID,
                    proposed_revision_id UUID,
                    logical_read_count INTEGER NOT NULL DEFAULT 1
                        CHECK (logical_read_count = 1),
                    page_count INTEGER NOT NULL DEFAULT 0
                        CHECK (page_count BETWEEN 0 AND 100),
                    diagnostic_code TEXT NOT NULL,
                    actor_id TEXT NOT NULL
                        CHECK (char_length(actor_id) BETWEEN 1 AND 255),
                    operator_reason_sha256 CHAR(64) NOT NULL
                        CHECK (operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'),
                    correlation_id TEXT NOT NULL
                        CHECK (
                            correlation_id ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    idempotency_key TEXT NOT NULL UNIQUE
                        CHECK (
                            idempotency_key ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_page (
                    cycle_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_product_catalog_cycle(cycle_id),
                    page_ordinal INTEGER NOT NULL
                        CHECK (page_ordinal BETWEEN 1 AND 100),
                    cursor_sha256 CHAR(64),
                    state TEXT NOT NULL
                        CHECK (state IN ('CLAIMED', 'RETURNED', 'UNKNOWN')),
                    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    returned_at TIMESTAMPTZ,
                    PRIMARY KEY (cycle_id, page_ordinal),
                    CHECK (
                        cursor_sha256 IS NULL
                        OR cursor_sha256 ~ '^[0-9a-f]{{64}}$'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_revision (
                    revision_id UUID PRIMARY KEY,
                    sequence_number BIGSERIAL UNIQUE,
                    revision INTEGER NOT NULL DEFAULT 1
                        CHECK (revision >= 1),
                    state TEXT NOT NULL CHECK (state IN ({revision_states})),
                    source TEXT NOT NULL CHECK (
                        source IN (
                            'COINBASE_CATALOG',
                            'OPERATOR_LIFECYCLE',
                            'ROLLBACK'
                        )
                    ),
                    source_cycle_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_cycle(cycle_id),
                    parent_revision_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    rollback_of_revision_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    snapshot_sha256 CHAR(64) NOT NULL
                        CHECK (snapshot_sha256 ~ '^[0-9a-f]{{64}}$'),
                    diff_sha256 CHAR(64) NOT NULL
                        CHECK (diff_sha256 ~ '^[0-9a-f]{{64}}$'),
                    product_count INTEGER NOT NULL CHECK (product_count >= 0),
                    added_count INTEGER NOT NULL CHECK (added_count >= 0),
                    changed_count INTEGER NOT NULL CHECK (changed_count >= 0),
                    removed_count INTEGER NOT NULL CHECK (removed_count >= 0),
                    unchanged_count INTEGER NOT NULL CHECK (unchanged_count >= 0),
                    actor_id TEXT NOT NULL
                        CHECK (char_length(actor_id) BETWEEN 1 AND 255),
                    operator_reason_sha256 CHAR(64) NOT NULL
                        CHECK (operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'),
                    correlation_id TEXT NOT NULL
                        CHECK (
                            correlation_id ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_product (
                    revision_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    product_id VARCHAR(131) NOT NULL,
                    product_type TEXT NOT NULL
                        CHECK (product_type IN ('SPOT', 'FUTURE')),
                    base_currency VARCHAR(32) NOT NULL,
                    quote_currency VARCHAR(32) NOT NULL,
                    base_increment TEXT NOT NULL,
                    quote_increment TEXT NOT NULL,
                    price_increment TEXT NOT NULL,
                    base_min_size TEXT NOT NULL,
                    base_max_size TEXT NOT NULL,
                    quote_min_size TEXT NOT NULL,
                    quote_max_size TEXT NOT NULL,
                    display_name VARCHAR(128) NOT NULL,
                    exchange_status TEXT NOT NULL CHECK (
                        exchange_status IN (
                            'ONLINE', 'OFFLINE', 'DELISTED', 'UNKNOWN'
                        )
                    ),
                    exchange_disabled BOOLEAN NOT NULL,
                    cancel_only BOOLEAN NOT NULL,
                    limit_only BOOLEAN NOT NULL,
                    post_only BOOLEAN NOT NULL,
                    view_only BOOLEAN NOT NULL,
                    lifecycle TEXT NOT NULL CHECK (lifecycle IN ({lifecycles})),
                    change_type TEXT NOT NULL
                        CHECK (change_type IN ({change_types})),
                    PRIMARY KEY (revision_id, product_id)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_product_catalog_product
                ADD COLUMN IF NOT EXISTS change_type TEXT NOT NULL
                    DEFAULT 'UNCHANGED'
                    CHECK (change_type IN ({change_types}))
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_active (
                    goal_id TEXT PRIMARY KEY REFERENCES
                        {self.prefix}operator_product_catalog_goal(goal_id),
                    revision_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_command (
                    idempotency_key TEXT PRIMARY KEY
                        CHECK (
                            idempotency_key ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operation TEXT NOT NULL,
                    state TEXT NOT NULL
                        CHECK (
                            state IN (
                                'IN_PROGRESS',
                                'COMPLETED',
                                'REJECTED',
                                'UNKNOWN'
                            )
                        ),
                    diagnostic_code TEXT,
                    cycle_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_cycle(cycle_id),
                    result_revision_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_product_catalog_command
                ADD COLUMN IF NOT EXISTS diagnostic_code TEXT
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_product_catalog_command
                DROP CONSTRAINT IF EXISTS
                    operator_product_catalog_command_state_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_product_catalog_command
                ADD CONSTRAINT
                    operator_product_catalog_command_state_check
                CHECK (
                    state IN (
                        'IN_PROGRESS',
                        'COMPLETED',
                        'REJECTED',
                        'UNKNOWN'
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_product_catalog_event (
                    event_id UUID PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    revision_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_revision(revision_id),
                    cycle_id UUID REFERENCES
                        {self.prefix}operator_product_catalog_cycle(cycle_id),
                    product_id VARCHAR(131),
                    actor_id TEXT NOT NULL
                        CHECK (char_length(actor_id) BETWEEN 1 AND 255),
                    correlation_id TEXT NOT NULL
                        CHECK (
                            correlation_id ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_product_catalog_revision_sequence_idx
                ON {self.prefix}operator_product_catalog_revision
                    (sequence_number DESC)
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_product_catalog_event_recorded_idx
                ON {self.prefix}operator_product_catalog_event
                    (recorded_at DESC)
                """
            )
            self._recover_interrupted_refreshes(cursor)

    def _recover_interrupted_refreshes(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_product_catalog_page
            SET state = 'UNKNOWN'
            WHERE state = 'CLAIMED'
            RETURNING cycle_id
            """
        )
        unknown_cycle_ids = {
            str(row["cycle_id"]) for row in _rows(cursor)
        }
        if unknown_cycle_ids:
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_cycle
                SET
                    state = 'UNKNOWN',
                    read_state = 'UNKNOWN_AFTER_PAGE_CLAIM',
                    diagnostic_code =
                        'product_catalog_refresh_interrupted_unknown',
                    updated_at = NOW()
                WHERE cycle_id = ANY(%s::uuid[])
                """,
                (list(unknown_cycle_ids),),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_command
                SET state = 'UNKNOWN', updated_at = NOW()
                WHERE cycle_id = ANY(%s::uuid[])
                """,
                (list(unknown_cycle_ids),),
            )
            cursor.execute(
                f"""
                SELECT cycle_id, actor_id, correlation_id
                FROM {self.prefix}operator_product_catalog_cycle
                WHERE cycle_id = ANY(%s::uuid[])
                """,
                (list(unknown_cycle_ids),),
            )
            for cycle in _rows(cursor):
                self._append_event(
                    cursor,
                    event_type="CATALOG_REFRESH_RECOVERED_UNKNOWN",
                    cycle_id=str(cycle["cycle_id"]),
                    actor_id=str(cycle["actor_id"]),
                    correlation_id=str(cycle["correlation_id"]),
                    evidence={
                        "state": "UNKNOWN",
                        "read_state": "UNKNOWN_AFTER_PAGE_CLAIM",
                        "diagnostic_code":
                            "product_catalog_refresh_interrupted_unknown",
                    },
                )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_product_catalog_cycle AS cycle
            SET
                state = 'FAILED',
                read_state = 'RETURNED_INCOMPLETE',
                diagnostic_code =
                    'product_catalog_refresh_interrupted_after_return',
                updated_at = NOW()
            WHERE cycle.state = 'READING'
              AND EXISTS (
                  SELECT 1
                  FROM {self.prefix}operator_product_catalog_page AS page
                  WHERE page.cycle_id = cycle.cycle_id
                    AND page.state = 'RETURNED'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM {self.prefix}operator_product_catalog_page AS page
                  WHERE page.cycle_id = cycle.cycle_id
                    AND page.state IN ('CLAIMED', 'UNKNOWN')
              )
            RETURNING cycle_id, actor_id, correlation_id
            """
        )
        returned_incomplete_cycles = _rows(cursor)
        if returned_incomplete_cycles:
            cycle_ids = [
                str(cycle["cycle_id"])
                for cycle in returned_incomplete_cycles
            ]
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_command
                SET
                    state = 'COMPLETED',
                    diagnostic_code =
                        'product_catalog_refresh_interrupted_after_return',
                    updated_at = NOW()
                WHERE cycle_id = ANY(%s::uuid[])
                  AND state = 'IN_PROGRESS'
                """,
                (cycle_ids,),
            )
            for cycle in returned_incomplete_cycles:
                self._append_event(
                    cursor,
                    event_type=(
                        "CATALOG_REFRESH_RECOVERED_INCOMPLETE"
                    ),
                    cycle_id=str(cycle["cycle_id"]),
                    actor_id=str(cycle["actor_id"]),
                    correlation_id=str(cycle["correlation_id"]),
                    evidence={
                        "state": "FAILED",
                        "read_state": "RETURNED_INCOMPLETE",
                        "diagnostic_code":
                            "product_catalog_refresh_interrupted_after_return",
                    },
                )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_product_catalog_cycle
            SET
                state = 'FAILED',
                read_state = 'NOT_RETURNED',
                diagnostic_code =
                    'product_catalog_refresh_interrupted_before_call',
                updated_at = NOW()
            WHERE state = 'CLAIMED'
            RETURNING cycle_id, actor_id, correlation_id
            """
        )
        before_call_cycles = _rows(cursor)
        if before_call_cycles:
            cycle_ids = [
                str(cycle["cycle_id"])
                for cycle in before_call_cycles
            ]
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_command
                SET state = 'COMPLETED', updated_at = NOW()
                WHERE cycle_id = ANY(%s::uuid[])
                  AND state = 'IN_PROGRESS'
                """,
                (cycle_ids,),
            )
            for cycle in before_call_cycles:
                self._append_event(
                    cursor,
                    event_type=(
                        "CATALOG_REFRESH_RECOVERED_NOT_RETURNED"
                    ),
                    cycle_id=str(cycle["cycle_id"]),
                    actor_id=str(cycle["actor_id"]),
                    correlation_id=str(cycle["correlation_id"]),
                    evidence={
                        "state": "FAILED",
                        "read_state": "NOT_RETURNED",
                        "diagnostic_code":
                            "product_catalog_refresh_interrupted_before_call",
                    },
                )

    def get_goal_budget(self) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT cycle_count, logical_read_count, page_count
                FROM {self.prefix}operator_product_catalog_goal
                WHERE goal_id = %s
                """,
                (_GOAL_ID,),
            )
            row = _one(cursor, "product_catalog_goal_missing")
        return {
            **row,
            "cycle_limit": 10,
            "trading_authority_granted": False,
            "portfolio_scope_expanded": False,
            "exchange_mutation_count": 0,
        }

    def get_active_revision_id(self) -> str | None:
        with self.database.get_cursor() as cursor:
            return self._active_revision_id(cursor)

    def _active_revision_id(self, cursor: Any) -> str | None:
        cursor.execute(
            f"""
            SELECT revision_id
            FROM {self.prefix}operator_product_catalog_active
            WHERE goal_id = %s
            """,
            (_GOAL_ID,),
        )
        rows = _rows(cursor)
        return str(rows[0]["revision_id"]) if rows else None

    def begin_refresh(
        self,
        *,
        expected_active_revision_id: str | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        payload_sha256 = _hash_json(
            {
                "operation": "REFRESH",
                "expected_active_revision_id": expected_active_revision_id,
                "actor_id": actor_id,
                "operator_reason_sha256": _sha256(operator_reason),
                "acknowledgement": acknowledgement,
            }
        )
        with self.database.get_cursor() as cursor:
            replay = self._existing_command(
                cursor,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
            if replay is not None:
                if replay.get("cycle_id") is None:
                    raise OperatorProductCatalogError(
                        "product_catalog_idempotency_state_invalid"
                    )
                return {
                    **self._cycle_by_id(
                        cursor,
                        str(replay["cycle_id"]),
                    ),
                    "command_replayed": True,
                }
            cursor.execute(
                f"""
                SELECT goal_id
                FROM {self.prefix}operator_product_catalog_goal
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (_GOAL_ID,),
            )
            _one(cursor, "product_catalog_goal_missing")
            active_revision_id = self._active_revision_id(cursor)
            if active_revision_id != expected_active_revision_id:
                raise OperatorProductCatalogError(
                    "product_catalog_active_revision_conflict"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_goal
                SET
                    cycle_count = cycle_count + 1,
                    logical_read_count = logical_read_count + 1,
                    updated_at = NOW()
                WHERE goal_id = %s AND cycle_count < 10
                RETURNING cycle_count
                """,
                (_GOAL_ID,),
            )
            rows = _rows(cursor)
            if not rows:
                raise OperatorProductCatalogError(
                    "product_catalog_cycles_exhausted"
                )
            cycle_id = str(uuid.uuid4())
            cycle_number = int(rows[0]["cycle_count"])
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_cycle (
                    cycle_id, cycle_number, state, read_state,
                    expected_active_revision_id, diagnostic_code, actor_id,
                    operator_reason_sha256, correlation_id, idempotency_key
                )
                VALUES (
                    %s::uuid, %s, 'CLAIMED', 'NOT_STARTED',
                    %s::uuid, 'product_catalog_refresh_claimed', %s,
                    %s, %s, %s
                )
                """,
                (
                    cycle_id,
                    cycle_number,
                    expected_active_revision_id,
                    actor_id,
                    _sha256(operator_reason),
                    correlation_id,
                    idempotency_key,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_command (
                    idempotency_key, payload_sha256, operation, state,
                    cycle_id
                )
                VALUES (%s, %s, 'REFRESH', 'IN_PROGRESS', %s::uuid)
                """,
                (idempotency_key, payload_sha256, cycle_id),
            )
            self._append_event(
                cursor,
                event_type="CATALOG_REFRESH_CLAIMED",
                cycle_id=cycle_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={"cycle_number": cycle_number},
            )
            return {
                **self._cycle_by_id(cursor, cycle_id),
                "command_replayed": False,
            }

    def record_page_call(
        self,
        *,
        cycle_id: str,
        page_ordinal: int,
        cursor_sha256: str | None,
    ) -> None:
        if (
            type(page_ordinal) is not int
            or page_ordinal < 1
            or page_ordinal > 100
            or (
                cursor_sha256 is not None
                and _SHA256_PATTERN.fullmatch(cursor_sha256) is None
            )
        ):
            raise OperatorProductCatalogError(
                "product_catalog_page_claim_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_cycle
                WHERE cycle_id = %s::uuid
                FOR UPDATE
                """,
                (cycle_id,),
            )
            cycle = _one(cursor, "product_catalog_cycle_not_found")
            if cycle["state"] not in {"CLAIMED", "READING"}:
                raise OperatorProductCatalogError(
                    "product_catalog_refresh_not_claimable"
                )
            if int(cycle["page_count"]) + 1 != page_ordinal:
                raise OperatorProductCatalogError(
                    "product_catalog_page_sequence_invalid"
                )
            if (page_ordinal == 1) != (cursor_sha256 is None):
                raise OperatorProductCatalogError(
                    "product_catalog_page_cursor_invalid"
                )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_page (
                    cycle_id, page_ordinal, cursor_sha256, state
                )
                VALUES (%s::uuid, %s, %s, 'CLAIMED')
                """,
                (cycle_id, page_ordinal, cursor_sha256),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_cycle
                SET
                    state = 'READING',
                    read_state = 'IN_PROGRESS',
                    page_count = page_count + 1,
                    updated_at = NOW()
                WHERE cycle_id = %s::uuid
                """,
                (cycle_id,),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_goal
                SET page_count = page_count + 1, updated_at = NOW()
                WHERE goal_id = %s
                """,
                (_GOAL_ID,),
            )

    def record_page_returned(
        self,
        *,
        cycle_id: str,
        page_ordinal: int,
    ) -> None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_page
                SET state = 'RETURNED', returned_at = NOW()
                WHERE cycle_id = %s::uuid
                  AND page_ordinal = %s
                  AND state = 'CLAIMED'
                RETURNING page_ordinal
                """,
                (cycle_id, page_ordinal),
            )
            _one(cursor, "product_catalog_page_return_conflict")

    def complete_refresh(
        self,
        *,
        cycle_id: str,
        read_result: ProductCatalogReadResult,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not read_result.pagination_complete:
            raise OperatorProductCatalogError(
                "product_catalog_pagination_incomplete"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_cycle
                WHERE cycle_id = %s::uuid
                FOR UPDATE
                """,
                (cycle_id,),
            )
            cycle = _one(cursor, "product_catalog_cycle_not_found")
            if (
                cycle["state"] not in {"CLAIMED", "READING"}
                or int(cycle["page_count"]) != read_result.page_count
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_refresh_completion_conflict"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self.prefix}operator_product_catalog_page
                WHERE cycle_id = %s::uuid AND state = 'RETURNED'
                """,
                (cycle_id,),
            )
            if int(_one(cursor, "product_catalog_page_count_invalid")["count"]) != read_result.page_count:
                raise OperatorProductCatalogError(
                    "product_catalog_page_accounting_mismatch"
                )
            if self._active_revision_id(cursor) != _optional_uuid_text(
                cycle["expected_active_revision_id"]
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_active_revision_conflict"
                )
            current = self._active_products(cursor)
            diff = build_product_catalog_diff(
                current=current,
                refreshed=read_result.products,
            )
            revision = self._insert_revision(
                cursor,
                state="PROPOSED",
                source="COINBASE_CATALOG",
                source_cycle_id=cycle_id,
                parent_revision_id=_optional_uuid_text(
                    cycle["expected_active_revision_id"]
                ),
                rollback_of_revision_id=None,
                diff=diff,
                actor_id=actor_id,
                operator_reason_sha256=str(
                    cycle["operator_reason_sha256"]
                ),
                correlation_id=correlation_id,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_cycle
                SET
                    state = 'PROPOSED',
                    read_state = 'RETURNED',
                    proposed_revision_id = %s::uuid,
                    diagnostic_code = 'product_catalog_refresh_proposed',
                    updated_at = NOW()
                WHERE cycle_id = %s::uuid
                """,
                (revision["revision_id"], cycle_id),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_command
                SET
                    state = 'COMPLETED',
                    result_revision_id = %s::uuid,
                    updated_at = NOW()
                WHERE cycle_id = %s::uuid
                """,
                (revision["revision_id"], cycle_id),
            )
            self._append_event(
                cursor,
                event_type="CATALOG_REFRESH_PROPOSED",
                cycle_id=cycle_id,
                revision_id=revision["revision_id"],
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "product_count": revision["product_count"],
                    "added_count": revision["added_count"],
                    "changed_count": revision["changed_count"],
                    "removed_count": revision["removed_count"],
                    "page_count": read_result.page_count,
                },
            )
            return revision

    def fail_refresh(
        self,
        *,
        cycle_id: str,
        diagnostic_code: str,
        read_state: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if diagnostic_code not in _DIAGNOSTIC_CODES:
            diagnostic_code = "product_catalog_read_failed"
        if read_state not in {
            "NOT_RETURNED",
            "RETURNED_INCOMPLETE",
            "UNKNOWN_AFTER_PAGE_CLAIM",
        }:
            raise OperatorProductCatalogError(
                "product_catalog_read_state_invalid"
            )
        state = (
            "UNKNOWN"
            if read_state == "UNKNOWN_AFTER_PAGE_CLAIM"
            else "FAILED"
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_cycle
                SET
                    state = %s,
                    read_state = %s,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE cycle_id = %s::uuid
                  AND state IN ('CLAIMED', 'READING')
                RETURNING *
                """,
                (state, read_state, diagnostic_code, cycle_id),
            )
            cycle = _one(cursor, "product_catalog_refresh_conflict")
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_page
                SET state = 'UNKNOWN'
                WHERE cycle_id = %s::uuid AND state = 'CLAIMED'
                """,
                (cycle_id,),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_command
                SET state = %s, updated_at = NOW()
                WHERE cycle_id = %s::uuid
                """,
                ("UNKNOWN" if state == "UNKNOWN" else "COMPLETED", cycle_id),
            )
            self._append_event(
                cursor,
                event_type="CATALOG_REFRESH_FAILED",
                cycle_id=cycle_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "state": state,
                    "read_state": read_state,
                    "diagnostic_code": diagnostic_code,
                },
            )
            return _cycle_record(cycle)

    def approve_revision(
        self,
        *,
        revision_id: str,
        expected_revision: int,
        snapshot_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        payload = _local_command_payload(
            operation="APPROVE",
            actor_id=actor_id,
            operator_reason=operator_reason,
            acknowledgement=acknowledgement,
            command_fields={
                "revision_id": revision_id,
                "expected_revision": expected_revision,
                "snapshot_sha256": snapshot_sha256,
            },
        )
        with self.database.get_cursor() as cursor:
            replay = self._claim_local_command(
                cursor,
                idempotency_key=idempotency_key,
                payload=payload,
                operation="APPROVE",
            )
            if replay is not None:
                return {
                    **self._revision_by_id(cursor, replay),
                    "command_replayed": True,
                }
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_revision
                WHERE revision_id = %s::uuid
                FOR UPDATE
                """,
                (revision_id,),
            )
            revision = _one(cursor, "product_catalog_revision_not_found")
            if (
                revision["state"] != "PROPOSED"
                or int(revision["revision"]) != expected_revision
                or str(revision["snapshot_sha256"]) != snapshot_sha256
                or self._active_revision_id(cursor)
                != _optional_uuid_text(revision["parent_revision_id"])
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_approval_conflict"
                )
            self._verified_products_for_revision(
                cursor,
                revision,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_product_catalog_revision
                SET
                    state = 'APPROVED',
                    revision = revision + 1,
                    updated_at = NOW()
                WHERE revision_id = %s::uuid
                RETURNING *
                """,
                (revision_id,),
            )
            approved = _revision_record(
                _one(cursor, "product_catalog_approval_conflict")
            )
            self._set_active(cursor, revision_id)
            self._complete_command(cursor, idempotency_key, revision_id)
            self._append_event(
                cursor,
                event_type="CATALOG_REVISION_APPROVED",
                revision_id=revision_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "revision": approved["revision"],
                    "product_count": approved["product_count"],
                },
            )
            return {
                **approved,
                "active": True,
                "command_replayed": False,
            }

    def change_product_lifecycle(
        self,
        *,
        product_id: str,
        action: str,
        expected_active_revision_id: str,
        expected_active_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        if action not in _ACTIONS:
            raise OperatorProductCatalogError(
                "product_catalog_action_invalid"
            )
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        payload = _local_command_payload(
            operation=action,
            actor_id=actor_id,
            operator_reason=operator_reason,
            acknowledgement=acknowledgement,
            command_fields={
                "product_id": product_id,
                "expected_active_revision_id":
                    expected_active_revision_id,
                "expected_active_revision": expected_active_revision,
            },
        )
        with self.database.get_cursor() as cursor:
            replay = self._claim_local_command(
                cursor,
                idempotency_key=idempotency_key,
                payload=payload,
                operation=action,
            )
            if replay is not None:
                return {
                    **self._revision_by_id(cursor, replay),
                    "command_replayed": True,
                }
            active = self._locked_active_revision(cursor)
            if (
                active["revision_id"] != expected_active_revision_id
                or int(active["revision"]) != expected_active_revision
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_active_revision_conflict"
                )
            products = self._verified_products_for_revision(
                cursor,
                active,
            )
            by_id = {item.product_id: item for item in products}
            target = by_id.get(product_id)
            if target is None:
                raise OperatorProductCatalogError(
                    "product_catalog_product_not_found"
                )
            if action == "ENABLE":
                if (
                    target.lifecycle is ProductCatalogLifecycle.RETIRED
                    or target.exchange_disabled
                    or target.exchange_status != "ONLINE"
                ):
                    raise OperatorProductCatalogError(
                        "product_catalog_enable_not_eligible"
                    )
                lifecycle = ProductCatalogLifecycle.ENABLED
            elif action == "DISABLE":
                if target.lifecycle is ProductCatalogLifecycle.RETIRED:
                    raise OperatorProductCatalogError(
                        "product_catalog_disable_not_eligible"
                    )
                lifecycle = ProductCatalogLifecycle.DISABLED
            else:
                lifecycle = ProductCatalogLifecycle.RETIRED
            if target.lifecycle is lifecycle:
                raise OperatorProductCatalogError(
                    "product_catalog_lifecycle_no_change"
                )
            by_id[product_id] = target.model_copy(
                update={"lifecycle": lifecycle}
            )
            snapshot = [by_id[key] for key in sorted(by_id)]
            diff = _action_diff(snapshot, action, product_id)
            result = self._insert_revision(
                cursor,
                state="APPLIED",
                source="OPERATOR_LIFECYCLE",
                source_cycle_id=None,
                parent_revision_id=expected_active_revision_id,
                rollback_of_revision_id=None,
                diff=diff,
                actor_id=actor_id,
                operator_reason_sha256=_sha256(operator_reason),
                correlation_id=correlation_id,
            )
            self._set_active(cursor, result["revision_id"])
            self._complete_command(
                cursor,
                idempotency_key,
                result["revision_id"],
            )
            self._append_event(
                cursor,
                event_type=f"PRODUCT_{action}D" if action != "RETIRE" else "PRODUCT_RETIRED",
                revision_id=result["revision_id"],
                product_id=product_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "action": action,
                    "lifecycle": lifecycle.value,
                },
            )
            return {
                **result,
                "active": True,
                "command_replayed": False,
            }

    def rollback_revision(
        self,
        *,
        target_revision_id: str,
        expected_active_revision_id: str,
        expected_active_revision: int,
        target_snapshot_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        payload = _local_command_payload(
            operation="ROLLBACK",
            actor_id=actor_id,
            operator_reason=operator_reason,
            acknowledgement=acknowledgement,
            command_fields={
                "target_revision_id": target_revision_id,
                "expected_active_revision_id":
                    expected_active_revision_id,
                "expected_active_revision": expected_active_revision,
                "target_snapshot_sha256": target_snapshot_sha256,
            },
        )
        with self.database.get_cursor() as cursor:
            replay = self._claim_local_command(
                cursor,
                idempotency_key=idempotency_key,
                payload=payload,
                operation="ROLLBACK",
            )
            if replay is not None:
                return {
                    **self._revision_by_id(cursor, replay),
                    "command_replayed": True,
                }
            active = self._locked_active_revision(cursor)
            if (
                active["revision_id"] != expected_active_revision_id
                or int(active["revision"]) != expected_active_revision
                or target_revision_id == expected_active_revision_id
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_rollback_conflict"
                )
            target = self._revision_by_id(cursor, target_revision_id)
            if (
                target["state"] not in {"APPROVED", "APPLIED", "ROLLED_BACK"}
                or target["snapshot_sha256"] != target_snapshot_sha256
            ):
                raise OperatorProductCatalogError(
                    "product_catalog_rollback_target_invalid"
                )
            products = self._products_for_revision(
                cursor,
                target_revision_id,
            )
            diff = _action_diff(products, "ROLLBACK", None)
            result = self._insert_revision(
                cursor,
                state="ROLLED_BACK",
                source="ROLLBACK",
                source_cycle_id=None,
                parent_revision_id=expected_active_revision_id,
                rollback_of_revision_id=target_revision_id,
                diff=diff,
                actor_id=actor_id,
                operator_reason_sha256=_sha256(operator_reason),
                correlation_id=correlation_id,
            )
            if result["snapshot_sha256"] != target_snapshot_sha256:
                raise OperatorProductCatalogError(
                    "product_catalog_rollback_snapshot_changed"
                )
            self._set_active(cursor, result["revision_id"])
            self._complete_command(
                cursor,
                idempotency_key,
                result["revision_id"],
            )
            self._append_event(
                cursor,
                event_type="CATALOG_REVISION_ROLLED_BACK",
                revision_id=result["revision_id"],
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={"target_revision_id": target_revision_id},
            )
            return {
                **result,
                "active": True,
                "command_replayed": False,
            }

    def list_revisions(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        if not 1 <= limit <= 100 or offset < 0:
            raise OperatorProductCatalogError(
                "product_catalog_pagination_invalid"
            )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self.prefix}operator_product_catalog_revision
                """
            )
            total = int(_one(cursor, "product_catalog_count_invalid")["count"])
            cursor.execute(
                f"""
                SELECT r.*,
                    (a.revision_id IS NOT NULL) AS active
                FROM {self.prefix}operator_product_catalog_revision r
                LEFT JOIN {self.prefix}operator_product_catalog_active a
                  ON a.goal_id = %s AND a.revision_id = r.revision_id
                ORDER BY r.sequence_number DESC
                LIMIT %s OFFSET %s
                """,
                (_GOAL_ID, limit, offset),
            )
            return [_revision_record(row) for row in _rows(cursor)], total

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            return self._revision_by_id(cursor, revision_id)

    def _revision_by_id(
        self,
        cursor: Any,
        revision_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT r.*,
                (a.revision_id IS NOT NULL) AS active
            FROM {self.prefix}operator_product_catalog_revision r
            LEFT JOIN {self.prefix}operator_product_catalog_active a
              ON a.goal_id = %s AND a.revision_id = r.revision_id
            WHERE r.revision_id = %s::uuid
            """,
            (_GOAL_ID, revision_id),
        )
        return _revision_record(
            _one(cursor, "product_catalog_revision_not_found")
        )

    def list_revision_products(
        self,
        revision_id: str,
    ) -> list[dict[str, Any]]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_product
                WHERE revision_id = %s::uuid
                ORDER BY product_id
                """,
                (revision_id,),
            )
            return [_product_record(row) for row in _rows(cursor)]

    def _products_for_revision(
        self,
        cursor: Any,
        revision_id: str,
    ) -> list[ProductCatalogNormalizedItem]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_product_catalog_product
            WHERE revision_id = %s::uuid
            ORDER BY product_id
            """,
            (revision_id,),
        )
        return [_product_item(row) for row in _rows(cursor)]

    def _verified_products_for_revision(
        self,
        cursor: Any,
        revision: dict[str, Any],
    ) -> list[ProductCatalogNormalizedItem]:
        products = self._products_for_revision(
            cursor,
            str(revision["revision_id"]),
        )
        snapshot_sha256 = _action_diff(
            products,
            "VERIFY",
            None,
        ).snapshot_sha256
        if snapshot_sha256 != str(revision["snapshot_sha256"]):
            raise OperatorProductCatalogError(
                "product_catalog_revision_snapshot_invalid"
            )
        return products

    def _active_products(
        self,
        cursor: Any,
    ) -> list[ProductCatalogNormalizedItem]:
        revision_id = self._active_revision_id(cursor)
        return (
            self._products_for_revision(cursor, revision_id)
            if revision_id is not None
            else []
        )

    def _locked_active_revision(self, cursor: Any) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT r.*
            FROM {self.prefix}operator_product_catalog_active a
            JOIN {self.prefix}operator_product_catalog_revision r
              ON r.revision_id = a.revision_id
            WHERE a.goal_id = %s
            FOR UPDATE OF a, r
            """,
            (_GOAL_ID,),
        )
        return _revision_record(
            _one(cursor, "product_catalog_active_revision_missing")
        )

    def get_cycle(self, cycle_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            return self._cycle_by_id(cursor, cycle_id)

    def list_cycles(self) -> list[dict[str, Any]]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_cycle
                ORDER BY cycle_number DESC
                LIMIT 10
                """
            )
            return [
                _cycle_record(row)
                for row in _rows(cursor)
            ]

    def get_cycle_page_state_counts(
        self,
        cycle_id: str,
    ) -> dict[str, int]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT state, COUNT(*) AS count
                FROM {self.prefix}operator_product_catalog_page
                WHERE cycle_id = %s::uuid
                GROUP BY state
                """,
                (cycle_id,),
            )
            counts = {
                str(row["state"]): int(row["count"])
                for row in _rows(cursor)
            }
        return {
            "CLAIMED": counts.get("CLAIMED", 0),
            "RETURNED": counts.get("RETURNED", 0),
            "UNKNOWN": counts.get("UNKNOWN", 0),
        }

    def _cycle_by_id(self, cursor: Any, cycle_id: str) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_product_catalog_cycle
            WHERE cycle_id = %s::uuid
            """,
            (cycle_id,),
        )
        return _cycle_record(
            _one(cursor, "product_catalog_cycle_not_found")
        )

    def list_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        revision_id: str | None = None,
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500 or offset < 0:
            raise OperatorProductCatalogError(
                "product_catalog_event_limit_invalid"
            )
        clauses: list[str] = []
        parameters: list[Any] = []
        if revision_id is not None:
            clauses.append("revision_id = %s::uuid")
            parameters.append(revision_id)
        if cycle_id is not None:
            clauses.append("cycle_id = %s::uuid")
            parameters.append(cycle_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_product_catalog_event
                {where}
                ORDER BY recorded_at DESC, event_id DESC
                LIMIT %s
                OFFSET %s
                """,
                (*parameters, limit, offset),
            )
            return [_event_record(row) for row in _rows(cursor)]

    def count_events(self) -> int:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self.prefix}operator_product_catalog_event
                """
            )
            return int(
                _one(
                    cursor,
                    "product_catalog_event_count_invalid",
                )["count"]
            )

    def _insert_revision(
        self,
        cursor: Any,
        *,
        state: str,
        source: str,
        source_cycle_id: str | None,
        parent_revision_id: str | None,
        rollback_of_revision_id: str | None,
        diff: ProductCatalogDiff,
        actor_id: str,
        operator_reason_sha256: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        revision_id = str(uuid.uuid4())
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_product_catalog_revision (
                revision_id, state, source, source_cycle_id,
                parent_revision_id, rollback_of_revision_id,
                snapshot_sha256, diff_sha256, product_count,
                added_count, changed_count, removed_count, unchanged_count,
                actor_id, operator_reason_sha256, correlation_id
            )
            VALUES (
                %s::uuid, %s, %s, %s::uuid, %s::uuid, %s::uuid,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                revision_id,
                state,
                source,
                source_cycle_id,
                parent_revision_id,
                rollback_of_revision_id,
                diff.snapshot_sha256,
                diff.diff_sha256,
                len(diff.snapshot),
                len(diff.added_product_ids),
                len(diff.changed_product_ids),
                len(diff.removed_product_ids),
                diff.unchanged_count,
                actor_id,
                operator_reason_sha256,
                correlation_id,
            ),
        )
        revision = _revision_record(
            _one(cursor, "product_catalog_revision_insert_failed")
        )
        for item in diff.snapshot:
            payload = item.model_dump(mode="json")
            change_type = _revision_product_change_type(
                source=source,
                product_id=item.product_id,
                diff=diff,
            )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_product (
                    revision_id, product_id, product_type,
                    base_currency, quote_currency, base_increment,
                    quote_increment, price_increment, base_min_size,
                    base_max_size, quote_min_size, quote_max_size,
                    display_name, exchange_status, exchange_disabled,
                    cancel_only, limit_only, post_only, view_only, lifecycle,
                    change_type
                )
                VALUES (
                    %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    revision_id,
                    payload["product_id"],
                    payload["product_type"],
                    payload["base_currency"],
                    payload["quote_currency"],
                    payload["base_increment"],
                    payload["quote_increment"],
                    payload["price_increment"],
                    payload["base_min_size"],
                    payload["base_max_size"],
                    payload["quote_min_size"],
                    payload["quote_max_size"],
                    payload["display_name"],
                    payload["exchange_status"],
                    payload["exchange_disabled"],
                    payload["cancel_only"],
                    payload["limit_only"],
                    payload["post_only"],
                    payload["view_only"],
                    payload["lifecycle"],
                    change_type,
                ),
            )
        return revision

    def _set_active(self, cursor: Any, revision_id: str) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_product_catalog_active (
                goal_id, revision_id
            )
            VALUES (%s, %s::uuid)
            ON CONFLICT (goal_id) DO UPDATE
            SET revision_id = EXCLUDED.revision_id, updated_at = NOW()
            """,
            (_GOAL_ID, revision_id),
        )

    def _validate_command(
        self,
        *,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> None:
        if (
            acknowledgement is not True
            or not isinstance(actor_id, str)
            or not 1 <= len(actor_id) <= 255
            or not isinstance(operator_reason, str)
            or not 1 <= len(operator_reason.strip()) <= 240
            or _EVIDENCE_ID_PATTERN.fullmatch(correlation_id) is None
            or _EVIDENCE_ID_PATTERN.fullmatch(idempotency_key) is None
        ):
            raise OperatorProductCatalogError(
                "product_catalog_command_invalid"
            )

    def record_local_command_rejection(
        self,
        *,
        operation: str,
        command_fields: dict[str, Any],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
        diagnostic_code: str,
    ) -> None:
        if operation not in _ACTIONS | {"APPROVE", "ROLLBACK"}:
            raise OperatorProductCatalogError(
                "product_catalog_operation_invalid"
            )
        if _DIAGNOSTIC_PATTERN.fullmatch(diagnostic_code) is None:
            diagnostic_code = "product_catalog_command_rejected"
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        payload = _local_command_payload(
            operation=operation,
            actor_id=actor_id,
            operator_reason=operator_reason,
            acknowledgement=acknowledgement,
            command_fields=command_fields,
        )
        payload_sha256 = _hash_json(payload)
        with self.database.get_cursor() as cursor:
            existing = self._existing_command(
                cursor,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
            if existing is not None:
                if existing["state"] == "REJECTED":
                    return
                raise OperatorProductCatalogError(
                    "product_catalog_idempotency_state_invalid"
                )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_product_catalog_command (
                    idempotency_key, payload_sha256, operation, state,
                    diagnostic_code
                )
                VALUES (%s, %s, %s, 'REJECTED', %s)
                """,
                (
                    idempotency_key,
                    payload_sha256,
                    operation,
                    diagnostic_code,
                ),
            )
            self._append_event(
                cursor,
                event_type="CATALOG_COMMAND_REJECTED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "operation": operation.lower(),
                    "diagnostic_code": diagnostic_code,
                },
            )

    def _existing_command(
        self,
        cursor: Any,
        *,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_product_catalog_command
            WHERE idempotency_key = %s
            FOR UPDATE
            """,
            (idempotency_key,),
        )
        rows = _rows(cursor)
        if not rows:
            return None
        row = rows[0]
        if str(row["payload_sha256"]) != payload_sha256:
            raise OperatorProductCatalogError(
                "product_catalog_idempotency_conflict"
            )
        return row

    def _claim_local_command(
        self,
        cursor: Any,
        *,
        idempotency_key: str,
        payload: dict[str, Any],
        operation: str,
    ) -> str | None:
        payload_sha256 = _hash_json(payload)
        existing = self._existing_command(
            cursor,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        if existing is not None:
            if existing["state"] == "REJECTED":
                diagnostic_code = str(
                    existing.get("diagnostic_code")
                    or "product_catalog_command_rejected"
                )
                raise OperatorProductCatalogError(diagnostic_code)
            result = existing.get("result_revision_id")
            if existing["state"] != "COMPLETED" or result is None:
                raise OperatorProductCatalogError(
                    "product_catalog_idempotency_state_invalid"
                )
            return str(result)
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_product_catalog_command (
                idempotency_key, payload_sha256, operation, state
            )
            VALUES (%s, %s, %s, 'IN_PROGRESS')
            """,
            (idempotency_key, payload_sha256, operation),
        )
        return None

    def _complete_command(
        self,
        cursor: Any,
        idempotency_key: str,
        revision_id: str,
    ) -> None:
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_product_catalog_command
            SET
                state = 'COMPLETED',
                result_revision_id = %s::uuid,
                updated_at = NOW()
            WHERE idempotency_key = %s AND state = 'IN_PROGRESS'
            """,
            (revision_id, idempotency_key),
        )

    def _append_event(
        self,
        cursor: Any,
        *,
        event_type: str,
        actor_id: str,
        correlation_id: str,
        evidence: dict[str, Any],
        revision_id: str | None = None,
        cycle_id: str | None = None,
        product_id: str | None = None,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_product_catalog_event (
                event_id, event_type, revision_id, cycle_id, product_id,
                actor_id, correlation_id, evidence
            )
            VALUES (
                %s::uuid, %s, %s::uuid, %s::uuid, %s, %s, %s, %s
            )
            """,
            (
                str(uuid.uuid4()),
                event_type,
                revision_id,
                cycle_id,
                product_id,
                actor_id,
                correlation_id,
                Json(evidence),
            ),
        )


def _local_command_payload(
    *,
    operation: str,
    actor_id: str,
    operator_reason: str,
    acknowledgement: bool,
    command_fields: dict[str, Any],
) -> dict[str, Any]:
    return {
        "operation": operation,
        **command_fields,
        "actor_id": actor_id,
        "operator_reason_sha256": _sha256(operator_reason),
        "acknowledgement": acknowledgement,
    }


def _action_diff(
    products: list[ProductCatalogNormalizedItem],
    action: str,
    product_id: str | None,
) -> ProductCatalogDiff:
    snapshot = sorted(products, key=lambda item: item.product_id)
    snapshot_payload = [
        item.model_dump(mode="json") for item in snapshot
    ]
    diff_payload = {"action": action, "product_id": product_id}
    return ProductCatalogDiff(
        snapshot=snapshot,
        added_product_ids=[],
        changed_product_ids=[product_id] if product_id is not None else [],
        removed_product_ids=[],
        unchanged_count=max(0, len(snapshot) - (1 if product_id else 0)),
        snapshot_sha256=_hash_json(snapshot_payload),
        diff_sha256=_hash_json(diff_payload),
    )


def _product_item(row: dict[str, Any]) -> ProductCatalogNormalizedItem:
    payload = {
        key: row[key]
        for key in (
            "product_id",
            "product_type",
            "base_currency",
            "quote_currency",
            "base_increment",
            "quote_increment",
            "price_increment",
            "base_min_size",
            "base_max_size",
            "quote_min_size",
            "quote_max_size",
            "display_name",
            "exchange_status",
            "exchange_disabled",
            "cancel_only",
            "limit_only",
            "post_only",
            "view_only",
            "lifecycle",
        )
    }
    return ProductCatalogNormalizedItem.model_validate(payload)


def _product_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_product_item(row).model_dump(mode="json"),
        "change_type": str(row["change_type"]),
    }


def _revision_product_change_type(
    *,
    source: str,
    product_id: str,
    diff: ProductCatalogDiff,
) -> str:
    if source == "ROLLBACK":
        return "ROLLBACK_RESTORED"
    if source == "OPERATOR_LIFECYCLE":
        return (
            "LIFECYCLE_CHANGED"
            if product_id in diff.changed_product_ids
            else "UNCHANGED"
        )
    if product_id in diff.added_product_ids:
        return "ADDED"
    if product_id in diff.changed_product_ids:
        return "CHANGED"
    if product_id in diff.removed_product_ids:
        return "REMOVED"
    return "UNCHANGED"


def _revision_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for key in (
        "revision_id",
        "source_cycle_id",
        "parent_revision_id",
        "rollback_of_revision_id",
    ):
        record[key] = _optional_uuid_text(record.get(key))
    record["active"] = bool(record.get("active", False))
    record["trading_authority_granted"] = False
    record["portfolio_scope_expanded"] = False
    record["exchange_mutation_count"] = 0
    record["created_at"] = _timestamp_text(record.get("created_at"))
    record["updated_at"] = _timestamp_text(record.get("updated_at"))
    return record


def _cycle_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for key in (
        "cycle_id",
        "expected_active_revision_id",
        "proposed_revision_id",
    ):
        record[key] = _optional_uuid_text(record.get(key))
    record.pop("operator_reason_sha256", None)
    return record


def _event_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for key in ("event_id", "revision_id", "cycle_id"):
        record[key] = _optional_uuid_text(record.get(key))
    evidence = record.get("evidence")
    record["evidence"] = dict(evidence) if isinstance(evidence, dict) else {}
    record["recorded_at"] = _timestamp_text(record.get("recorded_at"))
    return record


def _timestamp_text(value: Any) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description or ()]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorProductCatalogError(code)
    return rows[0]


def _optional_uuid_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def get_default_operator_product_catalog_repository(
) -> OperatorProductCatalogRepository:
    repository = OperatorProductCatalogRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def initialize_operator_product_catalog_schema() -> None:
    """Install and recover the durable catalog before serving operators."""

    get_default_operator_product_catalog_repository().ensure_schema()
