"""PostgreSQL revisions for the Goal 3 Futures product policy."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re
from typing import Any, Mapping

from application.admin_api.operator_futures_product_policy import (
    FuturesProductPolicyItem,
    FuturesProductPolicyRecord,
    OperatorFuturesProductPolicyError,
)
from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS,
    FUTURES_PRODUCT_TICKET_GOAL_ID,
    FuturesProductPolicySelection,
)
from database.database import PostgresDB


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EVIDENCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_PRODUCT_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+){2,3}$")
_ACTIONS = frozenset(
    {"APPROVE", "ENABLE", "DISABLE", "RETIRE", "SELECT"}
)
_LIFECYCLES = frozenset(
    {"PENDING", "APPROVED", "ENABLED", "DISABLED", "RETIRED"}
)
_GLOBAL_ALLOWED_ACTIONS = [
    "APPROVE",
    "DISABLE",
    "ENABLE",
    "RETIRE",
    "SELECT",
]
_ITEM_ALLOWED_ACTIONS = {
    "PENDING": ("APPROVE", "RETIRE"),
    "APPROVED": ("ENABLE", "RETIRE"),
    "ENABLED": ("DISABLE", "RETIRE", "SELECT"),
    "DISABLED": ("ENABLE", "RETIRE"),
    "RETIRED": (),
}
_ACTION_OPERATOR_INTENTS = {
    action: (
        f"{action.lower()}_exact_futures_product_for_operator_ticket"
    )
    for action in _ACTIONS
}


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((column[0] for column in cursor.description), value))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise OperatorFuturesProductPolicyError(
            "operator_futures_product_policy_stored_state_invalid"
        )
    return dict(value)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    return str(value)


def _initial_state() -> dict[str, str]:
    return {
        product_id: "PENDING"
        for product_id in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
    }


class OperatorFuturesProductPolicyRepository:
    """Serialize immutable policy revisions and exact selection binding."""

    def __init__(
        self,
        database: PostgresDB,
        *,
        schema: str = "public",
    ) -> None:
        if _SCHEMA_RE.fullmatch(schema) is None:
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_schema_invalid"
            )
        self.database = database
        self.schema = schema
        self.prefix = f'"{schema}".'

    @contextmanager
    def _cursor(self):
        with self.database.get_cursor() as cursor:
            yield cursor

    @staticmethod
    def _lock(cursor: Any) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(34994, 10)")

    def ensure_schema(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_futures_product_policy_goal (
                    goal_id TEXT PRIMARY KEY,
                    current_revision INTEGER NOT NULL
                        CHECK (current_revision >= 1),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_futures_product_policy_revision (
                    revision INTEGER PRIMARY KEY
                        CHECK (revision >= 1),
                    state_json JSONB NOT NULL,
                    snapshot_sha256 CHAR(64) NOT NULL
                        CHECK (snapshot_sha256 ~ '^[0-9a-f]{{64}}$'),
                    selected_product_id TEXT,
                    action TEXT NOT NULL,
                    product_id TEXT,
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT,
                    operator_reason_sha256 CHAR(64) NOT NULL
                        CHECK (
                            operator_reason_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    operator_intent_sha256 CHAR(64)
                        CHECK (
                            operator_intent_sha256 IS NULL OR
                            operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    confirmations_json JSONB NOT NULL DEFAULT '{{}}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_futures_product_policy_command (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_sha256 CHAR(64) NOT NULL
                        CHECK (payload_sha256 ~ '^[0-9a-f]{{64}}$'),
                    result_revision INTEGER NOT NULL REFERENCES
                        {self.prefix}operator_futures_product_policy_revision(
                            revision
                        ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {self.prefix}operator_futures_product_policy_event (
                    event_id BIGSERIAL PRIMARY KEY,
                    revision INTEGER NOT NULL REFERENCES
                        {self.prefix}operator_futures_product_policy_revision(
                            revision
                        ),
                    event_type TEXT NOT NULL,
                    product_id TEXT,
                    actor_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    reason_sha256 CHAR(64) NOT NULL
                        CHECK (reason_sha256 ~ '^[0-9a-f]{{64}}$'),
                    operator_intent_sha256 CHAR(64)
                        CHECK (
                            operator_intent_sha256 IS NULL OR
                            operator_intent_sha256 ~ '^[0-9a-f]{{64}}$'
                        ),
                    confirmations_json JSONB NOT NULL DEFAULT '{{}}',
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_futures_product_policy_revision
                ADD COLUMN IF NOT EXISTS operator_intent_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_futures_product_policy_revision
                ADD COLUMN IF NOT EXISTS
                    confirmations_json JSONB NOT NULL DEFAULT '{{}}'
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_futures_product_policy_event
                ADD COLUMN IF NOT EXISTS operator_intent_sha256 CHAR(64)
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE
                    {self.prefix}operator_futures_product_policy_event
                ADD COLUMN IF NOT EXISTS
                    confirmations_json JSONB NOT NULL DEFAULT '{{}}'
                """
            )
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION
                    {self.prefix}guard_operator_futures_product_policy_append_only()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE =
                            'operator_futures_product_policy_evidence_append_only';
                END;
                $$
                """
            )
            for table_name, trigger_name in (
                (
                    "operator_futures_product_policy_revision",
                    "operator_futures_product_policy_revision_append_only",
                ),
                (
                    "operator_futures_product_policy_command",
                    "operator_futures_product_policy_command_append_only",
                ),
                (
                    "operator_futures_product_policy_event",
                    "operator_futures_product_policy_event_append_only",
                ),
            ):
                cursor.execute(
                    f"DROP TRIGGER IF EXISTS {trigger_name} "
                    f"ON {self.prefix}{table_name}"
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER {trigger_name}
                    BEFORE UPDATE OR DELETE ON {self.prefix}{table_name}
                    FOR EACH ROW EXECUTE FUNCTION
                        {self.prefix}guard_operator_futures_product_policy_append_only()
                    """
                )
            initial_state = _initial_state()
            initial_hash = _canonical_sha256(initial_state)
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_futures_product_policy_revision (
                    revision,
                    state_json,
                    snapshot_sha256,
                    selected_product_id,
                    action,
                    product_id,
                    actor_id,
                    correlation_id,
                    operator_reason_sha256
                )
                VALUES (
                    1,
                    %s::jsonb,
                    %s,
                    NULL,
                    'INITIALIZE',
                    NULL,
                    'system',
                    NULL,
                    %s
                )
                ON CONFLICT (revision) DO NOTHING
                """,
                (
                    json.dumps(initial_state, sort_keys=True),
                    initial_hash,
                    _canonical_sha256(
                        {"reason": "configured_product_scope"}
                    ),
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_futures_product_policy_goal (
                    goal_id,
                    current_revision
                )
                VALUES (%s, 1)
                ON CONFLICT (goal_id) DO NOTHING
                """,
                (FUTURES_PRODUCT_TICKET_GOAL_ID,),
            )

    def _goal(self, cursor: Any, *, for_update: bool) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_futures_product_policy_goal
            WHERE goal_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (FUTURES_PRODUCT_TICKET_GOAL_ID,),
        )
        value = _row(cursor)
        if value is None:
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_goal_missing"
            )
        return value

    def _revision(self, cursor: Any, revision: int) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT *
            FROM {self.prefix}operator_futures_product_policy_revision
            WHERE revision = %s
            """,
            (revision,),
        )
        value = _row(cursor)
        if value is None:
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_revision_missing"
            )
        return value

    @staticmethod
    def _selection(
        *,
        revision: int,
        snapshot_sha256: str,
        state: Mapping[str, Any],
        selected_product_id: str | None,
    ) -> FuturesProductPolicySelection | None:
        if selected_product_id is None:
            return None
        lifecycle = str(state.get(selected_product_id) or "")
        if lifecycle != "ENABLED":
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_selection_invalid"
            )
        policy_sha256 = _canonical_sha256(
            {
                "goal_id": FUTURES_PRODUCT_TICKET_GOAL_ID,
                "policy_revision": revision,
                "snapshot_sha256": snapshot_sha256,
                "product_id": selected_product_id,
                "lifecycle": lifecycle,
            }
        )
        return FuturesProductPolicySelection(
            product_id=selected_product_id,
            policy_revision=revision,
            policy_sha256=policy_sha256,
            lifecycle=lifecycle,
        )

    @classmethod
    def _record(cls, value: Mapping[str, Any]) -> FuturesProductPolicyRecord:
        revision = int(value["revision"])
        state = _json_object(value["state_json"])
        normalized_state = {
            str(product_id): str(lifecycle)
            for product_id, lifecycle in state.items()
        }
        if (
            set(normalized_state)
            != set(FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS)
            or any(
                lifecycle not in _LIFECYCLES
                for lifecycle in normalized_state.values()
            )
        ):
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_stored_state_invalid"
            )
        expected_hash = _canonical_sha256(normalized_state)
        snapshot_hash = str(value["snapshot_sha256"])
        if snapshot_hash != expected_hash:
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_snapshot_invalid"
            )
        selected = (
            str(value["selected_product_id"])
            if value.get("selected_product_id")
            else None
        )
        selection = cls._selection(
            revision=revision,
            snapshot_sha256=snapshot_hash,
            state=normalized_state,
            selected_product_id=selected,
        )
        products = tuple(
            FuturesProductPolicyItem(
                product_id=product_id,
                lifecycle=normalized_state[product_id],
                allowed_actions=_ITEM_ALLOWED_ACTIONS[
                    normalized_state[product_id]
                ],
            )
            for product_id in sorted(normalized_state)
        )
        return FuturesProductPolicyRecord(
            revision=revision,
            snapshot_sha256=snapshot_hash,
            products=products,
            selected_product_id=selected,
            selection=selection,
            last_action=str(value["action"]),
            last_product_id=(
                str(value["product_id"])
                if value.get("product_id")
                else None
            ),
            last_correlation_id=(
                str(value["correlation_id"])
                if value.get("correlation_id")
                else None
            ),
            allowed_actions=list(_GLOBAL_ALLOWED_ACTIONS),
            updated_at=_iso(value["created_at"]),
        )

    def read(self) -> FuturesProductPolicyRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            goal = self._goal(cursor, for_update=False)
            return self._record(
                self._revision(cursor, int(goal["current_revision"]))
            )

    def selection(self) -> FuturesProductPolicySelection:
        record = self.read()
        if record.selection is None:
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_selection_unavailable"
            )
        return record.selection

    def _validate_command(
        self,
        *,
        action: str,
        product_id: str,
        expected_revision: int,
        actor_id: str,
        roles: tuple[str, ...],
        operator_reason: str,
        operator_intent: str,
        confirm_exact_product_policy_action: bool,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_action = str(action).strip().upper()
        normalized_product = str(product_id).strip().upper()
        if (
            normalized_action not in _ACTIONS
            or normalized_product
            not in FUTURES_PRODUCT_TICKET_CONFIGURED_PRODUCTS
            or _PRODUCT_RE.fullmatch(normalized_product) is None
            or not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
            or not str(actor_id).strip()
            or not roles
            or not all(str(role).strip() for role in roles)
            or not (1 <= len(str(operator_reason).strip()) <= 240)
            or str(operator_intent)
            != _ACTION_OPERATOR_INTENTS.get(normalized_action)
            or confirm_exact_product_policy_action is not True
            or _EVIDENCE_RE.fullmatch(str(correlation_id)) is None
            or _EVIDENCE_RE.fullmatch(str(idempotency_key)) is None
        ):
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_request_invalid",
                http_status_code=422,
            )
        return {
            "action": normalized_action,
            "product_id": normalized_product,
            "expected_revision": expected_revision,
            "actor_id": str(actor_id).strip(),
            "roles": sorted(str(role).strip() for role in roles),
            "operator_reason_sha256": hashlib.sha256(
                str(operator_reason).strip().encode("utf-8")
            ).hexdigest(),
            "operator_intent": str(operator_intent),
            "confirm_exact_product_policy_action": True,
            "correlation_id": str(correlation_id),
            "idempotency_key": str(idempotency_key),
        }

    def _ticket_goal_terminal(self, cursor: Any) -> bool:
        cursor.execute(
            "SELECT to_regclass(%s) AS table_name",
            (
                f"{self.schema}.operator_futures_manual_goal",
            ),
        )
        available = _row(cursor)
        if available is None or available.get("table_name") is None:
            return False
        cursor.execute(
            f"""
            SELECT preview_outcome
            FROM {self.prefix}operator_futures_manual_goal
            WHERE goal_id = %s
            """,
            (FUTURES_PRODUCT_TICKET_GOAL_ID,),
        )
        value = _row(cursor)
        return (
            value is not None
            and str(value.get("preview_outcome")) != "NOT_RUN"
        )

    def _invalidate_ticket(self, cursor: Any) -> None:
        cursor.execute(
            "SELECT to_regclass(%s) AS table_name",
            (
                f"{self.schema}.operator_futures_manual_goal",
            ),
        )
        available = _row(cursor)
        if available is None or available.get("table_name") is None:
            return
        cursor.execute(
            f"""
            UPDATE {self.prefix}operator_futures_manual_goal
            SET
                revision = revision + 1,
                eligibility_outcome = NULL,
                eligibility_diagnostic_code =
                    'operator_futures_product_ticket_policy_changed',
                category_attempts_json = %s::jsonb,
                candidate_json = NULL,
                candidate_sha256 = NULL,
                portfolio_id_sha256 = NULL,
                eligibility_evidence_sha256 = NULL,
                diagnostic_code =
                    'operator_futures_product_ticket_policy_changed',
                updated_at = NOW()
            WHERE goal_id = %s
              AND preview_outcome = 'NOT_RUN'
            """,
            (
                json.dumps(
                    {
                        category: 0
                        for category in (
                            "api_key_permissions",
                            "portfolio_catalog",
                            "product",
                            "best_bid_ask",
                            "futures_positions",
                            "futures_margin_collateral",
                        )
                    },
                    sort_keys=True,
                ),
                FUTURES_PRODUCT_TICKET_GOAL_ID,
            ),
        )

    def apply(
        self,
        *,
        action: str,
        product_id: str,
        expected_revision: int,
        actor_id: str,
        roles: tuple[str, ...],
        operator_reason: str,
        operator_intent: str,
        confirm_exact_product_policy_action: bool,
        correlation_id: str,
        idempotency_key: str,
    ) -> FuturesProductPolicyRecord:
        """Apply one exact local policy transition or replay it call-free."""

        self.ensure_schema()
        command = self._validate_command(
            action=action,
            product_id=product_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            roles=roles,
            operator_reason=operator_reason,
            operator_intent=operator_intent,
            confirm_exact_product_policy_action=(
                confirm_exact_product_policy_action
            ),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        payload_hash = _canonical_sha256(
            {
                key: value
                for key, value in command.items()
                if key != "idempotency_key"
            }
        )
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT payload_sha256, result_revision
                FROM {self.prefix}operator_futures_product_policy_command
                WHERE idempotency_key = %s
                """,
                (command["idempotency_key"],),
            )
            replay = _row(cursor)
            if replay is not None:
                if str(replay["payload_sha256"]) != payload_hash:
                    raise OperatorFuturesProductPolicyError(
                        "operator_futures_product_policy_idempotency_conflict"
                    )
                return self._record(
                    self._revision(cursor, int(replay["result_revision"]))
                )

            goal = self._goal(cursor, for_update=True)
            current_revision = int(goal["current_revision"])
            if current_revision != command["expected_revision"]:
                raise OperatorFuturesProductPolicyError(
                    "operator_futures_product_policy_revision_conflict"
                )
            if self._ticket_goal_terminal(cursor):
                raise OperatorFuturesProductPolicyError(
                    "operator_futures_product_policy_goal_terminal"
                )
            current = self._revision(cursor, current_revision)
            state = {
                str(key): str(value)
                for key, value in _json_object(
                    current["state_json"]
                ).items()
            }
            selected = (
                str(current["selected_product_id"])
                if current.get("selected_product_id")
                else None
            )
            lifecycle = state.get(command["product_id"])
            action_value = command["action"]
            if action_value == "APPROVE" and lifecycle == "PENDING":
                state[command["product_id"]] = "APPROVED"
            elif (
                action_value == "ENABLE"
                and lifecycle in {"APPROVED", "DISABLED"}
            ):
                state[command["product_id"]] = "ENABLED"
            elif action_value == "DISABLE" and lifecycle == "ENABLED":
                state[command["product_id"]] = "DISABLED"
                if selected == command["product_id"]:
                    selected = None
            elif action_value == "RETIRE" and lifecycle in {
                "PENDING",
                "APPROVED",
                "ENABLED",
                "DISABLED",
            }:
                state[command["product_id"]] = "RETIRED"
                if selected == command["product_id"]:
                    selected = None
            elif action_value == "SELECT" and lifecycle == "ENABLED":
                selected = command["product_id"]
            else:
                raise OperatorFuturesProductPolicyError(
                    "operator_futures_product_policy_transition_invalid"
                )

            next_revision = current_revision + 1
            snapshot_hash = _canonical_sha256(state)
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_futures_product_policy_revision (
                    revision,
                    state_json,
                    snapshot_sha256,
                    selected_product_id,
                    action,
                    product_id,
                    actor_id,
                    correlation_id,
                    operator_reason_sha256,
                    operator_intent_sha256,
                    confirmations_json
                )
                VALUES (
                    %s, %s::jsonb, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb
                )
                """,
                (
                    next_revision,
                    json.dumps(state, sort_keys=True),
                    snapshot_hash,
                    selected,
                    action_value,
                    command["product_id"],
                    command["actor_id"],
                    command["correlation_id"],
                    command["operator_reason_sha256"],
                    _sha256_text(command["operator_intent"]),
                    json.dumps(
                        {
                            "confirm_exact_product_policy_action": (
                                command[
                                    "confirm_exact_product_policy_action"
                                ]
                            )
                        },
                        sort_keys=True,
                    ),
                ),
            )
            cursor.execute(
                f"""
                UPDATE {self.prefix}operator_futures_product_policy_goal
                SET current_revision = %s, updated_at = NOW()
                WHERE goal_id = %s
                """,
                (
                    next_revision,
                    FUTURES_PRODUCT_TICKET_GOAL_ID,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_futures_product_policy_command (
                    idempotency_key,
                    payload_sha256,
                    result_revision
                )
                VALUES (%s, %s, %s)
                """,
                (
                    command["idempotency_key"],
                    payload_hash,
                    next_revision,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO
                    {self.prefix}operator_futures_product_policy_event (
                    revision,
                    event_type,
                    product_id,
                    actor_id,
                    correlation_id,
                    reason_sha256,
                    operator_intent_sha256,
                    confirmations_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    next_revision,
                    f"FUTURES_PRODUCT_{action_value}",
                    command["product_id"],
                    command["actor_id"],
                    command["correlation_id"],
                    command["operator_reason_sha256"],
                    _sha256_text(command["operator_intent"]),
                    json.dumps(
                        {
                            "confirm_exact_product_policy_action": (
                                command[
                                    "confirm_exact_product_policy_action"
                                ]
                            )
                        },
                        sort_keys=True,
                    ),
                ),
            )
            self._invalidate_ticket(cursor)
            return self._record(
                self._revision(cursor, next_revision)
            )

    def validate_selection_binding(
        self,
        *,
        cursor: Any,
        candidate: Mapping[str, Any],
    ) -> None:
        """Validate candidate policy binding under the shared advisory lock."""

        goal = self._goal(cursor, for_update=False)
        revision = self._revision(cursor, int(goal["current_revision"]))
        record = self._record(revision)
        selection = record.selection
        if (
            selection is None
            or candidate.get("product_id") != selection.product_id
            or candidate.get("product_policy_revision")
            != str(selection.policy_revision)
            or candidate.get("product_policy_sha256")
            != selection.policy_sha256
        ):
            raise OperatorFuturesProductPolicyError(
                "operator_futures_product_policy_candidate_stale"
            )


@lru_cache(maxsize=1)
def get_default_operator_futures_product_policy_repository(
) -> OperatorFuturesProductPolicyRepository:
    from database import order as order_db

    repository = OperatorFuturesProductPolicyRepository(order_db.DB_CLIENT)
    repository.ensure_schema()
    return repository


def initialize_operator_futures_product_policy_schema() -> None:
    get_default_operator_futures_product_policy_repository().ensure_schema()


__all__ = [
    "OperatorFuturesProductPolicyRepository",
    "get_default_operator_futures_product_policy_repository",
    "initialize_operator_futures_product_policy_schema",
]
