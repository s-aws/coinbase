"""PostgreSQL authority for the bounded Goal 11 Futures position lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.futures_public_projection import (
    is_opaque_futures_position_key,
    public_futures_product_id,
)
from application.admin_api.operator_futures_position_lifecycle import (
    FUTURES_POSITION_ELIGIBILITY_CATEGORIES,
    FUTURES_POSITION_GOAL_ID,
    FUTURES_POSITION_MODES,
    FuturesPositionEligibilityResult,
    FuturesPositionExecutionPlan,
    FuturesPositionGoalRecord,
    FuturesPositionLifecycleError,
    FuturesPositionRequestContext,
    classify_futures_position_selection_freshness,
)
from core.enums import (
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)
from database.operator_futures_cancel_invocation_seal import (
    ensure_futures_cancel_invocation_seal,
    futures_cancel_invocation_is_sealed,
    seal_futures_cancel_invocation,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ELIGIBILITY_CYCLES = 10
_EMPTY_ATTEMPTS = {
    category: 0 for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES
}
_EMPTY_ATTEMPTS_JSON = json.dumps(
    _EMPTY_ATTEMPTS,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
)
_STEP_COLUMNS = {
    "action": ("action_outcome", "action_exchange_invoked"),
    "order_reconciliation": (
        "order_reconciliation_outcome",
        "order_reconciliation_exchange_invoked",
    ),
    "position_reconciliation": (
        "position_reconciliation_outcome",
        "position_reconciliation_exchange_invoked",
    ),
    "cancel": ("cancel_outcome", "cancel_exchange_invoked"),
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((column[0] for column in cursor.description), value))


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("operator_futures_position_stored_json_invalid")
    return dict(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    normalized = str(value).strip()
    return normalized or None


def _exact_sha256(value: Any, *, code: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise FuturesPositionLifecycleError(code)
    return normalized


def _outcome(value: Any) -> AdminFuturesPositionCallOutcome:
    if isinstance(value, AdminFuturesPositionCallOutcome):
        return value
    try:
        return AdminFuturesPositionCallOutcome(str(value))
    except ValueError:
        raise FuturesPositionLifecycleError(
            "operator_futures_position_call_outcome_invalid"
        ) from None


class OperatorFuturesPositionLifecycleRepository:
    """Serialize Goal 11 state, calls, and append-only read claims."""

    def __init__(
        self,
        db: Any,
        *,
        configured_portfolio_id: str | None = None,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("operator_futures_position_schema_invalid")
        self.db = db
        self.schema = str(schema)
        self.configured_portfolio_id_sha256 = (
            _sha256_text(str(uuid.UUID(str(configured_portfolio_id))))
            if configured_portfolio_id
            else None
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @contextmanager
    def _cursor(self):
        with self.db.get_cursor() as cursor:
            yield cursor

    @staticmethod
    def _lock(cursor: Any) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(34994, 11)")

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._cursor() as cursor:
                ensure_futures_cancel_invocation_seal(
                    cursor,
                    schema=self.schema,
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_position_goal')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        revision INTEGER NOT NULL DEFAULT 0
                            CHECK (revision >= 0),
                        cycles_used INTEGER NOT NULL DEFAULT 0
                            CHECK (cycles_used BETWEEN 0 AND 10),
                        active_cycle_number INTEGER,
                        requested_position_key VARCHAR(80),
                        eligibility_outcome VARCHAR(16)
                            CHECK (
                                eligibility_outcome IS NULL OR
                                eligibility_outcome IN (
                                    'ELIGIBLE', 'INELIGIBLE', 'UNKNOWN'
                                )
                            ),
                        eligibility_diagnostic_code VARCHAR(128) NOT NULL,
                        category_attempts_json JSONB NOT NULL DEFAULT '{{}}',
                        selection_json JSONB,
                        selection_sha256 CHAR(64),
                        portfolio_id_sha256 CHAR(64),
                        bound_portfolio_id_sha256 CHAR(64),
                        eligibility_evidence_sha256 CHAR(64),
                        execution_claim_id UUID UNIQUE,
                        selected_mode VARCHAR(32)
                            CHECK (
                                selected_mode IS NULL OR
                                selected_mode IN (
                                    'CLOSE_FULL', 'REDUCE_ONE_CONTRACT'
                                )
                            ),
                        client_order_id VARCHAR(128) UNIQUE,
                        action_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (action_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        action_exchange_invoked BOOLEAN,
                        exchange_order_id_sha256 CHAR(64),
                        order_reconciliation_outcome VARCHAR(16)
                            NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (order_reconciliation_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        order_reconciliation_exchange_invoked BOOLEAN,
                        order_status VARCHAR(32),
                        authoritatively_nonterminal BOOLEAN,
                        position_reconciliation_outcome VARCHAR(16)
                            NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (position_reconciliation_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        position_reconciliation_exchange_invoked BOOLEAN,
                        remaining_contracts VARCHAR(64),
                        cancel_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (cancel_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        cancel_exchange_invoked BOOLEAN,
                        diagnostic_code VARCHAR(128) NOT NULL,
                        actor_id VARCHAR(255),
                        roles_json JSONB NOT NULL DEFAULT '[]',
                        correlation_id VARCHAR(255),
                        audit_id UUID,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        CHECK (
                            active_cycle_number IS NULL OR
                            active_cycle_number BETWEEN 1 AND 10
                        ),
                        CHECK (
                            (selection_json IS NULL
                             AND selection_sha256 IS NULL)
                            OR
                            (selection_json IS NOT NULL
                             AND selection_sha256 IS NOT NULL)
                        ),
                        CHECK (
                            (execution_claim_id IS NULL
                             AND selected_mode IS NULL
                             AND client_order_id IS NULL)
                            OR
                            (execution_claim_id IS NOT NULL
                             AND selected_mode IS NOT NULL
                             AND client_order_id IS NOT NULL)
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_position_cycle_category'
                        )} (
                        goal_id VARCHAR(128) NOT NULL,
                        cycle_number INTEGER NOT NULL
                            CHECK (cycle_number BETWEEN 1 AND 10),
                        category VARCHAR(64) NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (goal_id, cycle_number, category),
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table(
                                'operator_futures_position_goal'
                            )}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_position_command')} (
                        command_id UUID PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        action VARCHAR(16) NOT NULL
                            CHECK (action IN ('REFRESH', 'EXECUTE')),
                        expected_revision INTEGER NOT NULL,
                        result_revision INTEGER NOT NULL,
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        request_sha256 CHAR(64) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        confirmations_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table(
                                'operator_futures_position_goal'
                            )}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_position_command')}
                    ADD COLUMN IF NOT EXISTS request_sha256 CHAR(64)
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        {self._table(
                            'guard_operator_futures_position_append_only'
                        )}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = '55000',
                            MESSAGE =
                                'operator_futures_position_evidence_append_only';
                    END;
                    $$
                    """
                )
                for table, trigger in (
                    (
                        "operator_futures_position_cycle_category",
                        "operator_futures_position_category_append_only",
                    ),
                    (
                        "operator_futures_position_command",
                        "operator_futures_position_command_append_only",
                    ),
                ):
                    cursor.execute(
                        f"DROP TRIGGER IF EXISTS {trigger} "
                        f"ON {self._table(table)}"
                    )
                    cursor.execute(
                        f"""
                        CREATE TRIGGER {trigger}
                        BEFORE UPDATE OR DELETE ON {self._table(table)}
                        FOR EACH ROW EXECUTE FUNCTION
                            {self._table(
                                'guard_operator_futures_position_append_only'
                            )}()
                        """
                    )
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self._table('operator_futures_position_goal')} (
                        goal_id,
                        eligibility_diagnostic_code,
                        diagnostic_code,
                        category_attempts_json
                    ) VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (goal_id) DO NOTHING
                    """,
                    (
                        FUTURES_POSITION_GOAL_ID,
                        "operator_futures_position_not_refreshed",
                        "operator_futures_position_not_refreshed",
                        _EMPTY_ATTEMPTS_JSON,
                    ),
                )
                if self.configured_portfolio_id_sha256 is not None:
                    cursor.execute(
                        f"""
                        UPDATE
                            {self._table('operator_futures_position_goal')}
                        SET bound_portfolio_id_sha256 =
                            COALESCE(bound_portfolio_id_sha256, %s)
                        WHERE goal_id = %s
                        RETURNING bound_portfolio_id_sha256
                        """,
                        (
                            self.configured_portfolio_id_sha256,
                            FUTURES_POSITION_GOAL_ID,
                        ),
                    )
                    bound = _row(cursor)
                    if (
                        bound is None
                        or str(bound["bound_portfolio_id_sha256"])
                        != self.configured_portfolio_id_sha256
                    ):
                        raise RuntimeError(
                            "operator_futures_position_portfolio_binding_invalid"
                        )
                self._recover_inflight(cursor)
            self._schema_ready = True

    def _recover_inflight(self, cursor: Any) -> None:
        row = self._select(cursor, for_update=True)
        updates: list[str] = []
        params: list[Any] = []
        diagnostic: str | None = None
        if row.get("active_cycle_number") is not None:
            updates.extend(
                [
                    "active_cycle_number = NULL",
                    "eligibility_outcome = 'UNKNOWN'",
                    "eligibility_diagnostic_code = %s",
                ]
            )
            params.append(
                "operator_futures_position_restart_eligibility_unknown"
            )
            diagnostic = (
                "operator_futures_position_restart_eligibility_unknown"
            )
        for step, (outcome_column, _invoked_column) in _STEP_COLUMNS.items():
            if row.get(outcome_column) == "CLAIMED":
                updates.append(f"{outcome_column} = 'UNKNOWN'")
                diagnostic = (
                    f"operator_futures_position_restart_{step}_unknown"
                )
        if not updates:
            return
        updates.extend(
            [
                "diagnostic_code = %s",
                "revision = revision + 1",
                "updated_at = CURRENT_TIMESTAMP",
            ]
        )
        params.extend([diagnostic, FUTURES_POSITION_GOAL_ID])
        cursor.execute(
            f"""
            UPDATE {self._table('operator_futures_position_goal')}
            SET {", ".join(updates)}
            WHERE goal_id = %s
            """,
            tuple(params),
        )

    def _select(
        self,
        cursor: Any,
        *,
        for_update: bool,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT * FROM {self._table('operator_futures_position_goal')}
            WHERE goal_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (FUTURES_POSITION_GOAL_ID,),
        )
        value = _row(cursor)
        if value is None:
            raise RuntimeError("operator_futures_position_goal_missing")
        return value

    @staticmethod
    def _record(value: Mapping[str, Any]) -> FuturesPositionGoalRecord:
        selection_raw = value.get("selection_json")
        selection = (
            {
                str(key): str(item)
                for key, item in _json_object(selection_raw).items()
            }
            if selection_raw is not None
            else None
        )
        eligibility = value.get("eligibility_outcome")
        return FuturesPositionGoalRecord(
            goal_id=str(value["goal_id"]),
            revision=int(value["revision"]),
            cycles_used=int(value["cycles_used"]),
            active_cycle_number=(
                int(value["active_cycle_number"])
                if value.get("active_cycle_number") is not None
                else None
            ),
            eligibility_outcome=(
                AdminFuturesPositionEligibilityOutcome(str(eligibility))
                if eligibility is not None
                else None
            ),
            eligibility_diagnostic_code=str(
                value["eligibility_diagnostic_code"]
            ),
            category_attempts={
                str(key): int(item)
                for key, item in _json_object(
                    value.get("category_attempts_json")
                ).items()
            },
            selection=selection,
            selection_sha256=(
                str(value["selection_sha256"])
                if value.get("selection_sha256")
                else None
            ),
            portfolio_id_sha256=(
                str(value["portfolio_id_sha256"])
                if value.get("portfolio_id_sha256")
                else None
            ),
            eligibility_evidence_sha256=(
                str(value["eligibility_evidence_sha256"])
                if value.get("eligibility_evidence_sha256")
                else None
            ),
            selected_mode=(
                str(value["selected_mode"])
                if value.get("selected_mode")
                else None
            ),
            client_order_id=(
                str(value["client_order_id"])
                if value.get("client_order_id")
                else None
            ),
            action_outcome=_outcome(value["action_outcome"]),
            action_exchange_invoked=value.get("action_exchange_invoked"),
            exchange_order_id_sha256=(
                str(value["exchange_order_id_sha256"])
                if value.get("exchange_order_id_sha256")
                else None
            ),
            order_reconciliation_outcome=_outcome(
                value["order_reconciliation_outcome"]
            ),
            order_reconciliation_exchange_invoked=value.get(
                "order_reconciliation_exchange_invoked"
            ),
            order_status=(
                str(value["order_status"])
                if value.get("order_status")
                else None
            ),
            authoritatively_nonterminal=value.get(
                "authoritatively_nonterminal"
            ),
            position_reconciliation_outcome=_outcome(
                value["position_reconciliation_outcome"]
            ),
            position_reconciliation_exchange_invoked=value.get(
                "position_reconciliation_exchange_invoked"
            ),
            remaining_contracts=(
                str(value["remaining_contracts"])
                if value.get("remaining_contracts") is not None
                else None
            ),
            cancel_outcome=_outcome(value["cancel_outcome"]),
            cancel_exchange_invoked=value.get("cancel_exchange_invoked"),
            diagnostic_code=str(value["diagnostic_code"]),
            correlation_id=(
                str(value["correlation_id"])
                if value.get("correlation_id")
                else None
            ),
            audit_id=(
                str(value["audit_id"])
                if value.get("audit_id")
                else None
            ),
            updated_at=_iso(value.get("updated_at")),
        )

    @staticmethod
    def _validate_context(context: FuturesPositionRequestContext) -> None:
        if (
            not context.actor_id
            or not context.roles
            or context.expected_revision < 0
            or not context.idempotency_key
            or len(context.idempotency_key) > 255
            or not context.correlation_id
            or len(context.correlation_id) > 255
        ):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_context_invalid",
                http_status_code=422,
            )
        try:
            uuid.UUID(context.audit_id)
        except (ValueError, TypeError, AttributeError):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_context_invalid",
                http_status_code=422,
            ) from None

    def _idempotency_hash(
        self,
        *,
        action: str,
        context: FuturesPositionRequestContext,
    ) -> str:
        return _sha256_text(f"{action}:{context.idempotency_key}")

    @staticmethod
    def _confirmations(
        context: FuturesPositionRequestContext,
    ) -> dict[str, bool]:
        return {
            "authorize_one_no_retry_six_category_cycle": (
                context.authorize_one_no_retry_six_category_cycle
            ),
            "acknowledge_cycle_is_goal_global_and_limited_to_ten": (
                context.acknowledge_cycle_is_goal_global_and_limited_to_ten
            ),
            "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": (
                context.acknowledge_unsuccessful_or_unknown_cycle_fails_closed
            ),
            "authorize_exact_selected_position_action": (
                context.authorize_exact_selected_position_action
            ),
            "acknowledge_action_is_mutually_exclusive_and_single_use": (
                context.acknowledge_action_is_mutually_exclusive_and_single_use
            ),
            "acknowledge_unknown_outcome_consumes_allowance": (
                context.acknowledge_unknown_outcome_consumes_allowance
            ),
            "acknowledge_exact_order_cancel_only": (
                context.acknowledge_exact_order_cancel_only
            ),
        }

    def _request_hash(
        self,
        *,
        action: str,
        context: FuturesPositionRequestContext,
        position_key: str,
        mode: str | None,
    ) -> str:
        return _canonical_sha256(
            {
                "action": action,
                "actor_id": context.actor_id,
                "roles": list(context.roles),
                "expected_revision": context.expected_revision,
                "operator_intent": context.operator_intent,
                "position_key": position_key,
                "mode": mode,
                "confirmations": self._confirmations(context),
            }
        )

    def _replayed(
        self,
        cursor: Any,
        *,
        action: str,
        context: FuturesPositionRequestContext,
        request_sha256: str,
    ) -> bool:
        cursor.execute(
            f"""
            SELECT request_sha256
            FROM {self._table('operator_futures_position_command')}
            WHERE goal_id = %s
              AND action = %s
              AND idempotency_key_sha256 = %s
            """,
            (
                FUTURES_POSITION_GOAL_ID,
                action,
                self._idempotency_hash(action=action, context=context),
            ),
        )
        command = _row(cursor)
        if command is None:
            return False
        if command.get("request_sha256") != request_sha256:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_idempotency_conflict"
            )
        return True

    def _insert_command(
        self,
        cursor: Any,
        *,
        action: str,
        context: FuturesPositionRequestContext,
        request_sha256: str,
        result_revision: int,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO
                {self._table('operator_futures_position_command')} (
                command_id,
                goal_id,
                action,
                expected_revision,
                result_revision,
                idempotency_key_sha256,
                request_sha256,
                actor_id,
                roles_json,
                confirmations_json,
                correlation_id,
                audit_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s, %s
            )
            """,
            (
                str(uuid.uuid4()),
                FUTURES_POSITION_GOAL_ID,
                action,
                context.expected_revision,
                result_revision,
                self._idempotency_hash(action=action, context=context),
                request_sha256,
                context.actor_id,
                json.dumps(list(context.roles)),
                json.dumps(
                    self._confirmations(context),
                    sort_keys=True,
                ),
                context.correlation_id,
                context.audit_id,
            ),
        )

    def read(self) -> FuturesPositionGoalRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            return self._record(self._select(cursor, for_update=False))

    def begin_eligibility_cycle(
        self,
        *,
        context: FuturesPositionRequestContext,
        position_key: str,
    ) -> tuple[FuturesPositionGoalRecord, int | None]:
        self.ensure_schema()
        self._validate_context(context)
        if not is_opaque_futures_position_key(position_key):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_key_invalid",
                http_status_code=422,
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            request_sha256 = self._request_hash(
                action="REFRESH",
                context=context,
                position_key=position_key,
                mode=None,
            )
            if self._replayed(
                cursor,
                action="REFRESH",
                context=context,
                request_sha256=request_sha256,
            ):
                return self._record(row), None
            if int(row["revision"]) != context.expected_revision:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_revision_conflict"
                )
            if row.get("active_cycle_number") is not None:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_eligibility_cycle_active"
                )
            if row.get("action_outcome") != "NOT_RUN":
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_refresh_after_action_forbidden"
                )
            cycle_number = int(row["cycles_used"]) + 1
            if cycle_number > _MAX_ELIGIBILITY_CYCLES:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_eligibility_cycles_exhausted"
                )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    cycles_used = %s,
                    active_cycle_number = %s,
                    requested_position_key = %s,
                    eligibility_outcome = NULL,
                    eligibility_diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    selection_json = NULL,
                    selection_sha256 = NULL,
                    portfolio_id_sha256 = NULL,
                    eligibility_evidence_sha256 = NULL,
                    diagnostic_code = %s,
                    actor_id = %s,
                    roles_json = %s::jsonb,
                    correlation_id = %s,
                    audit_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    cycle_number,
                    cycle_number,
                    position_key,
                    "operator_futures_position_eligibility_claimed",
                    _EMPTY_ATTEMPTS_JSON,
                    "operator_futures_position_eligibility_claimed",
                    context.actor_id,
                    json.dumps(list(context.roles)),
                    context.correlation_id,
                    context.audit_id,
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            self._insert_command(
                cursor,
                action="REFRESH",
                context=context,
                request_sha256=request_sha256,
                result_revision=revision,
            )
            return (
                self._record(self._select(cursor, for_update=False)),
                cycle_number,
            )

    def claim_eligibility_category(
        self,
        *,
        cycle_number: int,
        category: str,
    ) -> None:
        self.ensure_schema()
        if category not in FUTURES_POSITION_ELIGIBILITY_CATEGORIES:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_category_not_authorized"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if row.get("active_cycle_number") != cycle_number:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_eligibility_cycle_not_active"
                )
            try:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self._table(
                            'operator_futures_position_cycle_category'
                        )} (
                        goal_id, cycle_number, category
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        FUTURES_POSITION_GOAL_ID,
                        cycle_number,
                        category,
                    ),
                )
            except Exception as exc:
                if getattr(exc, "pgcode", None) == "23505":
                    raise FuturesPositionLifecycleError(
                        "operator_futures_position_category_already_claimed"
                    ) from None
                raise

    def _claimed_categories(
        self,
        cursor: Any,
        *,
        cycle_number: int,
    ) -> set[str]:
        cursor.execute(
            f"""
            SELECT category
            FROM {self._table(
                'operator_futures_position_cycle_category'
            )}
            WHERE goal_id = %s AND cycle_number = %s
            """,
            (FUTURES_POSITION_GOAL_ID, cycle_number),
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def finish_eligibility_cycle(
        self,
        *,
        cycle_number: int,
        result: FuturesPositionEligibilityResult,
        context: FuturesPositionRequestContext,
    ) -> FuturesPositionGoalRecord:
        self.ensure_schema()
        expected_attempts = {
            category: int(result.category_attempts.get(category, 0))
            for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES
        }
        if (
            set(result.category_attempts) != set(expected_attempts)
            or any(value not in {0, 1} for value in expected_attempts.values())
        ):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_category_accounting_invalid"
            )
        evidence_hash = _exact_sha256(
            result.evidence_sha256,
            code="operator_futures_position_eligible_evidence_invalid",
        )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if row.get("active_cycle_number") != cycle_number:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_eligibility_cycle_not_active"
                )
            claimed = self._claimed_categories(
                cursor,
                cycle_number=cycle_number,
            )
            expected_claimed = {
                category
                for category, count in expected_attempts.items()
                if count == 1
            }
            if claimed != expected_claimed:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_category_accounting_invalid"
                )
            selection: dict[str, str] | None = None
            selection_hash: str | None = None
            portfolio_hash: str | None = None
            bound_hash = row.get("bound_portfolio_id_sha256")
            if (
                result.outcome
                is AdminFuturesPositionEligibilityOutcome.ELIGIBLE
            ):
                if (
                    any(value != 1 for value in expected_attempts.values())
                    or result.selection is None
                    or result.portfolio_id_sha256 is None
                ):
                    raise FuturesPositionLifecycleError(
                        "operator_futures_position_eligible_evidence_invalid"
                    )
                selection = {
                    str(key): str(value)
                    for key, value in result.selection.items()
                }
                required = {
                    "position_key",
                    "product_id",
                    "position_side",
                    "close_side",
                    "current_contracts",
                    "full_close_size",
                    "bounded_reduce_size",
                    "best_bid",
                    "best_ask",
                    "observed_at",
                }
                if (
                    set(selection) != required
                    or selection["position_key"]
                    != row.get("requested_position_key")
                    or not is_opaque_futures_position_key(
                        selection["position_key"]
                    )
                    or selection["position_side"] not in {"LONG", "SHORT"}
                    or selection["close_side"] not in {"BUY", "SELL"}
                    or (
                        selection["position_side"] == "LONG"
                        and selection["close_side"] != "SELL"
                    )
                    or (
                        selection["position_side"] == "SHORT"
                        and selection["close_side"] != "BUY"
                    )
                ):
                    raise FuturesPositionLifecycleError(
                        "operator_futures_position_eligible_evidence_invalid"
                    )
                try:
                    public_futures_product_id(selection["product_id"])
                except Exception:
                    raise FuturesPositionLifecycleError(
                        "operator_futures_position_eligible_evidence_invalid"
                    ) from None
                portfolio_hash = _exact_sha256(
                    result.portfolio_id_sha256,
                    code=(
                        "operator_futures_position_eligible_evidence_invalid"
                    ),
                )
                if bound_hash is not None and str(bound_hash) != portfolio_hash:
                    raise FuturesPositionLifecycleError(
                        "operator_futures_position_eligible_evidence_invalid"
                    )
                bound_hash = portfolio_hash
                selection_hash = _canonical_sha256(selection)
            elif (
                result.selection is not None
                or result.portfolio_id_sha256 is not None
            ):
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_ineligible_evidence_invalid"
                )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    active_cycle_number = NULL,
                    eligibility_outcome = %s,
                    eligibility_diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    selection_json = %s::jsonb,
                    selection_sha256 = %s,
                    portfolio_id_sha256 = %s,
                    bound_portfolio_id_sha256 = %s,
                    eligibility_evidence_sha256 = %s,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    audit_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    result.outcome.value,
                    result.diagnostic_code,
                    json.dumps(expected_attempts, sort_keys=True),
                    (
                        json.dumps(selection, sort_keys=True)
                        if selection is not None
                        else None
                    ),
                    selection_hash,
                    portfolio_hash,
                    bound_hash,
                    evidence_hash,
                    result.diagnostic_code,
                    context.correlation_id,
                    context.audit_id,
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            return self._record(self._select(cursor, for_update=False))

    def _require_fresh_selection(
        self,
        selection: Mapping[str, Any],
    ) -> None:
        now = self.clock()
        diagnostic = classify_futures_position_selection_freshness(
            selection,
            now=now,
        )
        if diagnostic != "operator_futures_position_selection_fresh":
            raise FuturesPositionLifecycleError(diagnostic)

    def claim_action(
        self,
        *,
        context: FuturesPositionRequestContext,
        mode: str,
    ) -> tuple[FuturesPositionGoalRecord, FuturesPositionExecutionPlan | None]:
        self.ensure_schema()
        self._validate_context(context)
        if mode not in FUTURES_POSITION_MODES:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_mode_invalid",
                http_status_code=422,
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            request_sha256 = self._request_hash(
                action="EXECUTE",
                context=context,
                position_key=str(row.get("requested_position_key") or ""),
                mode=mode,
            )
            if self._replayed(
                cursor,
                action="EXECUTE",
                context=context,
                request_sha256=request_sha256,
            ):
                return self._record(row), None
            if int(row["revision"]) != context.expected_revision:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_revision_conflict"
                )
            if row.get("action_outcome") != "NOT_RUN":
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_action_already_consumed"
                )
            if row.get("active_cycle_number") is not None:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_eligibility_cycle_active"
                )
            if row.get("eligibility_outcome") != "ELIGIBLE":
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_not_eligible"
                )
            selection = {
                str(key): str(value)
                for key, value in _json_object(
                    row.get("selection_json")
                ).items()
            }
            self._require_fresh_selection(selection)
            if (
                mode == "REDUCE_ONE_CONTRACT"
                and selection.get("bounded_reduce_size") != "1"
            ):
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_reduce_unavailable"
                )
            action_size = (
                None if mode == "CLOSE_FULL" else "1"
            )
            claim_id = str(uuid.uuid4())
            client_order_id = f"goal11-{uuid.uuid4()}"
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    execution_claim_id = %s,
                    selected_mode = %s,
                    client_order_id = %s,
                    action_outcome = 'CLAIMED',
                    action_exchange_invoked = NULL,
                    diagnostic_code = %s,
                    actor_id = %s,
                    roles_json = %s::jsonb,
                    correlation_id = %s,
                    audit_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    claim_id,
                    mode,
                    client_order_id,
                    "operator_futures_position_action_claimed",
                    context.actor_id,
                    json.dumps(list(context.roles)),
                    context.correlation_id,
                    context.audit_id,
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            self._insert_command(
                cursor,
                action="EXECUTE",
                context=context,
                request_sha256=request_sha256,
                result_revision=revision,
            )
            record = self._record(self._select(cursor, for_update=False))
            return (
                record,
                FuturesPositionExecutionPlan(
                    claim_id=claim_id,
                    client_order_id=client_order_id,
                    mode=mode,
                    product_id=selection["product_id"],
                    position_key=selection["position_key"],
                    action_size=action_size,
                    expected_contracts=selection["current_contracts"],
                    close_side=selection["close_side"],
                    portfolio_id_sha256=_exact_sha256(
                        row.get("portfolio_id_sha256"),
                        code=(
                            "operator_futures_position_portfolio_hash_invalid"
                        ),
                    ),
                ),
            )

    def _claim_row(
        self,
        cursor: Any,
        *,
        claim_id: str,
        step: str,
    ) -> dict[str, Any]:
        row = self._select(cursor, for_update=True)
        try:
            exact_claim_id = str(uuid.UUID(str(claim_id)))
        except (ValueError, TypeError, AttributeError):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_claim_invalid"
            ) from None
        if str(row.get("execution_claim_id") or "") != exact_claim_id:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_claim_invalid"
            )
        outcome_column, _invoked_column = _STEP_COLUMNS[step]
        if row.get(outcome_column) != "CLAIMED":
            raise FuturesPositionLifecycleError(
                f"operator_futures_position_{step}_not_claimed"
            )
        return row

    def _mark_invoked(self, *, claim_id: str, step: str) -> None:
        self.ensure_schema()
        outcome_column, invoked_column = _STEP_COLUMNS[step]
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(
                cursor,
                claim_id=claim_id,
                step=step,
            )
            if row.get(invoked_column) is True:
                raise FuturesPositionLifecycleError(
                    f"operator_futures_position_{step}_already_invoked"
                )
            if step == "cancel":
                try:
                    seal_futures_cancel_invocation(
                        cursor,
                        schema=self.schema,
                        owner_ledger=FUTURES_POSITION_GOAL_ID,
                        claim_id=str(claim_id),
                        portfolio_id_sha256=str(
                            row.get("bound_portfolio_id_sha256") or ""
                        ),
                        client_order_id=str(
                            row.get("client_order_id") or ""
                        ),
                        exchange_order_id_sha256=str(
                            row.get("exchange_order_id_sha256") or ""
                        ),
                    )
                except ValueError as exc:
                    code = str(exc)
                    if code not in {
                        (
                            "operator_futures_cancel_invocation_"
                            "binding_invalid"
                        ),
                        (
                            "operator_futures_cancel_invocation_"
                            "already_sealed"
                        ),
                    }:
                        code = (
                            "operator_futures_cancel_invocation_"
                            "binding_invalid"
                        )
                    raise FuturesPositionLifecycleError(code) from None
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET {invoked_column} = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                  AND {outcome_column} = 'CLAIMED'
                """,
                (FUTURES_POSITION_GOAL_ID,),
            )

    def mark_action_exchange_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(claim_id=claim_id, step="action")

    def mark_order_reconciliation_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(
            claim_id=claim_id,
            step="order_reconciliation",
        )

    def mark_position_reconciliation_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(
            claim_id=claim_id,
            step="position_reconciliation",
        )

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(claim_id=claim_id, step="cancel")

    @staticmethod
    def _execution_values(execution: Any) -> tuple[str, str]:
        outcome = _outcome(getattr(execution, "outcome", None))
        if outcome in {
            AdminFuturesPositionCallOutcome.NOT_RUN,
            AdminFuturesPositionCallOutcome.CLAIMED,
        }:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_execution_outcome_invalid"
            )
        diagnostic = str(
            getattr(execution, "diagnostic_code", "") or ""
        )
        if (
            not diagnostic
            or len(diagnostic) > 128
            or not diagnostic.startswith("operator_futures_position_")
        ):
            raise FuturesPositionLifecycleError(
                "operator_futures_position_execution_diagnostic_invalid"
            )
        return outcome.value, diagnostic

    def finish_action(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, diagnostic = self._execution_values(execution)
        if outcome == "ACCEPTED":
            raise FuturesPositionLifecycleError(
                "operator_futures_position_accepted_action_requires_reconciliation"
            )
        return self._finish_simple(
            claim_id=claim_id,
            step="action",
            outcome=outcome,
            diagnostic=diagnostic,
            assignments={},
        )

    def finish_action_and_claim_order_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, diagnostic = self._execution_values(execution)
        exchange_hash = _exact_sha256(
            getattr(execution, "exchange_order_id_sha256", None),
            code="operator_futures_position_exchange_order_hash_invalid",
        )
        if outcome != "ACCEPTED":
            raise FuturesPositionLifecycleError(
                "operator_futures_position_action_not_accepted"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(cursor, claim_id=claim_id, step="action")
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    action_outcome = 'ACCEPTED',
                    exchange_order_id_sha256 = %s,
                    order_reconciliation_outcome = 'CLAIMED',
                    order_reconciliation_exchange_invoked = NULL,
                    diagnostic_code = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    exchange_hash,
                    "operator_futures_position_order_reconciliation_claimed",
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            return self._record(self._select(cursor, for_update=False))

    def finish_order_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, diagnostic = self._execution_values(execution)
        if outcome == "ACCEPTED":
            raise FuturesPositionLifecycleError(
                "operator_futures_position_accepted_order_requires_position_read"
            )
        return self._finish_simple(
            claim_id=claim_id,
            step="order_reconciliation",
            outcome=outcome,
            diagnostic=diagnostic,
            assignments={
                "order_status": getattr(execution, "order_status", None),
                "authoritatively_nonterminal": bool(
                    getattr(
                        execution,
                        "authoritatively_nonterminal",
                        False,
                    )
                ),
            },
        )

    def finish_order_and_claim_position_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, _diagnostic = self._execution_values(execution)
        status = str(getattr(execution, "order_status", "") or "").upper()
        nonterminal = bool(
            getattr(execution, "authoritatively_nonterminal", False)
        )
        if outcome != "ACCEPTED" or not status:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_order_reconciliation_invalid"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(
                cursor,
                claim_id=claim_id,
                step="order_reconciliation",
            )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    order_reconciliation_outcome = 'ACCEPTED',
                    order_status = %s,
                    authoritatively_nonterminal = %s,
                    position_reconciliation_outcome = 'CLAIMED',
                    position_reconciliation_exchange_invoked = NULL,
                    diagnostic_code = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    status,
                    nonterminal,
                    "operator_futures_position_position_reconciliation_claimed",
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            return self._record(self._select(cursor, for_update=False))

    def finish_position_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, diagnostic = self._execution_values(execution)
        return self._finish_simple(
            claim_id=claim_id,
            step="position_reconciliation",
            outcome=outcome,
            diagnostic=diagnostic,
            assignments={
                "remaining_contracts": getattr(
                    execution,
                    "remaining_contracts",
                    None,
                )
            },
        )

    def finish_position_and_claim_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, _diagnostic = self._execution_values(execution)
        remaining = getattr(execution, "remaining_contracts", None)
        if outcome != "ACCEPTED" or remaining is None:
            raise FuturesPositionLifecycleError(
                "operator_futures_position_position_reconciliation_invalid"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(
                cursor,
                claim_id=claim_id,
                step="position_reconciliation",
            )
            if row.get("authoritatively_nonterminal") is not True:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_cancel_not_authorized"
                )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET revision = %s,
                    position_reconciliation_outcome = 'ACCEPTED',
                    remaining_contracts = %s,
                    cancel_outcome = 'CLAIMED',
                    cancel_exchange_invoked = FALSE,
                    diagnostic_code = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    revision,
                    str(remaining),
                    "operator_futures_position_cancel_claimed",
                    FUTURES_POSITION_GOAL_ID,
                ),
            )
            return self._record(self._select(cursor, for_update=False))

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesPositionGoalRecord:
        outcome, diagnostic = self._execution_values(execution)
        return self._finish_simple(
            claim_id=claim_id,
            step="cancel",
            outcome=outcome,
            diagnostic=diagnostic,
            assignments={},
        )

    def release_cancel_invocation_conflict(
        self,
        *,
        claim_id: str,
    ) -> FuturesPositionGoalRecord:
        """Release a local Cancel claim lost to the shared invocation seal."""

        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(
                cursor,
                claim_id=claim_id,
                step="cancel",
            )
            if row.get("cancel_exchange_invoked") is not False:
                raise FuturesPositionLifecycleError(
                    "operator_futures_position_cancel_release_not_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                   SET cancel_outcome = 'NOT_RUN',
                       cancel_exchange_invoked = NULL,
                       diagnostic_code =
                           'operator_futures_cancel_invocation_already_sealed',
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                """,
                (FUTURES_POSITION_GOAL_ID,),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def is_cancel_invocation_sealed(self) -> bool:
        """Return the shared exact-child Cancel boundary state."""

        self.ensure_schema()
        with self._cursor() as cursor:
            row = self._select(cursor, for_update=False)
            child = str(row.get("client_order_id") or "")
            portfolio_hash = str(
                row.get("bound_portfolio_id_sha256") or ""
            )
            if not child:
                return False
            try:
                return futures_cancel_invocation_is_sealed(
                    cursor,
                    schema=self.schema,
                    portfolio_id_sha256=portfolio_hash,
                    client_order_id=child,
                )
            except ValueError:
                raise FuturesPositionLifecycleError(
                    "operator_futures_cancel_invocation_binding_invalid"
                ) from None

    def _finish_simple(
        self,
        *,
        claim_id: str,
        step: str,
        outcome: str,
        diagnostic: str,
        assignments: Mapping[str, Any],
    ) -> FuturesPositionGoalRecord:
        outcome_column, _invoked_column = _STEP_COLUMNS[step]
        allowed_assignments = {
            "order_status",
            "authoritatively_nonterminal",
            "remaining_contracts",
        }
        if not set(assignments).issubset(allowed_assignments):
            raise RuntimeError("operator_futures_position_assignment_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._claim_row(
                cursor,
                claim_id=claim_id,
                step=step,
            )
            revision = int(row["revision"]) + 1
            set_parts = [
                "revision = %s",
                f"{outcome_column} = %s",
                "diagnostic_code = %s",
            ]
            params: list[Any] = [revision, outcome, diagnostic]
            for column, value in assignments.items():
                set_parts.append(f"{column} = %s")
                params.append(value)
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            params.append(FUTURES_POSITION_GOAL_ID)
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_position_goal')}
                SET {", ".join(set_parts)}
                WHERE goal_id = %s
                """,
                tuple(params),
            )
            return self._record(self._select(cursor, for_update=False))


_DEFAULT_REPOSITORY: OperatorFuturesPositionLifecycleRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_operator_futures_position_lifecycle_repository(
) -> OperatorFuturesPositionLifecycleRepository:
    """Return the installed PostgreSQL Goal 11 authority."""

    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                import os

                from database import order as order_db

                portfolio_id = str(
                    os.environ.get(
                        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
                    )
                    or ""
                ).strip()
                _DEFAULT_REPOSITORY = (
                    OperatorFuturesPositionLifecycleRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=(portfolio_id or None),
                    )
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def initialize_operator_futures_position_lifecycle_schema() -> None:
    get_default_operator_futures_position_lifecycle_repository().ensure_schema()


__all__ = [
    "OperatorFuturesPositionLifecycleRepository",
    "get_default_operator_futures_position_lifecycle_repository",
    "initialize_operator_futures_position_lifecycle_schema",
]
