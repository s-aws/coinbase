"""PostgreSQL authority for approved-Test Spot order operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_spot_order_truth import (
    SPOT_ORDER_TRUTH_CATEGORIES,
    SPOT_ORDER_TRUTH_GOAL_ID,
    SPOT_ORDER_TRUTH_MAX_CYCLES,
    SpotOrderCatalogResult,
)
from application.admin_api.operator_spot_order_truth_service import (
    SpotOrderTruthGoalRecord,
    SpotOrderTruthRequestContext,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_CLIENT_ORDER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ACTIONS = frozenset({"REFRESH_CATALOG", "RECONCILE_EXACT"})
_CANCEL_ELIGIBLE_ORDER_TYPES = (
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "BRACKET",
    "TWAP",
)
_EMPTY_ATTEMPTS = {
    category: 0 for category in SPOT_ORDER_TRUTH_CATEGORIES
}


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item[0] for item in cursor.description), value))


def _rows(cursor: Any) -> list[dict[str, Any]]:
    values = cursor.fetchall()
    if not values:
        return []
    if isinstance(values[0], Mapping):
        return [dict(item) for item in values]
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, item)) for item in values]


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("operator_spot_order_truth_stored_json_invalid")
    return dict(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_hash(
    context: SpotOrderTruthRequestContext,
    *,
    action: str,
    target_client_order_id: str | None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": action,
                "actor_id": context.actor_id,
                "correlation_id": context.correlation_id,
                "roles": sorted(set(context.roles)),
                "target_client_order_id": target_client_order_id,
                "expected_revision": context.expected_revision,
                "operator_intent": context.operator_intent,
                "authorize_one_no_retry_cycle": (
                    context.authorize_one_no_retry_cycle
                ),
                "acknowledge_cycle_is_goal_global_and_limited_to_one": (
                    context
                    .acknowledge_cycle_is_goal_global_and_limited_to_one
                ),
                "acknowledge_unknown_read_fails_closed": (
                    context.acknowledge_unknown_read_fails_closed
                ),
                "acknowledge_unknown_cancel_consumes_allowance": (
                    context
                    .acknowledge_unknown_cancel_consumes_allowance
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


_GOAL_RECORD_KEYS = {
    item.name for item in fields(SpotOrderTruthGoalRecord)
}


def _record_payload(
    record: SpotOrderTruthGoalRecord,
) -> dict[str, Any]:
    return asdict(record)


def _record_from_payload(value: Any) -> SpotOrderTruthGoalRecord:
    payload = _json_object(value)
    if set(payload) != _GOAL_RECORD_KEYS:
        raise ValueError(
            "operator_spot_order_truth_idempotency_replay_invalid"
        )
    return SpotOrderTruthGoalRecord(**payload)


class OperatorSpotOrderTruthRepository:
    """Serialize one read cycle and an independent single Cancel allowance."""

    def __init__(
        self,
        db: Any,
        *,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("operator_spot_order_truth_schema_invalid")
        self.db = db
        self.schema = str(schema)
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
        cursor.execute("SELECT pg_advisory_xact_lock(34994, 12)")

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_goal')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        revision INTEGER NOT NULL DEFAULT 0
                            CHECK (revision >= 0),
                        cycles_used INTEGER NOT NULL DEFAULT 0
                            CHECK (cycles_used BETWEEN 0 AND 1),
                        active_cycle_number INTEGER,
                        last_action VARCHAR(32),
                        last_target_client_order_id VARCHAR(128),
                        last_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (last_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'SUCCEEDED',
                                'INELIGIBLE', 'UNKNOWN'
                            )),
                        diagnostic_code VARCHAR(128) NOT NULL,
                        category_attempts_json JSONB NOT NULL DEFAULT '{{}}',
                        page_count INTEGER NOT NULL DEFAULT 0
                            CHECK (page_count BETWEEN 0 AND 100),
                        order_count INTEGER NOT NULL DEFAULT 0
                            CHECK (order_count >= 0),
                        portfolio_id_sha256 CHAR(64),
                        evidence_sha256 CHAR(64),
                        cancel_outcome VARCHAR(16) NOT NULL DEFAULT 'NOT_RUN'
                            CHECK (cancel_outcome IN (
                                'NOT_RUN', 'CLAIMED', 'ACCEPTED',
                                'REJECTED', 'UNKNOWN'
                            )),
                        cancel_exchange_invoked BOOLEAN,
                        cancel_target_client_order_id VARCHAR(128),
                        cancel_exchange_order_id_sha256 CHAR(64),
                        cancel_claim_id UUID UNIQUE,
                        cancel_cycle_number INTEGER,
                        correlation_id VARCHAR(255),
                        audit_id VARCHAR(255),
                        refreshed_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_goal')}
                    ADD COLUMN IF NOT EXISTS cancel_cycle_number INTEGER
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_cycle')} (
                        cycle_number INTEGER PRIMARY KEY
                            CHECK (cycle_number BETWEEN 1 AND 1),
                        action VARCHAR(32) NOT NULL,
                        target_client_order_id VARCHAR(128),
                        state VARCHAR(16) NOT NULL CHECK (state IN (
                            'CLAIMED', 'SUCCEEDED', 'INELIGIBLE', 'UNKNOWN'
                        )),
                        diagnostic_code VARCHAR(128) NOT NULL,
                        idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id VARCHAR(255) NOT NULL,
                        result_json JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_cycle')}
                    ADD COLUMN IF NOT EXISTS result_json JSONB
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        operator_spot_order_truth_cycle_correlation_uidx
                    ON {self._table('operator_spot_order_truth_cycle')}
                        (correlation_id)
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_cancel_request')} (
                        request_id UUID PRIMARY KEY,
                        claim_id UUID NOT NULL UNIQUE,
                        client_order_id VARCHAR(128) NOT NULL,
                        exchange_order_id_sha256 CHAR(64) NOT NULL,
                        idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL UNIQUE,
                        audit_id VARCHAR(255) NOT NULL,
                        state VARCHAR(16) NOT NULL CHECK (state IN (
                            'CLAIMED', 'PREBOUNDARY', 'ACCEPTED',
                            'REJECTED', 'UNKNOWN'
                        )),
                        call_boundary_entered BOOLEAN NOT NULL DEFAULT FALSE,
                        result_json JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_category')} (
                        cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_spot_order_truth_cycle')}
                            (cycle_number),
                        category VARCHAR(64) NOT NULL,
                        state VARCHAR(16) NOT NULL DEFAULT 'CLAIMED'
                            CHECK (state IN (
                                'CLAIMED', 'PREBOUNDARY', 'RETURNED', 'UNKNOWN'
                            )),
                        call_boundary_entered BOOLEAN NOT NULL DEFAULT FALSE,
                        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ,
                        PRIMARY KEY (cycle_number, category)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_page')} (
                        cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_spot_order_truth_cycle')}
                            (cycle_number),
                        page_ordinal INTEGER NOT NULL
                            CHECK (page_ordinal BETWEEN 1 AND 100),
                        cursor_sha256 CHAR(64),
                        state VARCHAR(16) NOT NULL DEFAULT 'CLAIMED'
                            CHECK (state IN (
                                'CLAIMED', 'PREBOUNDARY', 'RETURNED', 'UNKNOWN'
                            )),
                        call_boundary_entered BOOLEAN NOT NULL DEFAULT FALSE,
                        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        returned_at TIMESTAMPTZ,
                        PRIMARY KEY (cycle_number, page_ordinal)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_category')}
                    DROP CONSTRAINT IF EXISTS
                        operator_spot_order_truth_category_state_check
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_category')}
                    ADD CONSTRAINT
                        operator_spot_order_truth_category_state_check
                    CHECK (state IN (
                        'CLAIMED', 'PREBOUNDARY', 'RETURNED', 'UNKNOWN'
                    ))
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_page')}
                    DROP CONSTRAINT IF EXISTS
                        operator_spot_order_truth_page_state_check
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_page')}
                    ADD CONSTRAINT
                        operator_spot_order_truth_page_state_check
                    CHECK (state IN (
                        'CLAIMED', 'PREBOUNDARY', 'RETURNED', 'UNKNOWN'
                    ))
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_projection')} (
                        client_order_id VARCHAR(128) PRIMARY KEY,
                        product_id VARCHAR(128) NOT NULL,
                        side VARCHAR(8) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                        status VARCHAR(32) NOT NULL,
                        order_type VARCHAR(32) NOT NULL,
                        time_in_force VARCHAR(32) NOT NULL,
                        size VARCHAR(128),
                        limit_price VARCHAR(128),
                        filled_size VARCHAR(128),
                        ownership_provenance VARCHAR(64) NOT NULL
                            CHECK (ownership_provenance = 'ADMIN_MANUAL_ROOT'),
                        created_at TIMESTAMPTZ,
                        exchange_updated_at TIMESTAMPTZ,
                        exchange_order_id_sha256 CHAR(64) NOT NULL,
                        authoritatively_nonterminal BOOLEAN NOT NULL,
                        cancel_eligible BOOLEAN NOT NULL,
                        observed_cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_spot_order_truth_cycle')}
                            (cycle_number),
                        observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_projection')}
                    ADD COLUMN IF NOT EXISTS cancel_eligible BOOLEAN
                    """
                )
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_projection')}
                    SET cancel_eligible = (status = 'OPEN')
                    WHERE cancel_eligible IS NULL
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_projection')}
                    ALTER COLUMN cancel_eligible SET NOT NULL
                    """
                )
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_projection')}
                    SET cancel_eligible = FALSE,
                        updated_at = NOW()
                    WHERE cancel_eligible = TRUE
                      AND (
                          status <> 'OPEN'
                          OR authoritatively_nonterminal <> TRUE
                          OR order_type NOT IN (
                              'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT',
                              'BRACKET', 'TWAP'
                          )
                      )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_projection')}
                    DROP CONSTRAINT IF EXISTS
                        operator_spot_order_truth_projection_cancel_coherent
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_spot_order_truth_projection')}
                    ADD CONSTRAINT
                        operator_spot_order_truth_projection_cancel_coherent
                    CHECK (
                        NOT cancel_eligible
                        OR (
                            status = 'OPEN'
                            AND authoritatively_nonterminal = TRUE
                            AND order_type IN (
                                'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT',
                                'BRACKET', 'TWAP'
                            )
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_spot_order_truth_event')} (
                        event_id UUID PRIMARY KEY,
                        event_type VARCHAR(64) NOT NULL,
                        cycle_number INTEGER,
                        client_order_id VARCHAR(128),
                        diagnostic_code VARCHAR(128) NOT NULL,
                        correlation_id VARCHAR(255),
                        audit_id VARCHAR(255),
                        evidence_json JSONB NOT NULL DEFAULT '{{}}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self._table('operator_spot_order_truth_goal')} (
                            goal_id,
                            diagnostic_code,
                            category_attempts_json
                        )
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (goal_id) DO NOTHING
                    """,
                    (
                        SPOT_ORDER_TRUTH_GOAL_ID,
                        "operator_spot_order_truth_not_refreshed",
                        json.dumps(_EMPTY_ATTEMPTS, sort_keys=True),
                    ),
                )
                self._recover_locked(cursor)
            self._schema_ready = True

    def _recover_locked(self, cursor: Any) -> None:
        self._lock(cursor)
        row = self._select_goal(cursor, for_update=True)
        revision = int(row["revision"])
        if row.get("active_cycle_number") is not None:
            cycle_number = int(row["active_cycle_number"])
            cursor.execute(
                f"""
                SELECT category, call_boundary_entered
                FROM {self._table('operator_spot_order_truth_category')}
                WHERE cycle_number = %s
                """,
                (cycle_number,),
            )
            recovered_attempts = dict(_EMPTY_ATTEMPTS)
            for category_row in _rows(cursor):
                category = str(category_row.get("category") or "")
                if (
                    category in recovered_attempts
                    and category_row.get("call_boundary_entered") is True
                ):
                    recovered_attempts[category] = 1
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self._table('operator_spot_order_truth_page')}
                WHERE cycle_number = %s
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number,),
            )
            recovered_page_count = int(
                (_row(cursor) or {}).get("count") or 0
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET state = 'UNKNOWN',
                    finished_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET state = 'PREBOUNDARY',
                    finished_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'UNKNOWN',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'PREBOUNDARY',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_cycle')}
                SET state = 'UNKNOWN',
                    diagnostic_code = %s,
                    finished_at = NOW()
                WHERE cycle_number = %s AND state = 'CLAIMED'
                """,
                (
                    "operator_spot_order_truth_catalog_restart_unknown",
                    cycle_number,
                ),
            )
            revision += 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    active_cycle_number = NULL,
                    last_outcome = 'UNKNOWN',
                    diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    page_count = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    "operator_spot_order_truth_catalog_restart_unknown",
                    json.dumps(recovered_attempts, sort_keys=True),
                    recovered_page_count,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            row = self._select_goal(cursor, for_update=True)
            recovered = self._record(row)
            self._store_cycle_record(
                cursor,
                cycle_number=cycle_number,
                record=recovered,
            )
        if row.get("cancel_outcome") == "CLAIMED":
            invoked = row.get("cancel_exchange_invoked") is True
            cancel_claim_id = str(row.get("cancel_claim_id") or "")
            if invoked:
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_projection')}
                    SET authoritatively_nonterminal = FALSE,
                        cancel_eligible = FALSE,
                        updated_at = NOW()
                    WHERE client_order_id = %s
                      AND exchange_order_id_sha256 = %s
                    """,
                    (
                        row.get("cancel_target_client_order_id"),
                        row.get("cancel_exchange_order_id_sha256"),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "operator_spot_order_truth_cancel_projection_missing"
                    )
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    cancel_outcome = %s,
                    cancel_exchange_invoked = CASE
                        WHEN %s THEN TRUE ELSE NULL END,
                    cancel_claim_id = CASE WHEN %s THEN cancel_claim_id ELSE NULL END,
                    cancel_cycle_number = CASE
                        WHEN %s THEN cancel_cycle_number ELSE NULL END,
                    cancel_target_client_order_id = CASE
                        WHEN %s THEN cancel_target_client_order_id ELSE NULL END,
                    cancel_exchange_order_id_sha256 = CASE
                        WHEN %s THEN cancel_exchange_order_id_sha256 ELSE NULL END,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    "UNKNOWN" if invoked else "NOT_RUN",
                    invoked,
                    invoked,
                    invoked,
                    invoked,
                    invoked,
                    (
                        "operator_spot_order_truth_cancel_restart_unknown"
                        if invoked
                        else "operator_spot_order_truth_cancel_interrupted_before_call"
                    ),
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            row = self._select_goal(cursor, for_update=False)
            cursor.execute(
                f"""
                UPDATE {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                SET state = %s,
                    result_json = %s::jsonb,
                    finished_at = NOW()
                WHERE claim_id = %s
                  AND state = 'CLAIMED'
                """,
                (
                    "UNKNOWN" if invoked else "PREBOUNDARY",
                    json.dumps(
                        _record_payload(self._record(row)),
                        sort_keys=True,
                    ),
                    cancel_claim_id,
                ),
            )

    def _store_cycle_record(
        self,
        cursor: Any,
        *,
        cycle_number: int,
        record: SpotOrderTruthGoalRecord,
    ) -> None:
        cursor.execute(
            f"""
            UPDATE {self._table('operator_spot_order_truth_cycle')}
            SET result_json = %s::jsonb
            WHERE cycle_number = %s
              AND result_json IS NULL
            """,
            (
                json.dumps(_record_payload(record), sort_keys=True),
                cycle_number,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(
                "operator_spot_order_truth_cycle_result_missing"
            )

    def _select_goal(self, cursor: Any, *, for_update: bool) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_spot_order_truth_goal')}
            WHERE goal_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (SPOT_ORDER_TRUTH_GOAL_ID,),
        )
        row = _row(cursor)
        if row is None:
            raise RuntimeError("operator_spot_order_truth_goal_missing")
        return row

    def _record(self, row: Mapping[str, Any]) -> SpotOrderTruthGoalRecord:
        attempts = {
            category: int(
                _json_object(row.get("category_attempts_json")).get(
                    category, 0
                )
            )
            for category in SPOT_ORDER_TRUTH_CATEGORIES
        }
        return SpotOrderTruthGoalRecord(
            goal_id=str(row["goal_id"]),
            revision=int(row["revision"]),
            cycles_used=int(row["cycles_used"]),
            active_cycle_number=(
                int(row["active_cycle_number"])
                if row.get("active_cycle_number") is not None
                else None
            ),
            last_action=(
                str(row["last_action"])
                if row.get("last_action") is not None
                else None
            ),
            last_target_client_order_id=(
                str(row["last_target_client_order_id"])
                if row.get("last_target_client_order_id") is not None
                else None
            ),
            last_outcome=str(row["last_outcome"]),
            diagnostic_code=str(row["diagnostic_code"]),
            category_attempts=attempts,
            page_count=int(row["page_count"]),
            order_count=int(row["order_count"]),
            portfolio_id_sha256=(
                str(row["portfolio_id_sha256"])
                if row.get("portfolio_id_sha256")
                else None
            ),
            evidence_sha256=(
                str(row["evidence_sha256"])
                if row.get("evidence_sha256")
                else None
            ),
            cancel_outcome=str(row["cancel_outcome"]),
            cancel_exchange_invoked=(
                bool(row["cancel_exchange_invoked"])
                if row.get("cancel_exchange_invoked") is not None
                else None
            ),
            cancel_target_client_order_id=(
                str(row["cancel_target_client_order_id"])
                if row.get("cancel_target_client_order_id")
                else None
            ),
            cancel_exchange_order_id_sha256=(
                str(row["cancel_exchange_order_id_sha256"])
                if row.get("cancel_exchange_order_id_sha256")
                else None
            ),
            correlation_id=(
                str(row["correlation_id"])
                if row.get("correlation_id")
                else None
            ),
            audit_id=str(row["audit_id"]) if row.get("audit_id") else None,
            refreshed_at=_iso(row.get("refreshed_at")),
            updated_at=_iso(row.get("updated_at")),
        )

    def read_goal(self) -> SpotOrderTruthGoalRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            record = self._record(
                self._select_goal(cursor, for_update=False)
            )
            return record

    def read_cycle_result(
        self,
        *,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[
        bool,
        bool,
        SpotOrderTruthGoalRecord | None,
    ]:
        self.ensure_schema()
        exact_correlation = str(correlation_id or "").strip()
        exact_actor = str(actor_id or "").strip()
        if (
            not exact_correlation
            or len(exact_correlation) > 255
            or not exact_actor
            or len(exact_actor) > 255
        ):
            raise ValueError(
                "operator_spot_order_truth_request_identity_invalid"
            )
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT state, result_json
                FROM {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                WHERE correlation_id = %s
                  AND actor_id = %s
                """,
                (exact_correlation, exact_actor),
            )
            cancel_request = _row(cursor)
            if cancel_request is not None:
                if cancel_request.get("result_json") is None:
                    return True, False, None
                return (
                    True,
                    True,
                    _record_from_payload(cancel_request["result_json"]),
                )
            cursor.execute(
                f"""
                SELECT result_json
                FROM {
                    self._table(
                        'operator_spot_order_truth_cycle'
                    )
                }
                WHERE correlation_id = %s
                  AND actor_id = %s
                """,
                (exact_correlation, exact_actor),
            )
            cycle = _row(cursor)
            if cycle is None:
                return False, False, None
            if cycle.get("result_json") is None:
                return True, False, None
            return (
                True,
                True,
                _record_from_payload(cycle["result_json"]),
            )

    def begin_cycle(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[SpotOrderTruthGoalRecord, int | None, bool]:
        self.ensure_schema()
        if action not in _ACTIONS:
            raise ValueError("operator_spot_order_truth_action_invalid")
        target = str(target_client_order_id or "").strip() or None
        if action == "REFRESH_CATALOG" and target is not None:
            raise ValueError("operator_spot_order_truth_target_invalid")
        if action != "REFRESH_CATALOG" and target is None:
            raise ValueError("operator_spot_order_truth_target_invalid")
        if (
            target is not None
            and _CANONICAL_CLIENT_ORDER_ID_RE.fullmatch(target) is None
        ):
            raise ValueError("operator_spot_order_truth_identity_invalid")
        idem = str(context.idempotency_key or "").strip()
        if not idem:
            raise ValueError("operator_spot_order_truth_idempotency_invalid")
        payload_sha = _payload_hash(
            context,
            action=action,
            target_client_order_id=target,
        )
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_spot_order_truth_cycle')}
                WHERE idempotency_key = %s
                """,
                (idem,),
            )
            previous = _row(cursor)
            if previous is not None:
                if (
                    previous["payload_sha256"] != payload_sha
                    or previous["action"] != action
                    or previous.get("target_client_order_id") != target
                    or previous.get("actor_id") != context.actor_id
                ):
                    raise ValueError(
                        "operator_spot_order_truth_idempotency_conflict"
                    )
                if previous.get("result_json") is None:
                    raise ValueError(
                        "operator_spot_order_truth_idempotency_replay_pending"
                    )
                return (
                    _record_from_payload(previous["result_json"]),
                    None,
                    True,
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {
                    self._table(
                        'operator_spot_order_truth_cycle'
                    )
                }
                WHERE correlation_id = %s
                """,
                (context.correlation_id,),
            )
            if _row(cursor) is not None:
                raise ValueError(
                    "operator_spot_order_truth_correlation_conflict"
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                WHERE correlation_id = %s OR idempotency_key = %s
                """,
                (context.correlation_id, idem),
            )
            if _row(cursor) is not None:
                raise ValueError(
                    "operator_spot_order_truth_request_identity_conflict"
                )
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("cancel_outcome") == "CLAIMED":
                raise ValueError(
                    "operator_spot_order_truth_cancel_active"
                )
            if int(goal["revision"]) != context.expected_revision:
                raise ValueError("operator_spot_order_truth_revision_conflict")
            if goal.get("active_cycle_number") is not None:
                raise ValueError("operator_spot_order_truth_cycle_active")
            cycle_number = int(goal["cycles_used"]) + 1
            if cycle_number > SPOT_ORDER_TRUTH_MAX_CYCLES:
                raise ValueError("operator_spot_order_truth_cycles_exhausted")
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_spot_order_truth_cycle')} (
                        cycle_number, action, target_client_order_id,
                        state, diagnostic_code, idempotency_key,
                        payload_sha256, actor_id, correlation_id, audit_id
                    )
                VALUES (%s, %s, %s, 'CLAIMED', %s, %s, %s, %s, %s, %s)
                """,
                (
                    cycle_number,
                    action,
                    target,
                    "operator_spot_order_truth_cycle_claimed",
                    idem,
                    payload_sha,
                    context.actor_id,
                    context.correlation_id,
                    context.audit_id,
                ),
            )
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    cycles_used = %s,
                    active_cycle_number = %s,
                    last_action = %s,
                    last_target_client_order_id = %s,
                    last_outcome = 'CLAIMED',
                    diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    page_count = 0,
                    correlation_id = %s,
                    audit_id = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    cycle_number,
                    cycle_number,
                    action,
                    target,
                    "operator_spot_order_truth_cycle_claimed",
                    json.dumps(_EMPTY_ATTEMPTS, sort_keys=True),
                    context.correlation_id,
                    context.audit_id,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            return (
                self._record(self._select_goal(cursor, for_update=False)),
                cycle_number,
                False,
            )

    def claim_category(self, *, cycle_number: int, category: str) -> None:
        if category not in SPOT_ORDER_TRUTH_CATEGORIES:
            raise ValueError(
                "operator_spot_order_truth_category_not_authorized"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_spot_order_truth_cycle_not_active")
            try:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self._table('operator_spot_order_truth_category')} (
                            cycle_number, category
                        )
                    VALUES (%s, %s)
                    """,
                    (cycle_number, category),
                )
            except Exception:
                raise ValueError(
                    "operator_spot_order_truth_category_already_claimed"
                ) from None

    def mark_category_invoked(
        self, *, cycle_number: int, category: str
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET call_boundary_entered = TRUE
                WHERE cycle_number = %s
                  AND category = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number, category),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_category_invoke_not_claimed"
                )

    def finish_category(
        self, *, cycle_number: int, category: str, outcome: str
    ) -> None:
        if outcome not in {"RETURNED", "UNKNOWN"}:
            raise ValueError(
                "operator_spot_order_truth_category_outcome_invalid"
            )
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET state = %s,
                    finished_at = NOW()
                WHERE cycle_number = %s
                  AND category = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (outcome, cycle_number, category),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_category_not_active"
                )

    def claim_page(
        self,
        *,
        cycle_number: int,
        page_ordinal: int,
        cursor_sha256: str | None,
    ) -> None:
        if cursor_sha256 is not None and not _SHA256_RE.fullmatch(
            str(cursor_sha256)
        ):
            raise ValueError("operator_spot_order_truth_cursor_hash_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_spot_order_truth_cycle_not_active")
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_spot_order_truth_page')} (
                        cycle_number, page_ordinal, cursor_sha256
                    )
                VALUES (%s, %s, %s)
                """,
                (cycle_number, page_ordinal, cursor_sha256),
            )

    def mark_page_invoked(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET call_boundary_entered = TRUE
                WHERE cycle_number = %s
                  AND page_ordinal = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number, page_ordinal),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_page_invoke_not_claimed"
                )

    def mark_catalog_page_invoked(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None:
        """Atomically enter the catalog category and exact page boundary."""

        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT state, call_boundary_entered
                FROM {self._table('operator_spot_order_truth_category')}
                WHERE cycle_number = %s
                  AND category = 'spot_order_catalog'
                FOR UPDATE
                """,
                (cycle_number,),
            )
            category = _row(cursor)
            if (
                category is None
                or category.get("state") != "CLAIMED"
            ):
                raise ValueError(
                    "operator_spot_order_truth_category_invoke_not_claimed"
                )
            if category.get("call_boundary_entered") is False:
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_category')}
                    SET call_boundary_entered = TRUE
                    WHERE cycle_number = %s
                      AND category = 'spot_order_catalog'
                      AND state = 'CLAIMED'
                      AND call_boundary_entered = FALSE
                    """,
                    (cycle_number,),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "operator_spot_order_truth_category_invoke_not_claimed"
                    )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET call_boundary_entered = TRUE
                WHERE cycle_number = %s
                  AND page_ordinal = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number, page_ordinal),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_page_invoke_not_claimed"
                )

    def finish_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'RETURNED',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND page_ordinal = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number, page_ordinal),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_page_return_not_claimed"
                )

    def fail_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'UNKNOWN',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND page_ordinal = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number, page_ordinal),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_page_unknown_not_claimed"
                )

    def finish_cycle(
        self,
        *,
        cycle_number: int,
        result: SpotOrderCatalogResult,
        context: SpotOrderTruthRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> SpotOrderTruthGoalRecord:
        target = str(target_client_order_id or "").strip() or None
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_spot_order_truth_cycle_not_active")
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET state = 'UNKNOWN',
                    finished_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'UNKNOWN',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_category')}
                SET state = 'PREBOUNDARY',
                    finished_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_page')}
                SET state = 'PREBOUNDARY',
                    returned_at = NOW()
                WHERE cycle_number = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (cycle_number,),
            )
            cursor.execute(
                f"""
                SELECT category, state, call_boundary_entered
                FROM {self._table('operator_spot_order_truth_category')}
                WHERE cycle_number = %s
                """,
                (cycle_number,),
            )
            category_rows = _rows(cursor)
            invoked_categories = {
                item["category"]
                for item in category_rows
                if item.get("call_boundary_entered") is True
            }
            expected_categories = {
                category
                for category, count in result.category_attempts.items()
                if count == 1
            }
            if invoked_categories != expected_categories:
                raise ValueError(
                    "operator_spot_order_truth_category_accounting_mismatch"
                )
            if result.outcome == "SUCCEEDED" and any(
                item["state"] != "RETURNED" for item in category_rows
            ):
                raise ValueError(
                    "operator_spot_order_truth_category_accounting_mismatch"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count,
                       COUNT(*) FILTER (
                           WHERE call_boundary_entered = TRUE
                       ) AS invoked_count,
                       COUNT(*) FILTER (WHERE state = 'RETURNED')
                           AS returned_count
                FROM {self._table('operator_spot_order_truth_page')}
                WHERE cycle_number = %s
                """,
                (cycle_number,),
            )
            page_accounting = _row(cursor) or {}
            invoked_pages = int(
                page_accounting.get("invoked_count") or 0
            )
            returned_pages = int(
                page_accounting.get("returned_count") or 0
            )
            if (
                invoked_pages != result.page_count
                or (
                    result.outcome == "SUCCEEDED"
                    and returned_pages != result.page_count
                )
            ):
                raise ValueError(
                    "operator_spot_order_truth_page_accounting_mismatch"
                )
            outcome = result.outcome
            diagnostic = result.diagnostic_code
            matching = (
                next(
                    (
                        item
                        for item in result.orders
                        if item.client_order_id == target
                    ),
                    None,
                )
                if target
                else None
            )
            if result.outcome == "SUCCEEDED" and target and matching is None:
                outcome = "INELIGIBLE"
                diagnostic = "operator_spot_order_truth_exact_identity_not_found"
            elif (
                result.outcome == "SUCCEEDED"
                and action == "RECONCILE_EXACT"
                and matching is not None
                and matching.status == "UNKNOWN_ORDER_STATUS"
            ):
                outcome = "UNKNOWN"
                diagnostic = (
                    "operator_spot_order_truth_exact_order_status_unknown"
                )
            elif (
                result.outcome == "SUCCEEDED"
                and action == "RECONCILE_EXACT"
                and matching is not None
                and matching.order_type == "UNKNOWN_ORDER_TYPE"
                and not matching.cancel_eligible
            ):
                outcome = "INELIGIBLE"
                diagnostic = (
                    "operator_spot_order_truth_exact_order_type_unknown"
                )
            elif (
                result.outcome == "SUCCEEDED"
                and action == "RECONCILE_EXACT"
                and matching is not None
                and not matching.cancel_eligible
            ):
                outcome = "INELIGIBLE"
                diagnostic = "operator_spot_order_truth_exact_order_terminal"
            if result.outcome == "SUCCEEDED":
                for order in result.orders:
                    if order.ownership_provenance != "ADMIN_MANUAL_ROOT":
                        raise ValueError(
                            "operator_spot_order_truth_local_ownership_unproven"
                        )
                    cursor.execute(
                        f"""
                        INSERT INTO
                            {self._table('operator_spot_order_truth_projection')} (
                                client_order_id, product_id, side, status,
                                order_type, time_in_force, size, limit_price,
                                filled_size, ownership_provenance,
                                created_at, exchange_updated_at,
                                exchange_order_id_sha256,
                                authoritatively_nonterminal, cancel_eligible,
                                observed_cycle_number, observed_at, updated_at
                            )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                        )
                        ON CONFLICT (client_order_id) DO UPDATE SET
                            product_id = EXCLUDED.product_id,
                            side = EXCLUDED.side,
                            status = EXCLUDED.status,
                            order_type = EXCLUDED.order_type,
                            time_in_force = EXCLUDED.time_in_force,
                            size = EXCLUDED.size,
                            limit_price = EXCLUDED.limit_price,
                            filled_size = EXCLUDED.filled_size,
                            ownership_provenance =
                                EXCLUDED.ownership_provenance,
                            created_at = EXCLUDED.created_at,
                            exchange_updated_at = EXCLUDED.exchange_updated_at,
                            exchange_order_id_sha256 =
                                EXCLUDED.exchange_order_id_sha256,
                            authoritatively_nonterminal =
                                EXCLUDED.authoritatively_nonterminal,
                            cancel_eligible = EXCLUDED.cancel_eligible,
                            observed_cycle_number =
                                EXCLUDED.observed_cycle_number,
                            observed_at = NOW(),
                            updated_at = NOW()
                        """,
                        (
                            order.client_order_id,
                            order.product_id,
                            order.side,
                            order.status,
                            order.order_type,
                            order.time_in_force,
                            order.size,
                            order.limit_price,
                            order.filled_size,
                            order.ownership_provenance,
                            order.created_at,
                            order.updated_at,
                            order.exchange_order_id_sha256,
                            order.authoritatively_nonterminal,
                            order.cancel_eligible,
                            cycle_number,
                        ),
                    )
                if action == "REFRESH_CATALOG":
                    cursor.execute(
                        f"""
                        UPDATE
                            {self._table('operator_spot_order_truth_projection')}
                        SET authoritatively_nonterminal = FALSE,
                            cancel_eligible = FALSE,
                            updated_at = NOW()
                        WHERE observed_cycle_number <> %s
                          AND (
                              authoritatively_nonterminal = TRUE
                              OR cancel_eligible = TRUE
                          )
                        """,
                        (cycle_number,),
                    )
                elif (
                    action == "RECONCILE_EXACT"
                    and target is not None
                    and matching is None
                ):
                    cursor.execute(
                        f"""
                        UPDATE
                            {self._table('operator_spot_order_truth_projection')}
                        SET authoritatively_nonterminal = FALSE,
                            cancel_eligible = FALSE,
                            updated_at = NOW()
                        WHERE client_order_id = %s
                          AND (
                              authoritatively_nonterminal = TRUE
                              OR cancel_eligible = TRUE
                          )
                        """,
                        (target,),
                    )
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self._table('operator_spot_order_truth_projection')}
                """
            )
            order_count = int((_row(cursor) or {}).get("count") or 0)
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_cycle')}
                SET state = %s,
                    diagnostic_code = %s,
                    finished_at = NOW()
                WHERE cycle_number = %s AND state = 'CLAIMED'
                """,
                (outcome, diagnostic, cycle_number),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    active_cycle_number = NULL,
                    last_outcome = %s,
                    diagnostic_code = %s,
                    category_attempts_json = %s::jsonb,
                    page_count = %s,
                    order_count = %s,
                    portfolio_id_sha256 = %s,
                    evidence_sha256 = %s,
                    correlation_id = %s,
                    audit_id = %s,
                    refreshed_at = NOW(),
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    outcome,
                    diagnostic,
                    json.dumps(result.category_attempts, sort_keys=True),
                    result.page_count,
                    order_count,
                    result.portfolio_id_sha256,
                    result.evidence_sha256,
                    context.correlation_id,
                    context.audit_id,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_spot_order_truth_event')} (
                        event_id, event_type, cycle_number, client_order_id,
                        diagnostic_code, correlation_id, audit_id, evidence_json
                    )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    action,
                    cycle_number,
                    target,
                    diagnostic,
                    context.correlation_id,
                    context.audit_id,
                    json.dumps(
                        {
                            "outcome": outcome,
                            "evidence_sha256": result.evidence_sha256,
                            "page_count": result.page_count,
                            "raw_responses_included": False,
                            "private_identifiers_included": False,
                            "exception_text_included": False,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            terminal = self._record(
                self._select_goal(cursor, for_update=False)
            )
            self._store_cycle_record(
                cursor,
                cycle_number=cycle_number,
                record=terminal,
            )
            return terminal

    def claim_cancel(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        client_order_id: str,
        exchange_order_id_sha256: str,
        payload_sha256: str | None = None,
        expected_evidence_sha256: str | None = None,
        expected_portfolio_id_sha256: str | None = None,
    ) -> tuple[SpotOrderTruthGoalRecord, str, bool]:
        exact_id = str(client_order_id or "").strip()
        exchange_hash = str(exchange_order_id_sha256 or "").strip().lower()
        payload_hash = str(payload_sha256 or "").strip().lower() or _payload_hash(
            context,
            action="CANCEL_EXACT",
            target_client_order_id=exact_id,
        )
        if (
            _CANONICAL_CLIENT_ORDER_ID_RE.fullmatch(exact_id) is None
            or not _SHA256_RE.fullmatch(exchange_hash)
            or not _SHA256_RE.fullmatch(payload_hash)
        ):
            raise ValueError("operator_spot_order_truth_cancel_binding_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT *
                FROM {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                WHERE idempotency_key = %s OR correlation_id = %s
                """,
                (context.idempotency_key, context.correlation_id),
            )
            previous = _row(cursor)
            if previous is not None:
                if (
                    previous["idempotency_key"] != context.idempotency_key
                    or previous["correlation_id"] != context.correlation_id
                    or previous["payload_sha256"] != payload_hash
                    or previous["actor_id"] != context.actor_id
                    or previous["client_order_id"] != exact_id
                    or previous["exchange_order_id_sha256"] != exchange_hash
                ):
                    raise ValueError(
                        "operator_spot_order_truth_cancel_idempotency_conflict"
                    )
                if previous.get("result_json") is None:
                    raise ValueError(
                        "operator_spot_order_truth_cancel_request_pending"
                    )
                return (
                    _record_from_payload(previous["result_json"]),
                    str(previous["claim_id"]),
                    True,
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self._table('operator_spot_order_truth_cycle')}
                WHERE correlation_id = %s OR idempotency_key = %s
                """,
                (context.correlation_id, context.idempotency_key),
            )
            if _row(cursor) is not None:
                raise ValueError(
                    "operator_spot_order_truth_request_identity_conflict"
                )
            goal = self._select_goal(cursor, for_update=True)
            if goal["cancel_outcome"] != "NOT_RUN":
                raise ValueError(
                    "operator_spot_order_truth_cancel_allowance_consumed"
                )
            if (
                int(goal["cycles_used"]) != SPOT_ORDER_TRUTH_MAX_CYCLES
                or goal.get("active_cycle_number") is not None
                or goal["last_outcome"] != "SUCCEEDED"
                or int(goal["revision"]) != context.expected_revision
                or (
                    expected_evidence_sha256 is not None
                    and goal.get("evidence_sha256")
                    != expected_evidence_sha256
                )
                or (
                    expected_portfolio_id_sha256 is not None
                    and goal.get("portfolio_id_sha256")
                    != expected_portfolio_id_sha256
                )
            ):
                raise ValueError(
                    "operator_spot_order_truth_cancel_reconciliation_required"
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_spot_order_truth_projection')}
                WHERE client_order_id = %s
                  AND exchange_order_id_sha256 = %s
                  AND ownership_provenance = 'ADMIN_MANUAL_ROOT'
                  AND cancel_eligible = TRUE
                  AND authoritatively_nonterminal = TRUE
                  AND status = 'OPEN'
                  AND order_type = ANY(%s)
                  AND observed_cycle_number = %s
                """,
                (
                    exact_id,
                    exchange_hash,
                    list(_CANCEL_ELIGIBLE_ORDER_TYPES),
                    goal["cycles_used"],
                ),
            )
            if _row(cursor) is None:
                raise ValueError(
                    "operator_spot_order_truth_cancel_reconciliation_required"
                )
            claim_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                INSERT INTO {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                } (
                    request_id, claim_id, client_order_id,
                    exchange_order_id_sha256, idempotency_key,
                    payload_sha256, actor_id, correlation_id, audit_id, state
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'CLAIMED')
                """,
                (
                    request_id,
                    claim_id,
                    exact_id,
                    exchange_hash,
                    context.idempotency_key,
                    payload_hash,
                    context.actor_id,
                    context.correlation_id,
                    context.audit_id,
                ),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    last_action = 'CANCEL_EXACT',
                    last_target_client_order_id = %s,
                    cancel_outcome = 'CLAIMED',
                    cancel_exchange_invoked = FALSE,
                    cancel_target_client_order_id = %s,
                    cancel_exchange_order_id_sha256 = %s,
                    cancel_claim_id = %s,
                    cancel_cycle_number = %s,
                    diagnostic_code = %s,
                    correlation_id = %s,
                    audit_id = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    exact_id,
                    exact_id,
                    exchange_hash,
                    claim_id,
                    goal["cycles_used"],
                    "operator_spot_order_truth_cancel_claimed",
                    context.correlation_id,
                    context.audit_id,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            claimed = self._record(
                self._select_goal(cursor, for_update=False)
            )
            return claimed, claim_id, False

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                SET call_boundary_entered = TRUE
                WHERE claim_id = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = FALSE
                """,
                (claim_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_cancel_invoke_not_claimed"
                )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET cancel_exchange_invoked = TRUE,
                    updated_at = NOW()
                WHERE goal_id = %s
                  AND cancel_claim_id = %s
                  AND cancel_outcome = 'CLAIMED'
                  AND cancel_exchange_invoked = FALSE
                """,
                (SPOT_ORDER_TRUTH_GOAL_ID, claim_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_cancel_invoke_not_claimed"
                )

    def release_cancel_before_exchange(
        self,
        *,
        claim_id: str,
    ) -> SpotOrderTruthGoalRecord:
        return self._release_cancel_before_sdk(
            claim_id=claim_id,
            durable_marker_entered=False,
            diagnostic_code=(
                "operator_spot_order_truth_cancel_pre_call_blocked"
            ),
            event_type="CANCEL_EXACT_PRE_CALL_BLOCKED",
        )

    def restore_cancel_before_sdk(
        self,
        *,
        claim_id: str,
    ) -> SpotOrderTruthGoalRecord:
        """Restore a marked claim only when typed evidence proves no SDK call."""

        return self._release_cancel_before_sdk(
            claim_id=claim_id,
            durable_marker_entered=True,
            diagnostic_code=(
                "operator_spot_order_truth_cancel_pre_sdk_authority_blocked"
            ),
            event_type="CANCEL_EXACT_PRE_SDK_AUTHORITY_BLOCKED",
        )

    def _release_cancel_before_sdk(
        self,
        *,
        claim_id: str,
        durable_marker_entered: bool,
        diagnostic_code: str,
        event_type: str,
    ) -> SpotOrderTruthGoalRecord:
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if (
                str(goal.get("cancel_claim_id") or "") != claim_id
                or goal["cancel_outcome"] != "CLAIMED"
                or goal.get("cancel_exchange_invoked")
                is not durable_marker_entered
            ):
                raise ValueError(
                    "operator_spot_order_truth_cancel_release_not_claimed"
                )
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    cancel_outcome = 'NOT_RUN',
                    cancel_exchange_invoked = NULL,
                    cancel_target_client_order_id = NULL,
                    cancel_exchange_order_id_sha256 = NULL,
                    cancel_claim_id = NULL,
                    cancel_cycle_number = NULL,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    diagnostic_code,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_spot_order_truth_event')} (
                        event_id, event_type, cycle_number, client_order_id,
                        diagnostic_code, correlation_id, audit_id, evidence_json
                    )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    event_type,
                    goal["cycles_used"],
                    goal["cancel_target_client_order_id"],
                    diagnostic_code,
                    goal["correlation_id"],
                    goal["audit_id"],
                    json.dumps(
                        {
                            "call_boundary_entered": False,
                            "durable_marker_entered": (
                                durable_marker_entered
                            ),
                            "sdk_invocation_proven_absent": True,
                            "raw_response_included": False,
                            "private_identifiers_included": False,
                            "exception_text_included": False,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            released = self._record(
                self._select_goal(cursor, for_update=False)
            )
            cursor.execute(
                f"""
                UPDATE {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                SET state = 'PREBOUNDARY',
                    call_boundary_entered = FALSE,
                    result_json = %s::jsonb,
                    finished_at = NOW()
                WHERE claim_id = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = %s
                """,
                (
                    json.dumps(_record_payload(released), sort_keys=True),
                    claim_id,
                    durable_marker_entered,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_cancel_request_missing"
                )
            return released

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> SpotOrderTruthGoalRecord:
        outcome = str(getattr(execution, "outcome", ""))
        diagnostic = str(getattr(execution, "diagnostic_code", ""))
        exchange_hash = str(
            getattr(execution, "exchange_order_id_sha256", "")
        )
        if outcome not in {"ACCEPTED", "REJECTED", "UNKNOWN"}:
            raise ValueError("operator_spot_order_truth_cancel_outcome_invalid")
        if not diagnostic.startswith("operator_spot_order_truth_cancel_"):
            raise ValueError("operator_spot_order_truth_cancel_diagnostic_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if (
                str(goal.get("cancel_claim_id") or "") != claim_id
                or goal["cancel_outcome"] != "CLAIMED"
                or goal.get("cancel_exchange_invoked") is not True
                or goal.get("cancel_exchange_order_id_sha256")
                != exchange_hash
            ):
                raise ValueError(
                    "operator_spot_order_truth_cancel_finish_not_claimed"
                )
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_spot_order_truth_goal')}
                SET revision = %s,
                    cancel_outcome = %s,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    outcome,
                    diagnostic,
                    SPOT_ORDER_TRUTH_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_spot_order_truth_event')} (
                        event_id, event_type, cycle_number, client_order_id,
                        diagnostic_code, correlation_id, audit_id, evidence_json
                    )
                VALUES (%s, 'CANCEL_EXACT_TERMINAL', %s, %s, %s, %s, %s,
                        %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    goal["cycles_used"],
                    goal["cancel_target_client_order_id"],
                    diagnostic,
                    goal["correlation_id"],
                    goal["audit_id"],
                    json.dumps(
                        {
                            "outcome": outcome,
                            "exchange_order_id_sha256": exchange_hash,
                            "raw_response_included": False,
                            "private_identifiers_included": False,
                            "exception_text_included": False,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            if outcome == "ACCEPTED":
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_projection')}
                    SET status = 'CANCELLED',
                        authoritatively_nonterminal = FALSE,
                        cancel_eligible = FALSE,
                        updated_at = NOW()
                    WHERE client_order_id = %s
                      AND exchange_order_id_sha256 = %s
                    """,
                    (
                        goal["cancel_target_client_order_id"],
                        exchange_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "operator_spot_order_truth_cancel_projection_missing"
                    )
            elif outcome == "UNKNOWN":
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_spot_order_truth_projection')}
                    SET authoritatively_nonterminal = FALSE,
                        cancel_eligible = FALSE,
                        updated_at = NOW()
                    WHERE client_order_id = %s
                      AND exchange_order_id_sha256 = %s
                    """,
                    (
                        goal["cancel_target_client_order_id"],
                        exchange_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "operator_spot_order_truth_cancel_projection_missing"
                    )
            terminal = self._record(
                self._select_goal(cursor, for_update=False)
            )
            cursor.execute(
                f"""
                UPDATE {
                    self._table(
                        'operator_spot_order_truth_cancel_request'
                    )
                }
                SET state = %s,
                    result_json = %s::jsonb,
                    finished_at = NOW()
                WHERE claim_id = %s
                  AND state = 'CLAIMED'
                  AND call_boundary_entered = TRUE
                """,
                (
                    outcome,
                    json.dumps(_record_payload(terminal), sort_keys=True),
                    claim_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_spot_order_truth_cancel_request_missing"
                )
            return terminal

    def list_orders(
        self,
        *,
        product_id: str | None,
        order_status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        self.ensure_schema()
        exact_product = str(product_id or "").strip() or None
        exact_status = str(order_status or "").strip().upper() or None
        if limit < 1 or limit > 100 or offset < 0:
            raise ValueError("operator_spot_order_truth_pagination_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if exact_product:
            conditions.append("product_id = %s")
            params.append(exact_product)
        if exact_status:
            conditions.append("status = %s")
            params.append(exact_status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self._table('operator_spot_order_truth_projection')}
                {where}
                """,
                tuple(params),
            )
            total = int((_row(cursor) or {}).get("count") or 0)
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_spot_order_truth_projection')}
                {where}
                ORDER BY exchange_updated_at DESC NULLS LAST,
                         created_at DESC NULLS LAST,
                         client_order_id ASC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, limit, offset]),
            )
            items = [self._projection(item) for item in _rows(cursor)]
        next_offset = offset + len(items)
        has_more = next_offset < total
        return {
            "filters": {
                "product_id": exact_product,
                "order_status": exact_status,
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned_count": len(items),
                "total_matching_count": total,
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            "items": items,
            "raw_responses_included": False,
            "private_identifiers_included": False,
        }

    def get_order(self, client_order_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        exact_id = str(client_order_id or "").strip()
        if _CANONICAL_CLIENT_ORDER_ID_RE.fullmatch(exact_id) is None:
            return None
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_spot_order_truth_projection')}
                WHERE client_order_id = %s
                """,
                (exact_id,),
            )
            item = _row(cursor)
        return self._projection(item) if item is not None else None

    @staticmethod
    def _projection(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "client_order_id": str(row["client_order_id"]),
            "product_id": str(row["product_id"]),
            "side": str(row["side"]),
            "status": str(row["status"]),
            "order_type": str(row["order_type"]),
            "time_in_force": str(row["time_in_force"]),
            "size": str(row["size"]) if row.get("size") is not None else None,
            "limit_price": (
                str(row["limit_price"])
                if row.get("limit_price") is not None
                else None
            ),
            "filled_size": (
                str(row["filled_size"])
                if row.get("filled_size") is not None
                else None
            ),
            "ownership_provenance": str(row["ownership_provenance"]),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("exchange_updated_at")),
            "observed_at": _iso(row.get("observed_at")),
            "exchange_order_id_sha256": str(
                row["exchange_order_id_sha256"]
            ),
            "authoritatively_nonterminal": bool(
                row["authoritatively_nonterminal"]
            ),
            "cancel_eligible": bool(row["cancel_eligible"]),
        }


_DEFAULT_REPOSITORY: OperatorSpotOrderTruthRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_operator_spot_order_truth_repository(
) -> OperatorSpotOrderTruthRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                from database import order as order_db

                _DEFAULT_REPOSITORY = (
                    OperatorSpotOrderTruthRepository(
                        order_db.DB_CLIENT
                    )
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def reset_operator_spot_order_truth_repository_for_tests() -> None:
    global _DEFAULT_REPOSITORY
    with _DEFAULT_REPOSITORY_LOCK:
        _DEFAULT_REPOSITORY = None


__all__ = [
    "OperatorSpotOrderTruthRepository",
    "get_default_operator_spot_order_truth_repository",
    "reset_operator_spot_order_truth_repository_for_tests",
]
