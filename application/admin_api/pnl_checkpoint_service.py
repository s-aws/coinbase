"""Backend-owned Spot P/L checkpoint record service."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiPermission,
)

from .audit import FileAdminApiAuditStore
from .models import (
    SPOT_PNL_CHECKPOINT_LEGACY_AUDIT_DETAIL,
    SpotPnlCheckpointCreateRequest,
    SpotPnlCheckpointItem,
)
from .pnl_checkpoint import (
    FileSpotPnlCheckpointStore,
    SpotPnlCheckpointRecord,
)


class SpotPnlCheckpointError(ValueError):
    """Raised when a Spot P/L checkpoint record is invalid."""


class AdminApiSpotPnlCheckpointService:
    """Service boundary for append-only Spot P/L checkpoint records."""

    def record_checkpoint(
        self,
        *,
        store: FileSpotPnlCheckpointStore,
        body: SpotPnlCheckpointCreateRequest,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotPnlCheckpointItem:
        recorded_at = _normalize_now(now)
        self._validate_checkpoint(body)
        if store.find_by_checkpoint_id(body.checkpoint_id) is not None:
            raise SpotPnlCheckpointError("Spot P/L checkpoint already exists.")

        record = SpotPnlCheckpointRecord(
            checkpoint_id=body.checkpoint_id,
            recorded_at=recorded_at.isoformat(),
            scope=body.scope,
            product_ids=body.product_ids,
            pnl_snapshot=body.pnl_snapshot,
            average_cost_snapshot=body.average_cost_snapshot,
            source_report_route=body.source_report_route,
            review_status=body.review_status,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
            operator_notes=body.operator_notes,
        )
        store.append(record)
        return _item_from_record(record)

    def list_checkpoints(
        self,
        *,
        store: FileSpotPnlCheckpointStore,
        audit_store: FileAdminApiAuditStore | None = None,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[SpotPnlCheckpointItem]:
        items = [
            _item_from_record(record, audit_store=audit_store)
            for record in store.read_recent(limit=limit)
        ]
        if status_filter is not None:
            items = [item for item in items if item.review_status == status_filter]
        return items

    def get_checkpoint(
        self,
        *,
        store: FileSpotPnlCheckpointStore,
        checkpoint_id: str,
        audit_store: FileAdminApiAuditStore | None = None,
    ) -> SpotPnlCheckpointItem:
        record = store.find_by_checkpoint_id(checkpoint_id)
        if record is None:
            raise SpotPnlCheckpointError("Spot P/L checkpoint was not found.")
        return _item_from_record(record, audit_store=audit_store)

    @staticmethod
    def _validate_checkpoint(body: SpotPnlCheckpointCreateRequest) -> None:
        if body.source_report_route != "/api/v1/spot/sweep/pnl":
            raise SpotPnlCheckpointError(
                "Spot P/L checkpoints must reference /api/v1/spot/sweep/pnl."
            )
        if not body.pnl_snapshot:
            raise SpotPnlCheckpointError("Spot P/L checkpoint requires pnl_snapshot.")
        if body.average_cost_snapshot is not None and not body.average_cost_snapshot:
            raise SpotPnlCheckpointError(
                "Spot P/L checkpoint average_cost_snapshot must be non-empty when provided."
            )


def _item_from_record(
    record: SpotPnlCheckpointRecord,
    *,
    audit_store: FileAdminApiAuditStore | None = None,
) -> SpotPnlCheckpointItem:
    average_cost_reviewed = bool(record.average_cost_snapshot)
    average_cost_review_source = _average_cost_review_source(record.average_cost_snapshot)
    audit_event = (
        audit_store.find_by_audit_id(record.audit_id)
        if audit_store is not None and record.audit_id
        else None
    )
    audit_linked = (
        audit_event is not None
        and audit_event.action_class == AdminApiActionClass.LOCAL_STATE_MUTATION
        and audit_event.permission == AdminApiPermission.SPOT_PNL_RECORD
        and audit_event.status == AdminApiCommandStatus.ACCEPTED
        and audit_event.endpoint == "POST /api/v1/spot/pnl/checkpoints"
        and audit_event.actor_id == record.actor_id
        and audit_event.operator_intent == record.operator_intent
        and audit_event.idempotency_key == record.idempotency_key
    )
    audit_detail = (
        "Checkpoint is linked to a verified append-only Admin API audit event "
        "for this local-state record. The audit link is review evidence only "
        "and does not execute recovery, reconciliation, Coinbase orders, or "
        "browser authority."
        if audit_linked
        else (
            (
                "Checkpoint includes an audit_id, but no matching append-only "
                "Admin API audit event was found for this checkpoint route, "
                "actor, idempotency key, status, and permission; treat it as "
                "unverified local checkpoint evidence until the audit log is "
                "repaired."
            )
            if record.audit_id
            else SPOT_PNL_CHECKPOINT_LEGACY_AUDIT_DETAIL
        )
    )
    average_cost_review_detail = (
        "Checkpoint includes backend-sourced average-cost review evidence. "
        "This is still not sell authority, profitability authority, tax "
        "accounting, browser guard evidence, or Coinbase execution evidence."
        if average_cost_reviewed
        else (
            "Checkpoint does not include average-cost review evidence; use "
            "/api/v1/spot/sweep/pnl with include_coinbase_average_cost=true "
            "before recording average-cost review evidence."
        )
    )
    detail = (
        "Spot P/L checkpoint is durable operator review evidence only. It is "
        "not tax accounting, sell authority, profitability authority, browser "
        "guard evidence, or live Coinbase execution evidence."
    )
    return SpotPnlCheckpointItem(
        checkpoint_id=record.checkpoint_id,
        recorded_at=record.recorded_at,
        scope=record.scope,
        product_ids=record.product_ids,
        pnl_snapshot=record.pnl_snapshot,
        average_cost_snapshot=record.average_cost_snapshot,
        average_cost_reviewed=average_cost_reviewed,
        average_cost_review_source=average_cost_review_source,
        average_cost_review_detail=average_cost_review_detail,
        source_report_route=record.source_report_route,
        review_status=record.review_status,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        audit_linked=audit_linked,
        audit_source="admin_api_audit_log" if audit_linked else None,
        audit_detail=audit_detail,
        source=record.source,
        operator_notes=record.operator_notes,
        detail=detail,
    )


def _average_cost_review_source(snapshot: dict | None) -> str | None:
    if not snapshot:
        return None
    source = snapshot.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    return "average_cost_snapshot"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
