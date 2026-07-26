"""PostgreSQL authority for the bounded Goal 10 Futures lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FUTURES_MANUAL_ACTIVE_GOAL_ID,
    FUTURES_MANUAL_GOAL_ID,
    FUTURES_MANUAL_MARGIN_SUBREADS,
    FuturesManualEligibilityResult,
    FuturesManualExecutionPlan,
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
    FuturesManualRequestContext,
    FuturesHotpointExternalCommandClaim,
    FuturesHotpointExternalCommandReadback,
    classify_futures_manual_candidate_freshness,
    is_futures_manual_goal_terminal,
)
from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_GOAL_ID,
)
from application.admin_api.operator_futures_fill_triggered_follow_up import (
    FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
)
from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_GOAL_ID,
)
from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)
from database.operator_futures_cancel_invocation_seal import (
    ensure_futures_cancel_invocation_seal,
    futures_cancel_invocation_is_sealed,
    seal_futures_cancel_invocation,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ELIGIBILITY_CYCLES = 10
_EMPTY_CATEGORY_ATTEMPTS = {
    category: 0
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
}
_EMPTY_CATEGORY_ATTEMPTS_JSON = json.dumps(
    _EMPTY_CATEGORY_ATTEMPTS,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
)
_EMPTY_MARGIN_SUBREAD_ATTEMPTS = {
    subread: 0 for subread in FUTURES_MANUAL_MARGIN_SUBREADS
}
_EMPTY_MARGIN_SUBREAD_ATTEMPTS_JSON = json.dumps(
    _EMPTY_MARGIN_SUBREAD_ATTEMPTS,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
)
_CALL_COLUMNS = {
    "preview": ("preview_outcome", "preview_exchange_invoked"),
    "create": ("create_outcome", "create_exchange_invoked"),
    "reconciliation": (
        "reconciliation_outcome",
        "reconciliation_exchange_invoked",
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


def _command_confirmations(
    context: FuturesManualRequestContext,
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
        "authorize_preview_create_and_safe_closeout": (
            context.authorize_preview_create_and_safe_closeout
        ),
        "acknowledge_unknown_outcome_consumes_allowance": (
            context.acknowledge_unknown_outcome_consumes_allowance
        ),
        "acknowledge_create_requires_accepted_identical_preview": (
            context.acknowledge_create_requires_accepted_identical_preview
        ),
        "acknowledge_cancel_is_only_for_exact_nonterminal_child": (
            context.acknowledge_cancel_is_only_for_exact_nonterminal_child
        ),
    }


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
        raise ValueError("operator_futures_manual_stored_json_invalid")
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


def _json_result_default(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = _iso(value)
        if normalized is not None:
            return normalized
    return str(value)


def _exact_sha256(value: Any, *, code: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise FuturesManualLifecycleError(code)
    return normalized


class OperatorFuturesManualLifecycleRepository:
    """Serialize one Goal 10 ledger and every single-use call claim."""

    def __init__(
        self,
        db: Any,
        *,
        configured_portfolio_id: str | None = None,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
        goal_id: str = FUTURES_MANUAL_GOAL_ID,
        eligibility_evidence_validator: (
            Callable[[FuturesManualEligibilityResult], None] | None
        ) = None,
        claim_validator: (
            Callable[..., None] | None
        ) = None,
        preview_invocation_validator: (
            Callable[..., None] | None
        ) = None,
        create_invocation_validator: (
            Callable[..., None] | None
        ) = None,
        client_order_id_prefix: str = "operator-futures-manual-",
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("operator_futures_manual_schema_invalid")
        self.db = db
        self.schema = str(schema)
        if goal_id not in {
            FUTURES_MANUAL_GOAL_ID,
            FUTURES_MANUAL_ACTIVE_GOAL_ID,
            FUTURES_PRODUCT_TICKET_GOAL_ID,
            FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            FUTURES_HOTPOINT_GOAL_ID,
        }:
            raise ValueError("operator_futures_manual_goal_id_invalid")
        if (
            not isinstance(client_order_id_prefix, str)
            or not client_order_id_prefix.endswith("-")
            or not 1 <= len(client_order_id_prefix) <= 80
            or re.fullmatch(
                r"[a-z0-9-]+",
                client_order_id_prefix,
            )
            is None
        ):
            raise ValueError(
                "operator_futures_manual_client_order_prefix_invalid"
            )
        self.goal_id = goal_id
        if (
            self.goal_id == FUTURES_HOTPOINT_GOAL_ID
            and eligibility_evidence_validator is None
        ):
            raise ValueError(
                "operator_futures_hotpoint_eligibility_validator_required"
            )
        if (
            self.goal_id == FUTURES_HOTPOINT_GOAL_ID
            and claim_validator is None
        ):
            raise ValueError(
                "operator_futures_hotpoint_claim_validator_required"
            )
        if (
            self.goal_id == FUTURES_HOTPOINT_GOAL_ID
            and preview_invocation_validator is None
        ):
            raise ValueError(
                "operator_futures_hotpoint_preview_invocation_"
                "validator_required"
            )
        if (
            self.goal_id == FUTURES_HOTPOINT_GOAL_ID
            and create_invocation_validator is None
        ):
            raise ValueError(
                "operator_futures_hotpoint_create_invocation_"
                "validator_required"
            )
        self.eligibility_evidence_validator = (
            eligibility_evidence_validator
        )
        self.claim_validator = claim_validator
        self.preview_invocation_validator = (
            preview_invocation_validator
        )
        self.create_invocation_validator = (
            create_invocation_validator
        )
        self.client_order_id_prefix = client_order_id_prefix
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

    def _require_fresh_candidate(self, candidate: Mapping[str, Any]) -> None:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise FuturesManualLifecycleError(
                "operator_futures_manual_runtime_clock_invalid"
            )
        diagnostic = classify_futures_manual_candidate_freshness(
            candidate,
            now=now,
        )
        if diagnostic != "operator_futures_manual_candidate_fresh":
            raise FuturesManualLifecycleError(diagnostic)

    @contextmanager
    def _cursor(self):
        with self.db.get_cursor() as cursor:
            yield cursor

    @staticmethod
    def _lock(cursor: Any) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(34994, 10)")

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
                        {self._table('operator_futures_manual_goal')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        revision INTEGER NOT NULL DEFAULT 0
                            CHECK (revision >= 0),
                        cycles_used INTEGER NOT NULL DEFAULT 0
                            CHECK (cycles_used BETWEEN 0 AND 10),
                        active_cycle_number INTEGER,
                        eligibility_outcome VARCHAR(16)
                            CHECK (
                                eligibility_outcome IS NULL OR
                                eligibility_outcome IN (
                                    'ELIGIBLE', 'INELIGIBLE', 'UNKNOWN'
                                )
                            ),
                        eligibility_diagnostic_code VARCHAR(128) NOT NULL,
                        category_attempts_json JSONB NOT NULL DEFAULT '{{}}',
                        margin_subread_attempts_json JSONB NOT NULL
                            DEFAULT '{{}}',
                        candidate_json JSONB,
                        candidate_sha256 CHAR(64),
                        portfolio_id_sha256 CHAR(64),
                        bound_portfolio_id_sha256 CHAR(64),
                        eligibility_evidence_sha256 CHAR(64),
                        execution_claim_id UUID UNIQUE,
                        client_order_id VARCHAR(128) UNIQUE,
                        preview_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (preview_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        preview_exchange_invoked BOOLEAN,
                        preview_id_sha256 CHAR(64),
                        create_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (create_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        create_exchange_invoked BOOLEAN,
                        exchange_order_id_sha256 CHAR(64),
                        reconciliation_outcome VARCHAR(16)
                            NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (reconciliation_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        reconciliation_exchange_invoked BOOLEAN,
                        reconciliation_catalog_end_at TIMESTAMPTZ,
                        order_status VARCHAR(32),
                        authoritatively_nonterminal BOOLEAN,
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
                            (active_cycle_number IS NULL) OR
                            (active_cycle_number BETWEEN 1 AND 10)
                        ),
                        CHECK (
                            (candidate_json IS NULL
                             AND candidate_sha256 IS NULL)
                            OR
                            (candidate_json IS NOT NULL
                             AND candidate_sha256 IS NOT NULL)
                        ),
                        CHECK (
                            (execution_claim_id IS NULL
                             AND client_order_id IS NULL)
                            OR
                            (execution_claim_id IS NOT NULL
                             AND client_order_id IS NOT NULL)
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_hotpoint_v2_external_command'
                        )} (
                        command_id UUID PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        action VARCHAR(16) NOT NULL
                            CHECK (action IN ('RUN_ONCE', 'SAFE_CLOSEOUT')),
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        request_sha256 CHAR(64) NOT NULL,
                        request_revision BIGINT NOT NULL
                            CHECK (request_revision >= 0),
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table(
                                'operator_futures_manual_goal'
                            )}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_hotpoint_v2_external_'
                            'command_result'
                        )} (
                        command_id UUID PRIMARY KEY,
                        outcome VARCHAR(16) NOT NULL
                            CHECK (outcome IN (
                                'SUCCESS', 'FAILED', 'UNKNOWN'
                            )),
                        result_snapshot_json JSONB,
                        error_code VARCHAR(128),
                        http_status_code INTEGER,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (command_id) REFERENCES
                            {self._table(
                                'operator_futures_hotpoint_v2_external_'
                                'command'
                            )}(command_id),
                        CHECK (
                            (
                                outcome = 'SUCCESS'
                                AND result_snapshot_json IS NOT NULL
                                AND error_code IS NULL
                                AND http_status_code IS NULL
                            )
                            OR
                            (
                                outcome IN ('FAILED', 'UNKNOWN')
                                AND result_snapshot_json IS NULL
                                AND error_code IS NOT NULL
                                AND http_status_code BETWEEN 400 AND 599
                            )
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table(
                            'operator_futures_hotpoint_v2_external_command'
                        )}
                    ADD COLUMN IF NOT EXISTS request_revision BIGINT
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_manual_goal')}
                    ADD COLUMN IF NOT EXISTS
                        bound_portfolio_id_sha256 CHAR(64)
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_manual_goal')}
                    ADD COLUMN IF NOT EXISTS
                        reconciliation_catalog_end_at TIMESTAMPTZ
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_manual_goal')}
                    ADD COLUMN IF NOT EXISTS
                        margin_subread_attempts_json JSONB NOT NULL
                            DEFAULT '{{}}'
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_manual_cycle_category')} (
                        goal_id VARCHAR(128) NOT NULL,
                        cycle_number INTEGER NOT NULL
                            CHECK (cycle_number BETWEEN 1 AND 10),
                        category VARCHAR(64) NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (goal_id, cycle_number, category),
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table('operator_futures_manual_goal')}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_manual_cycle_margin_subread'
                        )} (
                        goal_id VARCHAR(128) NOT NULL,
                        cycle_number INTEGER NOT NULL
                            CHECK (cycle_number BETWEEN 1 AND 10),
                        subread VARCHAR(64) NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (goal_id, cycle_number, subread),
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table(
                                'operator_futures_manual_goal'
                            )}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_manual_command')} (
                        command_id UUID PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        action VARCHAR(16) NOT NULL
                            CHECK (action IN ('REFRESH', 'EXECUTE')),
                        expected_revision INTEGER NOT NULL,
                        result_revision INTEGER NOT NULL,
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        confirmations_json JSONB NOT NULL DEFAULT '{{}}',
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table('operator_futures_manual_goal')}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_manual_command')}
                    ADD COLUMN IF NOT EXISTS
                        confirmations_json JSONB NOT NULL DEFAULT '{{}}'
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_manual_command')}
                    ADD COLUMN IF NOT EXISTS request_sha256 CHAR(64)
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table(
                            'operator_futures_manual_command_result'
                        )} (
                        command_id UUID PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        action VARCHAR(16) NOT NULL
                            CHECK (action IN ('REFRESH', 'EXECUTE')),
                        result_revision INTEGER NOT NULL,
                        result_json JSONB NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (command_id) REFERENCES
                            {self._table(
                                'operator_futures_manual_command'
                            )}(command_id),
                        FOREIGN KEY (goal_id) REFERENCES
                            {self._table(
                                'operator_futures_manual_goal'
                            )}(goal_id)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        {self._table('guard_operator_futures_manual_append_only')}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = '55000',
                            MESSAGE =
                                'operator_futures_manual_evidence_append_only';
                    END;
                    $$
                    """
                )
                for table, trigger in (
                    (
                        "operator_futures_manual_cycle_category",
                        "operator_futures_manual_cycle_category_append_only",
                    ),
                    (
                        "operator_futures_manual_cycle_margin_subread",
                        (
                            "operator_futures_manual_cycle_margin_"
                            "subread_append_only"
                        ),
                    ),
                    (
                        "operator_futures_manual_command",
                        "operator_futures_manual_command_append_only",
                    ),
                    (
                        "operator_futures_manual_command_result",
                        "operator_futures_manual_command_result_append_only",
                    ),
                    (
                        "operator_futures_hotpoint_v2_external_command",
                        (
                            "operator_futures_hotpoint_v2_external_"
                            "command_append_only"
                        ),
                    ),
                    (
                        (
                            "operator_futures_hotpoint_v2_external_"
                            "command_result"
                        ),
                        (
                            "operator_futures_hotpoint_v2_external_"
                            "command_result_append_only"
                        ),
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
                                'guard_operator_futures_manual_append_only'
                            )}()
                        """
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_futures_manual_goal')} (
                        goal_id,
                        eligibility_diagnostic_code,
                        diagnostic_code,
                        category_attempts_json,
                        margin_subread_attempts_json
                    ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (goal_id) DO NOTHING
                    """,
                    (
                        self.goal_id,
                        "operator_futures_manual_not_refreshed",
                        "operator_futures_manual_not_refreshed",
                        _EMPTY_CATEGORY_ATTEMPTS_JSON,
                        _EMPTY_MARGIN_SUBREAD_ATTEMPTS_JSON,
                    ),
                )
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_manual_goal')}
                    SET category_attempts_json = %s::jsonb
                        , margin_subread_attempts_json = %s::jsonb
                    WHERE goal_id = %s
                      AND cycles_used = 0
                      AND active_cycle_number IS NULL
                      AND eligibility_outcome IS NULL
                      AND candidate_json IS NULL
                      AND preview_outcome = 'NOT_RUN'
                      AND create_outcome = 'NOT_RUN'
                      AND reconciliation_outcome = 'NOT_RUN'
                      AND cancel_outcome = 'NOT_RUN'
                      AND category_attempts_json = '{{}}'::jsonb
                      AND margin_subread_attempts_json = '{{}}'::jsonb
                    """,
                    (
                        _EMPTY_CATEGORY_ATTEMPTS_JSON,
                        _EMPTY_MARGIN_SUBREAD_ATTEMPTS_JSON,
                        self.goal_id,
                    ),
                )
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_manual_goal')}
                       SET margin_subread_attempts_json = %s::jsonb
                     WHERE goal_id = %s
                       AND cycles_used = 0
                       AND active_cycle_number IS NULL
                       AND eligibility_outcome IS NULL
                       AND candidate_json IS NULL
                       AND preview_outcome = 'NOT_RUN'
                       AND create_outcome = 'NOT_RUN'
                       AND reconciliation_outcome = 'NOT_RUN'
                       AND cancel_outcome = 'NOT_RUN'
                       AND margin_subread_attempts_json = '{{}}'::jsonb
                    """,
                    (
                        _EMPTY_MARGIN_SUBREAD_ATTEMPTS_JSON,
                        self.goal_id,
                    ),
                )
                if self.configured_portfolio_id_sha256 is not None:
                    cursor.execute(
                        f"""
                        UPDATE {self._table('operator_futures_manual_goal')}
                        SET bound_portfolio_id_sha256 =
                            COALESCE(bound_portfolio_id_sha256, %s)
                        WHERE goal_id = %s
                        RETURNING bound_portfolio_id_sha256
                        """,
                        (
                            self.configured_portfolio_id_sha256,
                            self.goal_id,
                        ),
                    )
                    bound = _row(cursor)
                    if (
                        bound is None
                        or str(bound["bound_portfolio_id_sha256"])
                        != self.configured_portfolio_id_sha256
                    ):
                        raise RuntimeError(
                            "operator_futures_manual_portfolio_binding_invalid"
                        )
                self._recover_inflight(cursor)
            self._schema_ready = True

    def _recover_inflight(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            SELECT * FROM {self._table('operator_futures_manual_goal')}
            WHERE goal_id = %s
            FOR UPDATE
            """,
            (self.goal_id,),
        )
        row = _row(cursor)
        if row is None:
            raise RuntimeError("operator_futures_manual_goal_missing")
        updates: list[str] = []
        params: list[Any] = []
        diagnostic = None
        if row.get("active_cycle_number") is not None:
            updates.extend(
                [
                    "active_cycle_number = NULL",
                    "eligibility_outcome = 'UNKNOWN'",
                    "eligibility_diagnostic_code = %s",
                ]
            )
            params.append(
                "operator_futures_manual_restart_eligibility_unknown"
            )
            diagnostic = (
                "operator_futures_manual_restart_eligibility_unknown"
            )
        for step, (outcome_column, _invoked_column) in _CALL_COLUMNS.items():
            if row.get(outcome_column) == "CLAIMED":
                updates.append(f"{outcome_column} = 'UNKNOWN'")
                diagnostic = (
                    f"operator_futures_manual_restart_{step}_unknown"
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
        params.extend([diagnostic, self.goal_id])
        cursor.execute(
            f"""
            UPDATE {self._table('operator_futures_manual_goal')}
            SET {", ".join(updates)}
            WHERE goal_id = %s
            """,
            tuple(params),
        )

    @staticmethod
    def _record(value: Mapping[str, Any]) -> FuturesManualGoalRecord:
        candidate_value = value.get("candidate_json")
        candidate = (
            {
                str(key): str(item)
                for key, item in _json_object(candidate_value).items()
            }
            if candidate_value is not None
            else None
        )
        eligibility_raw = value.get("eligibility_outcome")
        return FuturesManualGoalRecord(
            goal_id=str(value["goal_id"]),
            revision=int(value["revision"]),
            cycles_used=int(value["cycles_used"]),
            active_cycle_number=(
                int(value["active_cycle_number"])
                if value.get("active_cycle_number") is not None
                else None
            ),
            eligibility_outcome=(
                AdminFuturesManualEligibilityOutcome(str(eligibility_raw))
                if eligibility_raw is not None
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
            margin_subread_attempts={
                str(key): int(item)
                for key, item in _json_object(
                    value.get("margin_subread_attempts_json")
                ).items()
            },
            candidate=candidate,
            candidate_sha256=(
                str(value["candidate_sha256"])
                if value.get("candidate_sha256")
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
            client_order_id=(
                str(value["client_order_id"])
                if value.get("client_order_id")
                else None
            ),
            preview_outcome=AdminFuturesManualCallOutcome(
                str(value["preview_outcome"])
            ),
            preview_exchange_invoked=value.get(
                "preview_exchange_invoked"
            ),
            preview_id_sha256=(
                str(value["preview_id_sha256"])
                if value.get("preview_id_sha256")
                else None
            ),
            create_outcome=AdminFuturesManualCallOutcome(
                str(value["create_outcome"])
            ),
            create_exchange_invoked=value.get("create_exchange_invoked"),
            exchange_order_id_sha256=(
                str(value["exchange_order_id_sha256"])
                if value.get("exchange_order_id_sha256")
                else None
            ),
            reconciliation_outcome=AdminFuturesManualCallOutcome(
                str(value["reconciliation_outcome"])
            ),
            reconciliation_exchange_invoked=value.get(
                "reconciliation_exchange_invoked"
            ),
            order_status=(
                str(value["order_status"])
                if value.get("order_status")
                else None
            ),
            authoritatively_nonterminal=value.get(
                "authoritatively_nonterminal"
            ),
            cancel_outcome=AdminFuturesManualCallOutcome(
                str(value["cancel_outcome"])
            ),
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
            reconciliation_catalog_end_at=_iso(
                value.get("reconciliation_catalog_end_at")
            ),
            execution_claim_id=(
                str(value["execution_claim_id"])
                if value.get("execution_claim_id")
                else None
            ),
        )

    def _select(self, cursor: Any, *, for_update: bool) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT * FROM {self._table('operator_futures_manual_goal')}
            WHERE goal_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (self.goal_id,),
        )
        value = _row(cursor)
        if value is None:
            raise RuntimeError("operator_futures_manual_goal_missing")
        return value

    def read(self) -> FuturesManualGoalRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            return self._record(self._select(cursor, for_update=False))

    def claim_hotpoint_external_command(
        self,
        *,
        action: str,
        context: FuturesManualRequestContext,
        request_payload: Mapping[str, Any],
    ) -> FuturesHotpointExternalCommandClaim:
        """Persist a complete Goal13 RUN/SAFE digest before side effects."""

        if (
            self.goal_id != FUTURES_HOTPOINT_GOAL_ID
            or action not in {"RUN_ONCE", "SAFE_CLOSEOUT"}
            or not isinstance(request_payload, Mapping)
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_external_command_invalid",
                http_status_code=422,
            )
        self.ensure_schema()
        self._validate_context(context)
        try:
            normalized_audit = str(uuid.UUID(str(context.audit_id)))
            encoded_payload = json.loads(
                json.dumps(
                    dict(request_payload),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            )
        except (TypeError, ValueError, AttributeError):
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_external_command_invalid",
                http_status_code=422,
            ) from None
        request_hash = _canonical_sha256(
            {
                "goal_id": self.goal_id,
                "action": action,
                "request": encoded_payload,
                "actor_id": context.actor_id,
                "roles": sorted(
                    str(role).strip().lower()
                    for role in context.roles
                ),
                "correlation_id": context.correlation_id,
                "audit_id": normalized_audit,
            }
        )
        key_hash = _sha256_text(
            f"{self.goal_id}:{context.idempotency_key}"
        )
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT command_id, action, request_sha256
                  FROM {self._table(
                      'operator_futures_hotpoint_v2_external_command'
                  )}
                 WHERE goal_id = %s
                   AND idempotency_key_sha256 = %s
                """,
                (self.goal_id, key_hash),
            )
            existing = _row(cursor)
            if existing is not None:
                if (
                    existing.get("action") != action
                    or existing.get("request_sha256") != request_hash
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_hotpoint_idempotency_conflict"
                    )
                command_id = str(existing["command_id"])
                cursor.execute(
                    f"""
                    SELECT outcome, result_snapshot_json,
                           error_code, http_status_code
                      FROM {self._table(
                          'operator_futures_hotpoint_v2_external_'
                          'command_result'
                      )}
                     WHERE command_id = %s
                    """,
                    (command_id,),
                )
                result = _row(cursor)
                if result is None:
                    return FuturesHotpointExternalCommandClaim(
                        command_id=command_id,
                        status="IN_PROGRESS",
                    )
                return FuturesHotpointExternalCommandClaim(
                    command_id=command_id,
                    status=str(result["outcome"]),
                    result_snapshot=(
                        _json_object(result["result_snapshot_json"])
                        if result.get("result_snapshot_json") is not None
                        else None
                    ),
                    error_code=(
                        str(result["error_code"])
                        if result.get("error_code")
                        else None
                    ),
                    http_status_code=(
                        int(result["http_status_code"])
                        if result.get("http_status_code") is not None
                        else None
                    ),
                )
            command_id = str(uuid.uuid4())
            cursor.execute(
                f"""
                INSERT INTO {self._table(
                    'operator_futures_hotpoint_v2_external_command'
                )} (
                    command_id, goal_id, action,
                    idempotency_key_sha256, request_sha256,
                    request_revision,
                    actor_id, roles_json, correlation_id, audit_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s, %s
                )
                """,
                (
                    command_id,
                    self.goal_id,
                    action,
                    key_hash,
                    request_hash,
                    context.expected_revision,
                    context.actor_id,
                    json.dumps(
                        sorted(
                            str(role).strip().lower()
                            for role in context.roles
                        ),
                        separators=(",", ":"),
                    ),
                    context.correlation_id,
                    normalized_audit,
                ),
            )
            return FuturesHotpointExternalCommandClaim(
                command_id=command_id,
                status="NEW",
            )

    def finish_hotpoint_external_command(
        self,
        *,
        command_id: str,
        outcome: str,
        result_snapshot: Mapping[str, Any] | None,
        error_code: str | None,
        http_status_code: int | None,
    ) -> None:
        """Append one sanitized terminal result for an external command."""

        if self.goal_id != FUTURES_HOTPOINT_GOAL_ID:
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_external_command_invalid"
            )
        try:
            normalized_command_id = str(uuid.UUID(str(command_id)))
        except (TypeError, ValueError, AttributeError):
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_external_command_invalid"
            ) from None
        if outcome == "SUCCESS":
            if (
                not isinstance(result_snapshot, Mapping)
                or error_code is not None
                or http_status_code is not None
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_external_result_invalid"
                )
            try:
                snapshot_json = json.dumps(
                    dict(result_snapshot),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            except (TypeError, ValueError):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_external_result_invalid"
                ) from None
            exact_error = None
            exact_status = None
        elif outcome in {"FAILED", "UNKNOWN"}:
            exact_error = str(error_code or "").strip()
            exact_status = http_status_code
            snapshot_json = None
            if (
                result_snapshot is not None
                or not exact_error
                or len(exact_error) > 128
                or re.fullmatch(
                    r"operator_futures_hotpoint_[a-z0-9_]+",
                    exact_error,
                )
                is None
                or type(exact_status) is not int
                or not 400 <= exact_status <= 599
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_external_result_invalid"
                )
        else:
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_external_result_invalid"
            )
        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT goal_id FROM {self._table(
                    'operator_futures_hotpoint_v2_external_command'
                )}
                WHERE command_id = %s
                """,
                (normalized_command_id,),
            )
            command = _row(cursor)
            if (
                command is None
                or command.get("goal_id") != self.goal_id
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_external_command_invalid"
                )
            cursor.execute(
                f"""
                SELECT outcome, result_snapshot_json,
                       error_code, http_status_code
                  FROM {self._table(
                      'operator_futures_hotpoint_v2_external_'
                      'command_result'
                  )}
                 WHERE command_id = %s
                """,
                (normalized_command_id,),
            )
            existing = _row(cursor)
            expected = {
                "outcome": outcome,
                "result_snapshot_json": (
                    json.loads(snapshot_json)
                    if snapshot_json is not None
                    else None
                ),
                "error_code": exact_error,
                "http_status_code": exact_status,
            }
            if existing is not None:
                actual = {
                    "outcome": existing.get("outcome"),
                    "result_snapshot_json": (
                        _json_object(existing["result_snapshot_json"])
                        if existing.get("result_snapshot_json") is not None
                        else None
                    ),
                    "error_code": existing.get("error_code"),
                    "http_status_code": existing.get("http_status_code"),
                }
                if actual != expected:
                    raise FuturesManualLifecycleError(
                        "operator_futures_hotpoint_external_result_conflict"
                    )
                return
            cursor.execute(
                f"""
                INSERT INTO {self._table(
                    'operator_futures_hotpoint_v2_external_command_result'
                )} (
                    command_id, outcome, result_snapshot_json,
                    error_code, http_status_code
                ) VALUES (%s, %s, %s::jsonb, %s, %s)
                """,
                (
                    normalized_command_id,
                    outcome,
                    snapshot_json,
                    exact_error,
                    exact_status,
                ),
            )

    def recover_hotpoint_external_commands(self) -> None:
        """Terminalize crash-stranded external commands as fixed UNKNOWN."""

        if self.goal_id != FUTURES_HOTPOINT_GOAL_ID:
            return
        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                INSERT INTO {self._table(
                    'operator_futures_hotpoint_v2_external_command_result'
                )} (
                    command_id, outcome, result_snapshot_json,
                    error_code, http_status_code
                )
                SELECT command.command_id, 'UNKNOWN', NULL,
                       'operator_futures_hotpoint_command_outcome_unknown',
                       503
                  FROM {self._table(
                      'operator_futures_hotpoint_v2_external_command'
                  )} AS command
                  LEFT JOIN {self._table(
                      'operator_futures_hotpoint_v2_external_command_result'
                  )} AS result
                    ON result.command_id = command.command_id
                 WHERE command.goal_id = %s
                   AND result.command_id IS NULL
                ON CONFLICT (command_id) DO NOTHING
                """,
                (self.goal_id,),
            )

    def read_latest_hotpoint_external_command(
        self,
    ) -> FuturesHotpointExternalCommandReadback | None:
        """Return only fixed, sanitized metadata for the newest command."""

        if self.goal_id != FUTURES_HOTPOINT_GOAL_ID:
            return None
        self.ensure_schema()
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT command.action,
                       command.correlation_id,
                       command.request_revision,
                       COALESCE(result.outcome, 'IN_PROGRESS') AS status,
                       CASE
                           WHEN result.outcome = 'SUCCESS'
                           THEN
                               'operator_futures_hotpoint_command_succeeded'
                           WHEN result.error_code IS NOT NULL
                           THEN result.error_code
                           ELSE
                               'operator_futures_hotpoint_command_in_progress'
                       END AS diagnostic_code
                  FROM {self._table(
                      'operator_futures_hotpoint_v2_external_command'
                  )} AS command
                  LEFT JOIN {self._table(
                      'operator_futures_hotpoint_v2_external_command_result'
                  )} AS result
                    ON result.command_id = command.command_id
                 WHERE command.goal_id = %s
                 ORDER BY command.recorded_at DESC, command.command_id DESC
                 LIMIT 1
                """,
                (self.goal_id,),
            )
            row = _row(cursor)
        if row is None:
            return None
        return FuturesHotpointExternalCommandReadback(
            action=str(row["action"]),
            status=str(row["status"]),
            correlation_id=str(row["correlation_id"]),
            request_revision=(
                int(row["request_revision"])
                if row.get("request_revision") is not None
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
        )

    @staticmethod
    def _validate_context(context: FuturesManualRequestContext) -> None:
        if (
            not context.actor_id.strip()
            or not context.roles
            or not context.idempotency_key.strip()
            or not context.correlation_id.strip()
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_context_invalid",
                http_status_code=422,
            )
        try:
            uuid.UUID(str(context.audit_id))
        except (TypeError, ValueError, AttributeError):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_audit_id_invalid",
                http_status_code=422,
            ) from None

    def _replayed(
        self,
        cursor: Any,
        *,
        action: str,
        context: FuturesManualRequestContext,
        current_row: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        key_hash = _sha256_text(
            f"{self.goal_id}:{context.idempotency_key}"
        )
        legacy_key_hash = _sha256_text(
            f"{action}:{context.idempotency_key}"
        )
        request_hash = self._request_sha256(
            action=action,
            context=context,
        )
        cursor.execute(
            f"""
            SELECT command_id, action, request_sha256 FROM
                {self._table('operator_futures_manual_command')}
            WHERE goal_id = %s
              AND idempotency_key_sha256 IN (%s, %s)
            ORDER BY
                CASE WHEN idempotency_key_sha256 = %s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (
                self.goal_id,
                key_hash,
                legacy_key_hash,
                key_hash,
            ),
        )
        existing = _row(cursor)
        if existing is None:
            return None
        if (
            existing.get("action") != action
            or existing.get("request_sha256") != request_hash
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_idempotency_conflict"
            )
        cursor.execute(
            f"""
            SELECT result_json
            FROM {self._table(
                'operator_futures_manual_command_result'
            )}
            WHERE command_id = %s
            """,
            (existing["command_id"],),
        )
        completed = _row(cursor)
        if completed is not None:
            return _json_object(completed["result_json"])
        return dict(current_row)

    def _request_sha256(
        self,
        *,
        action: str,
        context: FuturesManualRequestContext,
    ) -> str:
        return _canonical_sha256(
            {
                "goal_id": self.goal_id,
                "action": action,
                "actor_id": context.actor_id,
                "roles": sorted(context.roles),
                "expected_revision": context.expected_revision,
                "operator_intent": context.operator_intent,
                "confirmations": _command_confirmations(context),
                "correlation_id": context.correlation_id,
            }
        )

    def _insert_command_result(
        self,
        cursor: Any,
        *,
        action: str,
        context: FuturesManualRequestContext,
        result_row: Mapping[str, Any],
    ) -> None:
        key_hash = _sha256_text(
            f"{self.goal_id}:{context.idempotency_key}"
        )
        legacy_key_hash = _sha256_text(
            f"{action}:{context.idempotency_key}"
        )
        cursor.execute(
            f"""
            SELECT command_id, request_sha256
            FROM {self._table('operator_futures_manual_command')}
            WHERE goal_id = %s
              AND action = %s
              AND idempotency_key_sha256 IN (%s, %s)
            ORDER BY
                CASE WHEN idempotency_key_sha256 = %s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (
                self.goal_id,
                action,
                key_hash,
                legacy_key_hash,
                key_hash,
            ),
        )
        command = _row(cursor)
        if (
            command is None
            or command.get("request_sha256")
            != self._request_sha256(action=action, context=context)
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_idempotency_conflict"
            )
        cursor.execute(
            f"""
            INSERT INTO
                {self._table(
                    'operator_futures_manual_command_result'
                )} (
                    command_id,
                    goal_id,
                    action,
                    result_revision,
                    result_json
                )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (command_id) DO NOTHING
            """,
            (
                command["command_id"],
                self.goal_id,
                action,
                int(result_row["revision"]),
                json.dumps(
                    dict(result_row),
                    sort_keys=True,
                    default=_json_result_default,
                ),
            ),
        )

    def _insert_command(
        self,
        cursor: Any,
        *,
        action: str,
        context: FuturesManualRequestContext,
        result_revision: int,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self._table('operator_futures_manual_command')} (
                command_id,
                goal_id,
                action,
                expected_revision,
                result_revision,
                idempotency_key_sha256,
                actor_id,
                roles_json,
                confirmations_json,
                request_sha256,
                correlation_id,
                audit_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s::jsonb, %s, %s, %s
            )
            """,
            (
                str(uuid.uuid4()),
                self.goal_id,
                action,
                context.expected_revision,
                result_revision,
                _sha256_text(
                    f"{self.goal_id}:{context.idempotency_key}"
                ),
                context.actor_id,
                json.dumps(list(context.roles)),
                json.dumps(
                    _command_confirmations(context),
                    sort_keys=True,
                ),
                self._request_sha256(
                    action=action,
                    context=context,
                ),
                context.correlation_id,
                context.audit_id,
            ),
        )

    def begin_eligibility_cycle(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> tuple[FuturesManualGoalRecord, int | None]:
        self.ensure_schema()
        self._validate_context(context)
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            replay = self._replayed(
                cursor,
                action="REFRESH",
                context=context,
                current_row=row,
            )
            if replay is not None:
                return self._record(replay), None
            if int(row["revision"]) != context.expected_revision:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_revision_conflict"
                )
            if row.get("active_cycle_number") is not None:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_eligibility_cycle_active"
                )
            if row.get("preview_outcome") != "NOT_RUN":
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_refresh_after_attempt_forbidden"
                )
            if is_futures_manual_goal_terminal(
                str(row.get("eligibility_diagnostic_code") or "")
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_goal_terminal"
                )
            cycle_number = int(row["cycles_used"]) + 1
            if cycle_number > _MAX_ELIGIBILITY_CYCLES:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_eligibility_cycles_exhausted"
                )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET revision = %s,
                    cycles_used = %s,
                    active_cycle_number = %s,
                    eligibility_outcome = NULL,
                    eligibility_diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    margin_subread_attempts_json = %s::jsonb,
                    candidate_json = NULL,
                    candidate_sha256 = NULL,
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
                    "operator_futures_manual_eligibility_cycle_claimed",
                    _EMPTY_CATEGORY_ATTEMPTS_JSON,
                    _EMPTY_MARGIN_SUBREAD_ATTEMPTS_JSON,
                    "operator_futures_manual_eligibility_cycle_claimed",
                    context.actor_id,
                    json.dumps(list(context.roles)),
                    context.correlation_id,
                    context.audit_id,
                    self.goal_id,
                ),
            )
            self._insert_command(
                cursor,
                action="REFRESH",
                context=context,
                result_revision=revision,
            )
            return self._record(
                self._select(cursor, for_update=False)
            ), cycle_number

    def claim_eligibility_category(
        self,
        *,
        cycle_number: int,
        category: str,
    ) -> None:
        self.ensure_schema()
        if category not in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
            raise FuturesManualLifecycleError(
                "operator_futures_manual_category_not_authorized"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if row.get("active_cycle_number") != cycle_number:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_cycle_not_active"
                )
            attempts = _json_object(row.get("category_attempts_json"))
            if int(attempts.get(category, 0)) != 0:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_category_already_claimed"
                )
            attempts[category] = 1
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_manual_cycle_category')} (
                    goal_id, cycle_number, category
                ) VALUES (%s, %s, %s)
                """,
                (self.goal_id, cycle_number, category),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET category_attempts_json = %s::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    json.dumps(attempts, sort_keys=True),
                    self.goal_id,
                ),
            )

    def claim_margin_subread(
        self,
        *,
        cycle_number: int,
        subread: str,
    ) -> None:
        """Durably mark one of the four no-retry CFM SDK boundaries."""

        self.ensure_schema()
        if (
            self.goal_id != FUTURES_HOTPOINT_GOAL_ID
            or subread not in FUTURES_MANUAL_MARGIN_SUBREADS
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_margin_subread_not_authorized"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if row.get("active_cycle_number") != cycle_number:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_cycle_not_active"
                )
            category_attempts = _json_object(
                row.get("category_attempts_json")
            )
            if int(
                category_attempts.get(
                    "futures_margin_collateral",
                    0,
                )
            ) != 1:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_margin_category_not_claimed"
                )
            attempts = _json_object(
                row.get("margin_subread_attempts_json")
            )
            if int(attempts.get(subread, 0)) != 0:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_margin_subread_already_claimed"
                )
            attempts[subread] = 1
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table(
                        'operator_futures_manual_cycle_margin_subread'
                    )} (
                    goal_id, cycle_number, subread
                ) VALUES (%s, %s, %s)
                """,
                (self.goal_id, cycle_number, subread),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                   SET margin_subread_attempts_json = %s::jsonb,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                """,
                (
                    json.dumps(attempts, sort_keys=True),
                    self.goal_id,
                ),
            )

    def finish_eligibility_cycle(
        self,
        *,
        cycle_number: int,
        result: FuturesManualEligibilityResult,
        context: FuturesManualRequestContext,
    ) -> FuturesManualGoalRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if row.get("active_cycle_number") != cycle_number:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_cycle_not_active"
                )
            attempts = {
                str(key): int(item)
                for key, item in _json_object(
                    row.get("category_attempts_json")
                ).items()
            }
            if attempts != result.category_attempts:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_category_accounting_mismatch"
                )
            if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
                margin_subreads = {
                    str(key): int(item)
                    for key, item in _json_object(
                        row.get("margin_subread_attempts_json")
                    ).items()
                }
                public_margin_subreads = result.public_evidence.get(
                    "margin_subread_attempts"
                )
                if (
                    margin_subreads.keys()
                    != _EMPTY_MARGIN_SUBREAD_ATTEMPTS.keys()
                    or not isinstance(public_margin_subreads, Mapping)
                    or {
                        str(key): int(item)
                        for key, item in public_margin_subreads.items()
                    }
                    != margin_subreads
                    or (
                        result.outcome
                        is AdminFuturesManualEligibilityOutcome.ELIGIBLE
                        and any(
                            value != 1
                            for value in margin_subreads.values()
                        )
                    )
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_margin_subread_"
                        "accounting_mismatch"
                    )
            candidate_json = None
            candidate_hash = None
            portfolio_hash = None
            evidence_hash = _exact_sha256(
                result.evidence_sha256,
                code=(
                    "operator_futures_manual_eligibility_evidence_invalid"
                ),
            )
            if (
                _canonical_sha256(result.public_evidence)
                != evidence_hash
                or result.public_evidence.get("raw_responses_included")
                is not False
                or result.public_evidence.get(
                    "private_identifiers_included"
                )
                is not False
                or result.public_evidence.get("exception_text_included")
                is not False
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_eligibility_evidence_invalid"
                )
            if (
                result.outcome
                is AdminFuturesManualEligibilityOutcome.ELIGIBLE
            ):
                stored_bound_hash = (
                    str(row["bound_portfolio_id_sha256"])
                    if row.get("bound_portfolio_id_sha256")
                    else None
                )
                expected_portfolio_hash = (
                    self.configured_portfolio_id_sha256
                    or stored_bound_hash
                )
                if (
                    result.candidate is None
                    or not _SHA256_RE.fullmatch(
                        str(result.portfolio_id_sha256 or "")
                    )
                    or (
                        expected_portfolio_hash is not None
                        and result.portfolio_id_sha256
                        != expected_portfolio_hash
                    )
                    or result.public_evidence.get("goal_id")
                    != self.goal_id
                    or result.public_evidence.get("profile_alias")
                    != "Default"
                    or result.public_evidence.get("portfolio_type")
                    != "DEFAULT"
                    or result.public_evidence.get("portfolio_id_sha256")
                    != result.portfolio_id_sha256
                    or result.public_evidence.get("credential_can_view")
                    is not True
                    or result.public_evidence.get("credential_can_trade")
                    is not True
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_eligible_evidence_invalid"
                    )
                if self.eligibility_evidence_validator is None:
                    public_caps = result.public_evidence.get("caps")
                    public_candidate = result.public_evidence.get(
                        "candidate"
                    )
                    if (
                        result.public_evidence.get(
                            "selection_authority"
                        )
                        != "cdp_api_key_permissioned_portfolio"
                        or result.public_evidence.get("product_id")
                        != "AVP-20DEC30-CDE"
                        or result.public_evidence.get("contract_count")
                        != "1"
                        or public_caps
                        != {
                            "opening_usdc": "100",
                            "exposure_usdc": "150",
                            "turnover_usdc": "300",
                            "comparison": "strictly_less_than",
                        }
                        or result.public_evidence.get(
                            "exact_v3_eligible"
                        )
                        is not True
                        or result.public_evidence.get(
                            "diagnostic_code"
                        )
                        != "operator_futures_manual_exact_v3_eligible"
                        or public_candidate != result.candidate
                    ):
                        raise FuturesManualLifecycleError(
                            "operator_futures_manual_eligible_evidence_invalid"
                        )
                else:
                    try:
                        self.eligibility_evidence_validator(result)
                    except Exception:
                        raise FuturesManualLifecycleError(
                            "operator_futures_manual_eligible_evidence_invalid"
                        ) from None
                candidate_json = {
                    str(key): str(item)
                    for key, item in result.candidate.items()
                }
                candidate_hash = _canonical_sha256(candidate_json)
                portfolio_hash = result.portfolio_id_sha256
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET revision = %s,
                    active_cycle_number = NULL,
                    eligibility_outcome = %s,
                    eligibility_diagnostic_code = %s,
                    candidate_json = %s::jsonb,
                    candidate_sha256 = %s,
                    portfolio_id_sha256 = %s,
                    bound_portfolio_id_sha256 =
                        COALESCE(bound_portfolio_id_sha256, %s),
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
                    (
                        json.dumps(candidate_json, sort_keys=True)
                        if candidate_json is not None
                        else None
                    ),
                    candidate_hash,
                    portfolio_hash,
                    portfolio_hash,
                    evidence_hash,
                    result.diagnostic_code,
                    context.correlation_id,
                    context.audit_id,
                    self.goal_id,
                ),
            )
            completed = self._select(cursor, for_update=False)
            self._insert_command_result(
                cursor,
                action="REFRESH",
                context=context,
                result_row=completed,
            )
            return self._record(completed)

    def claim_preview(
        self,
        *,
        context: FuturesManualRequestContext,
    ) -> tuple[FuturesManualGoalRecord, FuturesManualExecutionPlan | None]:
        self.ensure_schema()
        self._validate_context(context)
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            replay = self._replayed(
                cursor,
                action="EXECUTE",
                context=context,
                current_row=row,
            )
            if replay is not None:
                return self._record(replay), None
            if int(row["revision"]) != context.expected_revision:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_revision_conflict"
                )
            if (
                row.get("eligibility_outcome") != "ELIGIBLE"
                or row.get("active_cycle_number") is not None
                or row.get("preview_outcome") != "NOT_RUN"
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_preview_not_eligible"
                )
            candidate = {
                str(key): str(item)
                for key, item in _json_object(
                    row.get("candidate_json")
                ).items()
            }
            candidate_hash = _exact_sha256(
                row.get("candidate_sha256"),
                code="operator_futures_manual_candidate_hash_invalid",
            )
            evidence_hash = _exact_sha256(
                row.get("eligibility_evidence_sha256"),
                code=(
                    "operator_futures_manual_eligibility_evidence_invalid"
                ),
            )
            if _canonical_sha256(candidate) != candidate_hash:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_candidate_binding_invalid"
                )
            if self.claim_validator is not None:
                try:
                    self.claim_validator(
                        cursor=cursor,
                        candidate=candidate,
                    )
                except Exception:
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_candidate_binding_invalid"
                    ) from None
            self._require_fresh_candidate(candidate)
            claim_id = str(uuid.uuid4())
            client_order_id = (
                self.client_order_id_prefix + str(uuid.uuid4())
            )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET revision = %s,
                    execution_claim_id = %s,
                    client_order_id = %s,
                    preview_outcome = 'CLAIMED',
                    preview_exchange_invoked = FALSE,
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
                    client_order_id,
                    "operator_futures_manual_preview_claimed",
                    context.actor_id,
                    json.dumps(list(context.roles)),
                    context.correlation_id,
                    context.audit_id,
                    self.goal_id,
                ),
            )
            self._insert_command(
                cursor,
                action="EXECUTE",
                context=context,
                result_revision=revision,
            )
            record = self._record(
                self._select(cursor, for_update=False)
            )
            return record, FuturesManualExecutionPlan(
                claim_id=claim_id,
                client_order_id=client_order_id,
                candidate=candidate,
                candidate_sha256=candidate_hash,
                eligibility_evidence_sha256=evidence_hash,
            )

    def _claim_step(
        self,
        *,
        claim_id: str,
        step: str,
        prerequisites: Mapping[str, Any],
    ) -> FuturesManualGoalRecord:
        self.ensure_schema()
        outcome_column, invoked_column = _CALL_COLUMNS[step]
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if str(row.get("execution_claim_id") or "") != str(claim_id):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_claim_binding_invalid"
                )
            for column, expected in prerequisites.items():
                if row.get(column) != expected:
                    raise FuturesManualLifecycleError(
                        f"operator_futures_manual_{step}_not_authorized"
                    )
            if row.get(outcome_column) != "NOT_RUN":
                raise FuturesManualLifecycleError(
                    f"operator_futures_manual_{step}_already_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET {outcome_column} = 'CLAIMED',
                    {invoked_column} = FALSE,
                    diagnostic_code = %s,
                    revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    f"operator_futures_manual_{step}_claimed",
                    self.goal_id,
                ),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def claim_create(self, *, claim_id: str) -> FuturesManualGoalRecord:
        return self._claim_step(
            claim_id=claim_id,
            step="create",
            prerequisites={"preview_outcome": "ACCEPTED"},
        )

    def claim_reconciliation(
        self,
        *,
        claim_id: str,
        context: FuturesManualRequestContext | None = None,
    ) -> FuturesManualGoalRecord:
        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
            self.ensure_schema()
            if context is None:
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_closeout_context_required",
                    http_status_code=422,
                )
            self._validate_context(context)
            if (
                context.operator_intent
                != "safe_closeout_operator_hotpoint_child"
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_closeout_context_invalid",
                    http_status_code=422,
                )
            catalog_end_at = self.clock()
            if (
                catalog_end_at.tzinfo is None
                or catalog_end_at.utcoffset() is None
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_runtime_clock_invalid"
                )
            catalog_end_at = catalog_end_at.astimezone(timezone.utc)
            with self._cursor() as cursor:
                self._lock(cursor)
                row = self._select(cursor, for_update=True)
                if (
                    str(row.get("execution_claim_id") or "")
                    != str(claim_id)
                    or row.get("create_outcome")
                    not in {"ACCEPTED", "UNKNOWN"}
                    or row.get("reconciliation_outcome") != "NOT_RUN"
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_reconciliation_not_authorized"
                    )
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_manual_goal')}
                    SET reconciliation_outcome = 'CLAIMED',
                        reconciliation_exchange_invoked = FALSE,
                        reconciliation_catalog_end_at = %s,
                        diagnostic_code = %s,
                        actor_id = %s,
                        roles_json = %s::jsonb,
                        correlation_id = %s,
                        audit_id = %s,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE goal_id = %s
                    """,
                    (
                        catalog_end_at,
                        "operator_futures_hotpoint_reconciliation_claimed",
                        context.actor_id,
                        json.dumps(
                            list(context.roles),
                            separators=(",", ":"),
                        ),
                        context.correlation_id,
                        context.audit_id,
                        self.goal_id,
                    ),
                )
                return self._record(
                    self._select(cursor, for_update=False)
                )
        return self._claim_step(
            claim_id=claim_id,
            step="reconciliation",
            prerequisites={"create_outcome": "ACCEPTED"},
        )

    def claim_cancel(self, *, claim_id: str) -> FuturesManualGoalRecord:
        return self._claim_step(
            claim_id=claim_id,
            step="cancel",
            prerequisites={
                "create_outcome": "ACCEPTED",
                "reconciliation_outcome": "ACCEPTED",
                "authoritatively_nonterminal": True,
            },
        )

    def _mark_invoked(self, *, claim_id: str, step: str) -> None:
        self.ensure_schema()
        outcome_column, invoked_column = _CALL_COLUMNS[step]
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "") != str(claim_id)
                or row.get(outcome_column) != "CLAIMED"
                or row.get(invoked_column) is not False
            ):
                raise FuturesManualLifecycleError(
                    f"operator_futures_manual_{step}_invoke_not_claimed"
                )
            if (
                self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                and step in {"preview", "create"}
            ):
                candidate = {
                    str(key): str(value)
                    for key, value in _json_object(
                        row.get("candidate_json")
                    ).items()
                }
                # Recheck freshness in the same transaction that records the
                # actual SDK invocation boundary.  Claim-time freshness alone
                # is insufficient because the candidate can age out while the
                # claimed call is waiting to enter the transport.
                self._require_fresh_candidate(candidate)
                try:
                    if step == "preview":
                        assert (
                            self.preview_invocation_validator
                            is not None
                        )
                        self.preview_invocation_validator(
                            cursor=cursor,
                            candidate=candidate,
                        )
                    else:
                        assert (
                            self.create_invocation_validator
                            is not None
                        )
                        self.create_invocation_validator(
                            cursor=cursor,
                            candidate=candidate,
                            claim_id=str(claim_id),
                            client_order_id=str(
                                row.get("client_order_id") or ""
                            ),
                        )
                except Exception:
                    raise FuturesManualLifecycleError(
                        f"operator_futures_hotpoint_{step}_invocation_"
                        "not_authorized"
                    ) from None
            if step == "cancel":
                try:
                    seal_futures_cancel_invocation(
                        cursor,
                        schema=self.schema,
                        owner_ledger=self.goal_id,
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
                    raise FuturesManualLifecycleError(code) from None
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET {invoked_column} = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (self.goal_id,),
            )

    def mark_preview_exchange_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(claim_id=claim_id, step="preview")

    def mark_create_exchange_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(claim_id=claim_id, step="create")

    def mark_reconciliation_exchange_invoked(
        self,
        *,
        claim_id: str,
    ) -> None:
        self._mark_invoked(claim_id=claim_id, step="reconciliation")

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None:
        self._mark_invoked(claim_id=claim_id, step="cancel")

    def _finish_step(
        self,
        *,
        claim_id: str,
        step: str,
        execution: Any,
        extra: Mapping[str, Any],
    ) -> FuturesManualGoalRecord:
        self.ensure_schema()
        outcome = getattr(execution, "outcome", None)
        if outcome not in {
            AdminFuturesManualCallOutcome.ACCEPTED,
            AdminFuturesManualCallOutcome.REJECTED,
            AdminFuturesManualCallOutcome.UNKNOWN,
        }:
            raise FuturesManualLifecycleError(
                f"operator_futures_manual_{step}_outcome_invalid"
            )
        diagnostic = str(
            getattr(execution, "diagnostic_code", "") or ""
        )
        allowed_diagnostic_prefixes = {
            f"operator_futures_manual_{step}"
        }
        if self.goal_id in {
            FUTURES_PRODUCT_TICKET_GOAL_ID,
            FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            FUTURES_HOTPOINT_GOAL_ID,
        }:
            allowed_diagnostic_prefixes.add(
                f"operator_futures_product_ticket_{step}"
            )
        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
            allowed_diagnostic_prefixes.add(
                f"operator_futures_hotpoint_{step}"
            )
        if (
            not any(
                diagnostic.startswith(prefix)
                for prefix in allowed_diagnostic_prefixes
            )
            or len(diagnostic) > 128
        ):
            raise FuturesManualLifecycleError(
                f"operator_futures_manual_{step}_diagnostic_invalid"
            )
        outcome_column, _invoked_column = _CALL_COLUMNS[step]
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "") != str(claim_id)
                or row.get(outcome_column) != "CLAIMED"
                or (
                    self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                    and row.get(_invoked_column) is not True
                )
            ):
                raise FuturesManualLifecycleError(
                    f"operator_futures_manual_{step}_finish_not_claimed"
                )
            assignments = [
                f"{outcome_column} = %s",
                "diagnostic_code = %s",
                "revision = revision + 1",
                "updated_at = CURRENT_TIMESTAMP",
            ]
            params: list[Any] = [outcome.value, diagnostic]
            for column, value in extra.items():
                assignments.append(f"{column} = %s")
                params.append(value)
            params.append(self.goal_id)
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET {", ".join(assignments)}
                WHERE goal_id = %s
                """,
                tuple(params),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def finish_preview(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        preview_hash = getattr(execution, "preview_id_sha256", None)
        if preview_hash is not None:
            preview_hash = _exact_sha256(
                preview_hash,
                code="operator_futures_manual_preview_hash_invalid",
            )
        if (
            getattr(execution, "outcome", None)
            is AdminFuturesManualCallOutcome.ACCEPTED
            and preview_hash is None
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_preview_hash_missing"
            )
        return self._finish_step(
            claim_id=claim_id,
            step="preview",
            execution=execution,
            extra={"preview_id_sha256": preview_hash},
        )

    def finish_preview_and_claim_create(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        """Atomically bind accepted Preview evidence and claim Create."""

        self.ensure_schema()
        if (
            getattr(execution, "outcome", None)
            is not AdminFuturesManualCallOutcome.ACCEPTED
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_preview_outcome_invalid"
            )
        preview_hash = _exact_sha256(
            getattr(execution, "preview_id_sha256", None),
            code="operator_futures_manual_preview_hash_invalid",
        )
        diagnostic = str(
            getattr(execution, "diagnostic_code", "") or ""
        )
        allowed_prefixes = {"operator_futures_manual_preview"}
        if self.goal_id in {
            FUTURES_PRODUCT_TICKET_GOAL_ID,
            FUTURES_FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            FUTURES_HOTPOINT_GOAL_ID,
        }:
            allowed_prefixes.add("operator_futures_product_ticket_preview")
            allowed_prefixes.add("operator_futures_hotpoint_preview")
        if (
            not any(
                diagnostic.startswith(prefix)
                for prefix in allowed_prefixes
            )
            or len(diagnostic) > 128
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_preview_diagnostic_invalid"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "")
                != str(claim_id)
                or row.get("preview_outcome") != "CLAIMED"
                or row.get("preview_exchange_invoked") is not True
                or row.get("create_outcome") != "NOT_RUN"
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_create_not_authorized"
                )
            candidate = {
                str(key): str(value)
                for key, value in _json_object(
                    row.get("candidate_json")
                ).items()
            }
            candidate_hash = _exact_sha256(
                row.get("candidate_sha256"),
                code="operator_futures_manual_candidate_hash_invalid",
            )
            if _canonical_sha256(candidate) != candidate_hash:
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_candidate_binding_invalid"
                )
            self._require_fresh_candidate(candidate)
            if self.claim_validator is not None:
                try:
                    self.claim_validator(
                        cursor=cursor,
                        candidate=candidate,
                    )
                except Exception:
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_candidate_binding_invalid"
                    ) from None
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET preview_outcome = 'ACCEPTED',
                    preview_id_sha256 = %s,
                    create_outcome = 'CLAIMED',
                    create_exchange_invoked = FALSE,
                    diagnostic_code = %s,
                    revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    preview_hash,
                    "operator_futures_manual_create_claimed",
                    self.goal_id,
                ),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def finish_create(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        exchange_hash = getattr(
            execution, "exchange_order_id_sha256", None
        )
        if exchange_hash is not None:
            exchange_hash = _exact_sha256(
                exchange_hash,
                code=(
                    "operator_futures_manual_exchange_order_hash_invalid"
                ),
            )
        if (
            getattr(execution, "outcome", None)
            is AdminFuturesManualCallOutcome.ACCEPTED
            and exchange_hash is None
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_exchange_order_hash_missing"
            )
        return self._finish_step(
            claim_id=claim_id,
            step="create",
            execution=execution,
            extra={"exchange_order_id_sha256": exchange_hash},
        )

    def finish_create_and_claim_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        """Atomically bind accepted Create evidence and the next read claim."""

        self.ensure_schema()
        if (
            getattr(execution, "outcome", None)
            is not AdminFuturesManualCallOutcome.ACCEPTED
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_create_outcome_invalid"
            )
        exchange_hash = _exact_sha256(
            getattr(execution, "exchange_order_id_sha256", None),
            code="operator_futures_manual_exchange_order_hash_invalid",
        )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "")
                != str(claim_id)
                or row.get("create_outcome") != "CLAIMED"
                or row.get("reconciliation_outcome") != "NOT_RUN"
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_reconciliation_not_authorized"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET create_outcome = 'ACCEPTED',
                    exchange_order_id_sha256 = %s,
                    reconciliation_outcome = 'CLAIMED',
                    reconciliation_exchange_invoked = FALSE,
                    diagnostic_code = %s,
                    revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    exchange_hash,
                    "operator_futures_manual_reconciliation_claimed",
                    self.goal_id,
                ),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def finish_reconciliation(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
            self.ensure_schema()
            outcome = getattr(execution, "outcome", None)
            diagnostic = str(
                getattr(execution, "diagnostic_code", "") or ""
            )
            exchange_hash_value = getattr(
                execution,
                "exchange_order_id_sha256",
                None,
            )
            exchange_hash = (
                _exact_sha256(
                    exchange_hash_value,
                    code=(
                        "operator_futures_manual_exchange_order_hash_invalid"
                    ),
                )
                if exchange_hash_value is not None
                else None
            )
            order_status = str(
                getattr(execution, "order_status", "") or ""
            ).strip() or None
            authoritatively_nonterminal = getattr(
                execution,
                "authoritatively_nonterminal",
                None,
            )
            if (
                outcome
                not in {
                    AdminFuturesManualCallOutcome.ACCEPTED,
                    AdminFuturesManualCallOutcome.REJECTED,
                    AdminFuturesManualCallOutcome.UNKNOWN,
                }
                or not diagnostic.startswith(
                    "operator_futures_hotpoint_reconciliation"
                )
                or len(diagnostic) > 128
                or (
                    outcome is AdminFuturesManualCallOutcome.ACCEPTED
                    and (
                        exchange_hash is None
                        or order_status is None
                        or type(authoritatively_nonterminal) is not bool
                    )
                )
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_reconciliation_outcome_invalid"
                )
            with self._cursor() as cursor:
                self._lock(cursor)
                row = self._select(cursor, for_update=True)
                stored_hash = str(
                    row.get("exchange_order_id_sha256") or ""
                ).strip()
                if (
                    str(row.get("execution_claim_id") or "")
                    != str(claim_id)
                    or row.get("create_outcome")
                    not in {"ACCEPTED", "UNKNOWN"}
                    or row.get("reconciliation_outcome") != "CLAIMED"
                    or row.get("reconciliation_exchange_invoked")
                    is not True
                    or (
                        stored_hash
                        and exchange_hash
                        and stored_hash != exchange_hash
                    )
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_reconciliation_finish_not_claimed"
                    )
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_manual_goal')}
                    SET create_outcome = CASE
                            WHEN %s = 'ACCEPTED' THEN 'ACCEPTED'
                            ELSE create_outcome
                        END,
                        exchange_order_id_sha256 =
                            COALESCE(exchange_order_id_sha256, %s),
                        reconciliation_outcome = %s,
                        order_status = %s,
                        authoritatively_nonterminal = %s,
                        diagnostic_code = %s,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE goal_id = %s
                    """,
                    (
                        outcome.value,
                        exchange_hash,
                        outcome.value,
                        order_status,
                        authoritatively_nonterminal,
                        diagnostic,
                        self.goal_id,
                    ),
                )
                return self._record(
                    self._select(cursor, for_update=False)
                )
        return self._finish_step(
            claim_id=claim_id,
            step="reconciliation",
            execution=execution,
            extra={
                "order_status": getattr(execution, "order_status", None),
                "authoritatively_nonterminal": getattr(
                    execution,
                    "authoritatively_nonterminal",
                    None,
                ),
            },
        )

    def finish_reconciliation_and_claim_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        """Atomically bind a nonterminal exact read and its Cancel claim."""

        self.ensure_schema()
        if (
            getattr(execution, "outcome", None)
            is not AdminFuturesManualCallOutcome.ACCEPTED
            or getattr(execution, "authoritatively_nonterminal", None)
            is not True
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_manual_cancel_not_authorized"
            )
        order_status = str(
            getattr(execution, "order_status", "") or ""
        ).strip().upper()
        if (
            not order_status
            or (
                self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                and order_status != "OPEN"
            )
        ):
            raise FuturesManualLifecycleError(
                (
                    "operator_futures_manual_cancel_not_authorized"
                    if (
                        self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                        and order_status
                    )
                    else
                    "operator_futures_manual_reconciliation_outcome_invalid"
                )
            )
        exchange_hash = None
        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
            diagnostic = str(
                getattr(execution, "diagnostic_code", "") or ""
            )
            if (
                not diagnostic.startswith(
                    "operator_futures_hotpoint_reconciliation"
                )
                or len(diagnostic) > 128
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_reconciliation_outcome_invalid"
                )
            exchange_hash = _exact_sha256(
                getattr(
                    execution,
                    "exchange_order_id_sha256",
                    None,
                ),
                code=(
                    "operator_futures_manual_exchange_order_hash_invalid"
                ),
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "")
                != str(claim_id)
                or (
                    self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                    and row.get("create_outcome")
                    not in {"ACCEPTED", "UNKNOWN"}
                )
                or (
                    self.goal_id != FUTURES_HOTPOINT_GOAL_ID
                    and row.get("create_outcome") != "ACCEPTED"
                )
                or row.get("reconciliation_outcome") != "CLAIMED"
                or (
                    self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                    and row.get("reconciliation_exchange_invoked")
                    is not True
                )
                or row.get("cancel_outcome") != "NOT_RUN"
                or (
                    self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                    and row.get("exchange_order_id_sha256")
                    and row.get("exchange_order_id_sha256")
                    != exchange_hash
                )
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_cancel_not_authorized"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET create_outcome = CASE
                        WHEN %s THEN 'ACCEPTED'
                        ELSE create_outcome
                    END,
                    exchange_order_id_sha256 =
                        COALESCE(exchange_order_id_sha256, %s),
                    reconciliation_outcome = 'ACCEPTED',
                    order_status = %s,
                    authoritatively_nonterminal = TRUE,
                    cancel_outcome = 'CLAIMED',
                    cancel_exchange_invoked = FALSE,
                    diagnostic_code = %s,
                    revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE goal_id = %s
                """,
                (
                    self.goal_id == FUTURES_HOTPOINT_GOAL_ID,
                    exchange_hash,
                    order_status,
                    (
                        "operator_futures_hotpoint_cancel_claimed"
                        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID
                        else "operator_futures_manual_cancel_claimed"
                    ),
                    self.goal_id,
                ),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesManualGoalRecord:
        if self.goal_id == FUTURES_HOTPOINT_GOAL_ID:
            self.ensure_schema()
            outcome = getattr(execution, "outcome", None)
            diagnostic = str(
                getattr(execution, "diagnostic_code", "") or ""
            )
            exchange_hash = _exact_sha256(
                getattr(
                    execution,
                    "exchange_order_id_sha256",
                    None,
                ),
                code=(
                    "operator_futures_manual_exchange_order_hash_invalid"
                ),
            )
            if (
                outcome
                not in {
                    AdminFuturesManualCallOutcome.ACCEPTED,
                    AdminFuturesManualCallOutcome.REJECTED,
                    AdminFuturesManualCallOutcome.UNKNOWN,
                }
                or not (
                    diagnostic.startswith(
                        "operator_futures_product_ticket_cancel"
                    )
                    or diagnostic.startswith(
                        "operator_futures_hotpoint_cancel"
                    )
                )
                or len(diagnostic) > 128
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_manual_cancel_outcome_invalid"
                )
            with self._cursor() as cursor:
                self._lock(cursor)
                row = self._select(cursor, for_update=True)
                if (
                    str(row.get("execution_claim_id") or "")
                    != str(claim_id)
                    or row.get("cancel_outcome") != "CLAIMED"
                    or row.get("cancel_exchange_invoked") is not True
                    or row.get("exchange_order_id_sha256")
                    != exchange_hash
                ):
                    raise FuturesManualLifecycleError(
                        "operator_futures_manual_cancel_finish_not_claimed"
                    )
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_manual_goal')}
                    SET cancel_outcome = %s,
                        diagnostic_code = %s,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE goal_id = %s
                    """,
                    (outcome.value, diagnostic, self.goal_id),
                )
                return self._record(
                    self._select(cursor, for_update=False)
                )
        return self._finish_step(
            claim_id=claim_id,
            step="cancel",
            execution=execution,
            extra={},
        )

    def finish_unentered_claim_unknown(
        self,
        *,
        claim_id: str,
        step: str,
        diagnostic_code: str,
    ) -> FuturesManualGoalRecord:
        """Consume a Goal13 claim that failed before the SDK boundary."""

        if (
            self.goal_id != FUTURES_HOTPOINT_GOAL_ID
            or step not in _CALL_COLUMNS
            or diagnostic_code
            != f"operator_futures_hotpoint_{step}_preinvoke_unknown"
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_preinvoke_outcome_invalid"
            )
        self.ensure_schema()
        outcome_column, invoked_column = _CALL_COLUMNS[step]
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "")
                != str(claim_id)
                or row.get(outcome_column) != "CLAIMED"
                or row.get(invoked_column) is not False
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_preinvoke_finish_not_claimed"
                )
            assignments = [
                f"{outcome_column} = 'UNKNOWN'",
                "diagnostic_code = %s",
                "revision = revision + 1",
                "updated_at = CURRENT_TIMESTAMP",
            ]
            if step == "reconciliation":
                assignments.extend(
                    [
                        "order_status = NULL",
                        "authoritatively_nonterminal = NULL",
                    ]
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                SET {", ".join(assignments)}
                WHERE goal_id = %s
                """,
                (diagnostic_code, self.goal_id),
            )
            return self._record(
                self._select(cursor, for_update=False)
            )

    def release_cancel_invocation_conflict(
        self,
        *,
        claim_id: str,
    ) -> FuturesManualGoalRecord:
        """Release a Goal13 local claim lost to the shared Cancel seal."""

        if self.goal_id != FUTURES_HOTPOINT_GOAL_ID:
            raise FuturesManualLifecycleError(
                "operator_futures_cancel_invocation_binding_invalid"
            )
        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            row = self._select(cursor, for_update=True)
            if (
                str(row.get("execution_claim_id") or "")
                != str(claim_id)
                or row.get("cancel_outcome") != "CLAIMED"
                or row.get("cancel_exchange_invoked") is not False
            ):
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_cancel_release_not_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_manual_goal')}
                   SET cancel_outcome = 'NOT_RUN',
                       cancel_exchange_invoked = NULL,
                       diagnostic_code =
                           'operator_futures_cancel_invocation_already_sealed',
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                """,
                (self.goal_id,),
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
                raise FuturesManualLifecycleError(
                    "operator_futures_cancel_invocation_binding_invalid"
                ) from None


_DEFAULT_REPOSITORY: OperatorFuturesManualLifecycleRepository | None = None
_DEFAULT_HOTPOINT_REPOSITORY: (
    OperatorFuturesManualLifecycleRepository | None
) = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_operator_futures_manual_lifecycle_repository(
) -> OperatorFuturesManualLifecycleRepository:
    """Return the installed PostgreSQL Goal 10 authority."""

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
                    OperatorFuturesManualLifecycleRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=(portfolio_id or None),
                        goal_id=FUTURES_MANUAL_ACTIVE_GOAL_ID,
                    )
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def get_default_operator_futures_hotpoint_lifecycle_repository(
    *,
    control_repository: Any | None = None,
) -> OperatorFuturesManualLifecycleRepository:
    """Return Goal13's Default-profile ledger with strict claim rebinding."""

    global _DEFAULT_HOTPOINT_REPOSITORY
    if _DEFAULT_HOTPOINT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_HOTPOINT_REPOSITORY is None:
                from application.admin_api.operator_futures_hotpoint_v2 import (
                    validate_futures_hotpoint_eligibility_evidence,
                )
                from database import order as order_db
                from database.operator_hotpoint_control import (
                    get_default_operator_futures_hotpoint_control_repository,
                )

                exact_control = (
                    control_repository
                    or get_default_operator_futures_hotpoint_control_repository()
                )
                _DEFAULT_HOTPOINT_REPOSITORY = (
                    OperatorFuturesManualLifecycleRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=None,
                        goal_id=FUTURES_HOTPOINT_GOAL_ID,
                        eligibility_evidence_validator=(
                            validate_futures_hotpoint_eligibility_evidence
                        ),
                        claim_validator=(
                            exact_control.validate_futures_candidate_claim
                        ),
                        preview_invocation_validator=(
                            exact_control
                            .validate_futures_preview_invocation
                        ),
                        create_invocation_validator=(
                            exact_control
                            .validate_futures_create_invocation
                        ),
                        client_order_id_prefix=(
                            "operator-futures-hotpoint-v2-"
                        ),
                    )
                )
                _DEFAULT_HOTPOINT_REPOSITORY.ensure_schema()
    return _DEFAULT_HOTPOINT_REPOSITORY


def initialize_operator_futures_manual_lifecycle_schema() -> None:
    get_default_operator_futures_manual_lifecycle_repository().ensure_schema()


__all__ = [
    "OperatorFuturesManualLifecycleRepository",
    "get_default_operator_futures_hotpoint_lifecycle_repository",
    "get_default_operator_futures_manual_lifecycle_repository",
    "initialize_operator_futures_manual_lifecycle_schema",
]
