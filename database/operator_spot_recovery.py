"""PostgreSQL durability for operator-selected Spot recovery cases."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from functools import lru_cache
from typing import Any

from psycopg2.extras import Json

from application.admin_api.operator_spot_recovery import (
    OperatorSpotRecoveryError,
    SpotRecoveryPlan,
)
from core.enums import (
    OrderStatus,
    SpotRecoveryCaseState,
    SpotRecoveryPlanKind,
)
from database.database import PostgresDB


_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TERMINAL_STATUS_VALUES = frozenset(
    {
        OrderStatus.FILLED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.EXPIRED.value,
        OrderStatus.FAILED.value,
    }
)
_REFRESHABLE_STATES = frozenset(
    {
        SpotRecoveryCaseState.OPEN.value,
        SpotRecoveryCaseState.BLOCKED.value,
        SpotRecoveryCaseState.ROLLED_BACK.value,
    }
)
_ACTIVE_CASE_STATES = frozenset(
    {
        SpotRecoveryCaseState.OPEN.value,
        SpotRecoveryCaseState.REFRESHING.value,
        SpotRecoveryCaseState.PLAN_READY.value,
        SpotRecoveryCaseState.APPLIED.value,
        SpotRecoveryCaseState.ROLLED_BACK.value,
        SpotRecoveryCaseState.CANCEL_PENDING.value,
        SpotRecoveryCaseState.BLOCKED.value,
    }
)


class OperatorSpotRecoveryRepository:
    """Transaction-bounded recovery repository with immutable event readback."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
        order_schema: str = "public",
    ) -> None:
        if (
            _SCHEMA_PATTERN.fullmatch(schema) is None
            or _SCHEMA_PATTERN.fullmatch(order_schema) is None
        ):
            raise OperatorSpotRecoveryError(
                "operator_spot_recovery_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.order_schema = order_schema
        self.prefix = f'"{schema}".'
        self.order_prefix = f'"{order_schema}".'

    def ensure_schema(self) -> None:
        states = ", ".join(f"'{item.value}'" for item in SpotRecoveryCaseState)
        kinds = ", ".join(f"'{item.value}'" for item in SpotRecoveryPlanKind)
        active_states = ", ".join(f"'{item}'" for item in _ACTIVE_CASE_STATES)
        with self.database.get_cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_recovery_case (
                    case_id UUID PRIMARY KEY,
                    client_order_id VARCHAR(40) NOT NULL,
                    product_id VARCHAR(255) NOT NULL,
                    portfolio_id_sha256 CHAR(64) NOT NULL
                        CHECK (portfolio_id_sha256 ~ '^[0-9a-f]{{64}}$'),
                    state TEXT NOT NULL CHECK (state IN ({states})),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    refresh_count INTEGER NOT NULL DEFAULT 0
                        CHECK (refresh_count BETWEEN 0 AND 10),
                    order_read_logical_count INTEGER NOT NULL DEFAULT 0
                        CHECK (order_read_logical_count BETWEEN 0 AND 10),
                    fill_read_logical_count INTEGER NOT NULL DEFAULT 0
                        CHECK (fill_read_logical_count BETWEEN 0 AND 10),
                    cancel_call_count INTEGER NOT NULL DEFAULT 0
                        CHECK (cancel_call_count BETWEEN 0 AND 1),
                    cancel_allowance_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                    plan_kind TEXT CHECK (
                        plan_kind IS NULL OR plan_kind IN ({kinds})
                    ),
                    plan_sha256 CHAR(64) CHECK (
                        plan_sha256 IS NULL
                        OR plan_sha256 ~ '^[0-9a-f]{{64}}$'
                    ),
                    plan_json JSONB,
                    pre_apply_status TEXT,
                    applied_status TEXT,
                    diagnostic_code TEXT NOT NULL
                        CHECK (char_length(diagnostic_code) BETWEEN 1 AND 96),
                    created_by TEXT NOT NULL
                        CHECK (char_length(created_by) BETWEEN 1 AND 255),
                    correlation_id TEXT NOT NULL
                        CHECK (char_length(correlation_id) BETWEEN 1 AND 255),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    operator_spot_recovery_case_client_updated_idx
                ON {self.prefix}operator_spot_recovery_case
                    (client_order_id, updated_at DESC)
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    operator_spot_recovery_case_one_active_order_idx
                ON {self.prefix}operator_spot_recovery_case (client_order_id)
                WHERE state IN ({active_states})
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_spot_recovery_event (
                    event_id UUID PRIMARY KEY,
                    case_id UUID NOT NULL REFERENCES
                        {self.prefix}operator_spot_recovery_case(case_id),
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
                    operator_spot_recovery_event_case_recorded_idx
                ON {self.prefix}operator_spot_recovery_event
                    (case_id, recorded_at DESC)
                """
            )
            self._recover_interrupted_claims(cursor)

    def _recover_interrupted_claims(self, cursor: Any) -> None:
        """Fail closed after a process restart without replaying external work."""

        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_spot_recovery_case
            SET
                state = %s,
                revision = revision + 1,
                diagnostic_code = 'recovery_refresh_interrupted',
                updated_at = NOW()
            WHERE state = %s
            RETURNING *
            """,
            (
                SpotRecoveryCaseState.BLOCKED.value,
                SpotRecoveryCaseState.REFRESHING.value,
            ),
        )
        refresh_rows = _cursor_rows(cursor)
        for row in refresh_rows:
            self._append_event(
                cursor,
                case_id=str(row["case_id"]),
                event_type="REFRESH_FAILED",
                actor_id="system_restart_recovery",
                correlation_id=str(row["correlation_id"]),
                operator_reason=None,
                evidence={
                    "state": SpotRecoveryCaseState.BLOCKED.value,
                    "diagnostic_code": "recovery_refresh_interrupted",
                },
            )

        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_spot_recovery_case
            SET
                state = %s,
                revision = revision + 1,
                cancel_call_count = 1,
                cancel_allowance_consumed = TRUE,
                diagnostic_code = 'recovery_cancel_interrupted_unknown',
                updated_at = NOW()
            WHERE state = %s
            RETURNING *
            """,
            (
                SpotRecoveryCaseState.UNKNOWN.value,
                SpotRecoveryCaseState.CANCEL_PENDING.value,
            ),
        )
        cancel_rows = _cursor_rows(cursor)
        for row in cancel_rows:
            self._append_event(
                cursor,
                case_id=str(row["case_id"]),
                event_type="CANCEL_TERMINAL",
                actor_id="system_restart_recovery",
                correlation_id=str(row["correlation_id"]),
                operator_reason=None,
                evidence={
                    "state": SpotRecoveryCaseState.UNKNOWN.value,
                    "diagnostic_code": (
                        "recovery_cancel_interrupted_unknown"
                    ),
                    "cancel_call_count": 1,
                },
            )

    def read_local_order(self, client_order_id: str) -> dict[str, Any] | None:
        rows = self.database.execute_query(
            f"""
            SELECT
                client_order_id,
                product_id,
                side,
                status,
                ownership_provenance,
                retail_portfolio_id::text AS retail_portfolio_id,
                exchange_order_id
            FROM {self.order_prefix}order_parent
            WHERE client_order_id = %s
            """,
            (client_order_id,),
        )
        return rows[0] if rows else None

    def create_case(
        self,
        *,
        client_order_id: str,
        product_id: str,
        portfolio_id_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        case_id = str(uuid.uuid4())
        with self.database.get_cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (client_order_id,),
            )
            cursor.execute(
                f"""
                SELECT case_id
                FROM {self.prefix}operator_spot_recovery_case
                WHERE client_order_id = %s
                  AND state = ANY(%s)
                LIMIT 1
                """,
                (client_order_id, list(_ACTIVE_CASE_STATES)),
            )
            if cursor.fetchone() is not None:
                raise OperatorSpotRecoveryError(
                    "recovery_case_already_active"
                )
            cursor.execute(
                f"""
                INSERT INTO {self.prefix}operator_spot_recovery_case (
                    case_id,
                    client_order_id,
                    product_id,
                    portfolio_id_sha256,
                    state,
                    revision,
                    diagnostic_code,
                    created_by,
                    correlation_id
                )
                VALUES (
                    %s::uuid, %s, %s, %s, %s, 1,
                    'recovery_case_created', %s, %s
                )
                RETURNING *
                """,
                (
                    case_id,
                    client_order_id,
                    product_id,
                    portfolio_id_sha256,
                    SpotRecoveryCaseState.OPEN.value,
                    actor_id,
                    correlation_id,
                ),
            )
            row = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="CASE_CREATED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={"revision": 1},
            )
        return _normalize_case(row)

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        rows = self.database.execute_query(
            f"""
            SELECT *
            FROM {self.prefix}operator_spot_recovery_case
            WHERE case_id = %s::uuid
            """,
            (case_id,),
        )
        return _normalize_case(rows[0]) if rows else None

    def list_cases(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        rows = self.database.execute_query(
            f"""
            SELECT *
            FROM {self.prefix}operator_spot_recovery_case
            ORDER BY updated_at DESC, case_id DESC
            LIMIT %s OFFSET %s
            """,
            (normalized_limit, normalized_offset),
        )
        count = self.database.execute_query(
            f"""
            SELECT COUNT(*) AS total_count
            FROM {self.prefix}operator_spot_recovery_case
            """
        )[0]["total_count"]
        return [_normalize_case(row) for row in rows], int(count)

    def list_events(
        self,
        case_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.database.execute_query(
            f"""
            SELECT
                event_id::text AS event_id,
                case_id::text AS case_id,
                event_type,
                actor_id,
                correlation_id,
                evidence,
                recorded_at
            FROM {self.prefix}operator_spot_recovery_event
            WHERE case_id = %s::uuid
            ORDER BY recorded_at DESC, event_id DESC
            LIMIT %s
            """,
            (case_id, max(1, min(int(limit), 500))),
        )
        return [_normalize_json_values(row) for row in rows]

    def begin_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_case(cursor, case_id)
            self._require_revision(row, expected_revision)
            if row["state"] not in _REFRESHABLE_STATES:
                raise OperatorSpotRecoveryError(
                    "recovery_case_not_refreshable"
                )
            if int(row["refresh_count"]) >= 10:
                raise OperatorSpotRecoveryError(
                    "recovery_refresh_cycles_exhausted"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    refresh_count = refresh_count + 1,
                    order_read_logical_count = order_read_logical_count + 1,
                    plan_kind = NULL,
                    plan_sha256 = NULL,
                    plan_json = NULL,
                    diagnostic_code = 'recovery_refresh_claimed',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    SpotRecoveryCaseState.REFRESHING.value,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="REFRESH_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "revision": updated["revision"],
                    "refresh_count": updated["refresh_count"],
                    "order_read_logical_count": updated[
                        "order_read_logical_count"
                    ],
                },
            )
        return _normalize_case(updated)

    def record_fill_read_claim(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_case(cursor, case_id)
            self._require_revision(row, expected_revision)
            if row["state"] != SpotRecoveryCaseState.REFRESHING.value:
                raise OperatorSpotRecoveryError(
                    "recovery_refresh_not_in_progress"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    fill_read_logical_count = fill_read_logical_count + 1,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (case_id,),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="FILL_READ_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "fill_read_logical_count": updated[
                        "fill_read_logical_count"
                    ]
                },
            )
        return _normalize_case(updated)

    def complete_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan: SpotRecoveryPlan,
        order_read_page_count: int,
        fill_read_page_count: int | None,
        diagnostic_code: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_case(cursor, case_id)
            self._require_revision(row, expected_revision)
            if row["state"] != SpotRecoveryCaseState.REFRESHING.value:
                raise OperatorSpotRecoveryError(
                    "recovery_refresh_not_in_progress"
                )
            if row["client_order_id"] != plan.client_order_id:
                raise OperatorSpotRecoveryError(
                    "recovery_plan_identity_mismatch"
                )
            if row["product_id"] != plan.product_id:
                raise OperatorSpotRecoveryError(
                    "recovery_plan_product_mismatch"
                )
            if plan.kind is SpotRecoveryPlanKind.BLOCKED:
                state = SpotRecoveryCaseState.BLOCKED
            elif plan.kind is SpotRecoveryPlanKind.NO_CHANGE:
                state = SpotRecoveryCaseState.COMPLETE
            else:
                state = SpotRecoveryCaseState.PLAN_READY
            plan_payload = plan.model_dump(mode="json")
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    plan_kind = %s,
                    plan_sha256 = %s,
                    plan_json = %s,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    state.value,
                    plan.kind.value,
                    plan.plan_sha256,
                    Json(plan_payload),
                    diagnostic_code,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="REFRESH_COMPLETED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "revision": updated["revision"],
                    "state": state.value,
                    "plan_kind": plan.kind.value,
                    "plan_sha256": plan.plan_sha256,
                    "order_read_page_count": order_read_page_count,
                    "diagnostic_code": diagnostic_code,
                    **(
                        {"fill_read_page_count": fill_read_page_count}
                        if fill_read_page_count is not None
                        else {}
                    ),
                },
            )
        return _normalize_case(updated)

    def fail_refresh(
        self,
        *,
        case_id: str,
        expected_revision: int,
        diagnostic_code: str,
        actor_id: str,
        correlation_id: str,
        outcome_unknown: bool = False,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            row = self._locked_case(cursor, case_id)
            self._require_revision(row, expected_revision)
            if row["state"] != SpotRecoveryCaseState.REFRESHING.value:
                raise OperatorSpotRecoveryError(
                    "recovery_refresh_not_in_progress"
                )
            state = (
                SpotRecoveryCaseState.UNKNOWN
                if outcome_unknown
                else SpotRecoveryCaseState.BLOCKED
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (state.value, diagnostic_code, correlation_id, case_id),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="REFRESH_FAILED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "state": state.value,
                    "diagnostic_code": diagnostic_code,
                },
            )
        return _normalize_case(updated)

    def apply_plan(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            case = self._locked_case(cursor, case_id)
            self._require_revision(case, expected_revision)
            plan = _plan_from_case(case)
            if (
                case["state"] != SpotRecoveryCaseState.PLAN_READY.value
                or plan.kind is not SpotRecoveryPlanKind.SET_LOCAL_STATUS
                or not plan.apply_available
                or plan.to_status is None
            ):
                raise OperatorSpotRecoveryError(
                    "recovery_plan_not_apply_eligible"
                )
            local = self._locked_local_order(cursor, case["client_order_id"])
            if str(local["status"]).upper() != plan.from_status.value:
                raise OperatorSpotRecoveryError(
                    "recovery_local_state_changed"
                )
            cursor.execute(
                f"""
                UPDATE {self.order_prefix}order_parent
                SET status = %s
                WHERE client_order_id = %s
                  AND status = %s
                """,
                (
                    plan.to_status.value,
                    case["client_order_id"],
                    plan.from_status.value,
                ),
            )
            if cursor.rowcount != 1:
                raise OperatorSpotRecoveryError(
                    "recovery_local_state_changed"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    pre_apply_status = %s,
                    applied_status = %s,
                    diagnostic_code = 'recovery_plan_applied',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    SpotRecoveryCaseState.APPLIED.value,
                    plan.from_status.value,
                    plan.to_status.value,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="PLAN_APPLIED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "plan_sha256": plan.plan_sha256,
                    "from_status": plan.from_status.value,
                    "to_status": plan.to_status.value,
                    "order_state_mutated": True,
                    "exchange_state_mutated": False,
                },
            )
        return _normalize_case(updated)

    def rollback_plan(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.database.get_cursor() as cursor:
            case = self._locked_case(cursor, case_id)
            self._require_revision(case, expected_revision)
            plan = _plan_from_case(case)
            if (
                case["state"] != SpotRecoveryCaseState.APPLIED.value
                or not plan.rollback_after_apply_available
                or case["pre_apply_status"] not in _TERMINAL_STATUS_VALUES
                or case["applied_status"] not in _TERMINAL_STATUS_VALUES
            ):
                raise OperatorSpotRecoveryError("recovery_rollback_unsafe")
            local = self._locked_local_order(cursor, case["client_order_id"])
            if str(local["status"]).upper() != str(case["applied_status"]):
                raise OperatorSpotRecoveryError(
                    "recovery_local_state_changed"
                )
            cursor.execute(
                f"""
                UPDATE {self.order_prefix}order_parent
                SET status = %s
                WHERE client_order_id = %s
                  AND status = %s
                """,
                (
                    case["pre_apply_status"],
                    case["client_order_id"],
                    case["applied_status"],
                ),
            )
            if cursor.rowcount != 1:
                raise OperatorSpotRecoveryError(
                    "recovery_local_state_changed"
                )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    diagnostic_code = 'recovery_plan_rolled_back',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    SpotRecoveryCaseState.ROLLED_BACK.value,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="PLAN_ROLLED_BACK",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "plan_sha256": plan.plan_sha256,
                    "restored_status": case["pre_apply_status"],
                    "order_state_mutated": True,
                    "exchange_state_mutated": False,
                },
            )
        return _normalize_case(updated)

    def begin_cancel(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Durably claim the sole recovery Cancel allowance before invocation."""

        with self.database.get_cursor() as cursor:
            case = self._locked_case(cursor, case_id)
            self._require_revision(case, expected_revision)
            plan = _plan_from_case(case)
            local = self._locked_local_order(cursor, case["client_order_id"])
            self._require_cancel_candidate(
                case=case,
                plan=plan,
                plan_sha256=plan_sha256,
                local=local,
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    cancel_allowance_consumed = TRUE,
                    diagnostic_code = 'recovery_cancel_claimed',
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    SpotRecoveryCaseState.CANCEL_PENDING.value,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type="CANCEL_CLAIMED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=operator_reason,
                evidence={
                    "revision": updated["revision"],
                    "plan_sha256": plan.plan_sha256,
                    "cancel_call_count": 0,
                    "exchange_mutation_attempted": False,
                },
            )
        return _normalize_case(updated)

    def read_cancel_candidate(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str,
    ) -> dict[str, Any]:
        """Validate the proof pass without reserving the one-use allowance."""

        with self.database.get_cursor() as cursor:
            case = self._locked_case(cursor, case_id)
            self._require_revision(case, expected_revision)
            plan = _plan_from_case(case)
            local = self._locked_local_order(cursor, case["client_order_id"])
            self._require_cancel_candidate(
                case=case,
                plan=plan,
                plan_sha256=plan_sha256,
                local=local,
            )
        return _normalize_case(case)

    def record_cancel_result(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
        exchange_call_ran: bool,
        accepted: bool,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        """Close or safely release a claimed Cancel using fixed result evidence."""

        with self.database.get_cursor() as cursor:
            case = self._locked_case(cursor, case_id)
            self._require_revision(case, expected_revision)
            if (
                case["state"] != SpotRecoveryCaseState.CANCEL_PENDING.value
                or not bool(case["cancel_allowance_consumed"])
                or int(case["cancel_call_count"]) != 0
            ):
                raise OperatorSpotRecoveryError(
                    "recovery_cancel_not_in_progress"
                )
            if exchange_call_ran:
                state = (
                    SpotRecoveryCaseState.CANCELLED
                    if accepted
                    else SpotRecoveryCaseState.UNKNOWN
                )
                allowance_consumed = True
                cancel_call_count = 1
                event_type = "CANCEL_TERMINAL"
            else:
                state = SpotRecoveryCaseState.PLAN_READY
                allowance_consumed = False
                cancel_call_count = 0
                event_type = "CANCEL_RELEASED_PREBOUNDARY"
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_spot_recovery_case
                SET
                    state = %s,
                    revision = revision + 1,
                    cancel_call_count = %s,
                    cancel_allowance_consumed = %s,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    updated_at = NOW()
                WHERE case_id = %s::uuid
                RETURNING *
                """,
                (
                    state.value,
                    cancel_call_count,
                    allowance_consumed,
                    diagnostic_code,
                    correlation_id,
                    case_id,
                ),
            )
            updated = _cursor_row(cursor)
            self._append_event(
                cursor,
                case_id=case_id,
                event_type=event_type,
                actor_id=actor_id,
                correlation_id=correlation_id,
                operator_reason=None,
                evidence={
                    "state": state.value,
                    "diagnostic_code": diagnostic_code,
                    "cancel_call_count": cancel_call_count,
                    "exchange_mutation_attempted": exchange_call_ran,
                    "exchange_mutation_accepted": (
                        accepted if exchange_call_ran else False
                    ),
                },
            )
        return _normalize_case(updated)

    def _locked_case(self, cursor: Any, case_id: str) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_spot_recovery_case
            WHERE case_id = %s::uuid
            FOR UPDATE
            """,
            (case_id,),
        )
        row = _cursor_row(cursor)
        if row is None:
            raise OperatorSpotRecoveryError("recovery_case_not_found")
        return row

    def _locked_local_order(self, cursor: Any, client_order_id: str) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT client_order_id, status
            FROM {self.order_prefix}order_parent
            WHERE client_order_id = %s
            FOR UPDATE
            """,
            (client_order_id,),
        )
        row = _cursor_row(cursor)
        if row is None:
            raise OperatorSpotRecoveryError("recovery_local_order_not_found")
        return row

    @staticmethod
    def _require_revision(row: dict[str, Any], expected_revision: int) -> None:
        if int(row["revision"]) != int(expected_revision):
            raise OperatorSpotRecoveryError(
                "recovery_case_revision_conflict"
            )

    @staticmethod
    def _require_cancel_candidate(
        *,
        case: dict[str, Any],
        plan: SpotRecoveryPlan,
        plan_sha256: str,
        local: dict[str, Any],
    ) -> None:
        if (
            case["state"] != SpotRecoveryCaseState.PLAN_READY.value
            or plan.kind is not SpotRecoveryPlanKind.CANCEL_ACTIVE_ORPHAN
            or not plan.cancel_available
            or plan.plan_sha256 != plan_sha256
            or bool(case["cancel_allowance_consumed"])
            or int(case["cancel_call_count"]) != 0
        ):
            raise OperatorSpotRecoveryError(
                "recovery_cancel_not_claimable"
            )
        if str(local["status"]).upper() != plan.from_status.value:
            raise OperatorSpotRecoveryError(
                "recovery_local_state_changed"
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
        reason_hash = (
            hashlib.sha256(operator_reason.encode("utf-8")).hexdigest()
            if operator_reason
            else None
        )
        cursor.execute(
            f"""
            INSERT INTO {self.prefix}operator_spot_recovery_event (
                event_id,
                case_id,
                event_type,
                actor_id,
                correlation_id,
                operator_reason_sha256,
                evidence
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                case_id,
                event_type,
                actor_id,
                correlation_id,
                reason_hash,
                Json(evidence),
            ),
        )


def _cursor_row(cursor: Any) -> dict[str, Any] | None:
    raw = cursor.fetchone()
    if raw is None:
        return None
    return dict(zip((description[0] for description in cursor.description), raw))


@lru_cache(maxsize=1)
def get_default_operator_spot_recovery_repository(
) -> OperatorSpotRecoveryRepository:
    """Return the process-wide repository so startup recovery runs once."""

    repository = OperatorSpotRecoveryRepository(PostgresDB())
    repository.ensure_schema()
    return repository


def _cursor_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, raw)) for raw in cursor.fetchall()]


def _normalize_case(row: dict[str, Any]) -> dict[str, Any]:
    result = _normalize_json_values(dict(row))
    result["case_id"] = str(result["case_id"])
    result["revision"] = int(result["revision"])
    result["refresh_count"] = int(result["refresh_count"])
    result["order_read_logical_count"] = int(result["order_read_logical_count"])
    result["fill_read_logical_count"] = int(result["fill_read_logical_count"])
    result["cancel_call_count"] = int(result["cancel_call_count"])
    plan_json = result.get("plan_json")
    if isinstance(plan_json, str):
        plan_json = json.loads(plan_json)
    result["plan"] = plan_json
    result.pop("plan_json", None)
    return result


def _normalize_json_values(row: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(row.items()):
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            row[key] = str(value)
    return row


def _plan_from_case(case: dict[str, Any]) -> SpotRecoveryPlan:
    raw = case.get("plan_json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise OperatorSpotRecoveryError("recovery_plan_missing")
    plan = SpotRecoveryPlan.model_validate(raw)
    if plan.plan_sha256 != case.get("plan_sha256"):
        raise OperatorSpotRecoveryError("recovery_plan_hash_mismatch")
    return plan
