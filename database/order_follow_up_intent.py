"""Durable single-slot follow-up intent and automatic-claim persistence.

This module is deliberately local-state only.  It never imports an exchange
client and every decision is made from the existing PostgreSQL order/fill
evidence plus the two tables owned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
import threading
from typing import Any, Callable, Mapping
import uuid

from core.enums import (
    FollowUpSemanticClaimKind,
    FollowUpSemanticClaimState,
    OrderOwnershipProvenance,
)
from core.operator_follow_up_intent import (
    evaluate_operator_follow_up_intent_policy,
    operator_follow_up_intent_scope_applies,
    operator_follow_up_intent_enabled,
)
from core.product_capability import resolve_product_context
from core.spot_follow_up_policy import evaluate_spot_follow_up_policy


FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = operator_follow_up_intent_enabled

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AUTOMATIC_CLAIM_KINDS = {
    FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
    FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
}
_POSITIVE_FILL_EVIDENCE_TABLES = (
    "fill_ledger",
    "order_match_audit",
    "order_event_stream",
    "partial_fill_progress",
)


class FollowUpIntentStoreError(RuntimeError):
    """Value-blind base error raised by the persistence boundary."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


class FollowUpIntentStoreConflict(FollowUpIntentStoreError):
    """A stable state or idempotency conflict."""


class FollowUpIntentStoreUnavailable(FollowUpIntentStoreError):
    """Authoritative persistence evidence could not be established."""


@dataclass(frozen=True)
class FollowUpIntentCommand:
    source_client_order_id: str
    actor_id: str
    roles: tuple[str, ...]
    environment: str
    idempotency_key: str
    correlation_id: str
    operator_intent: str
    payload_sha256: str


@dataclass(frozen=True)
class FollowUpIntentEligibility:
    source_client_order_id: str
    root_client_order_id: str
    source_found: bool
    eligible: bool
    eligibility_status: str
    blockers: tuple[str, ...]
    source_status: str
    source_ownership_provenance: str
    product_id: str
    product_type: str
    source_is_child: bool
    source_authoritative_zero_fill: bool
    source_follow_up_child_absent: bool
    automatic_semantic_claim_absent: bool
    portfolio_scope_sha256: str
    slot_used: int
    semantic_intent: str | None = None
    derived_follow_up_side: str | None = None


@dataclass(frozen=True)
class FollowUpIntentRecord:
    follow_up_intent_id: str
    claim_id: str
    source_client_order_id: str
    root_client_order_id: str
    semantic_intent: str
    derived_follow_up_side: str
    intent_sha256: str
    audit_id: str
    correlation_id: str
    actor_id: str
    environment: str
    portfolio_scope_sha256: str
    idempotency_key: str
    payload_sha256: str
    recorded_at: str


@dataclass(frozen=True)
class FollowUpIntentReadback:
    eligibility: FollowUpIntentEligibility
    record: FollowUpIntentRecord | None


@dataclass(frozen=True)
class FollowUpIntentAttachResult:
    eligibility: FollowUpIntentEligibility
    record: FollowUpIntentRecord
    replayed: bool


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portfolio_sha256(portfolio_id: str) -> str:
    return hashlib.sha256(str(portfolio_id).encode("utf-8")).hexdigest()


def _require_source_uuid(source_client_order_id: str) -> str:
    value = str(source_client_order_id or "").strip()
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise FollowUpIntentStoreConflict(
            "source_client_order_id_invalid"
        ) from None
    if str(parsed) != value:
        raise FollowUpIntentStoreConflict(
            "source_client_order_id_invalid"
        )
    return str(parsed)


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, value))


class OperatorFollowUpIntentRepository:
    """PostgreSQL repository with one transaction and lock per source action."""

    def __init__(
        self,
        db: Any,
        *,
        configured_spot_portfolio_id: str,
        schema: str = "public",
        product_context_resolver: Callable[[str], Mapping[str, Any]] = (
            resolve_product_context
        ),
        spot_policy_evaluator: Callable[..., Any] = evaluate_spot_follow_up_policy,
    ) -> None:
        if not _SCHEMA_RE.fullmatch(str(schema)):
            raise ValueError("invalid_follow_up_intent_schema")
        self.db = db
        self.schema = str(schema)
        self.configured_spot_portfolio_id = str(
            configured_spot_portfolio_id or ""
        ).strip()
        self.product_context_resolver = product_context_resolver
        self.spot_policy_evaluator = spot_policy_evaluator
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('order_follow_up_semantic_claim')} (
                            claim_id UUID PRIMARY KEY,
                            source_client_order_id VARCHAR(128) NOT NULL,
                            claim_kind VARCHAR(40) NOT NULL,
                            trigger VARCHAR(20),
                            state VARCHAR(20) NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (source_client_order_id, claim_kind)
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS order_follow_up_semantic_claim_source_idx
                        ON {self._table('order_follow_up_semantic_claim')}
                        (source_client_order_id, state)
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self._table('operator_follow_up_intent')} (
                            follow_up_intent_id UUID PRIMARY KEY,
                            claim_id UUID NOT NULL UNIQUE,
                            source_client_order_id VARCHAR(128) NOT NULL UNIQUE,
                            root_client_order_id VARCHAR(128) NOT NULL,
                            product_id VARCHAR(255) NOT NULL,
                            source_side VARCHAR(10) NOT NULL,
                            derived_follow_up_side VARCHAR(10) NOT NULL,
                            semantic_intent VARCHAR(40) NOT NULL,
                            intent_sha256 CHAR(64) NOT NULL,
                            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
                            payload_sha256 CHAR(64) NOT NULL,
                            actor_id VARCHAR(255) NOT NULL,
                            roles_json JSONB NOT NULL,
                            environment VARCHAR(64) NOT NULL,
                            portfolio_scope_sha256 CHAR(64) NOT NULL,
                            correlation_id VARCHAR(255) NOT NULL,
                            operator_intent VARCHAR(255) NOT NULL,
                            audit_id UUID NOT NULL UNIQUE,
                            terminal_result VARCHAR(20) NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (claim_id)
                                REFERENCES {self._table('order_follow_up_semantic_claim')}(claim_id)
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE OR REPLACE FUNCTION {self._table('lock_operator_follow_up_source')}()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $$
                        BEGIN
                            IF NEW.client_order_id IS NOT NULL THEN
                                PERFORM pg_advisory_xact_lock(
                                    17291,
                                    hashtext(NEW.client_order_id::text)
                                );
                            END IF;
                            RETURN NEW;
                        END;
                        $$
                        """
                    )
                    for table_name in _POSITIVE_FILL_EVIDENCE_TABLES:
                        self._install_source_lock_trigger(cursor, table_name)
            except Exception as exc:
                raise FollowUpIntentStoreUnavailable(
                    "follow_up_intent_store_unavailable"
                ) from None
            self._schema_ready = True

    def _install_source_lock_trigger(self, cursor: Any, table_name: str) -> None:
        if table_name not in _POSITIVE_FILL_EVIDENCE_TABLES:
            raise ValueError("unsupported_follow_up_source_lock_table")
        cursor.execute("SELECT to_regclass(%s)", (f"{self.schema}.{table_name}",))
        row = cursor.fetchone()
        relation = (
            next(iter(row.values()), None)
            if isinstance(row, Mapping)
            else (row[0] if row else None)
        )
        if relation is None:
            return
        trigger_name = "operator_follow_up_source_lock"
        cursor.execute(
            f"DROP TRIGGER IF EXISTS {trigger_name} ON {self._table(table_name)}"
        )
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT OR UPDATE ON {self._table(table_name)}
            FOR EACH ROW
            EXECUTE FUNCTION {self._table('lock_operator_follow_up_source')}()
            """
        )

    def install_source_lock_trigger(self, table_name: str) -> None:
        """Install the source advisory-lock trigger on a newly created table."""

        if not self._schema_ready:
            return
        try:
            with self.db.get_cursor() as cursor:
                self._install_source_lock_trigger(cursor, table_name)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_source_lock_unavailable"
            ) from None

    @staticmethod
    def _lock_source(cursor: Any, source_client_order_id: str) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (17291, source_client_order_id),
        )

    def _read_intent(self, cursor: Any, source_client_order_id: str) -> FollowUpIntentRecord | None:
        cursor.execute(
            f"""
            SELECT follow_up_intent_id, claim_id, source_client_order_id,
                   root_client_order_id, semantic_intent,
                   derived_follow_up_side, intent_sha256, audit_id,
                   correlation_id, actor_id, environment,
                   portfolio_scope_sha256, idempotency_key, payload_sha256,
                   recorded_at
              FROM {self._table('operator_follow_up_intent')}
             WHERE source_client_order_id = %s
            """,
            (source_client_order_id,),
        )
        row = _row(cursor)
        return self._record(row) if row else None

    def _read_intent_by_idempotency(self, cursor: Any, key: str) -> FollowUpIntentRecord | None:
        cursor.execute(
            f"""
            SELECT follow_up_intent_id, claim_id, source_client_order_id,
                   root_client_order_id, semantic_intent,
                   derived_follow_up_side, intent_sha256, audit_id,
                   correlation_id, actor_id, environment,
                   portfolio_scope_sha256, idempotency_key, payload_sha256,
                   recorded_at
              FROM {self._table('operator_follow_up_intent')}
             WHERE idempotency_key = %s
            """,
            (key,),
        )
        row = _row(cursor)
        return self._record(row) if row else None

    @staticmethod
    def _record(row: Mapping[str, Any]) -> FollowUpIntentRecord:
        recorded_at = row["recorded_at"]
        if isinstance(recorded_at, datetime):
            recorded_at = recorded_at.astimezone(timezone.utc).isoformat()
        return FollowUpIntentRecord(
            follow_up_intent_id=str(row["follow_up_intent_id"]),
            claim_id=str(row["claim_id"]),
            source_client_order_id=str(row["source_client_order_id"]),
            root_client_order_id=str(row["root_client_order_id"]),
            semantic_intent=str(row["semantic_intent"]),
            derived_follow_up_side=str(row["derived_follow_up_side"]),
            intent_sha256=str(row["intent_sha256"]),
            audit_id=str(row["audit_id"]),
            correlation_id=str(row["correlation_id"]),
            actor_id=str(row["actor_id"]),
            environment=str(row["environment"]),
            portfolio_scope_sha256=str(row["portfolio_scope_sha256"]),
            idempotency_key=str(row["idempotency_key"]),
            payload_sha256=str(row["payload_sha256"]),
            recorded_at=str(recorded_at),
        )

    def _exists(self, cursor: Any, query: str, params: tuple[Any, ...]) -> bool:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return False
        if isinstance(row, Mapping):
            return bool(next(iter(row.values()), False))
        return bool(row[0])

    def _evaluate_locked(
        self,
        cursor: Any,
        source_client_order_id: str,
        *,
        existing_intent: FollowUpIntentRecord | None = None,
    ) -> FollowUpIntentEligibility:
        blockers: list[str] = []
        portfolio_hash = _portfolio_sha256(self.configured_spot_portfolio_id)
        cursor.execute(
            f"""
            SELECT client_order_id, product_id, side, status, parent_order_id,
                   ownership_provenance, retail_portfolio_id
              FROM {self._table('order_parent')}
             WHERE client_order_id = %s
             FOR UPDATE
            """,
            (source_client_order_id,),
        )
        source = _row(cursor)
        if source is None:
            return FollowUpIntentEligibility(
                source_client_order_id=source_client_order_id,
                root_client_order_id=source_client_order_id,
                source_found=False,
                eligible=False,
                eligibility_status="blocked",
                blockers=("source_order_not_found",),
                source_status="UNKNOWN",
                source_ownership_provenance="UNKNOWN",
                product_id="UNKNOWN",
                product_type="UNKNOWN",
                source_is_child=False,
                source_authoritative_zero_fill=False,
                source_follow_up_child_absent=False,
                automatic_semantic_claim_absent=False,
                portfolio_scope_sha256=portfolio_hash,
                slot_used=1 if existing_intent else 0,
            )

        source_status = str(source.get("status") or "UNKNOWN").upper()
        provenance = str(source.get("ownership_provenance") or "UNKNOWN")
        product_id = str(source.get("product_id") or "UNKNOWN")
        source_side = str(source.get("side") or "").upper()
        parent_id = str(source.get("parent_order_id") or "").strip()
        root_id = parent_id or source_client_order_id
        source_is_child = bool(parent_id)

        root_lineage_valid = False
        if source_is_child:
            cursor.execute(
                f"""
                SELECT client_order_id, product_id, parent_order_id,
                       ownership_provenance, retail_portfolio_id
                  FROM {self._table('order_parent')}
                 WHERE client_order_id = %s
                 FOR UPDATE
                """,
                (root_id,),
            )
            root = _row(cursor)
            root_lineage_valid = not (
                root is None
                or root.get("parent_order_id")
                or str(root.get("ownership_provenance") or "")
                != OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                or str(root.get("retail_portfolio_id") or "")
                != self.configured_spot_portfolio_id
                or str(root.get("product_id") or "") != product_id
            )
        else:
            root_lineage_valid = (
                provenance == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            )

        policy = evaluate_operator_follow_up_intent_policy(
            source_status=source_status,
            source_ownership_provenance=provenance,
            spot_portfolio_configured=bool(self.configured_spot_portfolio_id),
            source_portfolio_matches=(
                str(source.get("retail_portfolio_id") or "")
                == self.configured_spot_portfolio_id
            ),
            root_lineage_valid=root_lineage_valid,
            product_id=product_id,
            source_side=source_side,
            product_context_resolver=self.product_context_resolver,
            spot_policy_evaluator=self.spot_policy_evaluator,
        )
        blockers.extend(policy.blockers)
        product_type = policy.product_type
        follow_up_side = policy.derived_follow_up_side
        semantic_intent = policy.semantic_intent

        fill_present = any(
            (
                self._exists(
                    cursor,
                    f"SELECT EXISTS (SELECT 1 FROM {self._table(table)} " + predicate + ")",
                    (source_client_order_id,),
                )
            )
            for table, predicate in (
                ("fill_ledger", "WHERE client_order_id = %s AND COALESCE(quantity, 0) > 0"),
                (
                    "order_match_audit",
                    "WHERE client_order_id = %s AND (COALESCE(cumulative_quantity, 0) > 0 OR COALESCE(derived_size_delta, 0) > 0 OR COALESCE(number_of_fills, 0) > 0)",
                ),
                (
                    "order_event_stream",
                    "WHERE client_order_id = %s AND COALESCE(cumulative_filled_size, 0) > 0",
                ),
                (
                    "partial_fill_progress",
                    "WHERE client_order_id = %s AND (COALESCE(last_cumulative_qty_processed, 0) > 0 OR COALESCE(carry_remainder_qty, 0) > 0 OR COALESCE(last_number_of_fills_seen, 0) > 0 OR COALESCE(last_completion_pct_seen, 0) > 0 OR COALESCE(partial_follow_ups_created, 0) > 0)",
                ),
            )
        )
        if fill_present:
            blockers.append("source_has_positive_fill_evidence")

        cursor.execute(
            f"""
            SELECT client_order_id
              FROM {self._table('order_parent')}
             WHERE parent_order_id = %s AND client_order_id <> %s
             ORDER BY created_at ASC, id ASC
            """,
            (root_id, source_client_order_id if source_is_child else ""),
        )
        related_children = cursor.fetchall()
        child_absent = not related_children
        if related_children:
            blockers.append(
                "source_follow_up_child_attribution_ambiguous"
                if source_is_child
                else "source_follow_up_child_already_exists"
            )

        cursor.execute(
            f"""
            SELECT claim_kind, state
              FROM {self._table('order_follow_up_semantic_claim')}
             WHERE source_client_order_id = %s AND state IN (%s, %s)
            """,
            (
                source_client_order_id,
                FollowUpSemanticClaimState.CLAIMED.value,
                FollowUpSemanticClaimState.COMPLETED.value,
            ),
        )
        claim_rows = cursor.fetchall()
        automatic_claim_absent = True
        for claim_row in claim_rows:
            if isinstance(claim_row, Mapping):
                claim_kind = claim_row.get("claim_kind")
            else:
                claim_kind = claim_row[0]
            kind = str(claim_kind)
            automatic_claim_absent = False
            if kind in _AUTOMATIC_CLAIM_KINDS:
                blockers.append("automatic_follow_up_claim_present")
            elif kind == FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value:
                blockers.append("source_has_positive_fill_activity")
            elif (
                kind == FollowUpSemanticClaimKind.OPERATOR_INTENT.value
                and existing_intent is not None
            ):
                continue
            else:
                blockers.append("follow_up_semantic_claim_present")

        if existing_intent is not None:
            blockers.append("follow_up_intent_already_attached")

        blockers = list(dict.fromkeys(blockers))
        return FollowUpIntentEligibility(
            source_client_order_id=source_client_order_id,
            root_client_order_id=root_id,
            source_found=True,
            eligible=not blockers,
            eligibility_status=(
                "attached" if existing_intent is not None else (
                    "eligible" if not blockers else "blocked"
                )
            ),
            blockers=tuple(blockers),
            source_status=source_status,
            source_ownership_provenance=provenance,
            product_id=product_id,
            product_type=product_type,
            source_is_child=source_is_child,
            source_authoritative_zero_fill=not fill_present,
            source_follow_up_child_absent=child_absent,
            automatic_semantic_claim_absent=automatic_claim_absent,
            portfolio_scope_sha256=portfolio_hash,
            slot_used=1 if existing_intent else 0,
            semantic_intent=semantic_intent,
            derived_follow_up_side=follow_up_side,
        )

    def read(self, source_client_order_id: str) -> FollowUpIntentReadback:
        source_client_order_id = _require_source_uuid(source_client_order_id)
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                intent = self._read_intent(cursor, source_client_order_id)
                eligibility = self._evaluate_locked(
                    cursor,
                    source_client_order_id,
                    existing_intent=intent,
                )
                return FollowUpIntentReadback(eligibility=eligibility, record=intent)
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_evidence_unavailable"
            ) from None

    def slot_applies(self, source_client_order_id: str) -> bool:
        """Classify whether one engine order needs the durable slot interlock."""

        try:
            with self.db.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT product_id, ownership_provenance, retail_portfolio_id
                      FROM {self._table('order_parent')}
                     WHERE client_order_id = %s
                    """,
                    (source_client_order_id,),
                )
                source = _row(cursor)
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_scope_unavailable"
            ) from None
        if source is None:
            return False
        return operator_follow_up_intent_scope_applies(
            source_ownership_provenance=str(
                source.get("ownership_provenance") or ""
            ),
            spot_portfolio_configured=bool(self.configured_spot_portfolio_id),
            source_portfolio_matches=(
                str(source.get("retail_portfolio_id") or "")
                == self.configured_spot_portfolio_id
            ),
            product_id=str(source.get("product_id") or ""),
            product_context_resolver=self.product_context_resolver,
        )

    def attach(self, command: FollowUpIntentCommand) -> FollowUpIntentAttachResult:
        _require_source_uuid(command.source_client_order_id)
        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, command.source_client_order_id)
                replay = self._read_intent_by_idempotency(
                    cursor,
                    command.idempotency_key,
                )
                if replay is not None:
                    if (
                        replay.source_client_order_id
                        != command.source_client_order_id
                        or replay.payload_sha256 != command.payload_sha256
                    ):
                        raise FollowUpIntentStoreConflict("idempotency_conflict")
                    eligibility = self._evaluate_locked(
                        cursor,
                        command.source_client_order_id,
                        existing_intent=replay,
                    )
                    return FollowUpIntentAttachResult(
                        eligibility=eligibility,
                        record=replay,
                        replayed=True,
                    )

                existing = self._read_intent(cursor, command.source_client_order_id)
                eligibility = self._evaluate_locked(
                    cursor,
                    command.source_client_order_id,
                    existing_intent=existing,
                )
                if not eligibility.eligible:
                    raise FollowUpIntentStoreConflict(eligibility.blockers[0])

                claim_id = str(uuid.uuid4())
                intent_id = str(uuid.uuid4())
                audit_id = str(uuid.uuid4())
                semantic_intent = eligibility.semantic_intent or "EXIT"
                follow_up_side = eligibility.derived_follow_up_side or "SELL"
                intent_sha256 = _canonical_sha256(
                    {
                        "source_client_order_id": command.source_client_order_id,
                        "root_client_order_id": eligibility.root_client_order_id,
                        "trigger": "FILLED",
                        "intent_kind": "single_on_full_fill",
                        "semantic_intent": semantic_intent,
                        "derived_follow_up_side": follow_up_side,
                        "portfolio_scope_sha256": eligibility.portfolio_scope_sha256,
                    }
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        claim_id,
                        command.source_client_order_id,
                        FollowUpSemanticClaimKind.OPERATOR_INTENT.value,
                        "FILLED",
                        FollowUpSemanticClaimState.COMPLETED.value,
                    ),
                )
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('operator_follow_up_intent')} (
                        follow_up_intent_id, claim_id, source_client_order_id,
                        root_client_order_id, product_id, source_side,
                        derived_follow_up_side, semantic_intent, intent_sha256,
                        idempotency_key, payload_sha256, actor_id, roles_json,
                        environment, portfolio_scope_sha256, correlation_id,
                        operator_intent, audit_id, terminal_result
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, 'ATTACHED'
                    )
                    RETURNING follow_up_intent_id, claim_id,
                              source_client_order_id, root_client_order_id,
                              semantic_intent, derived_follow_up_side,
                              intent_sha256, audit_id, correlation_id, actor_id,
                              environment, portfolio_scope_sha256,
                              idempotency_key, payload_sha256, recorded_at
                    """,
                    (
                        intent_id,
                        claim_id,
                        command.source_client_order_id,
                        eligibility.root_client_order_id,
                        eligibility.product_id,
                        "BUY" if follow_up_side == "SELL" else "SELL",
                        follow_up_side,
                        semantic_intent,
                        intent_sha256,
                        command.idempotency_key,
                        command.payload_sha256,
                        command.actor_id,
                        json.dumps(list(command.roles), separators=(",", ":")),
                        command.environment,
                        eligibility.portfolio_scope_sha256,
                        command.correlation_id,
                        command.operator_intent,
                        audit_id,
                    ),
                )
                record = self._record(_row(cursor) or {})
                attached = FollowUpIntentEligibility(
                    **{
                        **eligibility.__dict__,
                        "eligible": False,
                        "eligibility_status": "attached",
                        "blockers": ("follow_up_intent_already_attached",),
                        "slot_used": 1,
                    }
                )
                return FollowUpIntentAttachResult(
                    eligibility=attached,
                    record=record,
                    replayed=False,
                )
        except FollowUpIntentStoreError:
            raise
        except Exception:
            raise FollowUpIntentStoreUnavailable(
                "follow_up_intent_persistence_unknown"
            ) from None

    def try_claim_automatic(self, *, source_client_order_id: str, trigger: str) -> str | None:
        self.ensure_schema()
        normalized = str(trigger or "").upper()
        kind_by_trigger = {
            "FILLED": FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
            "CANCELLED": FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
        }
        if normalized not in kind_by_trigger:
            return None
        kind = kind_by_trigger[normalized]
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    SELECT claim_kind, state FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND state IN (%s, %s)
                       AND claim_kind IN (%s, %s, %s)
                    """,
                    (
                        source_client_order_id,
                        FollowUpSemanticClaimState.CLAIMED.value,
                        FollowUpSemanticClaimState.COMPLETED.value,
                        FollowUpSemanticClaimKind.OPERATOR_INTENT.value,
                        FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
                        FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
                    ),
                )
                if cursor.fetchone() is not None:
                    return None
                claim_id = str(uuid.uuid4())
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_client_order_id, claim_kind) DO UPDATE
                       SET claim_id = EXCLUDED.claim_id,
                           trigger = EXCLUDED.trigger,
                           state = EXCLUDED.state,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE {self._table('order_follow_up_semantic_claim')}.state = %s
                    RETURNING claim_id
                    """,
                    (
                        claim_id,
                        source_client_order_id,
                        kind,
                        normalized,
                        FollowUpSemanticClaimState.CLAIMED.value,
                        FollowUpSemanticClaimState.RELEASED.value,
                    ),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception:
            return None

    def transition_automatic(
        self,
        *,
        source_client_order_id: str,
        trigger: str,
        claim_id: str,
        target_state: str,
    ) -> bool:
        self.ensure_schema()
        normalized = str(trigger or "").upper()
        kind_by_trigger = {
            "FILLED": FollowUpSemanticClaimKind.AUTOMATIC_FILLED.value,
            "CANCELLED": FollowUpSemanticClaimKind.AUTOMATIC_CANCELLED.value,
        }
        if normalized not in kind_by_trigger:
            return False
        kind = kind_by_trigger[normalized]
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    UPDATE {self._table('order_follow_up_semantic_claim')}
                       SET state = %s, updated_at = CURRENT_TIMESTAMP
                     WHERE source_client_order_id = %s
                       AND claim_kind = %s AND claim_id = %s
                       AND state = %s
                    """,
                    (
                        target_state,
                        source_client_order_id,
                        kind,
                        claim_id,
                        FollowUpSemanticClaimState.CLAIMED.value,
                    ),
                )
                if cursor.rowcount == 1:
                    return True
                cursor.execute(
                    f"""
                    SELECT state FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND claim_kind = %s AND claim_id = %s
                    """,
                    (source_client_order_id, kind, claim_id),
                )
                row = cursor.fetchone()
                return bool(row and str(row[0]) == target_state)
        except Exception:
            return False

    def mark_positive_fill_activity(self, *, source_client_order_id: str) -> bool:
        self.ensure_schema()
        try:
            with self.db.get_cursor() as cursor:
                self._lock_source(cursor, source_client_order_id)
                cursor.execute(
                    f"""
                    SELECT 1 FROM {self._table('order_follow_up_semantic_claim')}
                     WHERE source_client_order_id = %s
                       AND claim_kind = %s
                       AND state IN (%s, %s)
                    """,
                    (
                        source_client_order_id,
                        FollowUpSemanticClaimKind.OPERATOR_INTENT.value,
                        FollowUpSemanticClaimState.CLAIMED.value,
                        FollowUpSemanticClaimState.COMPLETED.value,
                    ),
                )
                if cursor.fetchone() is not None:
                    return False
                marker_id = str(uuid.uuid4())
                cursor.execute(
                    f"""
                    INSERT INTO {self._table('order_follow_up_semantic_claim')} (
                        claim_id, source_client_order_id, claim_kind, trigger, state
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_client_order_id, claim_kind) DO NOTHING
                    """,
                    (
                        marker_id,
                        source_client_order_id,
                        FollowUpSemanticClaimKind.POSITIVE_FILL_ACTIVITY.value,
                        "PARTIAL_FILL",
                        FollowUpSemanticClaimState.COMPLETED.value,
                    ),
                )
                return True
        except Exception:
            return False


_DEFAULT_REPOSITORY: OperatorFollowUpIntentRepository | None = None
_DEFAULT_REPOSITORY_LOCK = threading.Lock()


def get_default_repository() -> OperatorFollowUpIntentRepository:
    global _DEFAULT_REPOSITORY
    if _DEFAULT_REPOSITORY is None:
        with _DEFAULT_REPOSITORY_LOCK:
            if _DEFAULT_REPOSITORY is None:
                import os
                from database import order as order_db

                _DEFAULT_REPOSITORY = OperatorFollowUpIntentRepository(
                    order_db.DB_CLIENT,
                    configured_spot_portfolio_id=os.environ.get(
                        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", ""
                    ),
                )
    return _DEFAULT_REPOSITORY


def create_order_follow_up_intent_tables() -> None:
    """Create the durable follow-up-intent schema for the default runtime."""

    if not operator_follow_up_intent_enabled():
        return
    get_default_repository().ensure_schema()


def try_claim_automatic_order_follow_up(
    *, source_client_order_id: str, trigger: str
) -> str | None:
    return get_default_repository().try_claim_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
    )


def release_automatic_order_follow_up_claim(
    *, source_client_order_id: str, trigger: str, claim_id: str
) -> bool:
    return get_default_repository().transition_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
        claim_id=claim_id,
        target_state=FollowUpSemanticClaimState.RELEASED.value,
    )


def complete_automatic_order_follow_up_claim(
    *, source_client_order_id: str, trigger: str, claim_id: str
) -> bool:
    return get_default_repository().transition_automatic(
        source_client_order_id=source_client_order_id,
        trigger=trigger,
        claim_id=claim_id,
        target_state=FollowUpSemanticClaimState.COMPLETED.value,
    )


def mark_order_follow_up_positive_fill_activity(
    *, source_client_order_id: str
) -> bool:
    return get_default_repository().mark_positive_fill_activity(
        source_client_order_id=source_client_order_id
    )


def install_order_follow_up_source_lock_trigger(table_name: str) -> None:
    """Attach the shared source lock to a positive-fill evidence table."""

    if not operator_follow_up_intent_enabled():
        return
    get_default_repository().install_source_lock_trigger(table_name)


def operator_follow_up_intent_slot_applies(source_client_order_id: str) -> bool:
    """Fail closed on unknown scope evidence, but skip known out-of-scope rows."""

    if not operator_follow_up_intent_enabled():
        return False
    try:
        return get_default_repository().slot_applies(source_client_order_id)
    except FollowUpIntentStoreError:
        return True


def install_order_module_bindings() -> None:
    """Install the canonical wrappers on ``database.order`` for OrderEngine."""

    from database import order as order_db

    order_db.FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED = (
        operator_follow_up_intent_enabled
    )
    order_db.FOLLOW_UP_INTENT_DURABLE_SLOT_APPLIES = (
        operator_follow_up_intent_slot_applies
    )
    order_db.try_claim_automatic_order_follow_up = try_claim_automatic_order_follow_up
    order_db.release_automatic_order_follow_up_claim = (
        release_automatic_order_follow_up_claim
    )
    order_db.complete_automatic_order_follow_up_claim = (
        complete_automatic_order_follow_up_claim
    )
    order_db.mark_order_follow_up_positive_fill_activity = (
        mark_order_follow_up_positive_fill_activity
    )
