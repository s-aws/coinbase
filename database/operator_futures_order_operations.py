"""PostgreSQL authority for Default-profile Futures order operations."""

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

from application.admin_api.operator_futures_order_operations import (
    FUTURES_ORDER_OPERATIONS_CATEGORIES,
    FUTURES_ORDER_OPERATIONS_GOAL_ID,
    FUTURES_ORDER_OPERATIONS_MAX_CYCLES,
    FuturesOrderCatalogResult,
)
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsGoalRecord,
    FuturesOrderOperationsRequestContext,
)
from database.operator_futures_cancel_invocation_seal import (
    ensure_futures_cancel_invocation_seal,
    futures_cancel_invocation_is_sealed,
    seal_futures_cancel_invocation,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIONS = frozenset(
    {"REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"}
)
_EMPTY_ATTEMPTS = {
    category: 0 for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
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
        raise ValueError("operator_futures_orders_stored_json_invalid")
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
    context: FuturesOrderOperationsRequestContext,
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
                "acknowledge_cycle_is_goal_global_and_limited_to_ten": (
                    context
                    .acknowledge_cycle_is_goal_global_and_limited_to_ten
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
    item.name for item in fields(FuturesOrderOperationsGoalRecord)
}


def _record_payload(
    record: FuturesOrderOperationsGoalRecord,
) -> dict[str, Any]:
    return asdict(record)


def _record_from_payload(value: Any) -> FuturesOrderOperationsGoalRecord:
    payload = _json_object(value)
    if set(payload) != _GOAL_RECORD_KEYS:
        raise ValueError(
            "operator_futures_orders_idempotency_replay_invalid"
        )
    return FuturesOrderOperationsGoalRecord(**payload)


class OperatorFuturesOrderOperationsRepository:
    """Serialize the ten read cycles and independent single Cancel allowance."""

    def __init__(
        self,
        db: Any,
        *,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("operator_futures_orders_schema_invalid")
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
                ensure_futures_cancel_invocation_seal(
                    cursor,
                    schema=self.schema,
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_operations_goal')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        revision INTEGER NOT NULL DEFAULT 0
                            CHECK (revision >= 0),
                        cycles_used INTEGER NOT NULL DEFAULT 0
                            CHECK (cycles_used BETWEEN 0 AND 10),
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
                        {self._table('operator_futures_order_operations_goal')}
                    ADD COLUMN IF NOT EXISTS cancel_cycle_number INTEGER
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_operations_cycle')} (
                        cycle_number INTEGER PRIMARY KEY
                            CHECK (cycle_number BETWEEN 1 AND 10),
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
                        {self._table('operator_futures_order_operations_cycle')}
                    ADD COLUMN IF NOT EXISTS result_json JSONB
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        operator_futures_order_operations_cycle_correlation_uidx
                    ON {self._table('operator_futures_order_operations_cycle')}
                        (correlation_id)
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_operations_category')} (
                        cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_futures_order_operations_cycle')}
                            (cycle_number),
                        category VARCHAR(64) NOT NULL,
                        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (cycle_number, category)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_operations_page')} (
                        cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_futures_order_operations_cycle')}
                            (cycle_number),
                        page_ordinal INTEGER NOT NULL
                            CHECK (page_ordinal BETWEEN 1 AND 100),
                        cursor_sha256 CHAR(64),
                        state VARCHAR(16) NOT NULL DEFAULT 'CLAIMED'
                            CHECK (state IN ('CLAIMED', 'RETURNED')),
                        call_boundary_entered BOOLEAN NOT NULL DEFAULT FALSE,
                        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        returned_at TIMESTAMPTZ,
                        PRIMARY KEY (cycle_number, page_ordinal)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_projection')} (
                        client_order_id VARCHAR(128) PRIMARY KEY,
                        product_id VARCHAR(128) NOT NULL,
                        side VARCHAR(8) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                        status VARCHAR(32) NOT NULL,
                        order_type VARCHAR(32) NOT NULL,
                        time_in_force VARCHAR(32) NOT NULL,
                        size VARCHAR(128),
                        limit_price VARCHAR(128),
                        filled_size VARCHAR(128),
                        created_at TIMESTAMPTZ,
                        exchange_updated_at TIMESTAMPTZ,
                        exchange_order_id_sha256 CHAR(64) NOT NULL,
                        authoritatively_nonterminal BOOLEAN NOT NULL,
                        cancel_eligible BOOLEAN NOT NULL,
                        observed_cycle_number INTEGER NOT NULL REFERENCES
                            {self._table('operator_futures_order_operations_cycle')}
                            (cycle_number),
                        observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_order_projection')}
                    ADD COLUMN IF NOT EXISTS cancel_eligible BOOLEAN
                    """
                )
                cursor.execute(
                    f"""
                    UPDATE
                        {self._table('operator_futures_order_projection')}
                    SET cancel_eligible = (status = 'OPEN')
                    WHERE cancel_eligible IS NULL
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE
                        {self._table('operator_futures_order_projection')}
                    ALTER COLUMN cancel_eligible SET NOT NULL
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_order_operations_event')} (
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
                        {self._table('operator_futures_order_operations_goal')} (
                            goal_id,
                            diagnostic_code,
                            category_attempts_json
                        )
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (goal_id) DO NOTHING
                    """,
                    (
                        FUTURES_ORDER_OPERATIONS_GOAL_ID,
                        "operator_futures_orders_not_refreshed",
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
                UPDATE {self._table('operator_futures_order_operations_cycle')}
                SET state = 'UNKNOWN',
                    diagnostic_code = %s,
                    finished_at = NOW()
                WHERE cycle_number = %s AND state = 'CLAIMED'
                """,
                (
                    "operator_futures_orders_catalog_restart_unknown",
                    cycle_number,
                ),
            )
            revision += 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
                SET revision = %s,
                    active_cycle_number = NULL,
                    last_outcome = 'UNKNOWN',
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    "operator_futures_orders_catalog_restart_unknown",
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
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
            cancel_cycle_number = int(row["cancel_cycle_number"])
            revision = int(row["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
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
                        "operator_futures_order_cancel_restart_unknown"
                        if invoked
                        else "operator_futures_order_cancel_interrupted_before_call"
                    ),
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            recovered_row = self._select_goal(cursor, for_update=False)
            self._store_cycle_record(
                cursor,
                cycle_number=cancel_cycle_number,
                record=self._record(recovered_row),
            )
            row = recovered_row
        if (
            row.get("cancel_outcome") == "NOT_RUN"
            and row.get("active_cycle_number") is None
            and row.get("last_action") == "CANCEL_EXACT"
            and row.get("last_outcome") == "SUCCEEDED"
        ):
            cycle_number = int(row["cycles_used"])
            cursor.execute(
                f"""
                SELECT result_json
                FROM {self._table('operator_futures_order_operations_cycle')}
                WHERE cycle_number = %s
                  AND action = 'CANCEL_EXACT'
                  AND state = 'SUCCEEDED'
                """,
                (cycle_number,),
            )
            pending = _row(cursor)
            if pending is not None and pending.get("result_json") is None:
                revision = int(row["revision"]) + 1
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_futures_order_operations_goal')}
                    SET revision = %s,
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
                        "operator_futures_order_cancel_interrupted_before_claim",
                        FUTURES_ORDER_OPERATIONS_GOAL_ID,
                    ),
                )
                recovered_row = self._select_goal(
                    cursor,
                    for_update=False,
                )
                self._store_cycle_record(
                    cursor,
                    cycle_number=cycle_number,
                    record=self._record(recovered_row),
                )

    def _store_cycle_record(
        self,
        cursor: Any,
        *,
        cycle_number: int,
        record: FuturesOrderOperationsGoalRecord,
    ) -> None:
        cursor.execute(
            f"""
            UPDATE {self._table('operator_futures_order_operations_cycle')}
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
                "operator_futures_orders_cycle_result_missing"
            )

    def _select_goal(self, cursor: Any, *, for_update: bool) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_futures_order_operations_goal')}
            WHERE goal_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (FUTURES_ORDER_OPERATIONS_GOAL_ID,),
        )
        row = _row(cursor)
        if row is None:
            raise RuntimeError("operator_futures_orders_goal_missing")
        return row

    def _record(self, row: Mapping[str, Any]) -> FuturesOrderOperationsGoalRecord:
        attempts = {
            category: int(
                _json_object(row.get("category_attempts_json")).get(
                    category, 0
                )
            )
            for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
        }
        return FuturesOrderOperationsGoalRecord(
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

    def read_goal(self) -> FuturesOrderOperationsGoalRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            record = self._record(
                self._select_goal(cursor, for_update=False)
            )
            if (
                record.cancel_outcome == "NOT_RUN"
                and record.active_cycle_number is None
            ):
                cursor.execute(
                    f"""
                    SELECT cycle_number
                    FROM {
                        self._table(
                            'operator_futures_order_operations_cycle'
                        )
                    }
                    WHERE action = 'CANCEL_EXACT'
                      AND state = 'SUCCEEDED'
                      AND result_json IS NULL
                    ORDER BY cycle_number
                    LIMIT 1
                    """
                )
                pending = _row(cursor)
                if pending is not None:
                    return replace(
                        record,
                        active_cycle_number=int(
                            pending["cycle_number"]
                        ),
                        last_outcome="CLAIMED",
                        diagnostic_code=(
                            "operator_futures_order_cancel_transition_pending"
                        ),
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
        FuturesOrderOperationsGoalRecord | None,
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
                "operator_futures_orders_request_identity_invalid"
            )
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT result_json
                FROM {
                    self._table(
                        'operator_futures_order_operations_cycle'
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
        context: FuturesOrderOperationsRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[FuturesOrderOperationsGoalRecord, int | None, bool]:
        self.ensure_schema()
        if action not in _ACTIONS:
            raise ValueError("operator_futures_orders_action_invalid")
        target = str(target_client_order_id or "").strip() or None
        if action == "REFRESH_CATALOG" and target is not None:
            raise ValueError("operator_futures_orders_target_invalid")
        if action != "REFRESH_CATALOG" and target is None:
            raise ValueError("operator_futures_orders_target_invalid")
        idem = str(context.idempotency_key or "").strip()
        if not idem:
            raise ValueError("operator_futures_orders_idempotency_invalid")
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
                FROM {self._table('operator_futures_order_operations_cycle')}
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
                        "operator_futures_orders_idempotency_conflict"
                    )
                if previous.get("result_json") is None:
                    raise ValueError(
                        "operator_futures_orders_idempotency_replay_pending"
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
                        'operator_futures_order_operations_cycle'
                    )
                }
                WHERE correlation_id = %s
                """,
                (context.correlation_id,),
            )
            if _row(cursor) is not None:
                raise ValueError(
                    "operator_futures_orders_correlation_conflict"
                )
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("cancel_outcome") == "CLAIMED":
                raise ValueError(
                    "operator_futures_order_cancel_active"
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self._table('operator_futures_order_operations_cycle')}
                WHERE action = 'CANCEL_EXACT'
                  AND state = 'SUCCEEDED'
                  AND result_json IS NULL
                LIMIT 1
                """
            )
            if _row(cursor) is not None:
                raise ValueError(
                    "operator_futures_order_cancel_active"
                )
            if int(goal["revision"]) != context.expected_revision:
                raise ValueError("operator_futures_orders_revision_conflict")
            if goal.get("active_cycle_number") is not None:
                raise ValueError("operator_futures_orders_cycle_active")
            cycle_number = int(goal["cycles_used"]) + 1
            if cycle_number > FUTURES_ORDER_OPERATIONS_MAX_CYCLES:
                raise ValueError("operator_futures_orders_cycles_exhausted")
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_order_operations_cycle')} (
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
                    "operator_futures_orders_cycle_claimed",
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
                UPDATE {self._table('operator_futures_order_operations_goal')}
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
                    "operator_futures_orders_cycle_claimed",
                    json.dumps(_EMPTY_ATTEMPTS, sort_keys=True),
                    context.correlation_id,
                    context.audit_id,
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            return (
                self._record(self._select_goal(cursor, for_update=False)),
                cycle_number,
                False,
            )

    def claim_category(self, *, cycle_number: int, category: str) -> None:
        if category not in FUTURES_ORDER_OPERATIONS_CATEGORIES:
            raise ValueError(
                "operator_futures_orders_category_not_authorized"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_futures_orders_cycle_not_active")
            try:
                cursor.execute(
                    f"""
                    INSERT INTO
                        {self._table('operator_futures_order_operations_category')} (
                            cycle_number, category
                        )
                    VALUES (%s, %s)
                    """,
                    (cycle_number, category),
                )
            except Exception:
                raise ValueError(
                    "operator_futures_orders_category_already_claimed"
                ) from None

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
            raise ValueError("operator_futures_orders_cursor_hash_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_futures_orders_cycle_not_active")
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_order_operations_page')} (
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
                UPDATE {self._table('operator_futures_order_operations_page')}
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
                    "operator_futures_orders_page_invoke_not_claimed"
                )

    def finish_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_page')}
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
                    "operator_futures_orders_page_return_not_claimed"
                )

    def finish_cycle(
        self,
        *,
        cycle_number: int,
        result: FuturesOrderCatalogResult,
        context: FuturesOrderOperationsRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> FuturesOrderOperationsGoalRecord:
        target = str(target_client_order_id or "").strip() or None
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal.get("active_cycle_number") != cycle_number:
                raise ValueError("operator_futures_orders_cycle_not_active")
            cursor.execute(
                f"""
                SELECT category
                FROM {self._table('operator_futures_order_operations_category')}
                WHERE cycle_number = %s
                """,
                (cycle_number,),
            )
            claimed_categories = {item["category"] for item in _rows(cursor)}
            expected_categories = {
                category
                for category, count in result.category_attempts.items()
                if count == 1
            }
            if claimed_categories != expected_categories:
                raise ValueError(
                    "operator_futures_orders_category_accounting_mismatch"
                )
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count,
                       COUNT(*) FILTER (WHERE state = 'RETURNED')
                           AS returned_count
                FROM {self._table('operator_futures_order_operations_page')}
                WHERE cycle_number = %s
                """,
                (cycle_number,),
            )
            page_accounting = _row(cursor) or {}
            claimed_pages = int(page_accounting.get("count") or 0)
            returned_pages = int(
                page_accounting.get("returned_count") or 0
            )
            if (
                claimed_pages != result.page_count
                or (
                    result.outcome == "SUCCEEDED"
                    and returned_pages != result.page_count
                )
            ):
                raise ValueError(
                    "operator_futures_orders_page_accounting_mismatch"
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
                diagnostic = "operator_futures_order_exact_identity_not_found"
            elif (
                result.outcome == "SUCCEEDED"
                and action == "CANCEL_EXACT"
                and matching is not None
                and matching.status == "UNKNOWN_ORDER_STATUS"
            ):
                outcome = "UNKNOWN"
                diagnostic = (
                    "operator_futures_order_exact_order_status_unknown"
                )
            elif (
                result.outcome == "SUCCEEDED"
                and action == "CANCEL_EXACT"
                and matching is not None
                and matching.order_type == "UNKNOWN_ORDER_TYPE"
                and not matching.cancel_eligible
            ):
                outcome = "INELIGIBLE"
                diagnostic = (
                    "operator_futures_order_exact_order_type_unknown"
                )
            elif (
                result.outcome == "SUCCEEDED"
                and action == "CANCEL_EXACT"
                and matching is not None
                and not matching.cancel_eligible
            ):
                outcome = "INELIGIBLE"
                diagnostic = "operator_futures_order_exact_order_terminal"
            if result.outcome == "SUCCEEDED":
                for order in result.orders:
                    cursor.execute(
                        f"""
                        INSERT INTO
                            {self._table('operator_futures_order_projection')} (
                                client_order_id, product_id, side, status,
                                order_type, time_in_force, size, limit_price,
                                filled_size, created_at, exchange_updated_at,
                                exchange_order_id_sha256,
                                authoritatively_nonterminal, cancel_eligible,
                                observed_cycle_number, observed_at, updated_at
                            )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, NOW(), NOW()
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
                            {self._table('operator_futures_order_projection')}
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
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self._table('operator_futures_order_projection')}
                """
            )
            order_count = int((_row(cursor) or {}).get("count") or 0)
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_cycle')}
                SET state = %s,
                    diagnostic_code = %s,
                    finished_at = NOW()
                WHERE cycle_number = %s AND state = 'CLAIMED'
                """,
                (outcome, diagnostic, cycle_number),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
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
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_order_operations_event')} (
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
            if not (
                action == "CANCEL_EXACT"
                and outcome == "SUCCEEDED"
                and result.credential_can_trade is True
            ):
                self._store_cycle_record(
                    cursor,
                    cycle_number=cycle_number,
                    record=terminal,
                )
            return terminal

    def claim_cancel(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        client_order_id: str,
        exchange_order_id_sha256: str,
    ) -> tuple[FuturesOrderOperationsGoalRecord, str]:
        exact_id = str(client_order_id or "").strip()
        exchange_hash = str(exchange_order_id_sha256 or "").strip().lower()
        if not exact_id or not _SHA256_RE.fullmatch(exchange_hash):
            raise ValueError("operator_futures_order_cancel_binding_invalid")
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if goal["cancel_outcome"] != "NOT_RUN":
                raise ValueError(
                    "operator_futures_order_cancel_allowance_consumed"
                )
            if (
                goal["last_action"] != "CANCEL_EXACT"
                or goal.get("last_target_client_order_id") != exact_id
                or goal["last_outcome"] != "SUCCEEDED"
            ):
                raise ValueError(
                    "operator_futures_order_cancel_reconciliation_required"
                )
            if futures_cancel_invocation_is_sealed(
                cursor,
                schema=self.schema,
                portfolio_id_sha256=str(
                    goal.get("portfolio_id_sha256") or ""
                ),
                client_order_id=exact_id,
            ):
                raise ValueError(
                    "operator_futures_cancel_invocation_already_sealed"
                )
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_futures_order_projection')}
                WHERE client_order_id = %s
                  AND exchange_order_id_sha256 = %s
                  AND cancel_eligible = TRUE
                  AND observed_cycle_number = %s
                """,
                (exact_id, exchange_hash, goal["cycles_used"]),
            )
            if _row(cursor) is None:
                raise ValueError(
                    "operator_futures_order_cancel_reconciliation_required"
                )
            cursor.execute(
                f"""
                SELECT 1
                FROM {self._table('operator_futures_order_operations_cycle')}
                WHERE cycle_number = %s
                  AND action = 'CANCEL_EXACT'
                  AND state = 'SUCCEEDED'
                  AND result_json IS NULL
                """,
                (goal["cycles_used"],),
            )
            if _row(cursor) is None:
                raise ValueError(
                    "operator_futures_order_cancel_cycle_not_pending"
                )
            claim_id = str(uuid.uuid4())
            revision = int(goal["revision"]) + 1
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
                SET revision = %s,
                    cancel_outcome = 'CLAIMED',
                    cancel_exchange_invoked = FALSE,
                    cancel_target_client_order_id = %s,
                    cancel_exchange_order_id_sha256 = %s,
                    cancel_claim_id = %s,
                    cancel_cycle_number = %s,
                    diagnostic_code = %s,
                    updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    revision,
                    exact_id,
                    exchange_hash,
                    claim_id,
                    goal["cycles_used"],
                    "operator_futures_order_cancel_claimed",
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            claimed = self._record(
                self._select_goal(cursor, for_update=False)
            )
            return claimed, claim_id

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None:
        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if (
                str(goal.get("cancel_claim_id") or "") != claim_id
                or goal["cancel_outcome"] != "CLAIMED"
                or goal.get("cancel_exchange_invoked") is not False
            ):
                raise ValueError(
                    "operator_futures_order_cancel_invoke_not_claimed"
                )
            seal_futures_cancel_invocation(
                cursor,
                schema=self.schema,
                owner_ledger="ORDER_OPERATIONS",
                claim_id=claim_id,
                portfolio_id_sha256=str(
                    goal.get("portfolio_id_sha256") or ""
                ),
                client_order_id=str(
                    goal.get("cancel_target_client_order_id") or ""
                ),
                exchange_order_id_sha256=str(
                    goal.get("cancel_exchange_order_id_sha256") or ""
                ),
            )
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
                SET cancel_exchange_invoked = TRUE,
                    updated_at = NOW()
                WHERE goal_id = %s
                  AND cancel_claim_id = %s
                  AND cancel_outcome = 'CLAIMED'
                  AND cancel_exchange_invoked = FALSE
                """,
                (FUTURES_ORDER_OPERATIONS_GOAL_ID, claim_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_futures_order_cancel_invoke_not_claimed"
                )

    def release_cancel_before_exchange(
        self,
        *,
        claim_id: str,
        diagnostic_code: str = (
            "operator_futures_order_cancel_pre_call_blocked"
        ),
    ) -> FuturesOrderOperationsGoalRecord:
        diagnostic = str(diagnostic_code or "").strip()
        if diagnostic not in {
            "operator_futures_order_cancel_pre_call_blocked",
            "operator_futures_cancel_invocation_already_sealed",
        }:
            raise ValueError(
                "operator_futures_order_cancel_release_diagnostic_invalid"
            )
        with self._cursor() as cursor:
            self._lock(cursor)
            goal = self._select_goal(cursor, for_update=True)
            if (
                str(goal.get("cancel_claim_id") or "") != claim_id
                or goal["cancel_outcome"] != "CLAIMED"
                or goal.get("cancel_exchange_invoked") is not False
            ):
                raise ValueError(
                    "operator_futures_order_cancel_release_not_claimed"
                )
            revision = int(goal["revision"]) + 1
            cancel_cycle_number = int(goal["cancel_cycle_number"])
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
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
                    diagnostic,
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_order_operations_event')} (
                        event_id, event_type, cycle_number, client_order_id,
                        diagnostic_code, correlation_id, audit_id, evidence_json
                    )
                VALUES (%s, 'CANCEL_EXACT_PRE_CALL_BLOCKED', %s, %s, %s,
                        %s, %s, %s::jsonb)
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
                            "call_boundary_entered": False,
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
            self._store_cycle_record(
                cursor,
                cycle_number=cancel_cycle_number,
                record=released,
            )
            return released

    def finish_cancel(
        self,
        *,
        claim_id: str,
        execution: Any,
    ) -> FuturesOrderOperationsGoalRecord:
        outcome = str(getattr(execution, "outcome", ""))
        diagnostic = str(getattr(execution, "diagnostic_code", ""))
        exchange_hash = str(
            getattr(execution, "exchange_order_id_sha256", "")
        )
        if outcome not in {"ACCEPTED", "REJECTED", "UNKNOWN"}:
            raise ValueError("operator_futures_order_cancel_outcome_invalid")
        if not diagnostic.startswith("operator_futures_order_cancel_"):
            raise ValueError("operator_futures_order_cancel_diagnostic_invalid")
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
                    "operator_futures_order_cancel_finish_not_claimed"
                )
            revision = int(goal["revision"]) + 1
            cancel_cycle_number = int(goal["cancel_cycle_number"])
            cursor.execute(
                f"""
                UPDATE {self._table('operator_futures_order_operations_goal')}
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
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_order_operations_event')} (
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
            terminal = self._record(
                self._select_goal(cursor, for_update=False)
            )
            self._store_cycle_record(
                cursor,
                cycle_number=cancel_cycle_number,
                record=terminal,
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
            raise ValueError("operator_futures_orders_pagination_invalid")
        conditions: list[str] = []
        params: list[Any] = []
        if exact_product:
            conditions.append("projection.product_id = %s")
            params.append(exact_product)
        if exact_status:
            conditions.append("projection.status = %s")
            params.append(exact_status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {self._table(
                    'operator_futures_order_projection'
                )} AS projection
                {where}
                """,
                tuple(params),
            )
            total = int((_row(cursor) or {}).get("count") or 0)
            cursor.execute(
                f"""
                SELECT projection.*,
                       EXISTS (
                           SELECT 1
                             FROM {self._table(
                                 'operator_futures_cancel_invocation_seal'
                             )} AS seal
                            WHERE seal.portfolio_id_sha256 = (
                                SELECT portfolio_id_sha256
                                  FROM {self._table(
                                      'operator_futures_order_operations_goal'
                                  )}
                                 WHERE goal_id = %s
                            )
                              AND seal.client_order_id =
                                  projection.client_order_id
                              AND seal.mutation_class = 'CANCEL'
                       ) AS globally_cancel_sealed
                FROM {self._table(
                    'operator_futures_order_projection'
                )} AS projection
                {where}
                ORDER BY exchange_updated_at DESC NULLS LAST,
                         created_at DESC NULLS LAST,
                         client_order_id ASC
                LIMIT %s OFFSET %s
                """,
                tuple([
                    FUTURES_ORDER_OPERATIONS_GOAL_ID,
                    *params,
                    limit,
                    offset,
                ]),
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

    def is_cancel_invocation_sealed(
        self,
        client_order_id: str,
    ) -> bool:
        """Return the shared exact-child Cancel invocation state."""

        self.ensure_schema()
        exact_id = str(client_order_id or "").strip()
        if not exact_id:
            raise ValueError("operator_futures_order_identity_invalid")
        with self._cursor() as cursor:
            goal = self._select_goal(cursor, for_update=False)
            portfolio_hash = str(
                goal.get("portfolio_id_sha256") or ""
            )
            if not portfolio_hash:
                return False
            return futures_cancel_invocation_is_sealed(
                cursor,
                schema=self.schema,
                portfolio_id_sha256=portfolio_hash,
                client_order_id=exact_id,
            )

    def get_order(self, client_order_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        exact_id = str(client_order_id or "").strip()
        if not exact_id:
            raise ValueError("operator_futures_order_identity_invalid")
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT projection.*,
                       EXISTS (
                           SELECT 1
                             FROM {self._table(
                                 'operator_futures_cancel_invocation_seal'
                             )} AS seal
                            WHERE seal.portfolio_id_sha256 = (
                                SELECT portfolio_id_sha256
                                  FROM {self._table(
                                      'operator_futures_order_operations_goal'
                                  )}
                                 WHERE goal_id = %s
                            )
                              AND seal.client_order_id =
                                  projection.client_order_id
                              AND seal.mutation_class = 'CANCEL'
                       ) AS globally_cancel_sealed
                FROM {self._table(
                    'operator_futures_order_projection'
                )} AS projection
                WHERE projection.client_order_id = %s
                """,
                (FUTURES_ORDER_OPERATIONS_GOAL_ID, exact_id),
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
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("exchange_updated_at")),
            "observed_at": _iso(row.get("observed_at")),
            "exchange_order_id_sha256": str(
                row["exchange_order_id_sha256"]
            ),
            "authoritatively_nonterminal": bool(
                row["authoritatively_nonterminal"]
            ),
            "cancel_eligible": bool(
                row["cancel_eligible"]
                and not row.get("globally_cancel_sealed")
            ),
        }


_DEFAULT_REPOSITORY: OperatorFuturesOrderOperationsRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_operator_futures_order_operations_repository(
) -> OperatorFuturesOrderOperationsRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                from database import order as order_db

                _DEFAULT_REPOSITORY = (
                    OperatorFuturesOrderOperationsRepository(
                        order_db.DB_CLIENT
                    )
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def reset_operator_futures_order_operations_repository_for_tests() -> None:
    global _DEFAULT_REPOSITORY
    with _DEFAULT_REPOSITORY_LOCK:
        _DEFAULT_REPOSITORY = None


__all__ = [
    "OperatorFuturesOrderOperationsRepository",
    "get_default_operator_futures_order_operations_repository",
    "reset_operator_futures_order_operations_repository_for_tests",
]
