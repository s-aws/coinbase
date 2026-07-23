"""PostgreSQL durability for local operator stealth definitions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
    StealthDefinitionTerms,
    classify_stealth_definition_runtime,
    normalize_stealth_definition_terms,
)
from database.database import PostgresDB


_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_PRODUCT_CATALOG_GOAL_ID = "operator_product_catalog_administration_v1"
_EXPORT_SCHEMA_VERSION = "operator-stealth-definition/v1"
_RUNTIME_IDENTITY_LOCK_NAMESPACE = 31873
_TERM_FIELDS = (
    "name",
    "product_id",
    "side",
    "total_size",
    "limit_price",
    "reveal_condition_type",
    "reveal_price_threshold",
    "reveal_direction",
    "hold_duration_seconds",
    "delay_seconds",
    "reveal_pricing_policy",
    "sizing_mode",
    "follow_up_reveal_direction",
    "target_movement",
    "target_movement_type",
    "max_order_replacements",
    "allow_partial_fills",
    "post_only",
)
_IMPORT_FIELDS = frozenset(("definition_id", *_TERM_FIELDS))


class OperatorStealthDefinitionRepository:
    """Revision-bound definitions and append-only operator evidence."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
    ) -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_schema_invalid"
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
                    {self.prefix}operator_stealth_definition (
                    definition_id UUID PRIMARY KEY,
                    name VARCHAR(80) NOT NULL,
                    portfolio_scope_sha256 CHAR(64) NOT NULL CHECK (
                        portfolio_scope_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    admitted_product_catalog_revision_id UUID NOT NULL,
                    admitted_product_catalog_snapshot_sha256 CHAR(64)
                        NOT NULL CHECK (
                            admitted_product_catalog_snapshot_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    product_id VARCHAR(131) NOT NULL,
                    side VARCHAR(4) NOT NULL CHECK (
                        side IN ('BUY', 'SELL')
                    ),
                    total_size NUMERIC NOT NULL CHECK (total_size > 0),
                    limit_price NUMERIC NOT NULL CHECK (limit_price > 0),
                    reveal_condition_type TEXT NOT NULL CHECK (
                        reveal_condition_type IN ('PRICE', 'TIME_DELAY')
                    ),
                    reveal_price_threshold NUMERIC,
                    reveal_direction TEXT,
                    hold_duration_seconds INTEGER NOT NULL CHECK (
                        hold_duration_seconds BETWEEN 0 AND 86400
                    ),
                    delay_seconds INTEGER,
                    reveal_pricing_policy TEXT NOT NULL CHECK (
                        reveal_pricing_policy IN (
                            'CONFIGURED_LIMIT', 'TOP_OF_BOOK', 'MIDPOINT'
                        )
                    ),
                    sizing_mode TEXT NOT NULL CHECK (sizing_mode = 'FIXED'),
                    follow_up_reveal_direction TEXT NOT NULL CHECK (
                        follow_up_reveal_direction IN ('SAME', 'OPPOSITE')
                    ),
                    target_movement NUMERIC NOT NULL CHECK (
                        target_movement > 0
                    ),
                    target_movement_type CHAR(1) NOT NULL CHECK (
                        target_movement_type IN ('P', 'A')
                    ),
                    max_order_replacements INTEGER NOT NULL CHECK (
                        max_order_replacements BETWEEN 0 AND 100
                    ),
                    allow_partial_fills BOOLEAN NOT NULL,
                    post_only BOOLEAN NOT NULL CHECK (post_only),
                    lifecycle_state TEXT NOT NULL CHECK (
                        lifecycle_state IN ('DRAFT', 'CANCELLED', 'CLEARED')
                    ),
                    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
                    definition_sha256 CHAR(64) NOT NULL CHECK (
                        definition_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    imported_from_preview_id UUID,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    terminal_at TIMESTAMPTZ,
                    CHECK (
                        (
                            reveal_condition_type = 'PRICE'
                            AND reveal_price_threshold IS NOT NULL
                            AND reveal_price_threshold > 0
                            AND reveal_direction IN ('ABOVE', 'BELOW')
                            AND delay_seconds IS NULL
                        )
                        OR (
                            reveal_condition_type = 'TIME_DELAY'
                            AND reveal_price_threshold IS NULL
                            AND reveal_direction IS NULL
                            AND delay_seconds BETWEEN 0 AND 604800
                            AND hold_duration_seconds = 0
                        )
                    )
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_stealth_definition_command (
                    idempotency_key TEXT PRIMARY KEY CHECK (
                        idempotency_key ~
                            '^[A-Za-z0-9._:-]{{1,255}}$'
                    ),
                    payload_sha256 CHAR(64) NOT NULL CHECK (
                        payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    operation TEXT NOT NULL CHECK (
                        operation IN (
                            'CREATE', 'EDIT', 'CANCEL', 'CLEAR', 'EXPORT',
                            'IMPORT_PREVIEW', 'IMPORT_APPLY'
                        )
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN ('IN_PROGRESS', 'COMPLETED', 'REJECTED')
                    ),
                    diagnostic_code TEXT NOT NULL,
                    definition_id UUID REFERENCES
                        {self.prefix}operator_stealth_definition(definition_id),
                    result_revision INTEGER,
                    result_json JSONB,
                    actor_id TEXT NOT NULL,
                    operator_reason_sha256 CHAR(64) NOT NULL CHECK (
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
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_stealth_definition_event (
                    event_id UUID PRIMARY KEY,
                    definition_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_stealth_definition(definition_id),
                    event_type TEXT NOT NULL CHECK (
                        event_type IN (
                            'STEALTH_DEFINITION_CREATED',
                            'STEALTH_DEFINITION_EDITED',
                            'STEALTH_DEFINITION_CANCELLED',
                            'STEALTH_DEFINITION_CLEARED',
                            'STEALTH_DEFINITION_EXPORTED',
                            'STEALTH_DEFINITION_IMPORTED'
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
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_stealth_definition_import_preview (
                    preview_id UUID PRIMARY KEY,
                    manifest_sha256 CHAR(64) NOT NULL CHECK (
                        manifest_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    portfolio_scope_sha256 CHAR(64) NOT NULL CHECK (
                        portfolio_scope_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    state TEXT NOT NULL CHECK (
                        state IN ('PREVIEWED', 'REJECTED', 'APPLIED')
                    ),
                    item_count INTEGER NOT NULL CHECK (
                        item_count BETWEEN 1 AND 100
                    ),
                    valid_item_count INTEGER NOT NULL CHECK (
                        valid_item_count BETWEEN 0 AND 100
                    ),
                    items_json JSONB NOT NULL,
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    applied_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_stealth_definition_list_idx
                ON {self.prefix}operator_stealth_definition (
                    lifecycle_state, product_id, updated_at DESC,
                    definition_id
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_stealth_definition_event_idx
                ON {self.prefix}operator_stealth_definition_event (
                    definition_id, recorded_at DESC, event_id DESC
                )
                """
            )
            if self._table_exists(cursor, "stealth_orders"):
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        {self.prefix}operator_stealth_runtime_identity_guard()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $operator_stealth_runtime_identity_guard$
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
                            RAISE EXCEPTION USING
                                ERRCODE = '23505',
                                MESSAGE =
                                    'stealth_runtime_identity_reserved';
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
                UPDATE {self.prefix}operator_stealth_definition_command
                SET state = 'REJECTED',
                    diagnostic_code =
                        'stealth_definition_interrupted_command',
                    updated_at = NOW()
                WHERE state = 'IN_PROGRESS'
                """
            )

    def create_definition(
        self,
        *,
        definition_id: str | None,
        terms: StealthDefinitionTerms,
        portfolio_scope_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        normalized_id = (
            _uuid(definition_id)
            if definition_id
            else str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "|".join(
                        (
                            "operator-stealth-definition",
                            actor_id,
                            idempotency_key,
                        )
                    ),
                )
            )
        )
        payload = {
            "operation": "CREATE",
            "definition_id": normalized_id,
            "terms": _terms_payload(terms),
            "portfolio_scope_sha256": portfolio_scope_sha256,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="CREATE",
            definition_id=normalized_id,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_create(
                cursor,
                definition_id=normalized_id,
                terms=terms,
                portfolio_scope_sha256=portfolio_scope_sha256,
                actor_id=actor_id,
                correlation_id=correlation_id,
                event_type="STEALTH_DEFINITION_CREATED",
                import_preview_id=None,
            ),
        )

    def edit_definition(
        self,
        *,
        definition_id: str,
        expected_revision: int,
        terms: StealthDefinitionTerms,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        definition_id = _uuid(definition_id)
        payload = {
            "operation": "EDIT",
            "definition_id": definition_id,
            "expected_revision": expected_revision,
            "terms": _terms_payload(terms),
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="EDIT",
            definition_id=definition_id,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_edit(
                cursor,
                definition_id=definition_id,
                expected_revision=expected_revision,
                terms=terms,
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def cancel_definition(
        self,
        *,
        definition_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        definition_id = _uuid(definition_id)
        payload = {
            "operation": "CANCEL",
            "definition_id": definition_id,
            "expected_revision": expected_revision,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="CANCEL",
            definition_id=definition_id,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_terminal(
                cursor,
                definition_id=definition_id,
                expected_revision=expected_revision,
                lifecycle_state="CANCELLED",
                event_type="STEALTH_DEFINITION_CANCELLED",
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def clear_definitions(
        self,
        *,
        selections: list[tuple[str, int]],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        normalized = [(_uuid(item_id), revision) for item_id, revision in selections]
        if (
            not normalized
            or len(normalized) > 100
            or len({item_id for item_id, _ in normalized}) != len(normalized)
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_clear_selection_invalid"
            )
        payload = {
            "operation": "CLEAR",
            "selections": [
                {"definition_id": item_id, "expected_revision": revision}
                for item_id, revision in sorted(normalized)
            ],
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="CLEAR",
            definition_id=None,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_clear(
                cursor,
                selections=normalized,
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def export_definitions(
        self,
        *,
        definition_ids: list[str],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        normalized = [_uuid(item_id) for item_id in definition_ids]
        if (
            not normalized
            or len(normalized) > 100
            or len(set(normalized)) != len(normalized)
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_export_selection_invalid"
            )
        payload = {
            "operation": "EXPORT",
            "definition_ids": sorted(normalized),
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="EXPORT",
            definition_id=None,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_export(
                cursor,
                definition_ids=normalized,
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def create_import_preview(
        self,
        *,
        items: list[dict[str, Any]],
        manifest_sha256: str,
        portfolio_scope_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise OperatorStealthDefinitionError(
                "stealth_definition_import_manifest_invalid"
            )
        if _hash_json(items) != manifest_sha256:
            raise OperatorStealthDefinitionError(
                "stealth_definition_import_manifest_hash_mismatch"
            )
        payload = {
            "operation": "IMPORT_PREVIEW",
            "items": items,
            "manifest_sha256": manifest_sha256,
            "portfolio_scope_sha256": portfolio_scope_sha256,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="IMPORT_PREVIEW",
            definition_id=None,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_import_preview(
                cursor,
                items=items,
                manifest_sha256=manifest_sha256,
                portfolio_scope_sha256=portfolio_scope_sha256,
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def apply_import_preview(
        self,
        *,
        preview_id: str,
        expected_manifest_sha256: str,
        portfolio_scope_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
    ) -> dict[str, Any]:
        preview_id = _uuid(preview_id)
        payload = {
            "operation": "IMPORT_APPLY",
            "preview_id": preview_id,
            "expected_manifest_sha256": expected_manifest_sha256,
            "portfolio_scope_sha256": portfolio_scope_sha256,
            "actor_id": actor_id,
            "operator_reason_sha256": _sha256(operator_reason),
            "acknowledgement": acknowledgement,
        }
        return self._execute(
            operation="IMPORT_APPLY",
            definition_id=None,
            payload=payload,
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
            apply=lambda cursor: self._apply_import(
                cursor,
                preview_id=preview_id,
                expected_manifest_sha256=expected_manifest_sha256,
                portfolio_scope_sha256=portfolio_scope_sha256,
                actor_id=actor_id,
                correlation_id=correlation_id,
            ),
        )

    def list_definitions(
        self,
        *,
        lifecycle_state: str | None,
        product_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if lifecycle_state:
            clauses.append("lifecycle_state = %s")
            params.append(lifecycle_state)
        if product_id:
            clauses.append("product_id = %s")
            params.append(product_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_definition
                {where}
                """,
                tuple(params),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_definition
                {where}
                ORDER BY updated_at DESC, definition_id
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            return [
                self._project_definition(cursor, row)
                for row in _rows(cursor)
            ], total

    def get_definition(self, definition_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            return self._project_definition(
                cursor,
                self._definition_by_id(cursor, _uuid(definition_id)),
            )

    def list_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        definition_id = _uuid(definition_id)
        with self.database.get_cursor() as cursor:
            self._definition_by_id(cursor, definition_id)
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_definition_event
                WHERE definition_id = %s::uuid
                """,
                (definition_id,),
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_definition_event
                WHERE definition_id = %s::uuid
                ORDER BY recorded_at DESC, event_id DESC
                LIMIT %s OFFSET %s
                """,
                (definition_id, limit, offset),
            )
            return [_event(row) for row in _rows(cursor)], total

    def list_commands(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {self.prefix}operator_stealth_definition_command
                """
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT operation, state, diagnostic_code, definition_id,
                       result_revision, actor_id, correlation_id,
                       idempotency_key, created_at, updated_at
                FROM {self.prefix}operator_stealth_definition_command
                ORDER BY created_at DESC, idempotency_key DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [_command(row) for row in _rows(cursor)], total

    def get_import_preview(self, preview_id: str) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_stealth_definition_import_preview
                WHERE preview_id = %s::uuid
                """,
                (_uuid(preview_id),),
            )
            rows = _rows(cursor)
            if len(rows) != 1:
                raise OperatorStealthDefinitionError(
                    "stealth_definition_import_preview_not_found"
                )
            return _preview(rows[0])

    def _execute(
        self,
        *,
        operation: str,
        definition_id: str | None,
        payload: dict[str, Any],
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        idempotency_key: str,
        acknowledgement: bool,
        apply: Any,
    ) -> dict[str, Any]:
        payload_sha256 = _hash_json(payload)
        self._validate_command(
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=acknowledgement,
        )
        try:
            with self.database.get_cursor() as cursor:
                self._lock_idempotency(cursor, idempotency_key)
                replay = self._existing_command(
                    cursor,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                )
                if replay is not None:
                    return replay
                result = apply(cursor)
                result_revision = (
                    result.get("revision")
                    if isinstance(result, dict)
                    else None
                )
                self._insert_command(
                    cursor,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                    operation=operation,
                    state="COMPLETED",
                    diagnostic_code=_success_code(operation),
                    definition_id=definition_id,
                    result_revision=result_revision,
                    result=result,
                    actor_id=actor_id,
                    operator_reason=operator_reason,
                    correlation_id=correlation_id,
                )
                return {**result, "command_replayed": False}
        except OperatorStealthDefinitionError as exc:
            self._record_rejected_command(
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                operation=operation,
                diagnostic_code=exc.code,
                definition_id=definition_id,
                actor_id=actor_id,
                operator_reason=operator_reason,
                correlation_id=correlation_id,
            )
            raise

    def _apply_create(
        self,
        cursor: Any,
        *,
        definition_id: str,
        terms: StealthDefinitionTerms,
        portfolio_scope_sha256: str,
        actor_id: str,
        correlation_id: str,
        event_type: str,
        import_preview_id: str | None,
        expected_admission: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if _SHA256.fullmatch(portfolio_scope_sha256) is None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_portfolio_scope_invalid"
            )
        if self._identity_exists(cursor, definition_id):
            raise OperatorStealthDefinitionError(
                "stealth_definition_identity_conflict"
            )
        admission = self._active_product_admission(cursor, terms.product_id)
        if admission is None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_product_not_enabled"
            )
        if expected_admission and admission != expected_admission:
            raise OperatorStealthDefinitionError(
                "stealth_definition_import_catalog_changed"
            )
        self._validate_increments(terms, admission)
        definition_sha256 = _definition_sha256(
            definition_id=definition_id,
            terms=terms,
            portfolio_scope_sha256=portfolio_scope_sha256,
            admission=admission,
            lifecycle_state="DRAFT",
            revision=1,
        )
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_stealth_definition (
                definition_id, name, portfolio_scope_sha256,
                admitted_product_catalog_revision_id,
                admitted_product_catalog_snapshot_sha256,
                product_id, side, total_size, limit_price,
                reveal_condition_type, reveal_price_threshold,
                reveal_direction, hold_duration_seconds, delay_seconds,
                reveal_pricing_policy, sizing_mode,
                follow_up_reveal_direction, target_movement,
                target_movement_type, max_order_replacements,
                allow_partial_fills, post_only, lifecycle_state,
                revision, definition_sha256, imported_from_preview_id,
                created_by
            )
            VALUES (
                %s::uuid, %s, %s, %s::uuid, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                'DRAFT', 1, %s, %s::uuid, %s
            )
            """,
            (
                definition_id,
                terms.name,
                portfolio_scope_sha256,
                admission["revision_id"],
                admission["snapshot_sha256"],
                terms.product_id,
                terms.side,
                terms.total_size,
                terms.limit_price,
                terms.reveal_condition_type,
                terms.reveal_price_threshold,
                terms.reveal_direction,
                terms.hold_duration_seconds,
                terms.delay_seconds,
                terms.reveal_pricing_policy,
                terms.sizing_mode,
                terms.follow_up_reveal_direction,
                terms.target_movement,
                terms.target_movement_type,
                terms.max_order_replacements,
                terms.allow_partial_fills,
                terms.post_only,
                definition_sha256,
                import_preview_id,
                actor_id,
            ),
        )
        self._append_event(
            cursor,
            definition_id=definition_id,
            event_type=event_type,
            revision=1,
            actor_id=actor_id,
            correlation_id=correlation_id,
            evidence=(
                {
                    "lifecycle_state": "DRAFT",
                    "import_preview_id": import_preview_id,
                }
                if import_preview_id
                else {"lifecycle_state": "DRAFT"}
            ),
        )
        return self._project_definition(
            cursor,
            self._definition_by_id(cursor, definition_id),
        )

    def _apply_edit(
        self,
        cursor: Any,
        *,
        definition_id: str,
        expected_revision: int,
        terms: StealthDefinitionTerms,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        current = self._lock_definition(cursor, definition_id)
        self._require_mutable(
            cursor,
            current=current,
            expected_revision=expected_revision,
        )
        if (
            current["product_id"] != terms.product_id
            or current["side"] != terms.side
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_identity_terms_immutable"
            )
        admission = self._active_product_admission(cursor, terms.product_id)
        if admission is None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_product_not_enabled"
            )
        self._validate_increments(terms, admission)
        next_revision = int(current["revision"]) + 1
        definition_sha256 = _definition_sha256(
            definition_id=definition_id,
            terms=terms,
            portfolio_scope_sha256=current["portfolio_scope_sha256"],
            admission=admission,
            lifecycle_state="DRAFT",
            revision=next_revision,
        )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_stealth_definition
            SET name = %s,
                admitted_product_catalog_revision_id = %s::uuid,
                admitted_product_catalog_snapshot_sha256 = %s,
                total_size = %s,
                limit_price = %s,
                reveal_condition_type = %s,
                reveal_price_threshold = %s,
                reveal_direction = %s,
                hold_duration_seconds = %s,
                delay_seconds = %s,
                reveal_pricing_policy = %s,
                sizing_mode = %s,
                follow_up_reveal_direction = %s,
                target_movement = %s,
                target_movement_type = %s,
                max_order_replacements = %s,
                allow_partial_fills = %s,
                post_only = %s,
                revision = %s,
                definition_sha256 = %s,
                updated_at = NOW()
            WHERE definition_id = %s::uuid
            RETURNING *
            """,
            (
                terms.name,
                admission["revision_id"],
                admission["snapshot_sha256"],
                terms.total_size,
                terms.limit_price,
                terms.reveal_condition_type,
                terms.reveal_price_threshold,
                terms.reveal_direction,
                terms.hold_duration_seconds,
                terms.delay_seconds,
                terms.reveal_pricing_policy,
                terms.sizing_mode,
                terms.follow_up_reveal_direction,
                terms.target_movement,
                terms.target_movement_type,
                terms.max_order_replacements,
                terms.allow_partial_fills,
                terms.post_only,
                next_revision,
                definition_sha256,
                definition_id,
            ),
        )
        updated = _one(cursor, "stealth_definition_not_found")
        self._append_event(
            cursor,
            definition_id=definition_id,
            event_type="STEALTH_DEFINITION_EDITED",
            revision=next_revision,
            actor_id=actor_id,
            correlation_id=correlation_id,
            evidence={
                "lifecycle_state": "DRAFT",
                "revision": next_revision,
            },
        )
        return self._project_definition(cursor, updated)

    def _apply_terminal(
        self,
        cursor: Any,
        *,
        definition_id: str,
        expected_revision: int,
        lifecycle_state: str,
        event_type: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        current = self._lock_definition(cursor, definition_id)
        self._require_mutable(
            cursor,
            current=current,
            expected_revision=expected_revision,
        )
        next_revision = int(current["revision"]) + 1
        terms = _terms_from_row(current)
        admission = {
            "revision_id": str(
                current["admitted_product_catalog_revision_id"]
            ),
            "snapshot_sha256": current[
                "admitted_product_catalog_snapshot_sha256"
            ],
        }
        definition_sha256 = _definition_sha256(
            definition_id=definition_id,
            terms=terms,
            portfolio_scope_sha256=current["portfolio_scope_sha256"],
            admission=admission,
            lifecycle_state=lifecycle_state,
            revision=next_revision,
        )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_stealth_definition
            SET lifecycle_state = %s,
                revision = %s,
                definition_sha256 = %s,
                terminal_at = NOW(),
                updated_at = NOW()
            WHERE definition_id = %s::uuid
            RETURNING *
            """,
            (
                lifecycle_state,
                next_revision,
                definition_sha256,
                definition_id,
            ),
        )
        updated = _one(cursor, "stealth_definition_not_found")
        self._append_event(
            cursor,
            definition_id=definition_id,
            event_type=event_type,
            revision=next_revision,
            actor_id=actor_id,
            correlation_id=correlation_id,
            evidence={
                "lifecycle_state": lifecycle_state,
                "revision": next_revision,
            },
        )
        return self._project_definition(cursor, updated)

    def _apply_clear(
        self,
        cursor: Any,
        *,
        selections: list[tuple[str, int]],
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        locked: list[dict[str, Any]] = []
        for definition_id, expected_revision in sorted(selections):
            current = self._lock_definition(cursor, definition_id)
            self._require_mutable(
                cursor,
                current=current,
                expected_revision=expected_revision,
            )
            locked.append(current)
        definitions = [
            self._apply_terminal(
                cursor,
                definition_id=str(row["definition_id"]),
                expected_revision=int(row["revision"]),
                lifecycle_state="CLEARED",
                event_type="STEALTH_DEFINITION_CLEARED",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            for row in locked
        ]
        return {
            "cleared_count": len(definitions),
            "definitions": definitions,
            "local_state_mutated": True,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def _apply_export(
        self,
        cursor: Any,
        *,
        definition_ids: list[str],
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        for definition_id in sorted(definition_ids):
            row = self._lock_definition(cursor, definition_id)
            self._require_mutable(
                cursor,
                current=row,
                expected_revision=int(row["revision"]),
            )
            rows.append(row)
            items.append(_export_item(row))
        manifest_sha256 = _hash_json(items)
        export_id = str(uuid.uuid4())
        for row in rows:
            self._append_event(
                cursor,
                definition_id=str(row["definition_id"]),
                event_type="STEALTH_DEFINITION_EXPORTED",
                revision=int(row["revision"]),
                actor_id=actor_id,
                correlation_id=correlation_id,
                evidence={
                    "export_id": export_id,
                    "manifest_sha256": manifest_sha256,
                },
            )
        return {
            "export_id": export_id,
            "schema_version": _EXPORT_SCHEMA_VERSION,
            "manifest_sha256": manifest_sha256,
            "item_count": len(items),
            "items": items,
            "local_state_mutated": False,
            "audit_state_mutated": True,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def _apply_import_preview(
        self,
        cursor: Any,
        *,
        items: list[dict[str, Any]],
        manifest_sha256: str,
        portfolio_scope_sha256: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if _SHA256.fullmatch(portfolio_scope_sha256) is None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_portfolio_scope_invalid"
            )
        preview_id = str(uuid.uuid4())
        seen: set[str] = set()
        preview_items: list[dict[str, Any]] = []
        lock_ids: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict) or "definition_id" not in raw:
                continue
            try:
                lock_ids.add(_uuid(raw["definition_id"]))
            except OperatorStealthDefinitionError:
                continue
        for definition_id in sorted(lock_ids):
            self._lock_runtime_identity(cursor, definition_id)
        for ordinal, raw in enumerate(items, start=1):
            normalized: dict[str, Any] | None = None
            diagnostic = "stealth_definition_import_item_valid"
            try:
                if not isinstance(raw, dict) or set(raw) != _IMPORT_FIELDS:
                    raise OperatorStealthDefinitionError(
                        "stealth_definition_import_item_schema_invalid"
                    )
                definition_id = _uuid(raw["definition_id"])
                if definition_id in seen or self._identity_exists(
                    cursor,
                    definition_id,
                ):
                    raise OperatorStealthDefinitionError(
                        "stealth_definition_identity_conflict"
                    )
                seen.add(definition_id)
                terms = normalize_stealth_definition_terms(
                    **{field: raw[field] for field in _TERM_FIELDS}
                )
                admission = self._active_product_admission(
                    cursor,
                    terms.product_id,
                )
                if admission is None:
                    raise OperatorStealthDefinitionError(
                        "stealth_definition_product_not_enabled"
                    )
                self._validate_increments(terms, admission)
                normalized = {
                    "definition_id": definition_id,
                    **_terms_payload(terms),
                    "admission": admission,
                }
            except OperatorStealthDefinitionError as exc:
                diagnostic = exc.code
            preview_items.append(
                {
                    "ordinal": ordinal,
                    "definition_id": (
                        normalized["definition_id"] if normalized else None
                    ),
                    "valid": normalized is not None,
                    "diagnostic_code": diagnostic,
                    "normalized": normalized,
                }
            )
        valid_count = sum(bool(item["valid"]) for item in preview_items)
        state = "PREVIEWED" if valid_count == len(preview_items) else "REJECTED"
        cursor.execute(
            f"""
            INSERT INTO
                {self.prefix}operator_stealth_definition_import_preview (
                preview_id, manifest_sha256, portfolio_scope_sha256,
                state, item_count, valid_item_count, items_json,
                actor_id, correlation_id
            )
            VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                preview_id,
                manifest_sha256,
                portfolio_scope_sha256,
                state,
                len(preview_items),
                valid_count,
                Json(preview_items),
                actor_id,
                correlation_id,
            ),
        )
        return self._preview_by_id(cursor, preview_id)

    def _apply_import(
        self,
        cursor: Any,
        *,
        preview_id: str,
        expected_manifest_sha256: str,
        portfolio_scope_sha256: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_definition_import_preview
            WHERE preview_id = %s::uuid
            FOR UPDATE
            """,
            (preview_id,),
        )
        preview = _one(
            cursor,
            "stealth_definition_import_preview_not_found",
        )
        if (
            preview["state"] != "PREVIEWED"
            or str(preview["manifest_sha256"]) != expected_manifest_sha256
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_import_not_applicable"
            )
        if (
            _SHA256.fullmatch(portfolio_scope_sha256) is None
            or str(preview["portfolio_scope_sha256"])
            != portfolio_scope_sha256
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_import_portfolio_changed"
            )
        import_definition_ids = sorted(
            str(item["normalized"]["definition_id"])
            for item in preview["items_json"]
            if item.get("valid")
            and isinstance(item.get("normalized"), dict)
        )
        for definition_id in import_definition_ids:
            self._lock_runtime_identity(cursor, definition_id)
        definitions: list[dict[str, Any]] = []
        for item in preview["items_json"]:
            normalized = item.get("normalized")
            if not item.get("valid") or not isinstance(normalized, dict):
                raise OperatorStealthDefinitionError(
                    "stealth_definition_import_not_applicable"
                )
            terms = normalize_stealth_definition_terms(
                **{field: normalized[field] for field in _TERM_FIELDS}
            )
            definitions.append(
                self._apply_create(
                    cursor,
                    definition_id=normalized["definition_id"],
                    terms=terms,
                    portfolio_scope_sha256=portfolio_scope_sha256,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    event_type="STEALTH_DEFINITION_IMPORTED",
                    import_preview_id=preview_id,
                    expected_admission=normalized["admission"],
                )
            )
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_stealth_definition_import_preview
            SET state = 'APPLIED', applied_at = NOW(), updated_at = NOW()
            WHERE preview_id = %s::uuid
            """,
            (preview_id,),
        )
        return {
            "preview_id": preview_id,
            "manifest_sha256": expected_manifest_sha256,
            "imported_count": len(definitions),
            "definitions": definitions,
            "local_state_mutated": True,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def _require_mutable(
        self,
        cursor: Any,
        *,
        current: dict[str, Any],
        expected_revision: int,
    ) -> None:
        self._lock_runtime_identity(
            cursor,
            str(current["definition_id"]),
        )
        if int(current["revision"]) != expected_revision:
            raise OperatorStealthDefinitionError(
                "stealth_definition_revision_conflict"
            )
        if current["lifecycle_state"] != "DRAFT":
            raise OperatorStealthDefinitionError(
                "stealth_definition_not_draft"
            )
        runtime_status = self._runtime_status(
            cursor,
            str(current["definition_id"]),
        )
        if runtime_status is not None:
            raise OperatorStealthDefinitionError(
                "stealth_definition_materialized"
            )

    def _active_product_admission(
        self,
        cursor: Any,
        product_id: str,
    ) -> dict[str, str] | None:
        required = (
            "operator_product_catalog_active",
            "operator_product_catalog_revision",
            "operator_product_catalog_product",
        )
        if any(not self._table_exists(cursor, table) for table in required):
            return None
        cursor.execute(
            f"""
            SELECT active.revision_id, revision.snapshot_sha256,
                   product.base_increment, product.quote_increment,
                   product.price_increment, product.base_min_size,
                   product.base_max_size, product.quote_min_size,
                   product.quote_max_size
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
            key: str(rows[0][key])
            for key in (
                "revision_id",
                "snapshot_sha256",
                "base_increment",
                "quote_increment",
                "price_increment",
                "base_min_size",
                "base_max_size",
                "quote_min_size",
                "quote_max_size",
            )
        }

    @staticmethod
    def _validate_increments(
        terms: StealthDefinitionTerms,
        admission: dict[str, str],
    ) -> None:
        try:
            base_increment = Decimal(admission["base_increment"])
            price_increment = Decimal(admission["price_increment"])
            base_min = Decimal(admission["base_min_size"])
            base_max = Decimal(admission["base_max_size"])
            quote_min = Decimal(admission["quote_min_size"])
            quote_max = Decimal(admission["quote_max_size"])
        except (InvalidOperation, KeyError):
            raise OperatorStealthDefinitionError(
                "stealth_definition_product_metadata_invalid"
            ) from None
        if (
            base_increment <= 0
            or price_increment <= 0
            or terms.total_size < base_min
            or terms.total_size > base_max
            or terms.total_size % base_increment != 0
            or terms.limit_price % price_increment != 0
            or terms.total_size * terms.limit_price < quote_min
            or terms.total_size * terms.limit_price > quote_max
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_product_increment_invalid"
            )
        if (
            terms.reveal_price_threshold is not None
            and terms.reveal_price_threshold % price_increment != 0
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_product_increment_invalid"
            )

    def _project_definition(
        self,
        cursor: Any,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_status = self._runtime_status(
            cursor,
            str(row["definition_id"]),
        )
        runtime = classify_stealth_definition_runtime(runtime_status)
        lifecycle = str(row["lifecycle_state"])
        allowed_actions: list[str] = []
        if lifecycle == "DRAFT" and runtime.local_mutation_allowed:
            allowed_actions = ["EDIT", "CANCEL", "EXPORT", "CLEAR"]
        projected = {
            **row,
            "definition_id": str(row["definition_id"]),
            "admitted_product_catalog_revision_id": str(
                row["admitted_product_catalog_revision_id"]
            ),
            "imported_from_preview_id": (
                str(row["imported_from_preview_id"])
                if row.get("imported_from_preview_id")
                else None
            ),
            "total_size": _decimal(row["total_size"]),
            "limit_price": _decimal(row["limit_price"]),
            "reveal_price_threshold": (
                _decimal(row["reveal_price_threshold"])
                if row.get("reveal_price_threshold") is not None
                else None
            ),
            "target_movement": _decimal(row["target_movement"]),
            "runtime_status": runtime_status,
            "runtime_classification": runtime.classification,
            "blocked_navigation": runtime.blocked_navigation,
            "local_mutation_allowed": (
                lifecycle == "DRAFT"
                and runtime.local_mutation_allowed
            ),
            "allowed_actions": allowed_actions,
            "created_at": _timestamp(row["created_at"]),
            "updated_at": _timestamp(row["updated_at"]),
            "terminal_at": (
                _timestamp(row["terminal_at"])
                if row.get("terminal_at")
                else None
            ),
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }
        projected.pop("created_by", None)
        return projected

    def _identity_exists(self, cursor: Any, definition_id: str) -> bool:
        self._lock_runtime_identity(cursor, definition_id)
        cursor.execute(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM {self.prefix}operator_stealth_definition
                WHERE definition_id = %s::uuid
            )
            """,
            (definition_id,),
        )
        local_exists = bool(cursor.fetchone()[0])
        return local_exists or self._runtime_status(cursor, definition_id) is not None

    def _runtime_status(
        self,
        cursor: Any,
        definition_id: str,
    ) -> str | None:
        if not self._table_exists(cursor, "stealth_orders"):
            return "UNKNOWN"
        cursor.execute(
            f"""
            SELECT status
            FROM {self.prefix}stealth_orders
            WHERE stealth_order_id = %s::uuid
            """,
            (definition_id,),
        )
        rows = _rows(cursor)
        if not rows:
            return None
        return str(rows[0].get("status") or "UNKNOWN").upper()

    def _lock_runtime_identity(
        self,
        cursor: Any,
        definition_id: str,
    ) -> None:
        if not self._table_exists(cursor, "stealth_orders"):
            raise OperatorStealthDefinitionError(
                "stealth_definition_runtime_unavailable"
            )
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (_RUNTIME_IDENTITY_LOCK_NAMESPACE, definition_id),
        )

    def _lock_definition(
        self,
        cursor: Any,
        definition_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_definition
            WHERE definition_id = %s::uuid
            FOR UPDATE
            """,
            (definition_id,),
        )
        return _one(cursor, "stealth_definition_not_found")

    def _definition_by_id(
        self,
        cursor: Any,
        definition_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_definition
            WHERE definition_id = %s::uuid
            """,
            (definition_id,),
        )
        return _one(cursor, "stealth_definition_not_found")

    def _preview_by_id(
        self,
        cursor: Any,
        preview_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_stealth_definition_import_preview
            WHERE preview_id = %s::uuid
            """,
            (preview_id,),
        )
        return _preview(
            _one(
                cursor,
                "stealth_definition_import_preview_not_found",
            )
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
            FROM {self.prefix}operator_stealth_definition_command
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        rows = _rows(cursor)
        if not rows:
            return None
        row = rows[0]
        if str(row["payload_sha256"]) != payload_sha256:
            raise OperatorStealthDefinitionError(
                "stealth_definition_idempotency_conflict"
            )
        if row["state"] != "COMPLETED" or not isinstance(
            row.get("result_json"),
            dict,
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_command_terminal"
            )
        return {**row["result_json"], "command_replayed": True}

    def _insert_command(
        self,
        cursor: Any,
        *,
        idempotency_key: str,
        payload_sha256: str,
        operation: str,
        state: str,
        diagnostic_code: str,
        definition_id: str | None,
        result_revision: int | None,
        result: dict[str, Any] | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> None:
        persisted_definition_id: str | None = None
        if definition_id:
            cursor.execute(
                f"""
                SELECT definition_id
                FROM {self.prefix}operator_stealth_definition
                WHERE definition_id = %s::uuid
                """,
                (definition_id,),
            )
            if cursor.fetchone() is not None:
                persisted_definition_id = definition_id
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_stealth_definition_command (
                idempotency_key, payload_sha256, operation, state,
                diagnostic_code, definition_id, result_revision,
                result_json, actor_id, operator_reason_sha256,
                correlation_id
            )
            VALUES (
                %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s
            )
            """,
            (
                idempotency_key,
                payload_sha256,
                operation,
                state,
                diagnostic_code,
                persisted_definition_id,
                result_revision,
                Json(result) if result is not None else None,
                actor_id,
                _sha256(operator_reason),
                correlation_id,
            ),
        )

    def _record_rejected_command(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        operation: str,
        diagnostic_code: str,
        definition_id: str | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> None:
        if (
            _EVIDENCE_ID.fullmatch(idempotency_key) is None
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _ACTOR_ID.fullmatch(actor_id) is None
        ):
            return
        with self.database.get_cursor() as cursor:
            self._lock_idempotency(cursor, idempotency_key)
            cursor.execute(
                f"""
                SELECT payload_sha256
                FROM {self.prefix}operator_stealth_definition_command
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if str(existing[0]) != payload_sha256:
                    raise OperatorStealthDefinitionError(
                        "stealth_definition_idempotency_conflict"
                    )
                return
            self._insert_command(
                cursor,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                operation=operation,
                state="REJECTED",
                diagnostic_code=diagnostic_code,
                definition_id=definition_id,
                result_revision=None,
                result=None,
                actor_id=actor_id,
                operator_reason=operator_reason,
                correlation_id=correlation_id,
            )

    def _append_event(
        self,
        cursor: Any,
        *,
        definition_id: str,
        event_type: str,
        revision: int,
        actor_id: str,
        correlation_id: str,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_stealth_definition_event (
                event_id, definition_id, event_type, revision, actor_id,
                correlation_id, evidence
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                definition_id,
                event_type,
                revision,
                actor_id,
                correlation_id,
                Json(evidence),
            ),
        )

    def _table_exists(self, cursor: Any, table: str) -> bool:
        cursor.execute("SELECT to_regclass(%s)", (f"{self.schema}.{table}",))
        return cursor.fetchone()[0] is not None

    @staticmethod
    def _lock_idempotency(cursor: Any, key: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"operator-stealth-definition:{key}",),
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
            acknowledgement is not True
            or _ACTOR_ID.fullmatch(actor_id) is None
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
            or not 1 <= len(operator_reason.strip()) <= 240
        ):
            raise OperatorStealthDefinitionError(
                "stealth_definition_command_context_invalid"
            )


def _success_code(operation: str) -> str:
    return {
        "CREATE": "stealth_definition_created",
        "EDIT": "stealth_definition_edited",
        "CANCEL": "stealth_definition_cancelled",
        "CLEAR": "stealth_definitions_cleared",
        "EXPORT": "stealth_definitions_exported",
        "IMPORT_PREVIEW": "stealth_definition_import_previewed",
        "IMPORT_APPLY": "stealth_definitions_imported",
    }[operation]


def _terms_payload(terms: StealthDefinitionTerms) -> dict[str, Any]:
    return {
        "name": terms.name,
        "product_id": terms.product_id,
        "side": terms.side,
        "total_size": _decimal(terms.total_size),
        "limit_price": _decimal(terms.limit_price),
        "reveal_condition_type": terms.reveal_condition_type,
        "reveal_price_threshold": (
            _decimal(terms.reveal_price_threshold)
            if terms.reveal_price_threshold is not None
            else None
        ),
        "reveal_direction": terms.reveal_direction,
        "hold_duration_seconds": terms.hold_duration_seconds,
        "delay_seconds": terms.delay_seconds,
        "reveal_pricing_policy": terms.reveal_pricing_policy,
        "sizing_mode": terms.sizing_mode,
        "follow_up_reveal_direction": terms.follow_up_reveal_direction,
        "target_movement": _decimal(terms.target_movement),
        "target_movement_type": terms.target_movement_type,
        "max_order_replacements": terms.max_order_replacements,
        "allow_partial_fills": terms.allow_partial_fills,
        "post_only": terms.post_only,
    }


def _terms_from_row(row: dict[str, Any]) -> StealthDefinitionTerms:
    return normalize_stealth_definition_terms(
        **{field: row[field] for field in _TERM_FIELDS}
    )


def _definition_sha256(
    *,
    definition_id: str,
    terms: StealthDefinitionTerms,
    portfolio_scope_sha256: str,
    admission: dict[str, str],
    lifecycle_state: str,
    revision: int,
) -> str:
    return _hash_json(
        {
            "definition_id": definition_id,
            "terms": _terms_payload(terms),
            "portfolio_scope_sha256": portfolio_scope_sha256,
            "admitted_product_catalog_revision_id": admission["revision_id"],
            "admitted_product_catalog_snapshot_sha256": admission[
                "snapshot_sha256"
            ],
            "lifecycle_state": lifecycle_state,
            "revision": revision,
        }
    )


def _export_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "definition_id": str(row["definition_id"]),
        **_terms_payload(_terms_from_row(row)),
    }


def _preview(row: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in row["items_json"]:
        items.append(
            {
                "ordinal": int(item["ordinal"]),
                "definition_id": item.get("definition_id"),
                "valid": bool(item["valid"]),
                "diagnostic_code": item["diagnostic_code"],
            }
        )
    return {
        "preview_id": str(row["preview_id"]),
        "manifest_sha256": row["manifest_sha256"],
        "state": row["state"],
        "item_count": int(row["item_count"]),
        "valid_item_count": int(row["valid_item_count"]),
        "all_items_valid": (
            int(row["item_count"]) == int(row["valid_item_count"])
        ),
        "items": items,
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
        "applied_at": (
            _timestamp(row["applied_at"]) if row.get("applied_at") else None
        ),
        "local_state_mutated": row["state"] == "APPLIED",
        "trading_authority_granted": False,
        "exchange_call_count": 0,
        "exchange_mutation_count": 0,
    }


def _event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(row["event_id"]),
        "definition_id": str(row["definition_id"]),
        "event_type": row["event_type"],
        "revision": int(row["revision"]),
        "actor_id": row["actor_id"],
        "correlation_id": row["correlation_id"],
        "evidence": row["evidence"],
        "recorded_at": _timestamp(row["recorded_at"]),
    }


def _command(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": row["operation"],
        "state": row["state"],
        "diagnostic_code": row["diagnostic_code"],
        "definition_id": (
            str(row["definition_id"]) if row.get("definition_id") else None
        ),
        "result_revision": row.get("result_revision"),
        "actor_id": row["actor_id"],
        "correlation_id": row["correlation_id"],
        "idempotency_key": row["idempotency_key"],
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
    }


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorStealthDefinitionError(code)
    return rows[0]


def _uuid(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise OperatorStealthDefinitionError(
            "stealth_definition_identity_invalid"
        ) from None


def _uuid_or_new(value: Any) -> str:
    return _uuid(value) if value else str(uuid.uuid4())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _decimal(value: Decimal | Any) -> str:
    normalized = Decimal(str(value))
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _timestamp(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@lru_cache(maxsize=1)
def get_default_operator_stealth_definition_repository(
) -> OperatorStealthDefinitionRepository:
    repository = OperatorStealthDefinitionRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def initialize_operator_stealth_definition_schema() -> None:
    get_default_operator_stealth_definition_repository().ensure_schema()
