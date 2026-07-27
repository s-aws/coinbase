"""Separate PostgreSQL ledger for the Goal 16 Cancel-only Spot sweep."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from functools import lru_cache
from typing import Any, Iterator, Mapping, Sequence
import uuid

from psycopg2.extras import Json

from application.admin_api.operator_hotpoint_control import HOTPOINT_GOAL_ID
from database.database import PostgresDB


GOAL_ID = "operator_spot_sweep_safe_closeout_v1"
POLICY_REVISION = "OPERATOR_SPOT_SWEEP_SAFE_CLOSEOUT_V1"
MAX_CYCLES = 10
MAX_ITEMS = 3

_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_DIAGNOSTIC = re.compile(
    r"^operator_spot_sweep_[a-z0-9_]{1,75}$"
)
_ACTIVE_STATUSES = frozenset({"PENDING", "OPEN", "QUEUED"})
_PROVENANCES = frozenset(
    {"ADMIN_FILL_FOLLOW_UP", "ADMIN_HOTPOINT_CHILD"}
)
_ACTIONS = frozenset({"CREATE", "PAUSE", "RESUME", "ABORT"})
_INTENTS = {
    "CREATE": "create_operator_spot_safe_closeout_sweep",
    "PAUSE": "pause_operator_spot_safe_closeout_sweep",
    "RESUME": "resume_operator_spot_safe_closeout_sweep",
    "ABORT": "abort_operator_spot_safe_closeout_sweep",
}


class OperatorSpotSafeCloseoutSweepError(ValueError):
    """Fixed value-blind repository error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OperatorSpotSafeCloseoutSweepConflict(
    OperatorSpotSafeCloseoutSweepError
):
    """Durable identity, lifecycle, or idempotency conflict."""


class OperatorSpotSafeCloseoutSweepRepository:
    """One goal ledger with immutable plan/items/events and local projection."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
        configured_portfolio_id: str,
    ) -> None:
        if _SCHEMA.fullmatch(schema) is None:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.prefix = f'"{schema}".'
        self.configured_portfolio_id = _canonical_uuid(
            configured_portfolio_id,
            code="operator_spot_sweep_portfolio_configuration_invalid",
        )
        self.configured_portfolio_scope_sha256 = _sha(
            self.configured_portfolio_id
        )

    @contextmanager
    def command_lock(self) -> Iterator[None]:
        """Serialize service resolution and repository creation in-process."""

        with self.database._cursor_lock:
            yield

    def ensure_schema(self) -> None:
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_plan (
                    sweep_id UUID PRIMARY KEY,
                    goal_id TEXT NOT NULL UNIQUE CHECK (
                        goal_id = '{GOAL_ID}'
                    ),
                    policy_revision TEXT NOT NULL CHECK (
                        policy_revision = '{POLICY_REVISION}'
                    ),
                    configured_portfolio_scope_sha256 CHAR(64) NOT NULL
                        CHECK (
                            configured_portfolio_scope_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    max_items SMALLINT NOT NULL CHECK (
                        max_items = {MAX_ITEMS}
                    ),
                    zero_creates BOOLEAN NOT NULL CHECK (zero_creates),
                    plan_json JSONB NOT NULL,
                    plan_sha256 CHAR(64) NOT NULL UNIQUE CHECK (
                        plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_plan_item (
                    sweep_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_spot_safe_closeout_plan(
                            sweep_id
                        ) ON DELETE RESTRICT,
                    position SMALLINT NOT NULL CHECK (
                        position BETWEEN 1 AND {MAX_ITEMS}
                    ),
                    client_order_id UUID NOT NULL UNIQUE,
                    root_client_order_id UUID NOT NULL,
                    product_id TEXT NOT NULL CHECK (
                        product_id = 'BTC-USDC'
                    ),
                    status_snapshot TEXT NOT NULL CHECK (
                        status_snapshot IN ('PENDING', 'OPEN', 'QUEUED')
                    ),
                    ownership_provenance TEXT NOT NULL CHECK (
                        ownership_provenance IN (
                            'ADMIN_FILL_FOLLOW_UP',
                            'ADMIN_HOTPOINT_CHILD'
                        )
                    ),
                    portfolio_scope_sha256 CHAR(64) NOT NULL CHECK (
                        portfolio_scope_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    exchange_order_id_sha256 CHAR(64) NOT NULL CHECK (
                        exchange_order_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    predecessor_evidence_sha256 CHAR(64) NOT NULL CHECK (
                        predecessor_evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    candidate_evidence_sha256 CHAR(64) NOT NULL UNIQUE
                        CHECK (
                            candidate_evidence_sha256 ~
                                '^[0-9a-f]{{64}}$'
                        ),
                    PRIMARY KEY (sweep_id, position),
                    CHECK (client_order_id <> root_client_order_id)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_projection (
                    sweep_id UUID PRIMARY KEY REFERENCES
                        {self.prefix}operator_spot_safe_closeout_plan(
                            sweep_id
                        ) ON DELETE RESTRICT,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'READY', 'PAUSED', 'IN_PROGRESS', 'COMPLETE',
                            'ABORTED', 'QUARANTINED'
                        )
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_spot_sweep_[a-z0-9_]{{1,75}}$'
                    ),
                    local_cycles_used SMALLINT NOT NULL CHECK (
                        local_cycles_used BETWEEN 1 AND {MAX_CYCLES}
                    ),
                    latest_idempotency_key_sha256 CHAR(64) NOT NULL CHECK (
                        latest_idempotency_key_sha256 ~
                            '^[0-9a-f]{{64}}$'
                    ),
                    latest_payload_sha256 CHAR(64) NOT NULL CHECK (
                        latest_payload_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    latest_actor_id_sha256 CHAR(64) NOT NULL CHECK (
                        latest_actor_id_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    latest_evidence_sha256 CHAR(64) NOT NULL CHECK (
                        latest_evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    correlation_id TEXT NOT NULL,
                    operator_intent TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_item_projection (
                    sweep_id UUID NOT NULL,
                    position SMALLINT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'PENDING', 'IN_FLIGHT', 'CANCELLED',
                            'NOT_REQUIRED', 'REJECTED', 'UNKNOWN',
                            'QUARANTINED', 'ABORTED'
                        )
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_spot_sweep_[a-z0-9_]{{1,75}}$'
                    ),
                    last_event_sequence BIGINT NOT NULL CHECK (
                        last_event_sequence >= 1
                    ),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (sweep_id, position),
                    FOREIGN KEY (sweep_id, position) REFERENCES
                        {self.prefix}operator_spot_safe_closeout_plan_item(
                            sweep_id, position
                        ) ON DELETE RESTRICT
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_event (
                    event_sequence BIGSERIAL PRIMARY KEY,
                    event_id UUID NOT NULL UNIQUE,
                    sweep_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_spot_safe_closeout_plan(
                            sweep_id
                        ) ON DELETE RESTRICT,
                    event_type TEXT NOT NULL CHECK (
                        event_type IN (
                            'PLAN_CREATED', 'SWEEP_PAUSED',
                            'SWEEP_RESUMED', 'SWEEP_ABORTED',
                            'SWEEP_QUARANTINED'
                        )
                    ),
                    diagnostic_code TEXT NOT NULL CHECK (
                        diagnostic_code ~
                            '^operator_spot_sweep_[a-z0-9_]{{1,75}}$'
                    ),
                    correlation_id TEXT NOT NULL,
                    evidence_sha256 CHAR(64) NOT NULL CHECK (
                        evidence_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_safe_closeout_command (
                    command_id UUID PRIMARY KEY,
                    sweep_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_spot_safe_closeout_plan(
                            sweep_id
                        ) ON DELETE RESTRICT,
                    action TEXT NOT NULL CHECK (
                        action IN ('CREATE', 'PAUSE', 'RESUME', 'ABORT')
                    ),
                    cycle_number SMALLINT NOT NULL CHECK (
                        cycle_number BETWEEN 1 AND {MAX_CYCLES}
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
                    operator_reason_sha256 CHAR(64) NOT NULL CHECK (
                        operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    operator_intent TEXT NOT NULL,
                    resulting_revision INTEGER NOT NULL CHECK (
                        resulting_revision >= 1
                    ),
                    event_sequence BIGINT NOT NULL UNIQUE REFERENCES
                        {self.prefix}operator_spot_safe_closeout_event(
                            event_sequence
                        ) ON DELETE RESTRICT,
                    result_json JSONB NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (sweep_id, cycle_number),
                    UNIQUE (sweep_id, correlation_id)
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_spot_safe_closeout_command
                ADD COLUMN IF NOT EXISTS result_json JSONB
                """
            )
            cursor.execute(
                f"""
                SELECT 1
                FROM
                    {self.prefix}operator_spot_safe_closeout_command
                WHERE result_json IS NULL
                LIMIT 1
                """
            )
            if cursor.fetchone() is not None:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_replay_snapshot_unavailable"
                )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_spot_safe_closeout_command
                ALTER COLUMN result_json SET NOT NULL
                """
            )
            self._install_immutable_triggers(cursor)

    def _install_immutable_triggers(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            CREATE OR REPLACE FUNCTION
                {self.prefix}reject_operator_spot_sweep_immutable_mutation()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'operator_spot_sweep_immutable_append_only';
            END;
            $$
            """
        )
        for table in (
            "operator_spot_safe_closeout_plan",
            "operator_spot_safe_closeout_plan_item",
            "operator_spot_safe_closeout_event",
            "operator_spot_safe_closeout_command",
        ):
            row_trigger = f"{table}_append_only"
            truncate_trigger = f"{table}_reject_truncate"
            cursor.execute(
                f"DROP TRIGGER IF EXISTS {row_trigger} "
                f"ON {self.prefix}{table}"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER {row_trigger}
                BEFORE UPDATE OR DELETE ON {self.prefix}{table}
                FOR EACH ROW EXECUTE FUNCTION
                    {self.prefix}reject_operator_spot_sweep_immutable_mutation()
                """
            )
            cursor.execute(
                f"DROP TRIGGER IF EXISTS {truncate_trigger} "
                f"ON {self.prefix}{table}"
            )
            cursor.execute(
                f"""
                CREATE TRIGGER {truncate_trigger}
                BEFORE TRUNCATE ON {self.prefix}{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    {self.prefix}reject_operator_spot_sweep_immutable_mutation()
                """
            )

    def goal_is_bound(self) -> bool:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 1
                FROM {self.prefix}operator_spot_safe_closeout_plan
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            return cursor.fetchone() is not None

    def list_candidates(
        self,
        *,
        limit: int,
        offset: int,
        status_filter: str | None = None,
        ownership_provenance_filter: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if limit < 1 or limit > 100 or offset < 0:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_pagination_invalid"
            )
        status = _optional_member(
            status_filter,
            _ACTIVE_STATUSES,
            code="operator_spot_sweep_status_filter_invalid",
        )
        provenance = _optional_member(
            ownership_provenance_filter,
            _PROVENANCES,
            code="operator_spot_sweep_provenance_filter_invalid",
        )
        with self.database.get_cursor() as cursor:
            rows = self._candidate_rows(
                cursor,
                status_filter=status,
                ownership_provenance_filter=provenance,
            )
        candidates = [
            candidate
            for row in rows
            if (
                candidate := self._candidate_from_row(row)
            )
            is not None
        ]
        total = len(candidates)
        return candidates[offset : offset + limit], total

    def resolve_selected(
        self,
        selections: Sequence[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        if not 1 <= len(selections) <= MAX_ITEMS:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_item_count_invalid"
            )
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for client_order_id, evidence_sha256 in selections:
            client_id = _canonical_uuid(
                client_order_id,
                code="operator_spot_sweep_candidate_identity_invalid",
            )
            _require_sha(
                evidence_sha256,
                code="operator_spot_sweep_candidate_evidence_invalid",
            )
            if client_id in seen:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_duplicate_candidate"
                )
            seen.add(client_id)
            normalized.append((client_id, evidence_sha256))
        with self.database.get_cursor() as cursor:
            rows = self._candidate_rows(cursor)
        by_id = {
            candidate["client_order_id"]: candidate
            for row in rows
            if (
                candidate := self._candidate_from_row(row)
            )
            is not None
        }
        resolved: list[dict[str, Any]] = []
        for client_id, expected_evidence in normalized:
            candidate = by_id.get(client_id)
            if candidate is None:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_candidate_not_eligible"
                )
            if (
                candidate["candidate_evidence_sha256"]
                != expected_evidence
            ):
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_candidate_evidence_conflict"
                )
            resolved.append(candidate)
        return resolved

    def _candidate_rows(
        self,
        cursor: Any,
        *,
        status_filter: str | None = None,
        ownership_provenance_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._table_exists(cursor, "order_parent"):
            return []
        has_fill = self._table_exists(
            cursor,
            "operator_follow_up_materialization_attempt",
        ) and self._table_exists(
            cursor,
            "operator_follow_up_materialization_event",
        )
        has_hotpoint = self._table_exists(
            cursor,
            "operator_hotpoint_control",
        ) and self._table_exists(cursor, "order_event_stream")
        accepted: list[str] = []
        accepted_parameters: list[Any] = []
        if has_fill:
            accepted.append(
                f"""
                (
                    child.ownership_provenance = 'ADMIN_FILL_FOLLOW_UP'
                    AND root.ownership_provenance = 'ADMIN_MANUAL_ROOT'
                    AND root.status = 'FILLED'
                    AND EXISTS (
                        SELECT 1
                        FROM
                            {self.prefix}operator_follow_up_materialization_attempt
                                attempt
                        WHERE
                            attempt.child_client_order_id::text =
                                child.client_order_id::text
                            AND attempt.root_client_order_id::text =
                                child.parent_order_id::text
                            AND attempt.product_id = child.product_id
                            AND attempt.portfolio_id =
                                child.retail_portfolio_id
                            AND attempt.portfolio_scope_sha256 = %s
                            AND (
                                SELECT latest.state
                                FROM
                                    {self.prefix}operator_follow_up_materialization_event
                                        latest
                                WHERE latest.materialization_id =
                                    attempt.materialization_id
                                ORDER BY latest.event_sequence DESC
                                LIMIT 1
                            ) = 'CREATE_ACCEPTED_NONTERMINAL'
                    )
                )
                """
            )
            accepted_parameters.append(
                self.configured_portfolio_scope_sha256
            )
        if has_hotpoint:
            accepted.append(
                f"""
                (
                    child.ownership_provenance = 'ADMIN_HOTPOINT_CHILD'
                    AND root.ownership_provenance IN (
                        'ADMIN_MANUAL_ROOT',
                        'OPERATOR_PARENT_STRATEGY',
                        'ADMIN_PARENT_STRATEGY'
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM {self.prefix}operator_hotpoint_control control
                        WHERE control.child_client_order_id::text =
                                child.client_order_id::text
                            AND control.goal_id = %s
                            AND control.parent_client_order_id::text =
                                child.parent_order_id::text
                            AND control.product_id = child.product_id
                            AND control.create_state = 'ACCEPTED'
                            AND control.create_exchange_invoked IS TRUE
                            AND control.cancel_state = 'NOT_CLAIMED'
                            AND control.plan_evidence_sha256 ~
                                '^[0-9a-f]{{64}}$'
                            AND control.trigger_portfolio_id_sha256 = %s
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM {self.prefix}order_event_stream submitted
                        WHERE submitted.client_order_id::text =
                                child.client_order_id::text
                            AND submitted.order_id::text =
                                child.exchange_order_id::text
                            AND submitted.parent_client_order_id::text =
                                child.parent_order_id::text
                            AND submitted.product_id = child.product_id
                            AND submitted.event_type = 'order_submitted'
                            AND submitted.source_channel = 'rest_submit'
                    )
                )
                """
            )
            accepted_parameters.extend(
                [
                    HOTPOINT_GOAL_ID,
                    self.configured_portfolio_scope_sha256,
                ]
            )
        if not accepted:
            return []
        parameters: list[Any] = []
        conditions = [
            "child.product_id = 'BTC-USDC'",
            "root.product_id = 'BTC-USDC'",
            "child.status IN ('PENDING', 'OPEN', 'QUEUED')",
            (
                "child.ownership_provenance IN "
                "('ADMIN_FILL_FOLLOW_UP', 'ADMIN_HOTPOINT_CHILD')"
            ),
            "child.parent_order_id IS NOT NULL",
            "root.parent_order_id IS NULL",
            "child.client_order_id <> root.client_order_id",
            "child.retail_portfolio_id = %s::uuid",
            "root.retail_portfolio_id = %s::uuid",
            "NULLIF(BTRIM(child.exchange_order_id), '') IS NOT NULL",
            "NULLIF(BTRIM(root.exchange_order_id), '') IS NOT NULL",
            "NULLIF(BTRIM(root.correlation_id), '') IS NOT NULL",
            "NULLIF(BTRIM(root.audit_id), '') IS NOT NULL",
            (
                "NOT EXISTS (SELECT 1 FROM "
                f"{self.prefix}operator_spot_safe_closeout_plan_item bound "
                "WHERE bound.client_order_id::text = "
                "child.client_order_id::text)"
            ),
            f"({' OR '.join(accepted)})",
        ]
        parameters.extend(
            [
                self.configured_portfolio_id,
                self.configured_portfolio_id,
                *accepted_parameters,
            ]
        )
        if status_filter is not None:
            conditions.append("child.status = %s")
            parameters.append(status_filter)
        if ownership_provenance_filter is not None:
            conditions.append("child.ownership_provenance = %s")
            parameters.append(ownership_provenance_filter)
        cursor.execute(
            f"""
            SELECT
                child.client_order_id,
                root.client_order_id AS root_client_order_id,
                child.product_id,
                child.status,
                child.ownership_provenance,
                child.exchange_order_id,
                child.created_at,
                root.status AS root_status,
                root.ownership_provenance AS root_ownership_provenance,
                root.exchange_order_id AS root_exchange_order_id,
                root.correlation_id AS root_correlation_id,
                root.audit_id AS root_audit_id
                {(
                    ", (SELECT latest.exchange_order_id_sha256 "
                    "FROM "
                    f"{self.prefix}operator_follow_up_materialization_attempt "
                    "attempt JOIN "
                    f"{self.prefix}operator_follow_up_materialization_event "
                    "latest ON latest.materialization_id = "
                    "attempt.materialization_id "
                    "WHERE attempt.child_client_order_id::text = "
                    "child.client_order_id::text "
                    "ORDER BY latest.event_sequence DESC LIMIT 1) "
                    "AS fill_exchange_order_id_sha256"
                ) if has_fill else (
                    ", NULL::char(64) AS "
                    "fill_exchange_order_id_sha256"
                )}
            FROM {self.prefix}order_parent child
            JOIN {self.prefix}order_parent root
              ON root.client_order_id::text =
                    child.parent_order_id::text
            WHERE {' AND '.join(conditions)}
            ORDER BY child.created_at ASC, child.client_order_id ASC
            """,
            tuple(parameters),
        )
        return _rows(cursor)

    def _candidate_from_row(
        self,
        row: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        try:
            client_id = _canonical_uuid(
                row.get("client_order_id"),
                code="operator_spot_sweep_candidate_identity_invalid",
            )
            root_id = _canonical_uuid(
                row.get("root_client_order_id"),
                code="operator_spot_sweep_root_identity_invalid",
            )
            exchange_id = _canonical_uuid(
                row.get("exchange_order_id"),
                code="operator_spot_sweep_exchange_identity_invalid",
            )
            root_exchange_id = _canonical_uuid(
                row.get("root_exchange_order_id"),
                code="operator_spot_sweep_predecessor_evidence_invalid",
            )
        except OperatorSpotSafeCloseoutSweepError:
            return None
        status = str(row.get("status") or "").upper()
        provenance = str(row.get("ownership_provenance") or "")
        if (
            client_id == root_id
            or status not in _ACTIVE_STATUSES
            or provenance not in _PROVENANCES
        ):
            return None
        if (
            provenance == "ADMIN_FILL_FOLLOW_UP"
            and str(row.get("fill_exchange_order_id_sha256") or "")
            != _sha(exchange_id)
        ):
            return None
        created_at = row.get("created_at")
        if not isinstance(created_at, datetime):
            return None
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        predecessor = {
            "root_client_order_id": root_id,
            "root_status": str(row.get("root_status") or "").upper(),
            "root_ownership_provenance": str(
                row.get("root_ownership_provenance") or ""
            ),
            "root_exchange_order_id_sha256": _sha(root_exchange_id),
            "root_correlation_id_sha256": _sha(
                str(row.get("root_correlation_id") or "")
            ),
            "root_audit_id_sha256": _sha(
                str(row.get("root_audit_id") or "")
            ),
            "child_ownership_provenance": provenance,
        }
        predecessor_hash = _canonical_sha(predecessor)
        candidate = {
            "client_order_id": client_id,
            "root_client_order_id": root_id,
            "product_id": "BTC-USDC",
            "status": status,
            "ownership_provenance": provenance,
            "portfolio_scope_sha256": (
                self.configured_portfolio_scope_sha256
            ),
            "exchange_order_id_sha256": _sha(exchange_id),
            "predecessor_evidence_sha256": predecessor_hash,
            "created_at": created_at.isoformat(),
        }
        candidate["candidate_evidence_sha256"] = _canonical_sha(
            candidate
        )
        return candidate

    def get_command_replay(
        self,
        *,
        action: str,
        sweep_id: str | None,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> dict[str, Any] | None:
        normalized_action = _action(action)
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        sweep = (
            _canonical_uuid(
                sweep_id,
                code="operator_spot_sweep_identity_invalid",
            )
            if sweep_id is not None
            else None
        )
        with self.database.get_cursor() as cursor:
            self._advisory_lock(cursor)
            command = self._command_by_idempotency(
                cursor,
                idempotency_key=idempotency_key,
            )
            if command is None:
                return None
            self._require_replay_match(
                command,
                action=normalized_action,
                sweep_id=sweep,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload_sha256=payload_sha256,
            )
            return self._replay_snapshot(command)

    def create_plan(
        self,
        *,
        plan: Mapping[str, Any],
        plan_sha256: str,
        private_exchange_bindings: Mapping[str, str],
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
        operator_reason_sha256: str,
        operator_intent: str,
    ) -> dict[str, Any]:
        normalized = self._validate_plan(plan, plan_sha256)
        private_bindings = self._validate_private_exchange_bindings(
            normalized,
            private_exchange_bindings,
        )
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        _require_sha(
            operator_reason_sha256,
            code="operator_spot_sweep_reason_binding_invalid",
        )
        if operator_intent != _INTENTS["CREATE"]:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_operator_intent_invalid"
            )
        with self.database.get_cursor() as cursor:
            self._advisory_lock(cursor)
            replay = self._command_by_idempotency(
                cursor,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                self._require_replay_match(
                    replay,
                    action="CREATE",
                    sweep_id=None,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    payload_sha256=payload_sha256,
                )
                return self._replay_snapshot(replay)
            self._lock_candidate_evidence(cursor)
            self._revalidate_plan_candidates(
                cursor,
                plan=normalized,
                private_exchange_bindings=private_bindings,
            )
            cursor.execute(
                f"""
                SELECT sweep_id
                FROM {self.prefix}operator_spot_safe_closeout_plan
                WHERE goal_id = %s
                FOR UPDATE
                """,
                (GOAL_ID,),
            )
            if cursor.fetchone() is not None:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_goal_already_bound"
                )
            sweep_id = normalized["sweep_id"]
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_spot_safe_closeout_plan (
                    sweep_id, goal_id, policy_revision,
                    configured_portfolio_scope_sha256,
                    max_items, zero_creates, plan_json, plan_sha256
                ) VALUES (
                    %s::uuid, %s, %s, %s, %s, TRUE, %s, %s
                )
                """,
                (
                    sweep_id,
                    GOAL_ID,
                    POLICY_REVISION,
                    self.configured_portfolio_scope_sha256,
                    MAX_ITEMS,
                    Json(normalized),
                    plan_sha256,
                ),
            )
            for item in normalized["items"]:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self.prefix}operator_spot_safe_closeout_plan_item (
                        sweep_id, position, client_order_id,
                        root_client_order_id, product_id, status_snapshot,
                        ownership_provenance, portfolio_scope_sha256,
                        exchange_order_id_sha256,
                        predecessor_evidence_sha256,
                        candidate_evidence_sha256
                    ) VALUES (
                        %s::uuid, %s, %s::uuid, %s::uuid, 'BTC-USDC',
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        sweep_id,
                        item["position"],
                        item["client_order_id"],
                        item["root_client_order_id"],
                        item["status"],
                        item["ownership_provenance"],
                        item["portfolio_scope_sha256"],
                        private_bindings[item["client_order_id"]],
                        item["predecessor_evidence_sha256"],
                        item["candidate_evidence_sha256"],
                    ),
                )
            event = self._append_event(
                cursor,
                sweep_id=sweep_id,
                event_type="PLAN_CREATED",
                diagnostic_code="operator_spot_sweep_plan_ready",
                correlation_id=correlation_id,
                evidence={
                    "state": "READY",
                    "revision": 1,
                    "plan_sha256": plan_sha256,
                    "candidate_count": len(normalized["items"]),
                    "zero_creates": True,
                },
            )
            for item in normalized["items"]:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self.prefix}operator_spot_safe_closeout_item_projection (
                        sweep_id, position, state, diagnostic_code,
                        last_event_sequence
                    ) VALUES (
                        %s::uuid, %s, 'PENDING',
                        'operator_spot_sweep_item_pending', %s
                    )
                    """,
                    (
                        sweep_id,
                        item["position"],
                        event["event_sequence"],
                    ),
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_spot_safe_closeout_projection (
                    sweep_id, revision, state, diagnostic_code,
                    local_cycles_used,
                    latest_idempotency_key_sha256,
                    latest_payload_sha256, latest_actor_id_sha256,
                    latest_evidence_sha256, correlation_id,
                    operator_intent
                ) VALUES (
                    %s::uuid, 1, 'READY',
                    'operator_spot_sweep_plan_ready', 1,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    sweep_id,
                    _sha(idempotency_key),
                    payload_sha256,
                    _sha(actor_id),
                    event["evidence_sha256"],
                    correlation_id,
                    operator_intent,
                ),
            )
            result_snapshot = self._project(
                cursor,
                sweep_id,
                command={"action": "CREATE"},
            )
            command = self._insert_command(
                cursor,
                sweep_id=sweep_id,
                action="CREATE",
                cycle_number=1,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                operator_reason_sha256=operator_reason_sha256,
                operator_intent=operator_intent,
                resulting_revision=1,
                event_sequence=int(event["event_sequence"]),
                result_json=result_snapshot,
            )
            return self._project(
                cursor,
                sweep_id,
                command=command,
            )

    def _lock_candidate_evidence(self, cursor: Any) -> None:
        """Prevent canonical candidate truth from changing through commit."""

        for table in (
            "order_parent",
            "operator_follow_up_materialization_attempt",
            "operator_follow_up_materialization_event",
            "operator_hotpoint_control",
            "order_event_stream",
        ):
            if self._table_exists(cursor, table):
                cursor.execute(
                    f"LOCK TABLE {self.prefix}{table} IN SHARE MODE"
                )

    def _revalidate_plan_candidates(
        self,
        cursor: Any,
        *,
        plan: Mapping[str, Any],
        private_exchange_bindings: Mapping[str, str],
    ) -> None:
        current = {
            candidate["client_order_id"]: candidate
            for row in self._candidate_rows(cursor)
            if (
                candidate := self._candidate_from_row(row)
            )
            is not None
        }
        for item in plan["items"]:
            client_order_id = str(item["client_order_id"])
            candidate = current.get(client_order_id)
            expected_public = {
                key: item[key]
                for key in (
                    "client_order_id",
                    "root_client_order_id",
                    "product_id",
                    "status",
                    "ownership_provenance",
                    "portfolio_scope_sha256",
                    "predecessor_evidence_sha256",
                    "candidate_evidence_sha256",
                )
            }
            if (
                candidate is None
                or any(
                    candidate.get(key) != value
                    for key, value in expected_public.items()
                )
                or candidate.get("exchange_order_id_sha256")
                != private_exchange_bindings.get(client_order_id)
            ):
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_candidate_evidence_conflict"
                )

    def get_plan(self, *, sweep_id: str) -> dict[str, Any] | None:
        sweep = _canonical_uuid(
            sweep_id,
            code="operator_spot_sweep_identity_invalid",
        )
        with self.database.get_cursor() as cursor:
            return self._project_or_none(cursor, sweep)

    def get_current_plan(self) -> dict[str, Any] | None:
        with self.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT sweep_id
                FROM {self.prefix}operator_spot_safe_closeout_plan
                WHERE goal_id = %s
                """,
                (GOAL_ID,),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            if len(rows) != 1:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_singleton_invalid"
                )
            return self._project(cursor, str(rows[0]["sweep_id"]))

    def apply_local_action(
        self,
        *,
        sweep_id: str,
        action: str,
        expected_revision: int,
        expected_plan_sha256: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
        operator_reason_sha256: str,
        operator_intent: str,
    ) -> dict[str, Any]:
        sweep = _canonical_uuid(
            sweep_id,
            code="operator_spot_sweep_identity_invalid",
        )
        normalized_action = _action(action)
        if normalized_action == "CREATE":
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_local_action_invalid"
            )
        if operator_intent != _INTENTS[normalized_action]:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_operator_intent_invalid"
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_revision_invalid"
            )
        _require_sha(
            expected_plan_sha256,
            code="operator_spot_sweep_plan_binding_invalid",
        )
        _require_sha(
            operator_reason_sha256,
            code="operator_spot_sweep_reason_binding_invalid",
        )
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        with self.database.get_cursor() as cursor:
            self._advisory_lock(cursor)
            replay = self._command_by_idempotency(
                cursor,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                self._require_replay_match(
                    replay,
                    action=normalized_action,
                    sweep_id=sweep,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    payload_sha256=payload_sha256,
                )
                return self._replay_snapshot(replay)
            cursor.execute(
                f"""
                SELECT projection.*, plan.plan_sha256
                FROM
                    {self.prefix}operator_spot_safe_closeout_projection
                        projection
                JOIN {self.prefix}operator_spot_safe_closeout_plan plan
                  ON plan.sweep_id = projection.sweep_id
                WHERE projection.sweep_id = %s::uuid
                FOR UPDATE OF projection
                """,
                (sweep,),
            )
            rows = _rows(cursor)
            if not rows:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_not_found"
                )
            current = rows[0]
            if (
                int(current["revision"]) != expected_revision
                or str(current["plan_sha256"])
                != expected_plan_sha256
            ):
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_plan_binding_conflict"
                )
            if int(current["local_cycles_used"]) >= MAX_CYCLES:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_cycle_cap_reached"
                )
            transitions = {
                "PAUSE": (
                    "READY",
                    "PAUSED",
                    "SWEEP_PAUSED",
                    "operator_spot_sweep_paused",
                ),
                "RESUME": (
                    "PAUSED",
                    "READY",
                    "SWEEP_RESUMED",
                    "operator_spot_sweep_resumed",
                ),
                "ABORT": (
                    ("READY", "PAUSED"),
                    "ABORTED",
                    "SWEEP_ABORTED",
                    "operator_spot_sweep_aborted",
                ),
            }
            expected, next_state, event_type, diagnostic = transitions[
                normalized_action
            ]
            allowed_current = (
                current["state"] in expected
                if isinstance(expected, tuple)
                else current["state"] == expected
            )
            if not allowed_current:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    f"operator_spot_sweep_"
                    f"{normalized_action.lower()}_unavailable"
                )
            next_revision = int(current["revision"]) + 1
            cycle_number = int(current["local_cycles_used"]) + 1
            event = self._append_event(
                cursor,
                sweep_id=sweep,
                event_type=event_type,
                diagnostic_code=diagnostic,
                correlation_id=correlation_id,
                evidence={
                    "state": next_state,
                    "revision": next_revision,
                    "plan_sha256": expected_plan_sha256,
                    "action": normalized_action,
                },
            )
            cursor.execute(
                f"""
                UPDATE
                    {self.prefix}operator_spot_safe_closeout_projection
                SET revision = %s, state = %s, diagnostic_code = %s,
                    local_cycles_used = %s,
                    latest_idempotency_key_sha256 = %s,
                    latest_payload_sha256 = %s,
                    latest_actor_id_sha256 = %s,
                    latest_evidence_sha256 = %s,
                    correlation_id = %s, operator_intent = %s,
                    updated_at = NOW()
                WHERE sweep_id = %s::uuid
                """,
                (
                    next_revision,
                    next_state,
                    diagnostic,
                    cycle_number,
                    _sha(idempotency_key),
                    payload_sha256,
                    _sha(actor_id),
                    event["evidence_sha256"],
                    correlation_id,
                    operator_intent,
                    sweep,
                ),
            )
            if normalized_action == "ABORT":
                cursor.execute(
                    f"""
                    UPDATE
                        {self.prefix}operator_spot_safe_closeout_item_projection
                    SET state = 'ABORTED',
                        diagnostic_code =
                            'operator_spot_sweep_item_aborted',
                        last_event_sequence = %s, updated_at = NOW()
                    WHERE sweep_id = %s::uuid
                      AND state IN ('PENDING', 'REJECTED')
                    """,
                    (event["event_sequence"], sweep),
                )
            result_snapshot = self._project(
                cursor,
                sweep,
                command={"action": normalized_action},
            )
            command = self._insert_command(
                cursor,
                sweep_id=sweep,
                action=normalized_action,
                cycle_number=cycle_number,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
                operator_reason_sha256=operator_reason_sha256,
                operator_intent=operator_intent,
                resulting_revision=next_revision,
                event_sequence=int(event["event_sequence"]),
                result_json=result_snapshot,
            )
            return self._project(cursor, sweep, command=command)

    def recover_stranded_work(self) -> None:
        """Quarantine any state that could represent partial exchange work."""

        with self.database.get_cursor() as cursor:
            self._advisory_lock(cursor)
            cursor.execute(
                f"""
                SELECT projection.sweep_id, projection.revision,
                       projection.local_cycles_used, plan.plan_sha256,
                       projection.state
                FROM
                    {self.prefix}operator_spot_safe_closeout_projection
                        projection
                JOIN {self.prefix}operator_spot_safe_closeout_plan plan
                  ON plan.sweep_id = projection.sweep_id
                WHERE projection.state = 'IN_PROGRESS'
                   OR EXISTS (
                        SELECT 1
                        FROM
                            {self.prefix}operator_spot_safe_closeout_item_projection
                                item
                        WHERE item.sweep_id = projection.sweep_id
                          AND item.state IN ('IN_FLIGHT', 'UNKNOWN')
                   )
                FOR UPDATE OF projection
                """
            )
            for row in _rows(cursor):
                sweep = str(row["sweep_id"])
                next_revision = int(row["revision"]) + 1
                event = self._append_event(
                    cursor,
                    sweep_id=sweep,
                    event_type="SWEEP_QUARANTINED",
                    diagnostic_code=(
                        "operator_spot_sweep_restart_quarantined"
                    ),
                    correlation_id=(
                        "operator_spot_sweep_restart_recovery"
                    ),
                    evidence={
                        "state": "QUARANTINED",
                        "revision": next_revision,
                        "plan_sha256": str(row["plan_sha256"]),
                        "recovery": "restart_partial_result",
                    },
                )
                cursor.execute(
                    f"""
                    UPDATE
                        {self.prefix}operator_spot_safe_closeout_projection
                    SET revision = %s, state = 'QUARANTINED',
                        diagnostic_code =
                            'operator_spot_sweep_restart_quarantined',
                        local_cycles_used = LEAST(
                            {MAX_CYCLES}, local_cycles_used + 1
                        ),
                        latest_evidence_sha256 = %s,
                        correlation_id =
                            'operator_spot_sweep_restart_recovery',
                        updated_at = NOW()
                    WHERE sweep_id = %s::uuid
                    """,
                    (
                        next_revision,
                        event["evidence_sha256"],
                        sweep,
                    ),
                )
                cursor.execute(
                    f"""
                    UPDATE
                        {self.prefix}operator_spot_safe_closeout_item_projection
                    SET state = 'QUARANTINED',
                        diagnostic_code =
                            'operator_spot_sweep_item_quarantined',
                        last_event_sequence = %s, updated_at = NOW()
                    WHERE sweep_id = %s::uuid
                      AND state IN (
                        'PENDING', 'IN_FLIGHT', 'UNKNOWN'
                      )
                    """,
                    (event["event_sequence"], sweep),
                )

    def _validate_plan(
        self,
        plan: Mapping[str, Any],
        plan_sha256: str,
    ) -> dict[str, Any]:
        _require_sha(
            plan_sha256,
            code="operator_spot_sweep_plan_binding_invalid",
        )
        normalized = json.loads(
            json.dumps(
                dict(plan),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if _canonical_sha(normalized) != plan_sha256:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_plan_binding_conflict"
            )
        if (
            normalized.get("goal_id") != GOAL_ID
            or normalized.get("policy_revision") != POLICY_REVISION
            or normalized.get("configured_portfolio_scope_sha256")
            != self.configured_portfolio_scope_sha256
            or normalized.get("max_items") != MAX_ITEMS
            or normalized.get("zero_creates") is not True
        ):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_plan_invalid"
            )
        normalized["sweep_id"] = _canonical_uuid(
            normalized.get("sweep_id"),
            code="operator_spot_sweep_identity_invalid",
        )
        items = normalized.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_item_count_invalid"
            )
        identities: set[str] = set()
        for expected_position, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_plan_invalid"
                )
            item["client_order_id"] = _canonical_uuid(
                item.get("client_order_id"),
                code="operator_spot_sweep_candidate_identity_invalid",
            )
            item["root_client_order_id"] = _canonical_uuid(
                item.get("root_client_order_id"),
                code="operator_spot_sweep_root_identity_invalid",
            )
            if (
                item.get("position") != expected_position
                or item["client_order_id"] in identities
                or item["client_order_id"] == item["root_client_order_id"]
                or item.get("product_id") != "BTC-USDC"
                or item.get("status") not in _ACTIVE_STATUSES
                or item.get("ownership_provenance") not in _PROVENANCES
                or item.get("portfolio_scope_sha256")
                != self.configured_portfolio_scope_sha256
            ):
                raise OperatorSpotSafeCloseoutSweepConflict(
                    "operator_spot_sweep_plan_invalid"
                )
            identities.add(item["client_order_id"])
            for key in (
                "portfolio_scope_sha256",
                "predecessor_evidence_sha256",
                "candidate_evidence_sha256",
            ):
                _require_sha(
                    item.get(key),
                    code="operator_spot_sweep_plan_invalid",
                )
        return normalized

    def _validate_private_exchange_bindings(
        self,
        plan: Mapping[str, Any],
        bindings: Mapping[str, str],
    ) -> dict[str, str]:
        if not isinstance(bindings, Mapping):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_private_binding_invalid"
            )
        expected_ids = {
            str(item["client_order_id"]) for item in plan["items"]
        }
        normalized = {
            _canonical_uuid(
                key,
                code="operator_spot_sweep_candidate_identity_invalid",
            ): str(value)
            for key, value in bindings.items()
        }
        if set(normalized) != expected_ids:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_private_binding_invalid"
            )
        for value in normalized.values():
            _require_sha(
                value,
                code="operator_spot_sweep_private_binding_invalid",
            )
        return normalized

    def _append_event(
        self,
        cursor: Any,
        *,
        sweep_id: str,
        event_type: str,
        diagnostic_code: str,
        correlation_id: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._require_evidence_id(correlation_id)
        if _DIAGNOSTIC.fullmatch(diagnostic_code) is None:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_diagnostic_invalid"
            )
        evidence_sha256 = _canonical_sha(evidence)
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_spot_safe_closeout_event (
                event_id, sweep_id, event_type, diagnostic_code,
                correlation_id, evidence_sha256
            ) VALUES (
                %s::uuid, %s::uuid, %s, %s, %s, %s
            )
            RETURNING event_sequence, event_id, event_type,
                      diagnostic_code, correlation_id,
                      evidence_sha256, recorded_at
            """,
            (
                str(uuid.uuid4()),
                sweep_id,
                event_type,
                diagnostic_code,
                correlation_id,
                evidence_sha256,
            ),
        )
        return _one(
            cursor,
            "operator_spot_sweep_event_insert_failed",
        )

    def _insert_command(
        self,
        cursor: Any,
        *,
        sweep_id: str,
        action: str,
        cycle_number: int,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
        operator_reason_sha256: str,
        operator_intent: str,
        resulting_revision: int,
        event_sequence: int,
        result_json: Mapping[str, Any],
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_spot_safe_closeout_command (
                command_id, sweep_id, action, cycle_number,
                actor_id_sha256, correlation_id,
                idempotency_key_sha256, payload_sha256,
                operator_reason_sha256, operator_intent,
                resulting_revision, event_sequence, result_json
            ) VALUES (
                %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                str(uuid.uuid4()),
                sweep_id,
                action,
                cycle_number,
                _sha(actor_id),
                correlation_id,
                _sha(idempotency_key),
                payload_sha256,
                operator_reason_sha256,
                operator_intent,
                resulting_revision,
                event_sequence,
                Json(dict(result_json)),
            ),
        )
        return _one(
            cursor,
            "operator_spot_sweep_command_insert_failed",
        )

    def _command_by_idempotency(
        self,
        cursor: Any,
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_spot_safe_closeout_command
            WHERE idempotency_key_sha256 = %s
            FOR UPDATE
            """,
            (_sha(idempotency_key),),
        )
        rows = _rows(cursor)
        return rows[0] if rows else None

    def _require_replay_match(
        self,
        command: Mapping[str, Any],
        *,
        action: str,
        sweep_id: str | None,
        actor_id: str,
        correlation_id: str,
        payload_sha256: str,
    ) -> None:
        if not (
            str(command.get("action")) == action
            and (
                sweep_id is None
                or str(command.get("sweep_id")) == sweep_id
            )
            and str(command.get("actor_id_sha256")) == _sha(actor_id)
            and str(command.get("correlation_id")) == correlation_id
            and str(command.get("payload_sha256")) == payload_sha256
        ):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_idempotency_conflict"
            )

    def _replay_snapshot(
        self,
        command: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_snapshot = command.get("result_json")
        if not isinstance(raw_snapshot, Mapping):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_replay_snapshot_unavailable"
            )
        snapshot = json.loads(
            json.dumps(
                dict(raw_snapshot),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        events = snapshot.get("events")
        final_event = (
            events[-1]
            if isinstance(events, list) and events
            and isinstance(events[-1], Mapping)
            else {}
        )
        if not (
            snapshot.get("sweep_id") == str(command.get("sweep_id"))
            and snapshot.get("revision")
            == int(command.get("resulting_revision") or 0)
            and snapshot.get("local_cycles_used")
            == int(command.get("cycle_number") or 0)
            and snapshot.get("latest_action")
            == str(command.get("action") or "")
            and snapshot.get("latest_idempotency_key_sha256")
            == str(command.get("idempotency_key_sha256") or "")
            and snapshot.get("latest_payload_sha256")
            == str(command.get("payload_sha256") or "")
            and snapshot.get("latest_actor_id_sha256")
            == str(command.get("actor_id_sha256") or "")
            and snapshot.get("correlation_id")
            == str(command.get("correlation_id") or "")
            and snapshot.get("operator_intent")
            == str(command.get("operator_intent") or "")
            and final_event.get("event_sequence")
            == int(command.get("event_sequence") or 0)
            and snapshot.get("latest_evidence_sha256")
            == final_event.get("evidence_sha256")
        ):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_replay_snapshot_unavailable"
            )
        snapshot["command_replayed"] = True
        return snapshot

    def _project_or_none(
        self,
        cursor: Any,
        sweep_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT 1
            FROM {self.prefix}operator_spot_safe_closeout_plan
            WHERE sweep_id = %s::uuid AND goal_id = %s
            """,
            (sweep_id, GOAL_ID),
        )
        if cursor.fetchone() is None:
            return None
        return self._project(cursor, sweep_id)

    def _project(
        self,
        cursor: Any,
        sweep_id: str,
        *,
        command_replayed: bool = False,
        command: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT plan.sweep_id, plan.plan_json, plan.plan_sha256,
                   plan.configured_portfolio_scope_sha256,
                   plan.created_at, projection.revision,
                   projection.state, projection.diagnostic_code,
                   projection.local_cycles_used,
                   projection.latest_idempotency_key_sha256,
                   projection.latest_payload_sha256,
                   projection.latest_actor_id_sha256,
                   projection.latest_evidence_sha256,
                   projection.correlation_id,
                   projection.operator_intent,
                   projection.updated_at
            FROM {self.prefix}operator_spot_safe_closeout_plan plan
            JOIN {self.prefix}operator_spot_safe_closeout_projection projection
              ON projection.sweep_id = plan.sweep_id
            WHERE plan.sweep_id = %s::uuid AND plan.goal_id = %s
            """,
            (sweep_id, GOAL_ID),
        )
        rows = _rows(cursor)
        if not rows:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_not_found"
            )
        row = rows[0]
        cursor.execute(
            f"""
            SELECT item.position, item.client_order_id,
                   item.root_client_order_id, item.product_id,
                   item.status_snapshot, item.ownership_provenance,
                   item.portfolio_scope_sha256,
                   item.predecessor_evidence_sha256,
                   item.candidate_evidence_sha256,
                   projection.state, projection.diagnostic_code,
                   projection.last_event_sequence,
                   projection.updated_at
            FROM {self.prefix}operator_spot_safe_closeout_plan_item item
            JOIN
                {self.prefix}operator_spot_safe_closeout_item_projection
                    projection
              ON projection.sweep_id = item.sweep_id
             AND projection.position = item.position
            WHERE item.sweep_id = %s::uuid
            ORDER BY item.position ASC
            """,
            (sweep_id,),
        )
        items = [
            {
                "position": int(item["position"]),
                "client_order_id": str(item["client_order_id"]),
                "root_client_order_id": str(
                    item["root_client_order_id"]
                ),
                "product_id": str(item["product_id"]),
                "status": str(item["status_snapshot"]),
                "ownership_provenance": str(
                    item["ownership_provenance"]
                ),
                "portfolio_scope_sha256": str(
                    item["portfolio_scope_sha256"]
                ),
                "predecessor_evidence_sha256": str(
                    item["predecessor_evidence_sha256"]
                ),
                "candidate_evidence_sha256": str(
                    item["candidate_evidence_sha256"]
                ),
                "state": str(item["state"]),
                "diagnostic_code": str(item["diagnostic_code"]),
                "last_event_sequence": int(
                    item["last_event_sequence"]
                ),
                "updated_at": item["updated_at"].isoformat(),
            }
            for item in _rows(cursor)
        ]
        cursor.execute(
            f"""
            SELECT event_id, event_sequence, event_type,
                   diagnostic_code, correlation_id,
                   evidence_sha256, recorded_at
            FROM {self.prefix}operator_spot_safe_closeout_event
            WHERE sweep_id = %s::uuid
            ORDER BY event_sequence ASC
            """,
            (sweep_id,),
        )
        events = [
            {
                "event_id": str(event["event_id"]),
                "event_sequence": int(event["event_sequence"]),
                "event_type": str(event["event_type"]),
                "diagnostic_code": str(event["diagnostic_code"]),
                "correlation_id": str(event["correlation_id"]),
                "evidence_sha256": str(event["evidence_sha256"]),
                "recorded_at": event["recorded_at"].isoformat(),
            }
            for event in _rows(cursor)
        ]
        if command is None:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.prefix}operator_spot_safe_closeout_command
                WHERE sweep_id = %s::uuid
                ORDER BY cycle_number DESC
                LIMIT 1
                """,
                (sweep_id,),
            )
            commands = _rows(cursor)
            command = commands[0] if commands else None
        return {
            "sweep_id": str(row["sweep_id"]),
            "revision": int(row["revision"]),
            "state": str(row["state"]),
            "diagnostic_code": str(row["diagnostic_code"]),
            "plan": dict(row["plan_json"]),
            "plan_sha256": str(row["plan_sha256"]),
            "configured_portfolio_scope_sha256": str(
                row["configured_portfolio_scope_sha256"]
            ),
            "items": items,
            "events": events,
            "local_cycles_used": int(row["local_cycles_used"]),
            "latest_idempotency_key_sha256": str(
                row["latest_idempotency_key_sha256"]
            ),
            "latest_payload_sha256": str(
                row["latest_payload_sha256"]
            ),
            "latest_actor_id_sha256": str(
                row["latest_actor_id_sha256"]
            ),
            "latest_evidence_sha256": str(
                row["latest_evidence_sha256"]
            ),
            "correlation_id": str(row["correlation_id"]),
            "operator_intent": str(row["operator_intent"]),
            "latest_action": (
                str(command["action"]) if command is not None else "CREATE"
            ),
            "command_replayed": command_replayed,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    def _table_exists(self, cursor: Any, table: str) -> bool:
        cursor.execute(
            "SELECT to_regclass(%s)",
            (f"{self.schema}.{table}",),
        )
        return cursor.fetchone()[0] is not None

    @staticmethod
    def _advisory_lock(cursor: Any) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (GOAL_ID,),
        )

    @staticmethod
    def _require_evidence_id(value: str) -> None:
        if _EVIDENCE_ID.fullmatch(str(value or "")) is None:
            raise OperatorSpotSafeCloseoutSweepError(
                "operator_spot_sweep_command_identity_invalid"
            )

    def _require_command_identity(
        self,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ) -> None:
        self._require_evidence_id(actor_id)
        self._require_evidence_id(correlation_id)
        self._require_evidence_id(idempotency_key)
        _require_sha(
            payload_sha256,
            code="operator_spot_sweep_payload_binding_invalid",
        )


def _optional_member(
    value: str | None,
    allowed: frozenset[str],
    *,
    code: str,
) -> str | None:
    if value is None:
        return None
    normalized = str(value).upper()
    if normalized not in allowed:
        raise OperatorSpotSafeCloseoutSweepError(code)
    return normalized


def _action(value: str) -> str:
    normalized = str(value or "").upper()
    if normalized not in _ACTIONS:
        raise OperatorSpotSafeCloseoutSweepError(
            "operator_spot_sweep_local_action_invalid"
        )
    return normalized


def _canonical_uuid(value: Any, *, code: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = uuid.UUID(normalized)
    except (AttributeError, TypeError, ValueError) as exc:
        raise OperatorSpotSafeCloseoutSweepError(code) from exc
    if str(parsed) != normalized:
        raise OperatorSpotSafeCloseoutSweepError(code)
    return normalized


def _require_sha(value: Any, *, code: str) -> None:
    if _SHA256.fullmatch(str(value or "")) is None:
        raise OperatorSpotSafeCloseoutSweepError(code)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return _sha(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [
        dict(zip(names, row, strict=True))
        for row in cursor.fetchall()
    ]


def _one(cursor: Any, code: str) -> dict[str, Any]:
    rows = _rows(cursor)
    if len(rows) != 1:
        raise OperatorSpotSafeCloseoutSweepConflict(code)
    return rows[0]


@lru_cache(maxsize=1)
def get_default_operator_spot_safe_closeout_sweep_repository(
) -> OperatorSpotSafeCloseoutSweepRepository:
    return OperatorSpotSafeCloseoutSweepRepository(
        PostgresDB(),
        configured_portfolio_id=str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip(),
    )


def initialize_operator_spot_safe_closeout_sweep_schema() -> None:
    get_default_operator_spot_safe_closeout_sweep_repository().ensure_schema()


__all__ = [
    "GOAL_ID",
    "MAX_CYCLES",
    "MAX_ITEMS",
    "OperatorSpotSafeCloseoutSweepConflict",
    "OperatorSpotSafeCloseoutSweepError",
    "OperatorSpotSafeCloseoutSweepRepository",
    "get_default_operator_spot_safe_closeout_sweep_repository",
    "initialize_operator_spot_safe_closeout_sweep_schema",
]
