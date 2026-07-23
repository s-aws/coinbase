"""PostgreSQL durability for operator fill-ledger and inventory repair."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from application.admin_api.operator_fill_inventory_repair import (
    FillInventoryCatalogReadResult,
    FillInventoryCatalogSelector,
    FillInventoryProductProjection,
    FillInventoryProjectionEntry,
    NormalizedFillCatalogEntry,
    OperatorFillInventoryRepairError,
    PUBLIC_FILL_INVENTORY_REPAIR_CODES,
    build_fill_inventory_projection,
)
from core.enums import (
    FillInventoryRepairCaseState,
    FillInventoryRepairSelectorType,
)
from database.database import PostgresDB
from database.fill_ledger_lock import fill_ledger_product_lock_key


_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_ACTIVE_STATES = frozenset(
    {
        FillInventoryRepairCaseState.OPEN.value,
        FillInventoryRepairCaseState.REFRESHING.value,
        FillInventoryRepairCaseState.PLAN_READY.value,
        FillInventoryRepairCaseState.APPLIED.value,
        FillInventoryRepairCaseState.BLOCKED.value,
    }
)
_SYSTEM_OWNED = frozenset(
    {
        "ADMIN_MANUAL_ROOT",
        "ADMIN_AUTOMATION_ROOT",
        "ADMIN_FILL_FOLLOW_UP",
    }
)
_GOAL_ID = "operator_fill_ledger_and_inventory_repair_v1"


class OperatorFillInventoryRepairRepository:
    """Transaction-bounded import batches, projections, rollback, and audit."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
        order_schema: str = "public",
        fill_schema: str = "public",
    ) -> None:
        if any(
            _SCHEMA_PATTERN.fullmatch(value) is None
            for value in (schema, order_schema, fill_schema)
        ):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.order_schema = order_schema
        self.fill_schema = fill_schema
        self.prefix = f'"{schema}".'
        self.order_prefix = f'"{order_schema}".'
        self.fill_prefix = f'"{fill_schema}".'

    def ensure_schema(self) -> None:
        states = ", ".join(
            f"'{item.value}'" for item in FillInventoryRepairCaseState
        )
        selector_types = ", ".join(
            f"'{item.value}'" for item in FillInventoryRepairSelectorType
        )
        active_states = ", ".join(f"'{item}'" for item in _ACTIVE_STATES)
        diagnostic_codes = ", ".join(
            f"'{item}'" for item in PUBLIC_FILL_INVENTORY_REPAIR_CODES
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                ALTER TABLE {self.fill_prefix}fill_ledger
                ADD COLUMN IF NOT EXISTS exchange_fill_identity_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.fill_prefix}fill_ledger
                ADD COLUMN IF NOT EXISTS operator_import_batch_id UUID
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    operator_fill_ledger_identity_sha256_idx
                ON {self.fill_prefix}fill_ledger
                    (exchange_fill_identity_sha256)
                WHERE exchange_fill_identity_sha256 IS NOT NULL
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_fill_ledger_import_batch_idx
                ON {self.fill_prefix}fill_ledger (operator_import_batch_id)
                WHERE operator_import_batch_id IS NOT NULL
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_repair_case (
                    case_id UUID PRIMARY KEY,
                    selector_type TEXT NOT NULL
                        CHECK (selector_type IN ({selector_types})),
                    selector_sha256 CHAR(64) NOT NULL
                        CHECK (selector_sha256 ~ '^[0-9a-f]{{64}}$'),
                    client_order_id VARCHAR(40),
                    product_id VARCHAR(255) NOT NULL,
                    window_start TIMESTAMPTZ,
                    window_end TIMESTAMPTZ,
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    state TEXT NOT NULL CHECK (state IN ({states})),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    cycle_count INTEGER NOT NULL DEFAULT 0
                        CHECK (cycle_count BETWEEN 0 AND 10),
                    fill_read_logical_count INTEGER NOT NULL DEFAULT 0
                        CHECK (fill_read_logical_count BETWEEN 0 AND 10),
                    fill_read_page_count INTEGER NOT NULL DEFAULT 0
                        CHECK (fill_read_page_count BETWEEN 0 AND 2000),
                    last_cycle_fill_read_page_count INTEGER NOT NULL DEFAULT 0
                        CHECK (
                            last_cycle_fill_read_page_count BETWEEN 0 AND 200
                        ),
                    last_refresh_coinbase_read_state TEXT NOT NULL
                        DEFAULT 'NOT_RUN'
                        CHECK (
                            last_refresh_coinbase_read_state IN (
                                'NOT_RUN',
                                'RETURNED',
                                'UNKNOWN_AFTER_PAGE_CLAIM'
                            )
                        ),
                    catalog_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (catalog_fill_count >= 0),
                    missing_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (missing_fill_count >= 0),
                    existing_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (existing_fill_count >= 0),
                    unmatched_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (unmatched_fill_count >= 0),
                    affected_product_count INTEGER NOT NULL DEFAULT 0
                        CHECK (affected_product_count BETWEEN 0 AND 1),
                    imported_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (imported_fill_count >= 0),
                    rolled_back_fill_count INTEGER NOT NULL DEFAULT 0
                        CHECK (rolled_back_fill_count >= 0),
                    plan_sha256 CHAR(64) CHECK (
                        plan_sha256 IS NULL
                        OR plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    plan_json JSONB,
                    diagnostic_code TEXT NOT NULL
                        CHECK (diagnostic_code IN ({diagnostic_codes})),
                    created_by TEXT NOT NULL
                        CHECK (char_length(created_by) BETWEEN 1 AND 255),
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
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                DROP CONSTRAINT IF EXISTS
                    operator_fill_inventory_diagnostic_fixed
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                DROP CONSTRAINT IF EXISTS
                    operator_fill_inventory_correlation_fixed
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                ADD CONSTRAINT operator_fill_inventory_correlation_fixed
                    CHECK (
                        correlation_id ~
                            '^[A-Za-z0-9._:-]{{1,255}}$'
                    )
                    NOT VALID
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                VALIDATE CONSTRAINT
                    operator_fill_inventory_correlation_fixed
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                ADD CONSTRAINT operator_fill_inventory_diagnostic_fixed
                    CHECK (diagnostic_code IN ({diagnostic_codes}))
                    NOT VALID
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                VALIDATE CONSTRAINT
                    operator_fill_inventory_diagnostic_fixed
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                ADD COLUMN IF NOT EXISTS
                    last_cycle_fill_read_page_count INTEGER NOT NULL DEFAULT 0
                    CHECK (
                        last_cycle_fill_read_page_count BETWEEN 0 AND 200
                    )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_repair_case
                ADD COLUMN IF NOT EXISTS
                    last_refresh_coinbase_read_state TEXT NOT NULL
                    DEFAULT 'NOT_RUN'
                    CHECK (
                        last_refresh_coinbase_read_state IN (
                            'NOT_RUN',
                            'RETURNED',
                            'UNKNOWN_AFTER_PAGE_CLAIM'
                        )
                    )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_goal_ledger (
                    goal_id TEXT PRIMARY KEY
                        CHECK (
                            goal_id =
                            'operator_fill_ledger_and_inventory_repair_v1'
                        ),
                    cycle_count INTEGER NOT NULL DEFAULT 0
                        CHECK (cycle_count BETWEEN 0 AND 10),
                    fill_read_logical_count INTEGER NOT NULL DEFAULT 0
                        CHECK (fill_read_logical_count BETWEEN 0 AND 10),
                    fill_read_page_count INTEGER NOT NULL DEFAULT 0
                        CHECK (fill_read_page_count BETWEEN 0 AND 2000),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_fill_inventory_goal_ledger (
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
                    {self.prefix}operator_fill_inventory_page_claim (
                    case_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_fill_inventory_repair_case(case_id),
                    cycle_count INTEGER NOT NULL
                        CHECK (cycle_count BETWEEN 1 AND 10),
                    page_ordinal INTEGER NOT NULL
                        CHECK (page_ordinal BETWEEN 1 AND 200),
                    cursor_sha256 CHAR(64) CHECK (
                        cursor_sha256 IS NULL
                        OR cursor_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    invocation_state TEXT NOT NULL
                        DEFAULT 'UNKNOWN_AFTER_PAGE_CLAIM'
                        CHECK (
                            invocation_state IN (
                                'UNKNOWN_AFTER_PAGE_CLAIM',
                                'RETURNED'
                            )
                        ),
                    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    returned_at TIMESTAMPTZ,
                    PRIMARY KEY (case_id, cycle_count, page_ordinal)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_fill_inventory_page_claim
                ADD COLUMN IF NOT EXISTS invocation_state TEXT NOT NULL
                    DEFAULT 'UNKNOWN_AFTER_PAGE_CLAIM'
                    CHECK (
                        invocation_state IN (
                            'UNKNOWN_AFTER_PAGE_CLAIM',
                            'RETURNED'
                        )
                    )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_fill_inventory_page_claim
                ADD COLUMN IF NOT EXISTS returned_at TIMESTAMPTZ
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    operator_fill_inventory_one_active_selector_idx
                ON {self.prefix}operator_fill_inventory_repair_case
                    (selector_sha256)
                WHERE state IN ({active_states})
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_projection (
                    product_id VARCHAR(255) PRIMARY KEY,
                    source_case_id UUID NOT NULL,
                    fill_count INTEGER NOT NULL CHECK (fill_count >= 0),
                    open_lot_count INTEGER NOT NULL CHECK (open_lot_count >= 0),
                    open_quantity TEXT NOT NULL,
                    average_cost_basis TEXT NOT NULL,
                    remaining_cost_basis TEXT NOT NULL,
                    realized_operational_pnl TEXT NOT NULL,
                    total_fees TEXT NOT NULL,
                    projection_json JSONB NOT NULL,
                    projection_sha256 CHAR(64) NOT NULL
                        CHECK (projection_sha256 ~ '^[0-9a-f]{{64}}$'),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_lot (
                    product_id VARCHAR(255) NOT NULL REFERENCES
                        {self.prefix}operator_fill_inventory_projection(product_id)
                        ON DELETE CASCADE,
                    lot_identity_sha256 CHAR(64) NOT NULL
                        CHECK (lot_identity_sha256 ~ '^[0-9a-f]{{64}}$'),
                    source_case_id UUID NOT NULL,
                    remaining_quantity TEXT NOT NULL,
                    unit_cost_basis TEXT NOT NULL,
                    remaining_cost_basis TEXT NOT NULL,
                    acquired_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (product_id, lot_identity_sha256)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_import_batch (
                    batch_id UUID PRIMARY KEY,
                    case_id UUID NOT NULL UNIQUE REFERENCES
                        {self.prefix}operator_fill_inventory_repair_case(case_id),
                    product_id VARCHAR(255) NOT NULL,
                    before_projection_json JSONB,
                    before_projection_source_case_id UUID,
                    before_projection_snapshot_sha256 CHAR(64),
                    before_projection_snapshot_verified BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    CHECK (
                        (
                            before_projection_snapshot_verified
                            AND before_projection_snapshot_sha256 IS NOT NULL
                            AND before_projection_snapshot_sha256 ~
                                    '^[0-9a-f]{{64}}$'
                        )
                        OR (
                            NOT before_projection_snapshot_verified
                            AND before_projection_snapshot_sha256 IS NULL
                        )
                    ),
                    after_projection_sha256 CHAR(64) NOT NULL
                        CHECK (after_projection_sha256 ~ '^[0-9a-f]{{64}}$'),
                    after_ledger_sha256 CHAR(64) NOT NULL
                        CHECK (after_ledger_sha256 ~ '^[0-9a-f]{{64}}$'),
                    imported_fill_ownership_sha256 CHAR(64) NOT NULL
                        CHECK (
                            imported_fill_ownership_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    imported_alias_ownership_sha256 CHAR(64) NOT NULL
                        CHECK (
                            imported_alias_ownership_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    imported_fill_count INTEGER NOT NULL
                        CHECK (imported_fill_count >= 0),
                    imported_alias_count INTEGER NOT NULL
                        CHECK (imported_alias_count >= 0),
                    rolled_back BOOLEAN NOT NULL DEFAULT FALSE,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    rolled_back_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ADD COLUMN IF NOT EXISTS before_projection_source_case_id UUID
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ADD COLUMN IF NOT EXISTS
                    before_projection_snapshot_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ALTER COLUMN before_projection_snapshot_sha256 DROP NOT NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ADD COLUMN IF NOT EXISTS
                    before_projection_snapshot_verified BOOLEAN
                    NOT NULL DEFAULT FALSE
                """
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_import_batch
                SET before_projection_snapshot_sha256 = NULL
                WHERE NOT before_projection_snapshot_verified
                  AND before_projection_snapshot_sha256 IS NOT NULL
                """
            )
            cursor.execute(
                f"""
                SELECT batch_id::text, before_projection_json,
                       before_projection_source_case_id::text,
                       before_projection_snapshot_sha256
                FROM {self.prefix}operator_fill_inventory_import_batch
                WHERE before_projection_snapshot_verified
                FOR UPDATE
                """
            )
            for row in _rows(cursor):
                before_projection = row.get("before_projection_json")
                before_source_case_id = row.get(
                    "before_projection_source_case_id"
                )
                if (
                    (before_projection is None)
                    != (before_source_case_id is None)
                    or not row.get("before_projection_snapshot_sha256")
                    or _projection_snapshot_sha256(
                        dict(before_projection)
                        if before_projection is not None
                        else None,
                        str(before_source_case_id)
                        if before_source_case_id is not None
                        else None,
                    )
                    != row["before_projection_snapshot_sha256"]
                ):
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_schema_prior_projection_invalid"
                    )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                DROP CONSTRAINT IF EXISTS
                    before_projection_snapshot_binding_check
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ADD CONSTRAINT before_projection_snapshot_binding_check
                CHECK (
                    (
                        before_projection_snapshot_verified
                        AND before_projection_snapshot_sha256 IS NOT NULL
                        AND before_projection_snapshot_sha256 ~
                                '^[0-9a-f]{{64}}$'
                    )
                    OR (
                        NOT before_projection_snapshot_verified
                        AND before_projection_snapshot_sha256 IS NULL
                    )
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_fill_inventory_import_batch
                ADD COLUMN IF NOT EXISTS imported_alias_count INTEGER
                    NOT NULL DEFAULT 0 CHECK (imported_alias_count >= 0)
                """
            )
            for column in (
                "after_ledger_sha256",
                "imported_fill_ownership_sha256",
                "imported_alias_ownership_sha256",
            ):
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self.prefix}operator_fill_inventory_import_batch
                    ADD COLUMN IF NOT EXISTS {column} CHAR(64)
                        CHECK ({column} ~ '^[0-9a-f]{{64}}$')
                    """
                )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_identity_alias (
                    alias_sha256 CHAR(64) PRIMARY KEY
                        CHECK (alias_sha256 ~ '^[0-9a-f]{{64}}$'),
                    canonical_identity_sha256 CHAR(64) NOT NULL
                        CHECK (
                            canonical_identity_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    product_id VARCHAR(255) NOT NULL,
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_import_batch_id UUID NOT NULL,
                    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_fill_inventory_identity_alias_batch_idx
                ON {self.prefix}operator_fill_inventory_identity_alias
                    (operator_import_batch_id)
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_fill_inventory_repair_event (
                    event_id UUID PRIMARY KEY,
                    case_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_fill_inventory_repair_case(case_id),
                    event_type TEXT NOT NULL
                        CHECK (char_length(event_type) BETWEEN 1 AND 96),
                    actor_id TEXT NOT NULL
                        CHECK (char_length(actor_id) BETWEEN 1 AND 255),
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    operator_reason_sha256 CHAR(64) CHECK (
                        operator_reason_sha256 IS NULL
                        OR operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_fill_inventory_event_case_recorded_idx
                ON {self.prefix}operator_fill_inventory_repair_event
                    (case_id, recorded_at DESC)
                """
            )
            self._recover_interrupted_refreshes(cursor)

    def create_case(
        self,
        *,
        selector: FillInventoryCatalogSelector,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        case_id = str(uuid.uuid4())
        selector_json = {
            "selector_type": selector.selector_type.value,
            "client_order_id": selector.client_order_id,
            "product_id": selector.product_id,
            "window_start": (
                selector.window_start.isoformat()
                if selector.window_start is not None
                else None
            ),
            "window_end": (
                selector.window_end.isoformat()
                if selector.window_end is not None
                else None
            ),
            "portfolio_id_sha256": selector.portfolio_id_sha256,
        }
        selector_sha256 = _hash_json(selector_json)
        with self.database.get_cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self.prefix}operator_fill_inventory_repair_case (
                        case_id, selector_type, selector_sha256,
                        client_order_id, product_id, window_start, window_end,
                        portfolio_id_sha256, state, revision, diagnostic_code,
                        created_by, correlation_id
                    )
                    VALUES (
                        %s::uuid, %s, %s, %s, %s, %s, %s, %s,
                        %s, 1, 'fill_inventory_case_created', %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        case_id,
                        selector.selector_type.value,
                        selector_sha256,
                        selector.client_order_id,
                        selector.product_id,
                        selector.window_start,
                        selector.window_end,
                        selector.portfolio_id_sha256,
                        FillInventoryRepairCaseState.OPEN.value,
                        actor_id,
                        correlation_id,
                    ),
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolation":
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_case_conflict"
                    ) from exc
                raise
            row = _one(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="CASE_CREATED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={"revision": 1, "state": row["state"]},
            )
            return _case_record(row)

    def begin_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        allowed = (
            FillInventoryRepairCaseState.OPEN.value,
            FillInventoryRepairCaseState.PLAN_READY.value,
            FillInventoryRepairCaseState.BLOCKED.value,
        )
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_repair_case
                WHERE case_id = %s::uuid
                FOR UPDATE
                """,
                (case_id,),
            )
            current = _required_case(cursor)
            self._assert_revision(current, expected_revision)
            if current["state"] not in allowed:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_refresh_not_available"
                )
            if current["cycle_count"] >= 10:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_cycles_exhausted"
                )
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_goal_ledger
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (_GOAL_ID,),
            )
            goal = _one(cursor)
            if goal["cycle_count"] >= 10:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_goal_cycles_exhausted"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_goal_ledger
                SET cycle_count = cycle_count + 1,
                    fill_read_logical_count =
                        fill_read_logical_count + 1,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (_GOAL_ID,),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET state = %s,
                    revision = revision + 1,
                    cycle_count = cycle_count + 1,
                    fill_read_logical_count = fill_read_logical_count + 1,
                    last_cycle_fill_read_page_count = 0,
                    last_refresh_coinbase_read_state = 'NOT_RUN',
                    plan_sha256 = NULL,
                    plan_json = NULL,
                    diagnostic_code = 'fill_inventory_refresh_claimed',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    FillInventoryRepairCaseState.REFRESHING.value,
                    correlation_id,
                    case_id,
                ),
            )
            row = _one(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="CATALOG_REFRESH_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "revision": row["revision"],
                    "cycle_count": row["cycle_count"],
                    "fill_read_logical_count": row[
                        "fill_read_logical_count"
                    ],
                    "coinbase_read_ran": False,
                    "coinbase_read_state": "NOT_RUN",
                    "coinbase_order_mutation_ran": False,
                },
            )
            return _case_record(row)

    def record_fill_page_call(
        self,
        *,
        case_id: str,
        expected_revision: int,
        page_ordinal: int,
        cursor_sha256: str | None,
    ) -> dict[str, Any]:
        """Durably claim one page before its single network invocation."""

        if not 1 <= page_ordinal <= 200:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_page_ordinal_invalid"
            )
        if (
            cursor_sha256 is not None
            and re.fullmatch(r"^[0-9a-f]{64}$", cursor_sha256) is None
        ):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_page_cursor_hash_invalid"
            )
        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if current["state"] != FillInventoryRepairCaseState.REFRESHING.value:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_refresh_not_claimed"
                )
            if page_ordinal <= current["last_cycle_fill_read_page_count"]:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_page_claim_conflict"
                )
            if page_ordinal != current["last_cycle_fill_read_page_count"] + 1:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_page_claim_sequence_invalid"
                )
            try:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self.prefix}operator_fill_inventory_page_claim (
                        case_id, cycle_count, page_ordinal, cursor_sha256
                    )
                    VALUES (%s::uuid, %s, %s, %s)
                    """,
                    (
                        case_id,
                        current["cycle_count"],
                        page_ordinal,
                        cursor_sha256,
                    ),
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolation":
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_page_claim_conflict"
                    ) from exc
                raise
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET fill_read_page_count = fill_read_page_count + 1,
                    last_cycle_fill_read_page_count =
                        last_cycle_fill_read_page_count + 1,
                    last_refresh_coinbase_read_state =
                        'UNKNOWN_AFTER_PAGE_CLAIM',
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (case_id,),
            )
            row = _one(cursor)
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_goal_ledger
                SET fill_read_page_count = fill_read_page_count + 1,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (_GOAL_ID,),
            )
            return _case_record(row)

    def record_fill_page_returned(
        self,
        *,
        case_id: str,
        expected_revision: int,
        page_ordinal: int,
    ) -> dict[str, Any]:
        """Record that one claimed SDK page returned before normalization."""

        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if current["state"] != FillInventoryRepairCaseState.REFRESHING.value:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_refresh_not_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_page_claim
                SET invocation_state = 'RETURNED',
                    returned_at = NOW()
                WHERE case_id = %s::uuid
                  AND cycle_count = %s
                  AND page_ordinal = %s
                  AND invocation_state = 'UNKNOWN_AFTER_PAGE_CLAIM'
                """,
                (case_id, current["cycle_count"], page_ordinal),
            )
            if cursor.rowcount != 1:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_page_return_conflict"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*) FILTER (
                           WHERE invocation_state =
                               'UNKNOWN_AFTER_PAGE_CLAIM'
                       ) AS unknown_count
                FROM {self.prefix}operator_fill_inventory_page_claim
                WHERE case_id = %s::uuid
                  AND cycle_count = %s
                """,
                (case_id, current["cycle_count"]),
            )
            unknown_count = int(_one(cursor)["unknown_count"])
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET last_refresh_coinbase_read_state = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    (
                        "RETURNED"
                        if unknown_count == 0
                        else "UNKNOWN_AFTER_PAGE_CLAIM"
                    ),
                    case_id,
                ),
            )
            return _case_record(_one(cursor))

    def complete_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        catalog: FillInventoryCatalogReadResult,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if current["state"] != FillInventoryRepairCaseState.REFRESHING.value:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_refresh_not_claimed"
                )
            if current["last_cycle_fill_read_page_count"] != catalog.page_count:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_page_accounting_mismatch"
                )
            if current["last_refresh_coinbase_read_state"] != "RETURNED":
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_page_return_incomplete"
                )
            entries = list(catalog.entries)
            observed_identity_aliases: set[str] = set()
            for item in entries:
                aliases = set(item.fill_identity_aliases_sha256)
                if not observed_identity_aliases.isdisjoint(aliases):
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_catalog_duplicate_identity"
                    )
                observed_identity_aliases.update(aliases)
            for entry in entries:
                if (
                    entry.product_id != current["product_id"]
                    or entry.portfolio_id_sha256
                    != current["portfolio_id_sha256"]
                    or (
                        current["client_order_id"] is not None
                        and entry.client_order_id
                        != current["client_order_id"]
                    )
                ):
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_catalog_scope_mismatch"
                    )
            existing_hashes = self._existing_identity_hashes(
                cursor,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            missing = [
                entry
                for entry in entries
                if existing_hashes.isdisjoint(
                    entry.fill_identity_aliases_sha256
                )
            ]
            existing_count = len(entries) - len(missing)
            diagnostic = "fill_inventory_plan_ready"
            state = FillInventoryRepairCaseState.PLAN_READY.value
            projection: FillInventoryProductProjection | None = None
            try:
                projection_entries = self._projection_entries(
                    cursor,
                    product_id=current["product_id"],
                    portfolio_id_sha256=current["portfolio_id_sha256"],
                )
                base_ledger_sha256 = _projection_entries_sha256(
                    projection_entries
                )
                projection_entries.extend(missing)
                projection = build_fill_inventory_projection(
                    product_id=current["product_id"],
                    entries=projection_entries,
                )
            except OperatorFillInventoryRepairError as exc:
                base_ledger_sha256 = _projection_entries_sha256([])
                diagnostic = exc.code
                state = FillInventoryRepairCaseState.BLOCKED.value
            if catalog.unmatched_fill_count:
                diagnostic = "fill_inventory_unmatched_system_order"
                state = FillInventoryRepairCaseState.BLOCKED.value

            plan = {
                "selector_type": current["selector_type"],
                "catalog_fill_count": len(entries),
                "missing_fill_count": len(missing),
                "existing_fill_count": existing_count,
                "unmatched_fill_count": catalog.unmatched_fill_count,
                "affected_product_count": 1 if entries else 0,
                "apply_available": bool(
                    state == FillInventoryRepairCaseState.PLAN_READY.value
                    and missing
                    and projection is not None
                ),
                "base_ledger_sha256": base_ledger_sha256,
                "candidates": [
                    item.model_dump(mode="json") for item in missing
                ],
                "projection": (
                    projection.model_dump(mode="json")
                    if projection is not None
                    else None
                ),
                "diagnostic_code": diagnostic,
            }
            plan_sha256 = _hash_json(plan)
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET state = %s,
                    revision = revision + 1,
                    catalog_fill_count = %s,
                    missing_fill_count = %s,
                    existing_fill_count = %s,
                    unmatched_fill_count = %s,
                    affected_product_count = %s,
                    plan_sha256 = %s,
                    plan_json = %s,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    state,
                    len(entries),
                    len(missing),
                    existing_count,
                    catalog.unmatched_fill_count,
                    1 if entries else 0,
                    plan_sha256,
                    Json(plan),
                    diagnostic,
                    correlation_id,
                    case_id,
                ),
            )
            row = _one(cursor)
            event_type = (
                "CATALOG_REFRESH_COMPLETED"
                if state == FillInventoryRepairCaseState.PLAN_READY.value
                else "CATALOG_REFRESH_FAILED"
            )
            self._append_event(
                cursor,
                case_id=case_id,
                event_type=event_type,
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "revision": row["revision"],
                    "fill_read_page_count": catalog.page_count,
                    "catalog_fill_count": len(entries),
                    "missing_fill_count": len(missing),
                    "existing_fill_count": existing_count,
                    "unmatched_fill_count": catalog.unmatched_fill_count,
                    "affected_product_count": 1 if entries else 0,
                    "state": state,
                    "plan_sha256": plan_sha256,
                    "diagnostic_code": diagnostic,
                    "coinbase_read_ran": True,
                    "coinbase_order_mutation_ran": False,
                },
            )
            return _case_record(row)

    def fail_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        diagnostic_code: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if re.fullmatch(r"^[a-z][a-z0-9_]{0,95}$", diagnostic_code) is None:
            diagnostic_code = "fill_inventory_refresh_failed"
        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if current["state"] != FillInventoryRepairCaseState.REFRESHING.value:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_refresh_not_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET state = %s,
                    revision = revision + 1,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    FillInventoryRepairCaseState.BLOCKED.value,
                    diagnostic_code,
                    correlation_id,
                    case_id,
                ),
            )
            row = _one(cursor)
            read_state = str(
                row.get("last_refresh_coinbase_read_state") or "NOT_RUN"
            )
            read_evidence: dict[str, Any] = {
                "coinbase_read_state": read_state,
            }
            if read_state != "UNKNOWN_AFTER_PAGE_CLAIM":
                read_evidence["coinbase_read_ran"] = (
                    read_state == "RETURNED"
                )
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="CATALOG_REFRESH_FAILED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "revision": row["revision"],
                    "state": row["state"],
                    "diagnostic_code": diagnostic_code,
                    "coinbase_order_mutation_ran": False,
                    **read_evidence,
                },
            )
            return _case_record(row)

    def apply_import(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str,
        current_portfolio_id_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if (
                current["state"]
                != FillInventoryRepairCaseState.PLAN_READY.value
                or current["plan_sha256"] != plan_sha256
                or current["portfolio_id_sha256"]
                != current_portfolio_id_sha256
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_apply_conflict"
                )
            plan = current.get("plan_json") or {}
            if (
                _hash_json(plan) != plan_sha256
                or not plan.get("apply_available")
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_apply_not_available"
                )
            self._lock_product(cursor, current["product_id"])
            cursor.execute(
                f"""
                SELECT source_case_id, projection_json, projection_sha256
                FROM {self.prefix}operator_fill_inventory_projection
                WHERE product_id = %s
                FOR UPDATE
                """,
                (current["product_id"],),
            )
            projection_rows = _rows(cursor)
            if projection_rows:
                projection_row = projection_rows[0]
                before_projection = dict(
                    projection_row["projection_json"]
                )
                before_projection_source_case_id = str(
                    projection_row["source_case_id"]
                )
                if (
                    _hash_json(before_projection)
                    != projection_row["projection_sha256"]
                ):
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_apply_existing_projection_invalid"
                    )
                FillInventoryProductProjection.model_validate(
                    before_projection
                )
            else:
                before_projection = None
                before_projection_source_case_id = None
            before_projection_snapshot_sha256 = (
                _projection_snapshot_sha256(
                    before_projection,
                    before_projection_source_case_id,
                )
            )
            baseline_entries = self._projection_entries(
                cursor,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            if _projection_entries_sha256(
                baseline_entries
            ) != plan.get("base_ledger_sha256"):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_apply_baseline_changed"
                )
            candidates = [
                NormalizedFillCatalogEntry.model_validate(item)
                for item in plan.get("candidates", [])
            ]
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="IMPORT_APPLY_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "revision": current["revision"],
                    "missing_fill_count": len(candidates),
                    "coinbase_read_ran": False,
                    "coinbase_order_mutation_ran": False,
                },
            )
            imported_count = 0
            imported_alias_count = 0
            for entry in candidates:
                for alias_sha256 in entry.fill_identity_aliases_sha256:
                    cursor.execute(
                        f"""
                        INSERT INTO
                            {self.prefix}operator_fill_inventory_identity_alias (
                            alias_sha256, canonical_identity_sha256,
                            product_id, portfolio_id_sha256,
                            operator_import_batch_id
                        )
                        VALUES (%s, %s, %s, %s, %s::uuid)
                        ON CONFLICT (alias_sha256) DO NOTHING
                        RETURNING alias_sha256
                        """,
                        (
                            alias_sha256,
                            entry.fill_identity_sha256,
                            entry.product_id,
                            entry.portfolio_id_sha256,
                            case_id,
                        ),
                    )
                    if cursor.fetchone() is None:
                        raise OperatorFillInventoryRepairError(
                            "fill_inventory_apply_identity_alias_conflict"
                        )
                    imported_alias_count += 1
                derived_key = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"operator-fill-import:{entry.fill_identity_sha256}",
                    )
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self.fill_prefix}fill_ledger (
                        derived_trade_key,
                        exchange_fill_identity_sha256,
                        operator_import_batch_id,
                        instrument,
                        side,
                        quantity,
                        price,
                        timestamp,
                        fees,
                        commission_percentage,
                        client_order_id,
                        reconciliation_status,
                        reconciled_at
                    )
                    VALUES (
                        %s::uuid, %s, %s::uuid, %s, %s, %s, %s,
                        %s, %s, 0, %s, 'RECONCILED', NOW()
                    )
                    ON CONFLICT (exchange_fill_identity_sha256)
                        WHERE exchange_fill_identity_sha256 IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        derived_key,
                        entry.fill_identity_sha256,
                        case_id,
                        entry.product_id,
                        entry.side,
                        entry.quantity,
                        entry.price,
                        _database_utc_timestamp(entry.trade_time),
                        entry.fees,
                        entry.client_order_id,
                    ),
                )
                if cursor.fetchone() is None:
                    raise OperatorFillInventoryRepairError(
                        "fill_inventory_apply_identity_conflict"
                    )
                imported_count += 1

            after_entries = self._projection_entries(
                cursor,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            projection = build_fill_inventory_projection(
                product_id=current["product_id"],
                entries=after_entries,
            )
            projection_json = projection.model_dump(mode="json")
            if projection_json != plan.get("projection"):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_apply_projection_changed"
                )
            projection_sha256 = _hash_json(projection_json)
            after_ledger_sha256 = _projection_entries_sha256(after_entries)
            (
                imported_fill_ownership_sha256,
                owned_fill_count,
            ) = self._batch_fill_ownership_sha256(
                cursor,
                case_id=case_id,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            (
                imported_alias_ownership_sha256,
                owned_alias_count,
            ) = self._batch_alias_ownership_sha256(
                cursor,
                case_id=case_id,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            if (
                owned_fill_count != imported_count
                or owned_alias_count != imported_alias_count
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_apply_ownership_mismatch"
                )
            self._write_projection(
                cursor,
                projection=projection,
                source_case_id=case_id,
                projection_sha256=projection_sha256,
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_fill_inventory_import_batch (
                    batch_id, case_id, product_id, before_projection_json,
                    before_projection_source_case_id,
                    before_projection_snapshot_sha256,
                    before_projection_snapshot_verified,
                    after_projection_sha256, after_ledger_sha256,
                    imported_fill_ownership_sha256,
                    imported_alias_ownership_sha256,
                    imported_fill_count, imported_alias_count
                )
                VALUES (
                    %s::uuid, %s::uuid, %s, %s, %s::uuid, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    str(uuid.uuid4()),
                    case_id,
                    current["product_id"],
                    Json(before_projection)
                    if before_projection is not None
                    else None,
                    before_projection_source_case_id,
                    before_projection_snapshot_sha256,
                    True,
                    projection_sha256,
                    after_ledger_sha256,
                    imported_fill_ownership_sha256,
                    imported_alias_ownership_sha256,
                    imported_count,
                    imported_alias_count,
                ),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET state = %s,
                    revision = revision + 1,
                    imported_fill_count = %s,
                    diagnostic_code = 'fill_inventory_import_applied',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    FillInventoryRepairCaseState.APPLIED.value,
                    imported_count,
                    correlation_id,
                    case_id,
                ),
            )
            row = _one(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="IMPORT_APPLIED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "revision": row["revision"],
                    "imported_fill_count": imported_count,
                    "state": row["state"],
                    "coinbase_read_ran": False,
                    "coinbase_order_mutation_ran": False,
                },
            )
            return _case_record(row)

    def rollback_import(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str,
        current_portfolio_id_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            current = self._locked_case(cursor, case_id)
            self._assert_revision(current, expected_revision)
            if (
                current["state"]
                != FillInventoryRepairCaseState.APPLIED.value
                or current["portfolio_id_sha256"]
                != current_portfolio_id_sha256
                or current["plan_sha256"] != plan_sha256
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_conflict"
                )
            self._lock_product(cursor, current["product_id"])
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_import_batch
                WHERE case_id = %s::uuid
                FOR UPDATE
                """,
                (case_id,),
            )
            batch = _one(cursor)
            if batch["rolled_back"]:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_already_complete"
                )
            if batch.get("before_projection_snapshot_verified") is not True:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_prior_projection_unverified"
                )
            before_projection_value = batch.get("before_projection_json")
            before_projection = (
                dict(before_projection_value)
                if before_projection_value is not None
                else None
            )
            before_source_value = batch.get(
                "before_projection_source_case_id"
            )
            before_projection_source_case_id = (
                str(before_source_value)
                if before_source_value is not None
                else None
            )
            if (
                (before_projection is None)
                != (before_projection_source_case_id is None)
                or not batch.get("before_projection_snapshot_sha256")
                or _projection_snapshot_sha256(
                    before_projection,
                    before_projection_source_case_id,
                )
                != batch["before_projection_snapshot_sha256"]
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_prior_projection_changed"
                )
            validated_before_projection = (
                FillInventoryProductProjection.model_validate(
                    before_projection
                )
                if before_projection is not None
                else None
            )
            cursor.execute(
                f"""
                SELECT source_case_id, projection_json, projection_sha256
                FROM {self.prefix}operator_fill_inventory_projection
                WHERE product_id = %s
                FOR UPDATE
                """,
                (current["product_id"],),
            )
            projection_rows = _rows(cursor)
            if (
                not projection_rows
                or str(projection_rows[0]["source_case_id"]) != case_id
                or _hash_json(
                    dict(projection_rows[0]["projection_json"])
                )
                != projection_rows[0]["projection_sha256"]
                or projection_rows[0]["projection_sha256"]
                != batch["after_projection_sha256"]
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_superseded"
                )
            (
                current_fill_ownership_sha256,
                owned_fill_count,
            ) = self._batch_fill_ownership_sha256(
                cursor,
                case_id=case_id,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            if (
                not batch.get("imported_fill_ownership_sha256")
                or current_fill_ownership_sha256
                != batch["imported_fill_ownership_sha256"]
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_fill_ownership_mismatch"
                )
            (
                current_alias_ownership_sha256,
                owned_alias_count,
            ) = self._batch_alias_ownership_sha256(
                cursor,
                case_id=case_id,
                product_id=current["product_id"],
                portfolio_id_sha256=current["portfolio_id_sha256"],
            )
            if (
                not batch.get("imported_alias_ownership_sha256")
                or current_alias_ownership_sha256
                != batch["imported_alias_ownership_sha256"]
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_alias_ownership_mismatch"
                )
            after_ledger_sha256 = str(
                batch.get("after_ledger_sha256") or ""
            )
            current_ledger_sha256 = _projection_entries_sha256(
                self._projection_entries(
                    cursor,
                    product_id=current["product_id"],
                    portfolio_id_sha256=current["portfolio_id_sha256"],
                )
            )
            if (
                not after_ledger_sha256
                or current_ledger_sha256 != after_ledger_sha256
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_ledger_changed"
                )
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="IMPORT_ROLLBACK_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "revision": current["revision"],
                    "imported_fill_count": current["imported_fill_count"],
                    "coinbase_read_ran": False,
                    "coinbase_order_mutation_ran": False,
                },
            )
            if owned_fill_count != current["imported_fill_count"]:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_fill_count_mismatch"
                )
            if owned_alias_count != int(batch["imported_alias_count"]):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_alias_count_mismatch"
                )
            cursor.execute(
                f"""
                DELETE FROM {self.fill_prefix}fill_ledger
                WHERE operator_import_batch_id = %s::uuid
                """,
                (case_id,),
            )
            deleted_count = cursor.rowcount
            if deleted_count != current["imported_fill_count"]:
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_fill_count_mismatch"
                )
            cursor.execute(
                f"""
                DELETE FROM
                    {self.prefix}operator_fill_inventory_identity_alias
                WHERE operator_import_batch_id = %s::uuid
                """,
                (case_id,),
            )
            if cursor.rowcount != int(batch["imported_alias_count"]):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_alias_count_mismatch"
                )
            plan = current.get("plan_json") or {}
            remaining_ledger_sha256 = _projection_entries_sha256(
                self._projection_entries(
                    cursor,
                    product_id=current["product_id"],
                    portfolio_id_sha256=current["portfolio_id_sha256"],
                )
            )
            if (
                _hash_json(plan) != plan_sha256
                or remaining_ledger_sha256
                != plan.get("base_ledger_sha256")
            ):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_rollback_baseline_changed"
                )
            if validated_before_projection is None:
                cursor.execute(
                    f"""
                    DELETE FROM {self.prefix}operator_fill_inventory_projection
                    WHERE product_id = %s
                    """,
                    (current["product_id"],),
                )
            else:
                self._write_projection(
                    cursor,
                    projection=validated_before_projection,
                    source_case_id=before_projection_source_case_id,
                    projection_sha256=_hash_json(before_projection),
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_import_batch
                SET rolled_back = TRUE, rolled_back_at = NOW()
                WHERE case_id = %s::uuid
                """,
                (case_id,),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_fill_inventory_repair_case
                SET state = %s,
                    revision = revision + 1,
                    rolled_back_fill_count = %s,
                    diagnostic_code = 'fill_inventory_import_rolled_back',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    FillInventoryRepairCaseState.ROLLED_BACK.value,
                    deleted_count,
                    correlation_id,
                    case_id,
                ),
            )
            row = _one(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="IMPORT_ROLLED_BACK",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "revision": row["revision"],
                    "rolled_back_fill_count": deleted_count,
                    "state": row["state"],
                    "coinbase_read_ran": False,
                    "coinbase_order_mutation_ran": False,
                },
            )
            return _case_record(row)

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_repair_case
                WHERE case_id = %s::uuid
                """,
                (case_id,),
            )
            rows = _rows(cursor)
        if not rows:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_case_not_found"
            )
        return _case_record(rows[0])

    def list_cases(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM
                    {self.prefix}operator_fill_inventory_repair_case
                """
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_repair_case
                ORDER BY updated_at DESC, case_id DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = _rows(cursor)
        return [_case_record(row) for row in rows], total

    def get_goal_budget(self) -> dict[str, int]:
        """Return the one durable, goal-global refresh allowance ledger."""

        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT cycle_count, fill_read_logical_count,
                       fill_read_page_count
                FROM {self.prefix}operator_fill_inventory_goal_ledger
                WHERE goal_id = %s
                """,
                (_GOAL_ID,),
            )
            row = _one(cursor)
        return {
            "goal_cycle_count": int(row["cycle_count"]),
            "goal_cycle_limit": 10,
            "goal_fill_read_logical_count": int(
                row["fill_read_logical_count"]
            ),
            "goal_fill_read_page_count": int(row["fill_read_page_count"]),
        }

    def list_events(
        self,
        case_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM
                    {self.prefix}operator_fill_inventory_repair_event
                WHERE case_id = %s::uuid
                ORDER BY recorded_at ASC, event_id ASC
                LIMIT %s
                """,
                (case_id, limit),
            )
            return _rows(cursor)

    def get_projection(self, product_id: str) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            return self._projection_json(cursor, product_id)

    def resolve_system_order(
        self,
        *,
        exchange_order_id: str,
        product_id: str,
        portfolio_id_sha256: str,
    ) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, ownership_provenance,
                       retail_portfolio_id::text AS retail_portfolio_id
                FROM {self.order_prefix}order_parent
                WHERE exchange_order_id = %s AND product_id = %s
                LIMIT 2
                """,
                (exchange_order_id, product_id),
            )
            rows = _rows(cursor)
        if len(rows) != 1:
            return None
        row = rows[0]
        observed_hash = _sha256(str(row.get("retail_portfolio_id") or ""))
        return {
            "client_order_id": row["client_order_id"],
            "product_id": row["product_id"],
            "portfolio_id_sha256": observed_hash,
            "system_owned": (
                row.get("ownership_provenance") in _SYSTEM_OWNED
                and observed_hash == portfolio_id_sha256
            ),
        }

    def resolve_exact_order(
        self,
        *,
        client_order_id: str,
        configured_portfolio_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, ownership_provenance,
                       retail_portfolio_id::text AS retail_portfolio_id,
                       exchange_order_id
                FROM {self.order_prefix}order_parent
                WHERE client_order_id = %s
                """,
                (client_order_id,),
            )
            rows = _rows(cursor)
        if len(rows) != 1:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_order_not_found"
            )
        row = rows[0]
        if (
            row.get("ownership_provenance") not in _SYSTEM_OWNED
            or not row.get("exchange_order_id")
            or row.get("product_id") != "BTC-USDC"
            or str(row.get("retail_portfolio_id") or "")
            != configured_portfolio_id
        ):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_order_not_eligible"
            )
        return row

    def _recover_interrupted_refreshes(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_fill_inventory_repair_case
            SET state = %s,
                revision = revision + 1,
                diagnostic_code = CASE
                    WHEN last_refresh_coinbase_read_state =
                        'UNKNOWN_AFTER_PAGE_CLAIM'
                    THEN 'fill_inventory_refresh_interrupted_unknown'
                    WHEN last_refresh_coinbase_read_state = 'RETURNED'
                    THEN 'fill_inventory_refresh_interrupted_returned'
                    ELSE 'fill_inventory_refresh_interrupted_before_call'
                END,
                updated_at = NOW()
            WHERE state = %s
            RETURNING *
            """,
            (
                FillInventoryRepairCaseState.BLOCKED.value,
                FillInventoryRepairCaseState.REFRESHING.value,
            ),
        )
        for row in _rows(cursor):
            read_state = str(
                row.get("last_refresh_coinbase_read_state") or "NOT_RUN"
            )
            read_evidence: dict[str, Any] = {
                "coinbase_read_state": read_state,
            }
            if read_state != "UNKNOWN_AFTER_PAGE_CLAIM":
                read_evidence["coinbase_read_ran"] = (
                    read_state == "RETURNED"
                )
            self._append_event(
                cursor,
                case_id=str(row["case_id"]),
                event_type="CATALOG_REFRESH_FAILED",
                actor_id="system_restart_recovery",
                correlation_id=str(row["correlation_id"]),
                operator_reason=None,
                evidence={
                    "revision": row["revision"],
                    "cycle_count": row["cycle_count"],
                    "fill_read_logical_count": row[
                        "fill_read_logical_count"
                    ],
                    "state": row["state"],
                    "diagnostic_code": row["diagnostic_code"],
                    "coinbase_order_mutation_ran": False,
                    **read_evidence,
                },
            )

    def _locked_case(self, cursor: Any, case_id: str) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT * FROM {self.prefix}operator_fill_inventory_repair_case
            WHERE case_id = %s::uuid
            FOR UPDATE
            """,
            (case_id,),
        )
        return _required_case(cursor)

    @staticmethod
    def _assert_revision(row: dict[str, Any], expected: int) -> None:
        if row["revision"] != expected:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_revision_conflict"
            )

    def _existing_identity_hashes(
        self,
        cursor: Any,
        *,
        product_id: str,
        portfolio_id_sha256: str,
    ) -> set[str]:
        cursor.execute(
            f"""
            SELECT fl.exchange_fill_identity_sha256,
                   fl.exchange_trade_id::text AS exchange_trade_id,
                   fl.exchange_entry_id,
                   op.retail_portfolio_id::text AS retail_portfolio_id
            FROM {self.fill_prefix}fill_ledger fl
            JOIN {self.order_prefix}order_parent op
              ON op.client_order_id = fl.client_order_id
            WHERE fl.instrument = %s
              AND op.product_id = %s
              AND op.ownership_provenance = ANY(%s)
            """,
            (product_id, product_id, list(sorted(_SYSTEM_OWNED))),
        )
        values: set[str] = set()
        for row in _rows(cursor):
            if _sha256(
                str(row.get("retail_portfolio_id") or "")
            ) != portfolio_id_sha256:
                continue
            direct = str(
                row.get("exchange_fill_identity_sha256") or ""
            ).strip()
            if direct:
                values.add(direct)
            for key in ("exchange_trade_id", "exchange_entry_id"):
                raw = str(row.get(key) or "").strip()
                if raw:
                    values.add(_sha256(raw))
        cursor.execute(
            f"""
            SELECT alias_sha256
            FROM {self.prefix}operator_fill_inventory_identity_alias
            WHERE product_id = %s
              AND portfolio_id_sha256 = %s
            """,
            (product_id, portfolio_id_sha256),
        )
        values.update(str(row["alias_sha256"]) for row in _rows(cursor))
        return values

    def _batch_fill_ownership_sha256(
        self,
        cursor: Any,
        *,
        case_id: str,
        product_id: str,
        portfolio_id_sha256: str,
    ) -> tuple[str, int]:
        cursor.execute(
            f"""
            SELECT fl.exchange_fill_identity_sha256,
                   fl.client_order_id,
                   fl.instrument,
                   op.product_id AS order_product_id,
                   op.ownership_provenance,
                   op.retail_portfolio_id::text AS retail_portfolio_id
            FROM {self.fill_prefix}fill_ledger fl
            LEFT JOIN {self.order_prefix}order_parent op
              ON op.client_order_id = fl.client_order_id
            WHERE fl.operator_import_batch_id = %s::uuid
            ORDER BY fl.exchange_fill_identity_sha256 ASC,
                     fl.client_order_id ASC,
                     fl.instrument ASC
            """,
            (case_id,),
        )
        ownership = [
            {
                "fill_identity_sha256": str(
                    row.get("exchange_fill_identity_sha256") or ""
                ),
                "client_order_id_sha256": _sha256(
                    str(row.get("client_order_id") or "")
                ),
                "fill_product_id": str(row.get("instrument") or ""),
                "order_product_id": str(
                    row.get("order_product_id") or ""
                ),
                "ownership_provenance": str(
                    row.get("ownership_provenance") or ""
                ),
                "portfolio_id_sha256": _sha256(
                    str(row.get("retail_portfolio_id") or "")
                ),
            }
            for row in _rows(cursor)
        ]
        return (
            _hash_json(
                {
                    "expected_product_id": product_id,
                    "expected_portfolio_id_sha256": portfolio_id_sha256,
                    "fills": ownership,
                }
            ),
            len(ownership),
        )

    def _batch_alias_ownership_sha256(
        self,
        cursor: Any,
        *,
        case_id: str,
        product_id: str,
        portfolio_id_sha256: str,
    ) -> tuple[str, int]:
        cursor.execute(
            f"""
            SELECT alias_sha256, canonical_identity_sha256,
                   product_id, portfolio_id_sha256
            FROM {self.prefix}operator_fill_inventory_identity_alias
            WHERE operator_import_batch_id = %s::uuid
            ORDER BY alias_sha256 ASC
            """,
            (case_id,),
        )
        ownership = [
            {
                "alias_sha256": str(row["alias_sha256"]),
                "canonical_identity_sha256": str(
                    row["canonical_identity_sha256"]
                ),
                "product_id": str(row["product_id"]),
                "portfolio_id_sha256": str(
                    row["portfolio_id_sha256"]
                ),
            }
            for row in _rows(cursor)
        ]
        return (
            _hash_json(
                {
                    "expected_product_id": product_id,
                    "expected_portfolio_id_sha256": portfolio_id_sha256,
                    "aliases": ownership,
                }
            ),
            len(ownership),
        )

    def _projection_entries(
        self,
        cursor: Any,
        *,
        product_id: str,
        portfolio_id_sha256: str,
    ) -> list[FillInventoryProjectionEntry]:
        cursor.execute(
            f"""
            SELECT fl.derived_trade_key::text AS derived_trade_key,
                   fl.exchange_fill_identity_sha256,
                   fl.instrument, fl.side, fl.quantity::text AS quantity,
                   fl.price::text AS price, fl.fees::text AS fees,
                   fl.timestamp,
                   op.retail_portfolio_id::text AS retail_portfolio_id
            FROM {self.fill_prefix}fill_ledger fl
            JOIN {self.order_prefix}order_parent op
              ON op.client_order_id = fl.client_order_id
            WHERE fl.instrument = %s
              AND op.product_id = %s
              AND op.ownership_provenance = ANY(%s)
            ORDER BY fl.timestamp ASC, fl.id ASC
            """,
            (product_id, product_id, list(sorted(_SYSTEM_OWNED))),
        )
        entries: list[FillInventoryProjectionEntry] = []
        for row in _rows(cursor):
            observed_portfolio_hash = _sha256(
                str(row.get("retail_portfolio_id") or "")
            )
            if observed_portfolio_hash != portfolio_id_sha256:
                continue
            identity = str(
                row.get("exchange_fill_identity_sha256") or ""
            ).strip() or _sha256(str(row["derived_trade_key"]))
            entries.append(
                FillInventoryProjectionEntry(
                    fill_identity_sha256=identity,
                    product_id=row["instrument"],
                    side=str(row["side"]).upper(),
                    quantity=row["quantity"],
                    price=row["price"],
                    fees=row["fees"],
                    trade_time=_aware_utc_timestamp(row["timestamp"]),
                    portfolio_id_sha256=portfolio_id_sha256,
                )
            )
        return entries

    def _projection_json(
        self,
        cursor: Any,
        product_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT projection_json
            FROM {self.prefix}operator_fill_inventory_projection
            WHERE product_id = %s
            """,
            (product_id,),
        )
        rows = _rows(cursor)
        return dict(rows[0]["projection_json"]) if rows else None

    def _write_projection(
        self,
        cursor: Any,
        *,
        projection: FillInventoryProductProjection,
        source_case_id: str,
        projection_sha256: str,
    ) -> None:
        data = projection.model_dump(mode="json")
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_fill_inventory_projection (
                product_id, source_case_id, fill_count, open_lot_count,
                open_quantity, average_cost_basis, remaining_cost_basis,
                realized_operational_pnl, total_fees, projection_json,
                projection_sha256
            )
            VALUES (
                %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (product_id) DO UPDATE
            SET source_case_id = EXCLUDED.source_case_id,
                fill_count = EXCLUDED.fill_count,
                open_lot_count = EXCLUDED.open_lot_count,
                open_quantity = EXCLUDED.open_quantity,
                average_cost_basis = EXCLUDED.average_cost_basis,
                remaining_cost_basis = EXCLUDED.remaining_cost_basis,
                realized_operational_pnl =
                    EXCLUDED.realized_operational_pnl,
                total_fees = EXCLUDED.total_fees,
                projection_json = EXCLUDED.projection_json,
                projection_sha256 = EXCLUDED.projection_sha256,
                updated_at = NOW()
            """,
            (
                projection.product_id,
                source_case_id,
                projection.fill_count,
                projection.open_lot_count,
                projection.open_quantity,
                projection.average_cost_basis,
                projection.remaining_cost_basis,
                projection.realized_operational_pnl,
                projection.total_fees,
                Json(data),
                projection_sha256,
            ),
        )
        cursor.execute(
            f"""
            DELETE FROM {self.prefix}operator_fill_inventory_lot
            WHERE product_id = %s
            """,
            (projection.product_id,),
        )
        for lot in projection.lots:
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_fill_inventory_lot (
                    product_id, lot_identity_sha256, source_case_id,
                    remaining_quantity, unit_cost_basis,
                    remaining_cost_basis, acquired_at
                )
                VALUES (%s, %s, %s::uuid, %s, %s, %s, %s)
                """,
                (
                    projection.product_id,
                    lot.lot_identity_sha256,
                    source_case_id,
                    lot.remaining_quantity,
                    lot.unit_cost_basis,
                    lot.remaining_cost_basis,
                    lot.acquired_at,
                ),
            )

    @staticmethod
    def _lock_product(cursor: Any, product_id: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (fill_ledger_product_lock_key(product_id),),
        )

    def _append_event(
        self,
        cursor: Any,
        *,
        case_id: str,
        event_type: str,
        actor_id: str,
        correlation_id: str,
        operator_reason: str | None,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_fill_inventory_repair_event (
                event_id, case_id, event_type, actor_id, correlation_id,
                operator_reason_sha256, evidence
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                case_id,
                event_type,
                actor_id,
                correlation_id,
                _sha256(operator_reason) if operator_reason else None,
                Json(evidence),
            ),
        )


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description or ()]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one(cursor: Any) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_repository_row_count_invalid"
        )
    return rows[0]


def _required_case(cursor: Any) -> dict[str, Any]:
    rows = _rows(cursor)
    if not rows:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_case_not_found"
        )
    return rows[0]


def _case_record(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    record["case_id"] = str(record["case_id"])
    plan = record.pop("plan_json", None)
    record["plan"] = dict(plan) if isinstance(plan, dict) else None
    return record


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _projection_snapshot_sha256(
    projection: dict[str, Any] | None,
    source_case_id: str | None,
) -> str:
    """Bind exact prior projection bytes to their authoritative provenance."""

    return _hash_json(
        {
            "projection": projection,
            "source_case_id": source_case_id,
        }
    )


def _projection_entries_sha256(
    entries: list[FillInventoryProjectionEntry],
) -> str:
    """Hash the exact scoped FIFO inputs that an operator reviewed."""

    ordered = sorted(
        entries,
        key=lambda item: (item.trade_time, item.fill_identity_sha256),
    )
    return _hash_json(
        [item.model_dump(mode="json") for item in ordered]
    )


def _aware_utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_timestamp_invalid"
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_utc_timestamp(value: datetime) -> datetime:
    """Write canonical UTC wall time to production TIMESTAMP columns."""

    return _aware_utc_timestamp(value).replace(tzinfo=None)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def get_default_operator_fill_inventory_repair_repository(
) -> OperatorFillInventoryRepairRepository:
    repository = OperatorFillInventoryRepairRepository(PostgresDB())
    repository.ensure_schema()
    return repository
