"""PostgreSQL authority for one bounded operator Hotpoint placement."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HOTPOINT_GOAL_ID,
    HotpointCancelPlan,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointPlacementOutcome,
    HotpointPlacementPlan,
    HotpointScopePolicy,
    HotpointWindowState,
    OperatorHotpointControlRecord,
    SPOT_HOTPOINT_SCOPE_POLICY,
)
from business.hotpoint_detector import compute_bucket_id


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_ACTIONS = tuple(action.value for action in HotpointControlAction)
_KILL_SWITCH_STATES = tuple(state.value for state in HotpointKillSwitchState)
_WINDOW_STATES = tuple(state.value for state in HotpointWindowState)
_CREATE_STATES = tuple(state.value for state in HotpointCreateState)
_CANCEL_STATES = tuple(state.value for state in HotpointCancelState)
_WINDOW_SECONDS = 60
_TRIGGER_FILL_COUNT = 3
_BUCKET_WIDTH_PCT = Decimal("0.005")
_ALLOWED_PARENT_PROVENANCE = {
    "ADMIN_MANUAL_ROOT",
    "OPERATOR_PARENT_STRATEGY",
    "ADMIN_PARENT_STRATEGY",
}


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((column[0] for column in cursor.description), value))


def _iso(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    normalized = str(value).strip()
    return normalized or None


def _decimal(value: object, *, code: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(code) from None
    if not result.is_finite():
        raise ValueError(code)
    return result


def _metadata_value(metadata: object, key: str) -> object:
    if isinstance(metadata, Mapping):
        return metadata.get(key)
    return getattr(metadata, key, None)


def _futures_contract_multiplier(metadata: object) -> Decimal | None:
    details = _metadata_value(metadata, "future_product_details")
    raw_value = _metadata_value(details, "contract_size")
    if raw_value is None:
        raw_value = _metadata_value(metadata, "contract_size")
    if raw_value is None:
        return None
    multiplier = _decimal(
        raw_value,
        code="operator_hotpoint_product_metadata_invalid",
    )
    return multiplier if multiplier > 0 else None


class OperatorHotpointControlRepository:
    """Serialize one kill switch, one window, and one child claim."""

    def __init__(
        self,
        db: Any,
        *,
        schema: str = "public",
        configured_portfolio_id: str,
        product_metadata_provider: Callable[[str], object],
        policy: HotpointScopePolicy = SPOT_HOTPOINT_SCOPE_POLICY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("operator_hotpoint_schema_invalid")
        self.db = db
        self.schema = str(schema)
        self.configured_portfolio_id = str(
            uuid.UUID(str(configured_portfolio_id))
        )
        self.product_metadata_provider = product_metadata_provider
        if not isinstance(policy, HotpointScopePolicy):
            raise ValueError("operator_hotpoint_scope_policy_invalid")
        self.policy = policy
        self._advisory_lock_slot = (
            2 if policy == FUTURES_HOTPOINT_SCOPE_POLICY else 1
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _table(self, name: str) -> str:
        if self.policy == FUTURES_HOTPOINT_SCOPE_POLICY:
            name = {
                "operator_hotpoint_control": "operator_futures_hotpoint_control",
                "operator_hotpoint_control_command": (
                    "operator_futures_hotpoint_control_command"
                ),
                "guard_operator_hotpoint_command_append_only": (
                    "guard_operator_futures_hotpoint_command_append_only"
                ),
            }.get(name, name)
        return f'"{self.schema}"."{name}"'

    def _lock(self, cursor: Any) -> None:
        cursor.execute(
            f"SELECT pg_advisory_xact_lock(34990, {self._advisory_lock_slot})"
        )

    @staticmethod
    def _goal_allowance_lock(cursor: Any) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(34990, 0)")

    @contextmanager
    def _cursor(self):
        with self.db.get_cursor() as cursor:
            yield cursor

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS
                        {self._table('operator_hotpoint_goal_allowance')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        create_claim_id UUID UNIQUE NOT NULL,
                        create_claim_domain VARCHAR(16) NOT NULL
                            CHECK (create_claim_domain IN ('SPOT', 'FUTURES')),
                        cancel_claim_id UUID UNIQUE,
                        cancel_claim_domain VARCHAR(16)
                            CHECK (cancel_claim_domain IN ('SPOT', 'FUTURES')),
                        recorded_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP,
                        CHECK (
                            (cancel_claim_id IS NULL
                             AND cancel_claim_domain IS NULL)
                            OR
                            (cancel_claim_id IS NOT NULL
                             AND cancel_claim_domain = create_claim_domain)
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table('operator_hotpoint_control')} (
                        goal_id VARCHAR(128) PRIMARY KEY,
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        kill_switch_state VARCHAR(16) NOT NULL
                            CHECK (kill_switch_state IN ({_sql_values(_KILL_SWITCH_STATES)})),
                        delegated_create_authority BOOLEAN NOT NULL DEFAULT FALSE,
                        window_state VARCHAR(16) NOT NULL
                            CHECK (window_state IN ({_sql_values(_WINDOW_STATES)})),
                        parent_client_order_id VARCHAR(128),
                        product_id VARCHAR(32),
                        side VARCHAR(8),
                        window_id UUID UNIQUE,
                        window_started_at TIMESTAMPTZ,
                        window_expires_at TIMESTAMPTZ,
                        create_state VARCHAR(16) NOT NULL
                            CHECK (create_state IN ({_sql_values(_CREATE_STATES)})),
                        cancel_state VARCHAR(16) NOT NULL DEFAULT 'NOT_CLAIMED'
                            CHECK (cancel_state IN ({_sql_values(_CANCEL_STATES)})),
                        placement_claim_id UUID UNIQUE,
                        cancel_claim_id UUID UNIQUE,
                        create_exchange_invoked BOOLEAN,
                        cancel_exchange_invoked BOOLEAN,
                        child_client_order_id VARCHAR(128) UNIQUE,
                        base_size NUMERIC,
                        limit_price NUMERIC,
                        submitted_notional_usdc NUMERIC,
                        possible_execution_notional_usdc NUMERIC,
                        plan_evidence_sha256 CHAR(64),
                        diagnostic_code VARCHAR(96) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CHECK (
                            (window_state = 'NONE' AND window_id IS NULL)
                            OR
                            (window_state <> 'NONE' AND window_id IS NOT NULL)
                        ),
                        CHECK (
                            (create_state = 'NOT_CLAIMED'
                             AND placement_claim_id IS NULL)
                            OR
                            (create_state <> 'NOT_CLAIMED'
                             AND placement_claim_id IS NOT NULL)
                        )
                    )
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._table('operator_hotpoint_control')}
                    ADD COLUMN IF NOT EXISTS cancel_claim_id UUID UNIQUE
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._table('operator_hotpoint_control')}
                    ADD COLUMN IF NOT EXISTS create_exchange_invoked BOOLEAN
                    """
                )
                cursor.execute(
                    f"""
                    ALTER TABLE {self._table('operator_hotpoint_control')}
                    ADD COLUMN IF NOT EXISTS cancel_exchange_invoked BOOLEAN
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table('operator_hotpoint_control_command')} (
                        command_id UUID PRIMARY KEY,
                        action VARCHAR(16) NOT NULL
                            CHECK (action IN ({_sql_values(_CONTROL_ACTIONS)})),
                        expected_revision INTEGER NOT NULL,
                        result_revision INTEGER NOT NULL,
                        idempotency_key_sha256 CHAR(64) NOT NULL UNIQUE,
                        payload_sha256 CHAR(64) NOT NULL,
                        actor_id VARCHAR(255) NOT NULL,
                        roles_json JSONB NOT NULL,
                        correlation_id VARCHAR(255) NOT NULL,
                        audit_id UUID NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE OR REPLACE FUNCTION
                        {self._table('guard_operator_hotpoint_command_append_only')}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = '55000',
                            MESSAGE = 'operator_hotpoint_command_append_only';
                    END;
                    $$
                    """
                )
                cursor.execute(
                    f"DROP TRIGGER IF EXISTS operator_hotpoint_command_append_only "
                    f"ON {self._table('operator_hotpoint_control_command')}"
                )
                cursor.execute(
                    f"""
                    CREATE TRIGGER operator_hotpoint_command_append_only
                    BEFORE UPDATE OR DELETE ON
                        {self._table('operator_hotpoint_control_command')}
                    FOR EACH ROW EXECUTE FUNCTION
                        {self._table('guard_operator_hotpoint_command_append_only')}()
                    """
                )
            self._schema_ready = True

    @staticmethod
    def _record(row: Mapping[str, Any]) -> OperatorHotpointControlRecord:
        roles_value = row.get("roles_json")
        if isinstance(roles_value, str):
            roles_value = json.loads(roles_value)
        return OperatorHotpointControlRecord(
            goal_id=str(row["goal_id"]),
            revision=int(row["revision"]),
            kill_switch_state=HotpointKillSwitchState(
                str(row["kill_switch_state"])
            ),
            window_state=HotpointWindowState(str(row["window_state"])),
            parent_client_order_id=(
                str(row["parent_client_order_id"])
                if row.get("parent_client_order_id")
                else None
            ),
            product_id=(
                str(row["product_id"]) if row.get("product_id") else None
            ),
            side=str(row["side"]) if row.get("side") else None,
            window_id=(
                str(row["window_id"]) if row.get("window_id") else None
            ),
            window_started_at=_iso(row.get("window_started_at")),
            window_expires_at=_iso(row.get("window_expires_at")),
            create_state=HotpointCreateState(str(row["create_state"])),
            cancel_state=HotpointCancelState(str(row["cancel_state"])),
            create_exchange_invoked=row.get("create_exchange_invoked"),
            cancel_exchange_invoked=row.get("cancel_exchange_invoked"),
            placement_claim_id=(
                str(row["placement_claim_id"])
                if row.get("placement_claim_id")
                else None
            ),
            cancel_claim_id=(
                str(row["cancel_claim_id"])
                if row.get("cancel_claim_id")
                else None
            ),
            child_client_order_id=(
                str(row["child_client_order_id"])
                if row.get("child_client_order_id")
                else None
            ),
            diagnostic_code=str(row["diagnostic_code"]),
            actor_id=str(row["actor_id"]),
            roles=tuple(str(role) for role in (roles_value or [])),
            correlation_id=str(row["correlation_id"]),
            audit_id=str(row["audit_id"]),
            recorded_at=str(_iso(row["recorded_at"])),
            updated_at=str(_iso(row["updated_at"])),
            goal_create_claim_consumed=bool(row.get("goal_create_claim_id")),
            goal_create_claim_domain=(
                str(row["goal_create_claim_domain"])
                if row.get("goal_create_claim_domain")
                else None
            ),
            goal_cancel_claim_consumed=bool(row.get("goal_cancel_claim_id")),
            goal_cancel_claim_domain=(
                str(row["goal_cancel_claim_domain"])
                if row.get("goal_cancel_claim_domain")
                else None
            ),
        )

    def _current(self, cursor: Any, *, lock: bool) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT control.*,
                   (
                       SELECT create_claim_id
                         FROM {self._table('operator_hotpoint_goal_allowance')}
                        WHERE goal_id = %s
                   ) AS goal_create_claim_id,
                   (
                       SELECT create_claim_domain
                         FROM {self._table('operator_hotpoint_goal_allowance')}
                        WHERE goal_id = %s
                   ) AS goal_create_claim_domain,
                   (
                       SELECT cancel_claim_id
                         FROM {self._table('operator_hotpoint_goal_allowance')}
                        WHERE goal_id = %s
                   ) AS goal_cancel_claim_id,
                   (
                       SELECT cancel_claim_domain
                         FROM {self._table('operator_hotpoint_goal_allowance')}
                        WHERE goal_id = %s
                   ) AS goal_cancel_claim_domain
              FROM {self._table('operator_hotpoint_control')} AS control
             WHERE control.goal_id = %s
             {"FOR UPDATE" if lock else ""}
            """,
            (
                HOTPOINT_GOAL_ID,
                HOTPOINT_GOAL_ID,
                HOTPOINT_GOAL_ID,
                HOTPOINT_GOAL_ID,
                HOTPOINT_GOAL_ID,
            ),
        )
        return _row(cursor)

    @staticmethod
    def _default_record(
        *,
        goal_create_claim_id: str | None = None,
        goal_create_claim_domain: str | None = None,
        goal_cancel_claim_id: str | None = None,
        goal_cancel_claim_domain: str | None = None,
    ) -> OperatorHotpointControlRecord:
        epoch = "1970-01-01T00:00:00+00:00"
        return OperatorHotpointControlRecord(
            goal_id=HOTPOINT_GOAL_ID,
            revision=0,
            kill_switch_state=HotpointKillSwitchState.DISABLED,
            window_state=HotpointWindowState.NONE,
            parent_client_order_id=None,
            product_id=None,
            side=None,
            window_id=None,
            window_started_at=None,
            window_expires_at=None,
            create_state=HotpointCreateState.NOT_CLAIMED,
            cancel_state=HotpointCancelState.NOT_CLAIMED,
            create_exchange_invoked=None,
            cancel_exchange_invoked=None,
            placement_claim_id=None,
            cancel_claim_id=None,
            child_client_order_id=None,
            diagnostic_code="operator_hotpoint_disabled",
            actor_id="system",
            roles=(),
            correlation_id="not_recorded",
            audit_id="00000000-0000-0000-0000-000000000000",
            recorded_at=epoch,
            updated_at=epoch,
            goal_create_claim_consumed=goal_create_claim_id is not None,
            goal_create_claim_domain=goal_create_claim_domain,
            goal_cancel_claim_consumed=goal_cancel_claim_id is not None,
            goal_cancel_claim_domain=goal_cancel_claim_domain,
        )

    def read(self) -> OperatorHotpointControlRecord:
        self.ensure_schema()
        with self._cursor() as cursor:
            current = self._current(cursor, lock=False)
            if current is None:
                cursor.execute(
                    f"""
                    SELECT create_claim_id, create_claim_domain,
                           cancel_claim_id, cancel_claim_domain
                      FROM {self._table('operator_hotpoint_goal_allowance')}
                     WHERE goal_id = %s
                    """,
                    (HOTPOINT_GOAL_ID,),
                )
                allowance = _row(cursor) or {}
        return (
            self._record(current)
            if current is not None
            else self._default_record(
                goal_create_claim_id=(
                    str(allowance["create_claim_id"])
                    if allowance.get("create_claim_id")
                    else None
                ),
                goal_create_claim_domain=(
                    str(allowance["create_claim_domain"])
                    if allowance.get("create_claim_domain")
                    else None
                ),
                goal_cancel_claim_id=(
                    str(allowance["cancel_claim_id"])
                    if allowance.get("cancel_claim_id")
                    else None
                ),
                goal_cancel_claim_domain=(
                    str(allowance["cancel_claim_domain"])
                    if allowance.get("cancel_claim_domain")
                    else None
                ),
            )
        )

    def list_eligible_parents(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], int]:
        self.ensure_schema()
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, UPPER(side) AS side,
                       UPPER(status) AS status,
                       COUNT(*) OVER() AS total_count
                  FROM {self._table('order_parent')}
                 WHERE product_id = %s
                   AND UPPER(status) = 'OPEN'
                   AND parent_order_id IS NULL
                   AND ownership_provenance = ANY(%s)
                   AND retail_portfolio_id = %s
                   AND auto_placed_by_hotpoint IS NOT TRUE
                 ORDER BY created_at DESC, client_order_id ASC
                 LIMIT %s OFFSET %s
                """,
                (
                    self.policy.product_id,
                    sorted(_ALLOWED_PARENT_PROVENANCE),
                    self.configured_portfolio_id,
                    limit,
                    offset,
                ),
            )
            rows: list[dict[str, str]] = []
            total = 0
            while (row := _row(cursor)) is not None:
                total = int(row.get("total_count") or 0)
                rows.append(
                    {
                        "client_order_id": str(row["client_order_id"]),
                        "product_id": str(row["product_id"]),
                        "side": str(row["side"]),
                        "status": str(row["status"]),
                    }
                )
        return rows, total

    def _parent(self, cursor: Any, parent_id: str) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT client_order_id, product_id, side, status,
                   parent_order_id, ownership_provenance,
                   retail_portfolio_id, auto_placed_by_hotpoint
              FROM {self._table('order_parent')}
             WHERE client_order_id = %s
             FOR UPDATE
            """,
            (parent_id,),
        )
        parent = _row(cursor)
        if parent is None:
            raise ValueError("operator_hotpoint_parent_not_found")
        if (
            str(parent.get("product_id") or "") != self.policy.product_id
            or str(parent.get("status") or "").upper() != "OPEN"
            or parent.get("parent_order_id") is not None
            or str(parent.get("ownership_provenance") or "")
            not in _ALLOWED_PARENT_PROVENANCE
            or str(parent.get("retail_portfolio_id") or "")
            != self.configured_portfolio_id
            or parent.get("auto_placed_by_hotpoint") is True
            or str(parent.get("side") or "").upper() not in {"BUY", "SELL"}
        ):
            raise ValueError("operator_hotpoint_parent_ineligible")
        return parent

    def transition_control(
        self,
        *,
        action: HotpointControlAction,
        expected_revision: int,
        authorize_one_bounded_trigger_window: bool,
        acknowledge_unknown_outcome_consumes_create_allowance: bool,
        acknowledge_backend_derives_child_terms: bool,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        correlation_id: str,
        audit_id: str,
        parent_client_order_id: str | None = None,
    ) -> OperatorHotpointControlRecord:
        self.ensure_schema()
        if (
            not isinstance(action, HotpointControlAction)
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise ValueError("operator_hotpoint_control_invalid")
        delegated = bool(
            authorize_one_bounded_trigger_window is True
            and acknowledge_unknown_outcome_consumes_create_allowance is True
            and acknowledge_backend_derives_child_terms is True
        )
        if action is HotpointControlAction.ENABLE and not delegated:
            raise ValueError("operator_hotpoint_enable_authority_required")
        if action is not HotpointControlAction.ENABLE and any(
            (
                authorize_one_bounded_trigger_window,
                acknowledge_unknown_outcome_consumes_create_allowance,
                acknowledge_backend_derives_child_terms,
            )
        ):
            raise ValueError("operator_hotpoint_control_authority_invalid")
        key_hash = hashlib.sha256(str(idempotency_key).encode()).hexdigest()
        payload = {
            "action": action.value,
            "expected_revision": expected_revision,
            "parent_client_order_id": parent_client_order_id,
            "delegated": delegated,
            "actor_id": str(actor_id),
            "roles": list(roles),
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        normalized_audit = str(uuid.UUID(str(audit_id)))
        with self._cursor() as cursor:
            self._lock(cursor)
            cursor.execute(
                f"""
                SELECT payload_sha256, result_revision
                  FROM {self._table('operator_hotpoint_control_command')}
                 WHERE idempotency_key_sha256 = %s
                """,
                (key_hash,),
            )
            replay = _row(cursor)
            if replay is not None:
                if str(replay["payload_sha256"]) != payload_hash:
                    raise ValueError("operator_hotpoint_idempotency_conflict")
                current = self._current(cursor, lock=True)
                if (
                    current is None
                    or int(current["revision"]) != int(replay["result_revision"])
                ):
                    raise ValueError("operator_hotpoint_replay_invalid")
                return self._record(current)

            current_row = self._current(cursor, lock=True)
            current = (
                self._record(current_row)
                if current_row is not None
                else self._default_record()
            )
            if current.revision != expected_revision:
                raise ValueError("operator_hotpoint_revision_conflict")
            if (
                action
                in {
                    HotpointControlAction.ENABLE,
                    HotpointControlAction.ARM,
                }
                and current.goal_create_claim_consumed
            ):
                raise ValueError("operator_hotpoint_goal_allowance_consumed")
            next_revision = current.revision + 1
            now = self.clock()
            kill_state = current.kill_switch_state
            window_state = current.window_state
            window_id = current.window_id
            parent_id = current.parent_client_order_id
            product_id = current.product_id
            side = current.side
            started_at = current.window_started_at
            expires_at = current.window_expires_at
            diagnostic = current.diagnostic_code
            create_authority = (
                current_row.get("delegated_create_authority") is True
                if current_row is not None
                else False
            )
            if action is HotpointControlAction.ENABLE:
                kill_state = HotpointKillSwitchState.ENABLED
                create_authority = True
                diagnostic = "operator_hotpoint_enabled"
            elif action is HotpointControlAction.DISABLE:
                kill_state = HotpointKillSwitchState.DISABLED
                create_authority = False
                if window_state is HotpointWindowState.ARMED:
                    window_state = HotpointWindowState.DISARMED
                diagnostic = "operator_hotpoint_disabled"
            elif action is HotpointControlAction.ARM:
                if (
                    kill_state is not HotpointKillSwitchState.ENABLED
                    or not create_authority
                ):
                    raise ValueError("operator_hotpoint_enable_required")
                if window_id is not None:
                    raise ValueError("operator_hotpoint_window_single_use")
                parent_id = str(parent_client_order_id or "").strip()
                parent = self._parent(cursor, parent_id)
                product_id = str(parent["product_id"])
                side = str(parent["side"]).upper()
                window_id = str(uuid.uuid4())
                started = now.astimezone(timezone.utc)
                expires = started + timedelta(seconds=_WINDOW_SECONDS)
                started_at = started.isoformat()
                expires_at = expires.isoformat()
                window_state = HotpointWindowState.ARMED
                diagnostic = "operator_hotpoint_window_armed"
            elif action is HotpointControlAction.DISARM:
                if window_state is not HotpointWindowState.ARMED:
                    raise ValueError("operator_hotpoint_window_not_armed")
                window_state = HotpointWindowState.DISARMED
                diagnostic = "operator_hotpoint_window_disarmed"
            else:
                raise ValueError("operator_hotpoint_control_invalid")

            values = (
                HOTPOINT_GOAL_ID,
                next_revision,
                kill_state.value,
                create_authority,
                window_state.value,
                parent_id,
                product_id,
                side,
                window_id,
                started_at,
                expires_at,
                diagnostic,
                str(actor_id),
                json.dumps(list(roles), separators=(",", ":")),
                str(correlation_id),
                normalized_audit,
            )
            if current_row is None:
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_hotpoint_control')} (
                        goal_id, revision, kill_switch_state,
                        delegated_create_authority, window_state,
                        parent_client_order_id, product_id, side, window_id,
                        window_started_at, window_expires_at,
                        create_state, cancel_state, diagnostic_code,
                        actor_id, roles_json, correlation_id, audit_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'NOT_CLAIMED', 'NOT_CLAIMED', %s, %s, %s::jsonb,
                        %s, %s
                    )
                    """,
                    values,
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET revision = %s,
                           kill_switch_state = %s,
                           delegated_create_authority = %s,
                           window_state = %s,
                           parent_client_order_id = %s,
                           product_id = %s,
                           side = %s,
                           window_id = %s,
                           window_started_at = %s,
                           window_expires_at = %s,
                           diagnostic_code = %s,
                           actor_id = %s,
                           roles_json = %s::jsonb,
                           correlation_id = %s,
                           audit_id = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s
                       AND revision = %s
                    """,
                    (
                        next_revision,
                        kill_state.value,
                        create_authority,
                        window_state.value,
                        parent_id,
                        product_id,
                        side,
                        window_id,
                        started_at,
                        expires_at,
                        diagnostic,
                        str(actor_id),
                        json.dumps(list(roles), separators=(",", ":")),
                        str(correlation_id),
                        normalized_audit,
                        HOTPOINT_GOAL_ID,
                        current.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("operator_hotpoint_revision_conflict")
            cursor.execute(
                f"""
                INSERT INTO {self._table('operator_hotpoint_control_command')} (
                    command_id, action, expected_revision, result_revision,
                    idempotency_key_sha256, payload_sha256,
                    actor_id, roles_json, correlation_id, audit_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    action.value,
                    expected_revision,
                    next_revision,
                    key_hash,
                    payload_hash,
                    str(actor_id),
                    json.dumps(list(roles), separators=(",", ":")),
                    str(correlation_id),
                    normalized_audit,
                ),
            )
            persisted = self._current(cursor, lock=False)
            if persisted is None:
                raise ValueError("operator_hotpoint_persistence_unknown")
            return self._record(persisted)

    def _trigger_prices(
        self,
        cursor: Any,
        *,
        parent_id: str,
        product_id: str,
        side: str,
        started_at: str,
    ) -> tuple[Decimal, ...]:
        cursor.execute(
            f"""
            SELECT fill.price
              FROM {self._table('fill_ledger')} AS fill
              LEFT JOIN {self._table('order_parent')} AS source
                ON source.client_order_id = fill.client_order_id
             WHERE fill.created_at >= %s
               AND fill.instrument = %s
               AND UPPER(fill.side) = %s
               AND fill.quantity > 0
               AND (
                    fill.client_order_id = %s
                    OR source.parent_order_id = %s
               )
             ORDER BY fill.created_at ASC, fill.id ASC
            """,
            (started_at, product_id, side, parent_id, parent_id),
        )
        by_bucket: dict[int, list[Decimal]] = {}
        while (row := _row(cursor)) is not None:
            price = _decimal(
                row.get("price"),
                code="operator_hotpoint_fill_evidence_invalid",
            )
            if price <= 0:
                continue
            bucket_id = compute_bucket_id(
                float(price),
                float(_BUCKET_WIDTH_PCT),
            )
            by_bucket.setdefault(bucket_id, []).append(price)
        qualified = [
            prices
            for prices in by_bucket.values()
            if len(prices) >= _TRIGGER_FILL_COUNT
        ]
        if not qualified:
            return ()
        prices = qualified[-1][-_TRIGGER_FILL_COUNT:]
        return tuple(prices)

    def _plan(
        self,
        *,
        row: Mapping[str, Any],
        prices: tuple[Decimal, ...],
        claim_id: str,
    ) -> HotpointPlacementPlan | None:
        metadata = self.product_metadata_provider(str(row["product_id"]))
        minimum = _decimal(
            _metadata_value(metadata, "base_min_size"),
            code="operator_hotpoint_product_metadata_invalid",
        )
        base_increment = _decimal(
            _metadata_value(metadata, "base_increment"),
            code="operator_hotpoint_product_metadata_invalid",
        )
        price_increment = _decimal(
            _metadata_value(metadata, "price_increment"),
            code="operator_hotpoint_product_metadata_invalid",
        )
        if minimum <= 0 or base_increment <= 0 or price_increment <= 0:
            return None
        size_steps = (minimum / base_increment).to_integral_value(
            rounding=ROUND_CEILING
        )
        size = size_steps * base_increment
        if self.policy.exact_size is not None:
            if (
                self.policy.exact_size < minimum
                or self.policy.exact_size % base_increment != 0
            ):
                return None
            size = self.policy.exact_size
        mean_price = sum(prices, Decimal("0")) / Decimal(len(prices))
        rounding = (
            ROUND_FLOOR
            if str(row["side"]).upper() == "BUY"
            else ROUND_CEILING
        )
        price_steps = (mean_price / price_increment).to_integral_value(
            rounding=rounding
        )
        price = price_steps * price_increment
        contract_multiplier = Decimal("1")
        if self.policy.domain == "FUTURES":
            futures_multiplier = _futures_contract_multiplier(metadata)
            if futures_multiplier is None:
                return None
            contract_multiplier = futures_multiplier
        notional = size * price * contract_multiplier
        if (
            size <= 0
            or price <= 0
            or (
                notional >= self.policy.max_submitted_notional_usdc
                if self.policy.strict_caps
                else notional > self.policy.max_submitted_notional_usdc
            )
            or (
                notional >= self.policy.max_possible_execution_notional_usdc
                if self.policy.strict_caps
                else notional
                > self.policy.max_possible_execution_notional_usdc
            )
            or (
                self.policy.max_turnover_notional_usdc is not None
                and (
                    notional >= self.policy.max_turnover_notional_usdc
                    if self.policy.strict_caps
                    else notional > self.policy.max_turnover_notional_usdc
                )
            )
        ):
            return None
        child_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                ":".join(
                    (
                        HOTPOINT_GOAL_ID,
                        self.policy.domain,
                        str(row["window_id"]),
                        str(row["parent_client_order_id"]),
                    )
                ),
            )
        )
        evidence = {
            "goal_id": HOTPOINT_GOAL_ID,
            "domain": self.policy.domain,
            "portfolio_profile_alias": self.policy.portfolio_profile_alias,
            "window_id": str(row["window_id"]),
            "parent_client_order_id": str(row["parent_client_order_id"]),
            "child_client_order_id": child_id,
            "product_id": str(row["product_id"]),
            "side": str(row["side"]),
            "base_size": str(size),
            "contract_multiplier": str(contract_multiplier),
            "limit_price": str(price),
            "post_only": True,
            "fill_count": len(prices),
            "max_submitted_notional_usdc": str(
                self.policy.max_submitted_notional_usdc
            ),
            "max_possible_execution_notional_usdc": str(
                self.policy.max_possible_execution_notional_usdc
            ),
            "max_turnover_notional_usdc": (
                str(self.policy.max_turnover_notional_usdc)
                if self.policy.max_turnover_notional_usdc is not None
                else None
            ),
            "portfolio_id_sha256": hashlib.sha256(
                self.configured_portfolio_id.encode()
            ).hexdigest(),
        }
        evidence_hash = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return HotpointPlacementPlan(
            goal_id=HOTPOINT_GOAL_ID,
            window_id=str(row["window_id"]),
            placement_claim_id=claim_id,
            parent_client_order_id=str(row["parent_client_order_id"]),
            child_client_order_id=child_id,
            product_id=str(row["product_id"]),
            side=str(row["side"]),
            base_size=size,
            limit_price=price,
            post_only=True,
            submitted_notional_usdc=notional,
            possible_execution_notional_usdc=notional,
            max_submitted_notional_usdc=(
                self.policy.max_submitted_notional_usdc
            ),
            max_possible_execution_notional_usdc=(
                self.policy.max_possible_execution_notional_usdc
            ),
            evidence_sha256=evidence_hash,
            portfolio_id=self.configured_portfolio_id,
            actor_id=str(row["actor_id"]),
            roles=tuple(
                str(role)
                for role in (
                    json.loads(row["roles_json"])
                    if isinstance(row.get("roles_json"), str)
                    else row.get("roles_json") or []
                )
            ),
            correlation_id=str(row["correlation_id"]),
            audit_id=str(row["audit_id"]),
        )

    def claim_placement(
        self,
        *,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        correlation_id: str,
        audit_id: str,
    ) -> tuple[OperatorHotpointControlRecord, HotpointPlacementPlan] | None:
        del idempotency_key
        self.ensure_schema()
        with self._cursor() as cursor:
            self._goal_allowance_lock(cursor)
            self._lock(cursor)
            row = self._current(cursor, lock=True)
            if row is None:
                return None
            current = self._record(row)
            if (
                current.kill_switch_state
                is not HotpointKillSwitchState.ENABLED
                or row.get("delegated_create_authority") is not True
                or current.window_state is not HotpointWindowState.ARMED
                or current.create_state is not HotpointCreateState.NOT_CLAIMED
                or not current.parent_client_order_id
                or not current.window_id
                or not current.window_started_at
                or not current.window_expires_at
            ):
                return None
            now = self.clock().astimezone(timezone.utc)
            expires = datetime.fromisoformat(current.window_expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now >= expires:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET window_state = 'EXPIRED',
                           diagnostic_code = 'operator_hotpoint_window_expired',
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s AND window_state = 'ARMED'
                    """,
                    (HOTPOINT_GOAL_ID,),
                )
                return None
            self._parent(cursor, current.parent_client_order_id)
            prices = self._trigger_prices(
                cursor,
                parent_id=current.parent_client_order_id,
                product_id=str(current.product_id),
                side=str(current.side),
                started_at=current.window_started_at,
            )
            if not prices:
                return None
            claim_id = str(uuid.uuid4())
            claim_row = dict(row)
            claim_row.update(
                {
                    "actor_id": str(actor_id),
                    "roles_json": list(roles),
                    "correlation_id": str(correlation_id),
                    "audit_id": str(uuid.UUID(str(audit_id))),
                }
            )
            plan = self._plan(
                row=claim_row,
                prices=prices,
                claim_id=claim_id,
            )
            if plan is None:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET window_state = 'TERMINAL',
                           diagnostic_code =
                               'operator_hotpoint_no_cap_safe_size',
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s
                       AND window_state = 'ARMED'
                       AND create_state = 'NOT_CLAIMED'
                    """,
                    (HOTPOINT_GOAL_ID,),
                )
                return None
            cursor.execute(
                f"""
                INSERT INTO {self._table('operator_hotpoint_goal_allowance')} (
                    goal_id, create_claim_id, create_claim_domain
                ) VALUES (%s, %s, %s)
                ON CONFLICT (goal_id) DO NOTHING
                """,
                (HOTPOINT_GOAL_ID, claim_id, self.policy.domain),
            )
            if cursor.rowcount != 1:
                return None
            cursor.execute(
                f"""
                UPDATE {self._table('operator_hotpoint_control')}
                   SET window_state = 'CLAIMED',
                       create_state = 'CLAIMED',
                       placement_claim_id = %s,
                       child_client_order_id = %s,
                       base_size = %s,
                       limit_price = %s,
                       submitted_notional_usdc = %s,
                       possible_execution_notional_usdc = %s,
                       plan_evidence_sha256 = %s,
                       actor_id = %s,
                       roles_json = %s::jsonb,
                       correlation_id = %s,
                       audit_id = %s,
                       diagnostic_code = 'operator_hotpoint_create_claimed',
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                   AND window_state = 'ARMED'
                   AND create_state = 'NOT_CLAIMED'
                """,
                (
                    claim_id,
                    plan.child_client_order_id,
                    plan.base_size,
                    plan.limit_price,
                    plan.submitted_notional_usdc,
                    plan.possible_execution_notional_usdc,
                    plan.evidence_sha256,
                    plan.actor_id,
                    json.dumps(list(plan.roles), separators=(",", ":")),
                    plan.correlation_id,
                    plan.audit_id,
                    HOTPOINT_GOAL_ID,
                ),
            )
            if cursor.rowcount != 1:
                return None
            claimed = self._current(cursor, lock=False)
            if claimed is None:
                raise ValueError("operator_hotpoint_claim_persistence_unknown")
            return self._record(claimed), plan

    def finalize_placement(
        self,
        *,
        placement_claim_id: str,
        outcome: HotpointPlacementOutcome,
        child_client_order_id: str | None,
        diagnostic_code: str,
        exchange_invoked: bool | None,
    ) -> OperatorHotpointControlRecord:
        self.ensure_schema()
        claim_id = str(uuid.UUID(str(placement_claim_id)))
        if not isinstance(outcome, HotpointPlacementOutcome):
            raise ValueError("operator_hotpoint_terminal_invalid")
        create_state = {
            HotpointPlacementOutcome.ACCEPTED: HotpointCreateState.ACCEPTED,
            HotpointPlacementOutcome.REJECTED: HotpointCreateState.REJECTED,
            HotpointPlacementOutcome.UNKNOWN: HotpointCreateState.UNKNOWN,
        }[outcome]
        with self._cursor() as cursor:
            self._lock(cursor)
            current_row = self._current(cursor, lock=True)
            if current_row is None:
                raise ValueError("operator_hotpoint_not_found")
            current = self._record(current_row)
            if current.create_state.is_terminal:
                if (
                    current.placement_claim_id == claim_id
                    and current.create_state is create_state
                ):
                    return current
                raise ValueError("operator_hotpoint_terminal_conflict")
            if (
                current.create_state is not HotpointCreateState.CLAIMED
                or current.placement_claim_id != claim_id
                or (
                    outcome is HotpointPlacementOutcome.ACCEPTED
                    and child_client_order_id
                    != current.child_client_order_id
                )
            ):
                raise ValueError("operator_hotpoint_claim_conflict")
            cursor.execute(
                f"""
                UPDATE {self._table('operator_hotpoint_control')}
                   SET kill_switch_state = 'DISABLED',
                       delegated_create_authority = FALSE,
                       window_state = 'TERMINAL',
                       create_state = %s,
                       child_client_order_id = %s,
                       create_exchange_invoked = %s,
                       diagnostic_code = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                   AND placement_claim_id = %s
                   AND create_state = 'CLAIMED'
                """,
                (
                    create_state.value,
                    (
                        child_client_order_id
                        if outcome is HotpointPlacementOutcome.ACCEPTED
                        else current.child_client_order_id
                    ),
                    exchange_invoked,
                    str(diagnostic_code),
                    HOTPOINT_GOAL_ID,
                    claim_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("operator_hotpoint_terminal_persistence_unknown")
            finalized = self._current(cursor, lock=False)
            if finalized is None:
                raise ValueError("operator_hotpoint_terminal_persistence_unknown")
            return self._record(finalized)

    def claim_cancel(
        self,
        *,
        idempotency_key: str,
        actor_id: str,
        roles: tuple[str, ...],
        correlation_id: str,
        audit_id: str,
    ) -> tuple[OperatorHotpointControlRecord, HotpointCancelPlan] | None:
        del idempotency_key
        self.ensure_schema()
        normalized_audit = str(uuid.UUID(str(audit_id)))
        with self._cursor() as cursor:
            self._goal_allowance_lock(cursor)
            self._lock(cursor)
            row = self._current(cursor, lock=True)
            if row is None:
                return None
            current = self._record(row)
            if current.cancel_state.is_terminal:
                return None
            if (
                current.create_state is not HotpointCreateState.ACCEPTED
                or current.cancel_state is not HotpointCancelState.NOT_CLAIMED
                or not current.placement_claim_id
                or not current.parent_client_order_id
                or not current.child_client_order_id
                or not row.get("plan_evidence_sha256")
            ):
                raise ValueError("operator_hotpoint_cancel_not_available")
            cursor.execute(
                f"""
                SELECT client_order_id, parent_order_id, product_id, status,
                       ownership_provenance, retail_portfolio_id
                  FROM {self._table('order_parent')}
                 WHERE client_order_id = %s
                 FOR UPDATE
                """,
                (current.child_client_order_id,),
            )
            child = _row(cursor)
            if (
                child is None
                or str(child.get("client_order_id") or "")
                != current.child_client_order_id
                or str(child.get("parent_order_id") or "")
                != current.parent_client_order_id
                or str(child.get("product_id") or "")
                != self.policy.product_id
                or str(child.get("ownership_provenance") or "")
                != "ADMIN_HOTPOINT_CHILD"
                or str(child.get("retail_portfolio_id") or "")
                != self.configured_portfolio_id
            ):
                raise ValueError("operator_hotpoint_cancel_child_mismatch")
            status = str(child.get("status") or "").upper()
            if status in {"CANCELLED", "FILLED", "EXPIRED", "FAILED"}:
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET cancel_state = 'NOT_REQUIRED',
                           diagnostic_code =
                               'operator_hotpoint_cancel_not_required_terminal',
                           actor_id = %s,
                           roles_json = %s::jsonb,
                           correlation_id = %s,
                           audit_id = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s
                       AND cancel_state = 'NOT_CLAIMED'
                    """,
                    (
                        str(actor_id),
                        json.dumps(list(roles), separators=(",", ":")),
                        str(correlation_id),
                        normalized_audit,
                        HOTPOINT_GOAL_ID,
                    ),
                )
                return None
            if status not in {"PENDING", "OPEN", "QUEUED"}:
                raise ValueError("operator_hotpoint_cancel_child_state_unknown")
            cancel_claim_id = str(uuid.uuid4())
            cursor.execute(
                f"""
                UPDATE {self._table('operator_hotpoint_goal_allowance')}
                   SET cancel_claim_id = %s,
                       cancel_claim_domain = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                   AND create_claim_id = %s
                   AND create_claim_domain = %s
                   AND cancel_claim_id IS NULL
                """,
                (
                    cancel_claim_id,
                    self.policy.domain,
                    HOTPOINT_GOAL_ID,
                    current.placement_claim_id,
                    self.policy.domain,
                ),
            )
            if cursor.rowcount != 1:
                return None
            cursor.execute(
                f"""
                UPDATE {self._table('operator_hotpoint_control')}
                   SET cancel_state = 'CLAIMED',
                       cancel_claim_id = %s,
                       diagnostic_code = 'operator_hotpoint_cancel_claimed',
                       actor_id = %s,
                       roles_json = %s::jsonb,
                       correlation_id = %s,
                       audit_id = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                   AND create_state = 'ACCEPTED'
                   AND cancel_state = 'NOT_CLAIMED'
                """,
                (
                    cancel_claim_id,
                    str(actor_id),
                    json.dumps(list(roles), separators=(",", ":")),
                    str(correlation_id),
                    normalized_audit,
                    HOTPOINT_GOAL_ID,
                ),
            )
            if cursor.rowcount != 1:
                return None
            claimed_row = self._current(cursor, lock=False)
            if claimed_row is None:
                raise ValueError("operator_hotpoint_cancel_claim_unknown")
            claimed = self._record(claimed_row)
            plan = HotpointCancelPlan(
                goal_id=HOTPOINT_GOAL_ID,
                cancel_claim_id=cancel_claim_id,
                placement_claim_id=str(current.placement_claim_id),
                parent_client_order_id=str(current.parent_client_order_id),
                child_client_order_id=str(current.child_client_order_id),
                product_id=self.policy.product_id,
                plan_sha256=str(row["plan_evidence_sha256"]),
                portfolio_id=self.configured_portfolio_id,
                actor_id=str(actor_id),
                roles=tuple(str(role) for role in roles),
                correlation_id=str(correlation_id),
                audit_id=normalized_audit,
            )
            return claimed, plan

    def finalize_cancel(
        self,
        *,
        cancel_claim_id: str,
        outcome: HotpointPlacementOutcome,
        diagnostic_code: str,
        exchange_invoked: bool | None,
    ) -> OperatorHotpointControlRecord:
        self.ensure_schema()
        claim_id = str(uuid.UUID(str(cancel_claim_id)))
        if not isinstance(outcome, HotpointPlacementOutcome):
            raise ValueError("operator_hotpoint_cancel_terminal_invalid")
        cancel_state = {
            HotpointPlacementOutcome.ACCEPTED: HotpointCancelState.ACCEPTED,
            HotpointPlacementOutcome.REJECTED: HotpointCancelState.REJECTED,
            HotpointPlacementOutcome.UNKNOWN: HotpointCancelState.UNKNOWN,
        }[outcome]
        with self._cursor() as cursor:
            self._lock(cursor)
            current_row = self._current(cursor, lock=True)
            if current_row is None:
                raise ValueError("operator_hotpoint_not_found")
            current = self._record(current_row)
            if current.cancel_state.is_terminal:
                if (
                    current.cancel_claim_id == claim_id
                    and current.cancel_state is cancel_state
                ):
                    return current
                raise ValueError("operator_hotpoint_cancel_terminal_conflict")
            if (
                current.cancel_state is not HotpointCancelState.CLAIMED
                or current.cancel_claim_id != claim_id
            ):
                raise ValueError("operator_hotpoint_cancel_claim_conflict")
            cursor.execute(
                f"""
                UPDATE {self._table('operator_hotpoint_control')}
                   SET cancel_state = %s,
                       cancel_exchange_invoked = %s,
                       diagnostic_code = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE goal_id = %s
                   AND cancel_claim_id = %s
                   AND cancel_state = 'CLAIMED'
                """,
                (
                    cancel_state.value,
                    exchange_invoked,
                    str(diagnostic_code),
                    HOTPOINT_GOAL_ID,
                    claim_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "operator_hotpoint_cancel_terminal_persistence_unknown"
                )
            finalized = self._current(cursor, lock=False)
            if finalized is None:
                raise ValueError(
                    "operator_hotpoint_cancel_terminal_persistence_unknown"
                )
            return self._record(finalized)

    def recover_stranded_claim(self) -> OperatorHotpointControlRecord | None:
        """Terminalize a post-claim restart as unknown without replay."""

        self.ensure_schema()
        with self._cursor() as cursor:
            self._lock(cursor)
            current_row = self._current(cursor, lock=True)
            if current_row is None:
                return None
            current = self._record(current_row)
            if (
                current.create_state is HotpointCreateState.CLAIMED
                and current.placement_claim_id
            ):
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET kill_switch_state = 'DISABLED',
                           delegated_create_authority = FALSE,
                           window_state = 'TERMINAL',
                           create_state = 'UNKNOWN',
                           diagnostic_code =
                               'operator_hotpoint_create_outcome_unknown',
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s
                       AND create_state = 'CLAIMED'
                    """,
                    (HOTPOINT_GOAL_ID,),
                )
            elif (
                current.cancel_state is HotpointCancelState.CLAIMED
                and current.cancel_claim_id
            ):
                cursor.execute(
                    f"""
                    UPDATE {self._table('operator_hotpoint_control')}
                       SET cancel_state = 'UNKNOWN',
                           diagnostic_code =
                               'operator_hotpoint_cancel_outcome_unknown',
                           updated_at = CURRENT_TIMESTAMP
                     WHERE goal_id = %s
                       AND cancel_state = 'CLAIMED'
                    """,
                    (HOTPOINT_GOAL_ID,),
                )
            else:
                return None
            recovered = self._current(cursor, lock=False)
            return self._record(recovered) if recovered is not None else None


_DEFAULT_REPOSITORY: OperatorHotpointControlRepository | None = None
_DEFAULT_FUTURES_REPOSITORY: OperatorHotpointControlRepository | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_product_metadata(product_id: str) -> object:
    from configuration import PRODUCT_METADATA

    return PRODUCT_METADATA.get(product_id) or {}


def get_default_operator_hotpoint_control_repository(
) -> OperatorHotpointControlRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_REPOSITORY is None:
                import os

                from database import order as order_db

                portfolio_id = str(
                    os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID")
                    or ""
                ).strip()
                if not portfolio_id:
                    raise RuntimeError("operator_hotpoint_portfolio_not_configured")
                _DEFAULT_REPOSITORY = OperatorHotpointControlRepository(
                    order_db.DB_CLIENT,
                    configured_portfolio_id=portfolio_id,
                    product_metadata_provider=_default_product_metadata,
                    policy=SPOT_HOTPOINT_SCOPE_POLICY,
                )
    return _DEFAULT_REPOSITORY


def get_default_operator_futures_hotpoint_control_repository(
) -> OperatorHotpointControlRepository:
    """Return the separately stored Futures Hotpoint authority."""

    global _DEFAULT_FUTURES_REPOSITORY
    if _DEFAULT_FUTURES_REPOSITORY is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_FUTURES_REPOSITORY is None:
                import os

                from database import order as order_db

                portfolio_id = str(
                    os.environ.get(
                        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
                    )
                    or ""
                ).strip()
                if not portfolio_id:
                    raise RuntimeError(
                        "operator_futures_hotpoint_portfolio_not_configured"
                    )
                _DEFAULT_FUTURES_REPOSITORY = (
                    OperatorHotpointControlRepository(
                        order_db.DB_CLIENT,
                        configured_portfolio_id=portfolio_id,
                        product_metadata_provider=_default_product_metadata,
                        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
                    )
                )
    return _DEFAULT_FUTURES_REPOSITORY


def initialize_operator_hotpoint_control_schema() -> None:
    repository = get_default_operator_hotpoint_control_repository()
    repository.ensure_schema()
    repository.recover_stranded_claim()
    import os

    if str(
        os.environ.get("COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID") or ""
    ).strip():
        futures = get_default_operator_futures_hotpoint_control_repository()
        futures.ensure_schema()
        futures.recover_stranded_claim()
