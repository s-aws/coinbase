"""PostgreSQL durability for operator parent-strategy administration."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
    ParentStrategyTerms,
    evaluate_parent_strategy_delete,
)
from database.database import PostgresDB


_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_PRODUCT_CATALOG_GOAL_ID = "operator_product_catalog_administration_v1"
_FOLLOW_UP_ROOT_LOCK_NAMESPACE = 17291
_TERMINAL_PARENT_STATES = frozenset(
    {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
)
_COMMAND_RESULT_FIELDS = (
    "strategy_id",
    "name",
    "portfolio_scope_sha256",
    "admitted_product_catalog_revision_id",
    "admitted_product_catalog_snapshot_sha256",
    "product_id",
    "side",
    "reference_size",
    "reference_price",
    "target_movement",
    "target_movement_type",
    "max_order_replacement",
    "allow_partial_fills",
    "child_order_type",
    "child_time_in_force",
    "child_post_only",
    "lifecycle_state",
    "revision",
    "use_count",
    "materialized_root_client_order_id",
    "unused_or_terminal",
    "active_placement_count",
    "child_count",
    "unresolved_claim_count",
    "reconciliation_required",
    "delete_allowed",
    "delete_blockers",
    "allowed_actions",
    "created_at",
    "updated_at",
)


class OperatorParentStrategyRepository:
    """Revision-bound local definitions and append-only command evidence."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
    ) -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorParentStrategyError(
                "parent_strategy_schema_invalid"
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
                    {self.prefix}operator_parent_strategy (
                    strategy_id UUID PRIMARY KEY,
                    name VARCHAR(80) NOT NULL,
                    portfolio_scope_sha256 CHAR(64) NOT NULL
                        CHECK (
                            portfolio_scope_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    admitted_product_catalog_revision_id UUID NOT NULL,
                    admitted_product_catalog_snapshot_sha256 CHAR(64) NOT NULL
                        CHECK (
                            admitted_product_catalog_snapshot_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    product_id VARCHAR(131) NOT NULL,
                    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    reference_size NUMERIC NOT NULL
                        CHECK (reference_size > 0),
                    reference_price NUMERIC NOT NULL
                        CHECK (reference_price > 0),
                    target_movement NUMERIC NOT NULL
                        CHECK (target_movement > 0),
                    target_movement_type CHAR(1) NOT NULL
                        CHECK (target_movement_type IN ('P', 'A')),
                    max_order_replacement INTEGER NOT NULL
                        CHECK (
                            max_order_replacement BETWEEN 0 AND 100
                        ),
                    allow_partial_fills BOOLEAN NOT NULL,
                    child_order_type TEXT NOT NULL
                        CHECK (child_order_type = 'LIMIT'),
                    child_time_in_force TEXT NOT NULL
                        CHECK (
                            child_time_in_force =
                                'GOOD_UNTIL_CANCELLED'
                        ),
                    child_post_only BOOLEAN NOT NULL
                        CHECK (child_post_only),
                    lifecycle_state TEXT NOT NULL
                        CHECK (
                            lifecycle_state IN (
                                'ACTIVE', 'DEACTIVATED', 'DELETED'
                            )
                        ),
                    revision INTEGER NOT NULL DEFAULT 1
                        CHECK (revision >= 1),
                    use_count INTEGER NOT NULL DEFAULT 0
                        CHECK (use_count >= 0),
                    materialized_root_client_order_id VARCHAR(40),
                    reconciliation_required BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    deleted_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_parent_strategy_command (
                    idempotency_key TEXT PRIMARY KEY
                        CHECK (
                            idempotency_key ~
                                '^[A-Za-z0-9._:-]{{1,255}}$'
                        ),
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operation TEXT NOT NULL
                        CHECK (
                            operation IN (
                                'CREATE', 'EDIT', 'DEACTIVATE', 'DELETE'
                            )
                        ),
                    state TEXT NOT NULL
                        CHECK (
                            state IN (
                                'IN_PROGRESS', 'COMPLETED', 'REJECTED'
                            )
                        ),
                    diagnostic_code TEXT NOT NULL,
                    strategy_id UUID REFERENCES
                        {self.prefix}operator_parent_strategy(strategy_id),
                    result_revision INTEGER,
                    result_json JSONB,
                    actor_id TEXT NOT NULL,
                    operator_reason_sha256 CHAR(64) NOT NULL
                        CHECK (
                            operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    correlation_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_parent_strategy
                ADD COLUMN IF NOT EXISTS
                    admitted_product_catalog_revision_id UUID
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_parent_strategy
                ADD COLUMN IF NOT EXISTS
                    admitted_product_catalog_snapshot_sha256 CHAR(64)
                """
            )
            catalog_tables = (
                "operator_product_catalog_active",
                "operator_product_catalog_revision",
                "operator_product_catalog_product",
            )
            if all(
                self._table_exists(cursor, table)
                for table in catalog_tables
            ):
                cursor.execute(
                    f"""
                    UPDATE
                        {self.prefix}operator_parent_strategy AS strategy
                    SET admitted_product_catalog_revision_id =
                            active.revision_id,
                        admitted_product_catalog_snapshot_sha256 =
                            revision.snapshot_sha256
                    FROM
                        {self.prefix}operator_product_catalog_active AS active
                    JOIN
                        {self.prefix}operator_product_catalog_revision
                            AS revision
                      ON revision.revision_id = active.revision_id
                    JOIN
                        {self.prefix}operator_product_catalog_product
                            AS product
                      ON product.revision_id = active.revision_id
                    WHERE active.goal_id = %s
                      AND product.product_id = strategy.product_id
                      AND product.product_type = 'SPOT'
                      AND product.lifecycle = 'ENABLED'
                      AND product.exchange_status = 'ONLINE'
                      AND NOT product.exchange_disabled
                      AND NOT product.cancel_only
                      AND NOT product.view_only
                      AND (
                          strategy.admitted_product_catalog_revision_id
                              IS NULL
                          OR admitted_product_catalog_snapshot_sha256
                              IS NULL
                      )
                    """,
                    (_PRODUCT_CATALOG_GOAL_ID,),
                )
            cursor.execute(
                f"""
                ALTER TABLE {self.prefix}operator_parent_strategy
                ALTER COLUMN admitted_product_catalog_revision_id
                    SET NOT NULL,
                ALTER COLUMN admitted_product_catalog_snapshot_sha256
                    SET NOT NULL
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_parent_strategy_command
                ADD COLUMN IF NOT EXISTS result_json JSONB
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_parent_strategy_event (
                    event_id UUID PRIMARY KEY,
                    strategy_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_parent_strategy(strategy_id),
                    event_type TEXT NOT NULL CHECK (
                        event_type IN (
                            'PARENT_STRATEGY_CREATED',
                            'PARENT_STRATEGY_EDITED',
                            'PARENT_STRATEGY_DEACTIVATED',
                            'PARENT_STRATEGY_DELETED',
                            'PARENT_STRATEGY_MATERIALIZED'
                        )
                    ),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_parent_strategy_list_idx
                ON {self.prefix}operator_parent_strategy
                    (lifecycle_state, product_id, updated_at DESC, strategy_id)
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_parent_strategy_event_idx
                ON {self.prefix}operator_parent_strategy_event
                    (strategy_id, recorded_at DESC, event_id DESC)
                """
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_strategy_command
                SET state = 'REJECTED',
                    diagnostic_code =
                        'parent_strategy_interrupted_command',
                    updated_at = NOW()
                WHERE state = 'IN_PROGRESS'
                """
            )

    def product_is_active_spot(self, product_id: str) -> bool:
        with self.database.get_cursor() as cursor:
            return (
                self._active_spot_product_admission(
                    cursor,
                    product_id,
                )
                is not None
            )

    def _active_spot_product_admission(
        self,
        cursor: Any,
        product_id: str,
    ) -> dict[str, str] | None:
        required_tables = (
            "operator_product_catalog_active",
            "operator_product_catalog_revision",
            "operator_product_catalog_product",
        )
        if any(
            not self._table_exists(cursor, table)
            for table in required_tables
        ):
            return None
        cursor.execute(
            f"""
            SELECT active.revision_id, revision.snapshot_sha256
            FROM {self.prefix}operator_product_catalog_active AS active
            JOIN {self.prefix}operator_product_catalog_revision AS revision
              ON revision.revision_id = active.revision_id
            JOIN {self.prefix}operator_product_catalog_product AS product
              ON product.revision_id = active.revision_id
            WHERE active.goal_id = %s
              AND product.product_id = %s
              AND product.product_type = 'SPOT'
              AND product.lifecycle = 'ENABLED'
              AND product.exchange_status = 'ONLINE'
              AND NOT product.exchange_disabled
              AND NOT product.cancel_only
              AND NOT product.view_only
            FOR SHARE OF active, revision, product
            """,
            (_PRODUCT_CATALOG_GOAL_ID, product_id),
        )
        rows = _rows(cursor)
        if len(rows) != 1:
            return None
        return {
            "revision_id": str(rows[0]["revision_id"]),
            "snapshot_sha256": str(rows[0]["snapshot_sha256"]),
        }

    def list_strategies(
        self,
        *,
        lifecycle_state: str | None,
        product_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if lifecycle_state not in {
            None,
            "ACTIVE",
            "DEACTIVATED",
            "DELETED",
        }:
            raise OperatorParentStrategyError(
                "parent_strategy_lifecycle_filter_invalid"
            )
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        clauses: list[str] = []
        params: list[Any] = []
        if lifecycle_state is None:
            clauses.append("lifecycle_state <> 'DELETED'")
        else:
            clauses.append("lifecycle_state = %s")
            params.append(lifecycle_state)
        if product_id:
            clauses.append("product_id = %s")
            params.append(product_id)
        where = " WHERE " + " AND ".join(clauses)
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_parent_strategy
                {where}
                """,
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_strategy
                {where}
                ORDER BY updated_at DESC, strategy_id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, normalized_limit, normalized_offset]),
            )
            rows = _rows(cursor)
            return [
                self._project_strategy(cursor, row)
                for row in rows
            ], total

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            return self._strategy_by_id(cursor, strategy_id)

    def list_events(
        self,
        *,
        strategy_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        with self.database.get_cursor() as cursor:
            self._strategy_row(cursor, strategy_id)
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_parent_strategy_event
                WHERE strategy_id = %s::uuid
                """,
                (strategy_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT event_id, event_type, revision, actor_id,
                       correlation_id, evidence, recorded_at
                FROM {self.prefix}operator_parent_strategy_event
                WHERE strategy_id = %s::uuid
                ORDER BY recorded_at DESC, event_id DESC
                LIMIT %s OFFSET %s
                """,
                (strategy_id, normalized_limit, normalized_offset),
            )
            return [
                {
                    **row,
                    "event_id": str(row["event_id"]),
                    "recorded_at": _timestamp(row["recorded_at"]),
                    "evidence": dict(row.get("evidence") or {}),
                }
                for row in _rows(cursor)
            ], total

    def list_commands(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_parent_strategy_command
                """
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT operation, state, diagnostic_code, strategy_id,
                       result_revision, actor_id, correlation_id,
                       idempotency_key, created_at, updated_at
                FROM {self.prefix}operator_parent_strategy_command
                ORDER BY created_at DESC, idempotency_key DESC
                LIMIT %s OFFSET %s
                """,
                (normalized_limit, normalized_offset),
            )
            return [
                {
                    **row,
                    "strategy_id": (
                        str(row["strategy_id"])
                        if row.get("strategy_id") is not None
                        else None
                    ),
                    "created_at": _timestamp(row["created_at"]),
                    "updated_at": _timestamp(row["updated_at"]),
                }
                for row in _rows(cursor)
            ], total

    def create_strategy(
        self,
        *,
        name: str,
        terms: ParentStrategyTerms,
        portfolio_scope_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        payload = {
            "operation": "CREATE",
            "name": name,
            "terms": _terms_payload(terms),
            "portfolio_scope_sha256": portfolio_scope_sha256,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        payload_sha256 = _hash_json(payload)
        try:
            self._validate_command(
                actor_id=actor_id,
                operator_reason=operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=acknowledgement,
            )
            if _SHA256.fullmatch(portfolio_scope_sha256) is None:
                raise OperatorParentStrategyError(
                    "parent_strategy_portfolio_scope_invalid"
                )
            with self.database.get_cursor() as cursor:
                return self._create_strategy(
                    cursor,
                    name=name,
                    terms=terms,
                    portfolio_scope_sha256=portfolio_scope_sha256,
                    actor_id=actor_id,
                    operator_reason=operator_reason,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                )
        except OperatorParentStrategyError as exc:
            self._record_rejected_command(
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                operation="CREATE",
                diagnostic_code=exc.code,
                strategy_id=None,
                actor_id=actor_id,
                operator_reason=operator_reason,
                correlation_id=correlation_id,
            )
            raise

    def _create_strategy(
        self,
        cursor: Any,
        *,
        name: str,
        terms: ParentStrategyTerms,
        portfolio_scope_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any]:
        self._lock_idempotency(cursor, idempotency_key)
        replay = self._existing_command(
            cursor,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        if replay is not None:
            return replay
        admission = self._active_spot_product_admission(
            cursor,
            terms.product_id,
        )
        if admission is None:
            raise OperatorParentStrategyError(
                "parent_strategy_product_not_enabled"
            )
        strategy_id = str(uuid.uuid4())
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_parent_strategy (
                strategy_id, name, portfolio_scope_sha256,
                admitted_product_catalog_revision_id,
                admitted_product_catalog_snapshot_sha256,
                product_id, side, reference_size, reference_price,
                target_movement, target_movement_type,
                max_order_replacement, allow_partial_fills,
                child_order_type, child_time_in_force,
                child_post_only, lifecycle_state, created_by
            )
            VALUES (
                %s::uuid, %s, %s, %s::uuid, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, 'ACTIVE', %s
            )
            """,
            (
                strategy_id,
                name,
                portfolio_scope_sha256,
                admission["revision_id"],
                admission["snapshot_sha256"],
                terms.product_id,
                terms.side,
                terms.reference_size,
                terms.reference_price,
                terms.target_movement,
                terms.target_movement_type,
                terms.max_order_replacement,
                terms.allow_partial_fills,
                terms.child_order_type,
                terms.child_time_in_force,
                terms.child_post_only,
                actor_id,
            ),
        )
        projected = self._strategy_by_id(cursor, strategy_id)
        self._insert_completed_command(
            cursor,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
            operation="CREATE",
            diagnostic_code="parent_strategy_created",
            strategy_id=strategy_id,
            result_revision=1,
            result_snapshot=projected,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )
        self._append_event(
            cursor,
            strategy_id=strategy_id,
            event_type="PARENT_STRATEGY_CREATED",
            revision=1,
            actor_id=actor_id,
            correlation_id=correlation_id,
            evidence={
                "lifecycle_state": "ACTIVE",
                "child_order_type": "LIMIT",
                "child_time_in_force": "GOOD_UNTIL_CANCELLED",
                "child_post_only": True,
            },
        )
        return {**projected, "command_replayed": False}

    def edit_strategy(
        self,
        *,
        strategy_id: str,
        expected_revision: int,
        name: str,
        terms: ParentStrategyTerms,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        payload = {
            "operation": "EDIT",
            "strategy_id": strategy_id,
            "expected_revision": expected_revision,
            "name": name,
            "terms": _terms_payload(terms),
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._mutate(
            operation="EDIT",
            strategy_id=strategy_id,
            expected_revision=expected_revision,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor, current: self._apply_edit(
                cursor,
                current=current,
                name=name,
                terms=terms,
            ),
        )

    def deactivate_strategy(
        self,
        *,
        strategy_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        payload = {
            "operation": "DEACTIVATE",
            "strategy_id": strategy_id,
            "expected_revision": expected_revision,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._mutate(
            operation="DEACTIVATE",
            strategy_id=strategy_id,
            expected_revision=expected_revision,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=self._apply_deactivate,
        )

    def delete_strategy(
        self,
        *,
        strategy_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        payload = {
            "operation": "DELETE",
            "strategy_id": strategy_id,
            "expected_revision": expected_revision,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._mutate(
            operation="DELETE",
            strategy_id=strategy_id,
            expected_revision=expected_revision,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=self._apply_delete,
        )

    def bind_materialized_root(
        self,
        *,
        strategy_id: str,
        expected_revision: int,
        root_client_order_id: str,
    ) -> dict[str, Any]:
        """Domain-only hook; not exposed by the Goal 4 Admin API."""

        try:
            normalized_root = str(uuid.UUID(root_client_order_id))
        except (TypeError, ValueError, AttributeError):
            raise OperatorParentStrategyError(
                "parent_strategy_root_identity_invalid"
            ) from None
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_parent_strategy
                WHERE strategy_id = %s::uuid
                FOR UPDATE
                """,
                (strategy_id,),
            )
            current = _one(cursor, "parent_strategy_not_found")
            if (
                current["lifecycle_state"] != "ACTIVE"
                or int(current["revision"]) != expected_revision
                or current.get("materialized_root_client_order_id")
            ):
                raise OperatorParentStrategyError(
                    "parent_strategy_materialization_conflict"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_parent_strategy
                SET materialized_root_client_order_id = %s,
                    use_count = use_count + 1,
                    revision = revision + 1,
                    updated_at = NOW()
                WHERE strategy_id = %s::uuid
                RETURNING *
                """,
                (normalized_root, strategy_id),
            )
            updated = _one(
                cursor,
                "parent_strategy_materialization_conflict",
            )
            self._append_event(
                cursor,
                strategy_id=strategy_id,
                event_type="PARENT_STRATEGY_MATERIALIZED",
                revision=int(updated["revision"]),
                actor_id="domain-service",
                correlation_id="parent-strategy-domain-binding",
                evidence={"use_count": int(updated["use_count"])},
            )
            return self._project_strategy(cursor, updated)

    def _mutate(
        self,
        *,
        operation: str,
        strategy_id: str,
        expected_revision: int,
        payload: dict[str, Any],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
        apply: Any,
    ) -> dict[str, Any]:
        payload_sha256 = _hash_json(payload)
        try:
            self._validate_command(
                actor_id=actor_id,
                operator_reason=operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=acknowledgement,
            )
            with self.database.get_cursor() as cursor:
                self._lock_idempotency(cursor, idempotency_key)
                replay = self._existing_command(
                    cursor,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                )
                if replay is not None:
                    return replay
                cursor.execute(
                    f"""
                    SELECT *
                    FROM {self.prefix}operator_parent_strategy
                    WHERE strategy_id = %s::uuid
                    FOR UPDATE
                    """,
                    (strategy_id,),
                )
                current = _one(cursor, "parent_strategy_not_found")
                if int(current["revision"]) != expected_revision:
                    raise OperatorParentStrategyError(
                        "parent_strategy_revision_conflict"
                    )
                updated, diagnostic, event_type = apply(cursor, current)
                revision = int(updated["revision"])
                projected = self._project_strategy(cursor, updated)
                self._insert_completed_command(
                    cursor,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                    operation=operation,
                    diagnostic_code=diagnostic,
                    strategy_id=strategy_id,
                    result_revision=revision,
                    result_snapshot=projected,
                    actor_id=actor_id,
                    operator_reason=operator_reason,
                    correlation_id=correlation_id,
                )
                self._append_event(
                    cursor,
                    strategy_id=strategy_id,
                    event_type=event_type,
                    revision=revision,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    evidence={
                        "lifecycle_state": updated["lifecycle_state"],
                        "revision": revision,
                    },
                )
                return {**projected, "command_replayed": False}
        except OperatorParentStrategyError as exc:
            if (
                _ACTOR_ID.fullmatch(actor_id) is not None
                and _EVIDENCE_ID.fullmatch(correlation_id) is not None
                and _EVIDENCE_ID.fullmatch(idempotency_key) is not None
            ):
                self._record_rejected_command(
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                    operation=operation,
                    diagnostic_code=exc.code,
                    strategy_id=strategy_id,
                    actor_id=actor_id,
                    operator_reason=operator_reason,
                    correlation_id=correlation_id,
                )
            raise

    def _apply_edit(
        self,
        cursor: Any,
        *,
        current: dict[str, Any],
        name: str,
        terms: ParentStrategyTerms,
    ) -> tuple[dict[str, Any], str, str]:
        if current["lifecycle_state"] == "DELETED":
            raise OperatorParentStrategyError(
                "parent_strategy_deleted"
            )
        immutable_matches = (
            current["product_id"] == terms.product_id
            and current["side"] == terms.side
            and current["reference_size"] == terms.reference_size
            and current["reference_price"] == terms.reference_price
        )
        if not immutable_matches:
            raise OperatorParentStrategyError(
                "parent_strategy_immutable_terms_conflict"
            )
        admission: dict[str, str] | None = None
        if current["lifecycle_state"] == "ACTIVE":
            admission = self._active_spot_product_admission(
                cursor,
                terms.product_id,
            )
            if admission is None:
                raise OperatorParentStrategyError(
                    "parent_strategy_product_not_enabled"
                )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_parent_strategy
            SET name = %s,
                target_movement = %s,
                target_movement_type = %s,
                max_order_replacement = %s,
                allow_partial_fills = %s,
                child_order_type = %s,
                child_time_in_force = %s,
                child_post_only = %s,
                admitted_product_catalog_revision_id =
                    COALESCE(
                        %s::uuid,
                        admitted_product_catalog_revision_id
                    ),
                admitted_product_catalog_snapshot_sha256 =
                    COALESCE(
                        %s,
                        admitted_product_catalog_snapshot_sha256
                    ),
                revision = revision + 1,
                updated_at = NOW()
            WHERE strategy_id = %s::uuid
            RETURNING *
            """,
            (
                name,
                terms.target_movement,
                terms.target_movement_type,
                terms.max_order_replacement,
                terms.allow_partial_fills,
                terms.child_order_type,
                terms.child_time_in_force,
                terms.child_post_only,
                admission["revision_id"] if admission else None,
                admission["snapshot_sha256"] if admission else None,
                str(current["strategy_id"]),
            ),
        )
        return (
            _one(cursor, "parent_strategy_edit_conflict"),
            "parent_strategy_edited",
            "PARENT_STRATEGY_EDITED",
        )

    def _apply_deactivate(
        self,
        cursor: Any,
        current: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        if current["lifecycle_state"] != "ACTIVE":
            raise OperatorParentStrategyError(
                "parent_strategy_deactivate_conflict"
            )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_parent_strategy
            SET lifecycle_state = 'DEACTIVATED',
                revision = revision + 1,
                updated_at = NOW()
            WHERE strategy_id = %s::uuid
            RETURNING *
            """,
            (str(current["strategy_id"]),),
        )
        return (
            _one(cursor, "parent_strategy_deactivate_conflict"),
            "parent_strategy_deactivated",
            "PARENT_STRATEGY_DEACTIVATED",
        )

    def _apply_delete(
        self,
        cursor: Any,
        current: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        root_id = str(
            current.get("materialized_root_client_order_id") or ""
        ).strip()
        if root_id:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                (_FOLLOW_UP_ROOT_LOCK_NAMESPACE, root_id),
            )
        projection = self._project_strategy(cursor, current)
        if not projection["delete_allowed"]:
            raise OperatorParentStrategyError(
                "parent_strategy_delete_blocked"
            )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_parent_strategy
            SET lifecycle_state = 'DELETED',
                revision = revision + 1,
                deleted_at = NOW(),
                updated_at = NOW()
            WHERE strategy_id = %s::uuid
            RETURNING *
            """,
            (str(current["strategy_id"]),),
        )
        return (
            _one(cursor, "parent_strategy_delete_conflict"),
            "parent_strategy_deleted",
            "PARENT_STRATEGY_DELETED",
        )

    def _strategy_by_id(
        self,
        cursor: Any,
        strategy_id: str,
    ) -> dict[str, Any]:
        row = self._strategy_row(cursor, strategy_id)
        return self._project_strategy(cursor, row)

    def _strategy_row(
        self,
        cursor: Any,
        strategy_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_parent_strategy
            WHERE strategy_id = %s::uuid
            """,
            (strategy_id,),
        )
        return _one(cursor, "parent_strategy_not_found")

    def _project_strategy(
        self,
        cursor: Any,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        state = str(row["lifecycle_state"])
        root_id = str(
            row.get("materialized_root_client_order_id") or ""
        ).strip()
        unused_or_terminal = not root_id
        active_placement_count = 0
        child_count = 0
        unresolved_claim_count = 0
        reconciliation_required = bool(
            row.get("reconciliation_required")
        )
        if root_id:
            if self._table_exists(cursor, "order_parent"):
                cursor.execute(
                    f"""
                    SELECT status
                    FROM {self.prefix}order_parent
                    WHERE client_order_id = %s
                    """,
                    (root_id,),
                )
                root_rows = _rows(cursor)
                root_status = (
                    str(root_rows[0]["status"]).upper()
                    if root_rows
                    else "UNKNOWN"
                )
                unused_or_terminal = (
                    root_status in _TERMINAL_PARENT_STATES
                )
                active_placement_count = (
                    0 if unused_or_terminal else 1
                )
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {self.prefix}order_parent
                    WHERE parent_order_id = %s
                    """,
                    (root_id,),
                )
                child_count = int(cursor.fetchone()[0])
            else:
                unused_or_terminal = False
                active_placement_count = 1
            if self._table_exists(
                cursor,
                "order_follow_up_semantic_claim",
            ):
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {self.prefix}order_follow_up_semantic_claim
                    WHERE source_client_order_id = %s
                      AND state <> 'RELEASED'
                    """,
                    (root_id,),
                )
                unresolved_claim_count = int(cursor.fetchone()[0])
            else:
                reconciliation_required = True
            if self._table_exists(
                cursor,
                "operator_follow_up_materialization_attempt",
            ):
                cursor.execute(
                    f"""
                    SELECT EXISTS (
                        SELECT 1
                        FROM
                            {self.prefix}operator_follow_up_materialization_attempt
                        WHERE root_client_order_id = %s
                    )
                    """,
                    (root_id,),
                )
                reconciliation_required = (
                    reconciliation_required
                    or bool(cursor.fetchone()[0])
                )
            else:
                reconciliation_required = True
            if self._table_exists(cursor, "partial_fill_progress"):
                cursor.execute(
                    f"""
                    SELECT EXISTS (
                        SELECT 1
                        FROM {self.prefix}partial_fill_progress
                        WHERE client_order_id = %s
                          AND UPPER(status) NOT IN (
                              'FINALIZED', 'CANCELLED'
                          )
                    )
                    """,
                    (root_id,),
                )
                reconciliation_required = (
                    reconciliation_required
                    or bool(cursor.fetchone()[0])
                )
            else:
                reconciliation_required = True
        decision = evaluate_parent_strategy_delete(
            lifecycle_state=state,
            unused_or_terminal=unused_or_terminal,
            active_placement_count=active_placement_count,
            child_count=child_count,
            unresolved_claim_count=unresolved_claim_count,
            reconciliation_required=reconciliation_required,
        )
        if state == "ACTIVE":
            allowed_actions = ["EDIT", "DEACTIVATE"]
        elif state == "DEACTIVATED":
            allowed_actions = ["EDIT"]
            if decision.allowed:
                allowed_actions.append("DELETE")
        else:
            allowed_actions = []
            decision = type(decision)(
                allowed=False,
                blockers=("parent_strategy_deleted",),
            )
        return {
            **row,
            "strategy_id": str(row["strategy_id"]),
            "materialized_root_client_order_id": root_id or None,
            "unused_or_terminal": unused_or_terminal,
            "active_placement_count": active_placement_count,
            "child_count": child_count,
            "unresolved_claim_count": unresolved_claim_count,
            "reconciliation_required": reconciliation_required,
            "delete_allowed": decision.allowed,
            "delete_blockers": list(decision.blockers),
            "allowed_actions": allowed_actions,
            "created_at": _timestamp(row["created_at"]),
            "updated_at": _timestamp(row["updated_at"]),
        }

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
            FROM {self.prefix}operator_parent_strategy_command
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        rows = _rows(cursor)
        if not rows:
            return None
        command = rows[0]
        if command["payload_sha256"] != payload_sha256:
            raise OperatorParentStrategyError(
                "parent_strategy_idempotency_conflict"
            )
        if (
            command["state"] != "COMPLETED"
            or command.get("strategy_id") is None
        ):
            raise OperatorParentStrategyError(
                str(command.get("diagnostic_code"))
                or "parent_strategy_command_conflict"
            )
        result = command.get("result_json")
        if (
            not isinstance(result, dict)
            or str(result.get("strategy_id") or "")
                != str(command["strategy_id"])
            or int(result.get("revision") or 0)
                != int(command.get("result_revision") or 0)
        ):
            raise OperatorParentStrategyError(
                "parent_strategy_replay_evidence_unavailable"
            )
        return {
            **result,
            "command_replayed": True,
        }

    def _insert_completed_command(
        self,
        cursor: Any,
        *,
        idempotency_key: str,
        payload_sha256: str,
        operation: str,
        diagnostic_code: str,
        strategy_id: str,
        result_revision: int,
        result_snapshot: dict[str, Any],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_parent_strategy_command (
                idempotency_key, payload_sha256, operation, state,
                diagnostic_code, strategy_id, result_revision, actor_id,
                result_json, operator_reason_sha256, correlation_id
            )
            VALUES (
                %s, %s, %s, 'COMPLETED', %s, %s::uuid, %s, %s, %s,
                %s, %s
            )
            """,
            (
                idempotency_key,
                payload_sha256,
                operation,
                diagnostic_code,
                strategy_id,
                result_revision,
                actor_id,
                Json(_command_result_snapshot(result_snapshot)),
                _sha256(operator_reason),
                correlation_id,
            ),
        )

    def record_rejected_request(
        self,
        *,
        operation: str,
        strategy_id: str | None,
        request_payload: dict[str, Any],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        diagnostic_code: str,
    ) -> None:
        payload_sha256 = _hash_json(
            {
                "operation": operation,
                "strategy_id": strategy_id,
                "request": request_payload,
                "actor_id": actor_id,
                "operator_reason_sha256": _sha256(operator_reason),
            }
        )
        self._record_rejected_command(
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
            operation=operation,
            diagnostic_code=diagnostic_code,
            strategy_id=strategy_id,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def _record_rejected_command(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        operation: str,
        diagnostic_code: str,
        strategy_id: str | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> None:
        if (
            _ACTOR_ID.fullmatch(actor_id) is None
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
        ):
            raise OperatorParentStrategyError(
                "parent_strategy_command_context_invalid"
            )
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            cursor.execute(
                f"""
                SELECT payload_sha256
                FROM {self.prefix}operator_parent_strategy_command
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if str(existing[0]) != payload_sha256:
                    raise OperatorParentStrategyError(
                        "parent_strategy_idempotency_conflict"
                    )
                return
            persisted_strategy_id: str | None = None
            if strategy_id:
                cursor.execute(
                    f"""
                    SELECT strategy_id
                    FROM {self.prefix}operator_parent_strategy
                    WHERE strategy_id = %s::uuid
                    """,
                    (strategy_id,),
                )
                if cursor.fetchone() is not None:
                    persisted_strategy_id = strategy_id
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_parent_strategy_command (
                    idempotency_key, payload_sha256, operation, state,
                    diagnostic_code, strategy_id, actor_id,
                    operator_reason_sha256, correlation_id
                )
                VALUES (
                    %s, %s, %s, 'REJECTED', %s, %s::uuid, %s, %s, %s
                )
                """,
                (
                    idempotency_key,
                    payload_sha256,
                    operation,
                    diagnostic_code,
                    persisted_strategy_id,
                    actor_id,
                    _sha256(operator_reason),
                    correlation_id,
                ),
            )

    def _append_event(
        self,
        cursor: Any,
        *,
        strategy_id: str,
        event_type: str,
        revision: int,
        actor_id: str,
        correlation_id: str,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_parent_strategy_event (
                event_id, strategy_id, event_type, revision, actor_id,
                correlation_id, evidence
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                strategy_id,
                event_type,
                revision,
                actor_id,
                correlation_id,
                Json(evidence),
            ),
        )

    def _table_exists(self, cursor: Any, table: str) -> bool:
        cursor.execute(
            "SELECT to_regclass(%s)",
            (f"{self.schema}.{table}",),
        )
        return cursor.fetchone()[0] is not None

    @staticmethod
    def _lock_idempotency(cursor: Any, key: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (key,),
        )

    @staticmethod
    def _validate_command(
        *,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> None:
        if (
            _ACTOR_ID.fullmatch(actor_id) is None
            or not operator_reason.strip()
            or len(operator_reason) > 240
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
            or acknowledgement is not True
        ):
            raise OperatorParentStrategyError(
                "parent_strategy_command_context_invalid"
            )


def _terms_payload(terms: ParentStrategyTerms) -> dict[str, Any]:
    return {
        "product_id": terms.product_id,
        "side": terms.side,
        "reference_size": format(terms.reference_size, "f"),
        "reference_price": format(terms.reference_price, "f"),
        "target_movement": format(terms.target_movement, "f"),
        "target_movement_type": terms.target_movement_type,
        "max_order_replacement": terms.max_order_replacement,
        "allow_partial_fills": terms.allow_partial_fills,
        "child_order_type": terms.child_order_type,
        "child_time_in_force": terms.child_time_in_force,
        "child_post_only": terms.child_post_only,
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    return _sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _command_result_snapshot(
    projection: dict[str, Any],
) -> dict[str, Any]:
    snapshot = {
        field: projection[field]
        for field in _COMMAND_RESULT_FIELDS
    }
    for field in (
        "reference_size",
        "reference_price",
        "target_movement",
    ):
        snapshot[field] = str(snapshot[field])
    snapshot["strategy_id"] = str(snapshot["strategy_id"])
    admission_revision = snapshot[
        "admitted_product_catalog_revision_id"
    ]
    snapshot["admitted_product_catalog_revision_id"] = str(
        admission_revision
    )
    root_id = snapshot.get("materialized_root_client_order_id")
    snapshot["materialized_root_client_order_id"] = (
        str(root_id) if root_id else None
    )
    snapshot["created_at"] = _timestamp(snapshot["created_at"])
    snapshot["updated_at"] = _timestamp(snapshot["updated_at"])
    return snapshot


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description or ()]
    return [
        dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorParentStrategyError(code)
    return rows[0]


def _timestamp(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@lru_cache(maxsize=1)
def get_default_operator_parent_strategy_repository(
) -> OperatorParentStrategyRepository:
    database = PostgresDB()
    database.connect()
    repository = OperatorParentStrategyRepository(database)
    repository.ensure_schema()
    return repository


def initialize_operator_parent_strategy_schema() -> None:
    """Create the installed parent-strategy schema before serving traffic."""

    get_default_operator_parent_strategy_repository().ensure_schema()
