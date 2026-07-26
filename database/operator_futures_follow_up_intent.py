"""PostgreSQL authority for one local Futures follow-up intent."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_futures_follow_up_intent import (
    FUTURES_FOLLOW_UP_CONTRACT_COUNT,
    FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
    FUTURES_FOLLOW_UP_OPERATOR_INTENT,
    FUTURES_FOLLOW_UP_REASON_CODE,
    FuturesFollowUpIntentRecord,
    FuturesFollowUpIntentRequestContext,
    evaluate_futures_follow_up_intent_eligibility,
    futures_follow_up_source_evidence_sha256,
)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item[0] for item in cursor.description), value))


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


def _payload_sha256(
    *,
    context: FuturesFollowUpIntentRequestContext,
    source_client_order_id: str,
    expected_source_observed_at: str,
    expected_source_evidence_sha256: str,
) -> str:
    payload = {
        "goal_id": FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
        "actor_id": context.actor_id,
        "roles": sorted(set(context.roles)),
        "correlation_id": context.correlation_id,
        "operator_intent": context.operator_intent,
        "reason_code": context.reason_code,
        "source_client_order_id": source_client_order_id,
        "expected_source_observed_at": expected_source_observed_at,
        "expected_source_evidence_sha256": (
            expected_source_evidence_sha256
        ),
        "acknowledge_future_materialization_requires_fresh_authorization": (
            context
            .acknowledge_future_materialization_requires_fresh_authorization
        ),
        "acknowledge_no_coinbase_call_or_child_creation": (
            context.acknowledge_no_coinbase_call_or_child_creation
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


class OperatorFuturesFollowUpIntentRepository:
    """Atomically bind one immutable intent to one durable source projection."""

    def __init__(
        self,
        db: Any,
        *,
        schema: str = "public",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError(
                "operator_futures_follow_up_intent_schema_invalid"
            )
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
        cursor.execute("SELECT pg_advisory_xact_lock(34994, 14)")

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
                        {self._table('operator_futures_follow_up_intent')} (
                        follow_up_intent_id UUID PRIMARY KEY,
                        goal_id VARCHAR(128) NOT NULL,
                        source_client_order_id VARCHAR(128) NOT NULL UNIQUE
                            REFERENCES
                            {self._table('operator_futures_order_projection')}
                            (client_order_id) ON DELETE RESTRICT,
                        root_client_order_id VARCHAR(128) NOT NULL,
                        product_id VARCHAR(128) NOT NULL,
                        source_side VARCHAR(8) NOT NULL
                            CHECK (source_side IN ('BUY', 'SELL')),
                        derived_follow_up_side VARCHAR(8) NOT NULL
                            CHECK (derived_follow_up_side IN ('BUY', 'SELL')),
                        contract_count VARCHAR(32) NOT NULL
                            CHECK (contract_count = '1'),
                        state VARCHAR(16) NOT NULL
                            CHECK (state = 'ATTACHED'),
                        source_status_at_attach VARCHAR(32) NOT NULL
                            CHECK (source_status_at_attach = 'OPEN'),
                        source_observed_at TIMESTAMPTZ NOT NULL,
                        source_evidence_sha256 CHAR(64) NOT NULL,
                        reason_code VARCHAR(64) NOT NULL
                            CHECK (
                                reason_code =
                                'FULL_FILL_OPPOSITE_ONE_CONTRACT'
                            ),
                        idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL UNIQUE,
                        audit_id VARCHAR(255) NOT NULL UNIQUE,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_futures_follow_up_intent_event')} (
                        event_id UUID PRIMARY KEY,
                        follow_up_intent_id UUID NOT NULL UNIQUE REFERENCES
                            {self._table('operator_futures_follow_up_intent')}
                            (follow_up_intent_id) ON DELETE RESTRICT,
                        event_type VARCHAR(64) NOT NULL
                            CHECK (event_type = 'INTENT_ATTACHED'),
                        source_client_order_id VARCHAR(128) NOT NULL,
                        root_client_order_id VARCHAR(128) NOT NULL,
                        diagnostic_code VARCHAR(128) NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id VARCHAR(255) NOT NULL,
                        evidence_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        "{self.schema}".
                        operator_futures_follow_up_intent_reject_mutation()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION
                            'operator_futures_follow_up_intent_immutable';
                    END;
                    $$
                    """
                )
                for table_name in (
                    "operator_futures_follow_up_intent",
                    "operator_futures_follow_up_intent_event",
                ):
                    trigger_name = f"{table_name}_immutable_trigger"
                    cursor.execute(
                        f"""
                        DROP TRIGGER IF EXISTS "{trigger_name}"
                        ON {self._table(table_name)}
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TRIGGER "{trigger_name}"
                        BEFORE UPDATE OR DELETE
                        ON {self._table(table_name)}
                        FOR EACH ROW EXECUTE FUNCTION
                            "{self.schema}".
                            operator_futures_follow_up_intent_reject_mutation()
                        """
                    )
            self._schema_ready = True

    def read(
        self,
        source_client_order_id: str,
    ) -> tuple[dict[str, Any] | None, FuturesFollowUpIntentRecord | None]:
        self.ensure_schema()
        exact_source = str(source_client_order_id or "").strip()
        if not exact_source:
            raise ValueError(
                "operator_futures_follow_up_intent_source_invalid"
            )
        with self._cursor() as cursor:
            projection = self._select_projection(
                cursor,
                exact_source,
                for_update=False,
            )
            intent = self._select_intent_by_source(
                cursor,
                exact_source,
                for_update=False,
            )
        return (
            self._projection(projection)
            if projection is not None
            else None,
            self._record(intent) if intent is not None else None,
        )

    def attach(
        self,
        *,
        context: FuturesFollowUpIntentRequestContext,
        source_client_order_id: str,
        expected_source_observed_at: str,
        expected_source_evidence_sha256: str,
    ) -> tuple[FuturesFollowUpIntentRecord, bool]:
        self.ensure_schema()
        exact_source = str(source_client_order_id or "").strip()
        exact_observed_at = str(expected_source_observed_at or "").strip()
        exact_evidence = str(
            expected_source_evidence_sha256 or ""
        ).strip()
        self._validate_context(context)
        if (
            not exact_source
            or not exact_observed_at
            or not _SHA256_RE.fullmatch(exact_evidence)
        ):
            raise ValueError(
                "operator_futures_follow_up_intent_source_binding_invalid"
            )
        payload_hash = _payload_sha256(
            context=context,
            source_client_order_id=exact_source,
            expected_source_observed_at=exact_observed_at,
            expected_source_evidence_sha256=exact_evidence,
        )
        now = self.clock()
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT *
                FROM {self._table('operator_futures_follow_up_intent')}
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (context.idempotency_key,),
            )
            replay = _row(cursor)
            if replay is not None:
                if (
                    str(replay["payload_sha256"]) != payload_hash
                    or str(replay["actor_id"]) != context.actor_id
                ):
                    raise ValueError(
                        "operator_futures_follow_up_intent_idempotency_conflict"
                    )
                return self._record(replay), True

            projection_row = self._select_projection(
                cursor,
                exact_source,
                for_update=True,
            )
            projection = (
                self._projection(projection_row)
                if projection_row is not None
                else None
            )
            existing = self._select_intent_by_source(
                cursor,
                exact_source,
                for_update=True,
            )
            eligibility = evaluate_futures_follow_up_intent_eligibility(
                projection,
                intent_attached=existing is not None,
            )
            if not eligibility.eligible:
                blocker = (
                    eligibility.blockers[0]
                    if eligibility.blockers
                    else "source_ineligible"
                )
                if blocker == "futures_follow_up_intent_already_attached":
                    raise ValueError(
                        "operator_futures_follow_up_intent_already_attached"
                    )
                raise ValueError(
                    f"operator_futures_follow_up_intent_{blocker}"
                )
            if (
                eligibility.source_observed_at != exact_observed_at
                or eligibility.source_evidence_sha256 != exact_evidence
            ):
                raise ValueError(
                    "operator_futures_follow_up_intent_source_changed"
                )
            if (
                eligibility.product_id is None
                or eligibility.source_side not in {"BUY", "SELL"}
                or eligibility.derived_follow_up_side not in {"BUY", "SELL"}
                or eligibility.source_status != "OPEN"
                or eligibility.source_observed_at is None
                or eligibility.source_evidence_sha256 is None
            ):
                raise ValueError(
                    "operator_futures_follow_up_intent_source_ineligible"
                )

            intent_id = str(uuid.uuid4())
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_follow_up_intent')} (
                        follow_up_intent_id, goal_id,
                        source_client_order_id, root_client_order_id,
                        product_id, source_side, derived_follow_up_side,
                        contract_count, state, source_status_at_attach,
                        source_observed_at, source_evidence_sha256,
                        reason_code, idempotency_key, payload_sha256,
                        actor_id, roles_json, correlation_id, audit_id,
                        created_at
                    )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, 'ATTACHED',
                    'OPEN', %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s
                )
                RETURNING *
                """,
                (
                    intent_id,
                    FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
                    exact_source,
                    exact_source,
                    eligibility.product_id,
                    eligibility.source_side,
                    eligibility.derived_follow_up_side,
                    FUTURES_FOLLOW_UP_CONTRACT_COUNT,
                    eligibility.source_observed_at,
                    eligibility.source_evidence_sha256,
                    FUTURES_FOLLOW_UP_REASON_CODE,
                    context.idempotency_key,
                    payload_hash,
                    context.actor_id,
                    json.dumps(sorted(set(context.roles))),
                    context.correlation_id,
                    context.audit_id,
                    now,
                ),
            )
            inserted = _row(cursor)
            if inserted is None:
                raise ValueError(
                    "operator_futures_follow_up_intent_persistence_unknown"
                )
            cursor.execute(
                f"""
                INSERT INTO
                    {self._table('operator_futures_follow_up_intent_event')} (
                        event_id, follow_up_intent_id, event_type,
                        source_client_order_id, root_client_order_id,
                        diagnostic_code, correlation_id, audit_id,
                        evidence_json, created_at
                    )
                VALUES (
                    %s, %s, 'INTENT_ATTACHED', %s, %s, %s, %s, %s,
                    %s::jsonb, %s
                )
                """,
                (
                    str(uuid.uuid4()),
                    intent_id,
                    exact_source,
                    exact_source,
                    "operator_futures_follow_up_intent_attached",
                    context.correlation_id,
                    context.audit_id,
                    json.dumps(
                        {
                            "goal_id": FUTURES_FOLLOW_UP_INTENT_GOAL_ID,
                            "product_id": eligibility.product_id,
                            "source_side": eligibility.source_side,
                            "derived_follow_up_side": (
                                eligibility.derived_follow_up_side
                            ),
                            "contract_count": (
                                FUTURES_FOLLOW_UP_CONTRACT_COUNT
                            ),
                            "source_evidence_sha256": (
                                eligibility.source_evidence_sha256
                            ),
                            "coinbase_calls": 0,
                            "child_created": False,
                            "raw_responses_included": False,
                            "private_identifiers_included": False,
                            "exception_text_included": False,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            return self._record(inserted), False

    def _select_projection(
        self,
        cursor: Any,
        source_client_order_id: str,
        *,
        for_update: bool,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_futures_order_projection')}
            WHERE client_order_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (source_client_order_id,),
        )
        return _row(cursor)

    def _select_intent_by_source(
        self,
        cursor: Any,
        source_client_order_id: str,
        *,
        for_update: bool,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT *
            FROM {self._table('operator_futures_follow_up_intent')}
            WHERE source_client_order_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (source_client_order_id,),
        )
        return _row(cursor)

    @staticmethod
    def _projection(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "client_order_id": str(row["client_order_id"]),
            "product_id": str(row["product_id"]),
            "side": str(row["side"]),
            "status": str(row["status"]),
            "size": (
                str(row["size"]) if row.get("size") is not None else None
            ),
            "observed_at": _iso(row.get("observed_at")),
            "exchange_order_id_sha256": str(
                row["exchange_order_id_sha256"]
            ),
            "authoritatively_nonterminal": bool(
                row["authoritatively_nonterminal"]
            ),
        }

    @staticmethod
    def _record(row: Mapping[str, Any]) -> FuturesFollowUpIntentRecord:
        return FuturesFollowUpIntentRecord(
            goal_id=str(row["goal_id"]),
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            root_client_order_id=str(row["root_client_order_id"]),
            product_id=str(row["product_id"]),
            source_side=str(row["source_side"]),
            derived_follow_up_side=str(row["derived_follow_up_side"]),
            contract_count=str(row["contract_count"]),
            state=str(row["state"]),
            source_status_at_attach=str(row["source_status_at_attach"]),
            source_observed_at=str(_iso(row["source_observed_at"])),
            source_evidence_sha256=str(row["source_evidence_sha256"]),
            reason_code=str(row["reason_code"]),
            correlation_id=str(row["correlation_id"]),
            audit_id=str(row["audit_id"]),
            created_at=str(_iso(row["created_at"])),
        )

    @staticmethod
    def _validate_context(
        context: FuturesFollowUpIntentRequestContext,
    ) -> None:
        if (
            not str(context.actor_id or "").strip()
            or not str(context.idempotency_key or "").strip()
            or not str(context.correlation_id or "").strip()
            or not str(context.audit_id or "").strip()
        ):
            raise ValueError(
                "operator_futures_follow_up_intent_context_invalid"
            )
        if context.operator_intent != FUTURES_FOLLOW_UP_OPERATOR_INTENT:
            raise ValueError(
                "operator_futures_follow_up_intent_operator_intent_invalid"
            )
        if context.reason_code != FUTURES_FOLLOW_UP_REASON_CODE:
            raise ValueError(
                "operator_futures_follow_up_intent_reason_code_invalid"
            )
        if (
            not context
            .acknowledge_future_materialization_requires_fresh_authorization
            or not context.acknowledge_no_coinbase_call_or_child_creation
        ):
            raise ValueError(
                "operator_futures_follow_up_intent_confirmation_required"
            )


_DEFAULT_REPOSITORY: OperatorFuturesFollowUpIntentRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_operator_futures_follow_up_intent_repository(
) -> OperatorFuturesFollowUpIntentRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                from database import order as order_db
                from database.operator_futures_order_operations import (
                    get_default_operator_futures_order_operations_repository,
                )

                get_default_operator_futures_order_operations_repository()
                _DEFAULT_REPOSITORY = OperatorFuturesFollowUpIntentRepository(
                    order_db.DB_CLIENT
                )
                _DEFAULT_REPOSITORY.ensure_schema()
    return _DEFAULT_REPOSITORY


def reset_operator_futures_follow_up_intent_repository_for_tests() -> None:
    global _DEFAULT_REPOSITORY
    with _DEFAULT_REPOSITORY_LOCK:
        _DEFAULT_REPOSITORY = None


__all__ = [
    "OperatorFuturesFollowUpIntentRepository",
    "get_default_operator_futures_follow_up_intent_repository",
    "reset_operator_futures_follow_up_intent_repository_for_tests",
]
