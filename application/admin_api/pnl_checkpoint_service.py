"""Backend-owned Spot P/L checkpoint record service."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import AdminApiGateStatus

from .models import (
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
            operator_notes=body.operator_notes,
        )
        store.append(record)
        return _item_from_record(record)

    def list_checkpoints(
        self,
        *,
        store: FileSpotPnlCheckpointStore,
        status_filter: AdminApiGateStatus | None = None,
        limit: int = 100,
    ) -> list[SpotPnlCheckpointItem]:
        items = [_item_from_record(record) for record in store.read_recent(limit=limit)]
        if status_filter is not None:
            items = [item for item in items if item.review_status == status_filter]
        return items

    def get_checkpoint(
        self,
        *,
        store: FileSpotPnlCheckpointStore,
        checkpoint_id: str,
    ) -> SpotPnlCheckpointItem:
        record = store.find_by_checkpoint_id(checkpoint_id)
        if record is None:
            raise SpotPnlCheckpointError("Spot P/L checkpoint was not found.")
        return _item_from_record(record)

    @staticmethod
    def _validate_checkpoint(body: SpotPnlCheckpointCreateRequest) -> None:
        if body.source_report_route != "/api/v1/spot/sweep/pnl":
            raise SpotPnlCheckpointError(
                "Spot P/L checkpoints must reference /api/v1/spot/sweep/pnl."
            )
        if not body.pnl_snapshot:
            raise SpotPnlCheckpointError("Spot P/L checkpoint requires pnl_snapshot.")


def _item_from_record(record: SpotPnlCheckpointRecord) -> SpotPnlCheckpointItem:
    detail = (
        "Spot P/L checkpoint is durable operator review evidence only. It is "
        "not tax accounting, sell authority, profitability authority, or live "
        "Coinbase execution evidence."
    )
    return SpotPnlCheckpointItem(
        checkpoint_id=record.checkpoint_id,
        recorded_at=record.recorded_at,
        scope=record.scope,
        product_ids=record.product_ids,
        pnl_snapshot=record.pnl_snapshot,
        average_cost_snapshot=record.average_cost_snapshot,
        source_report_route=record.source_report_route,
        review_status=record.review_status,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        source=record.source,
        operator_notes=record.operator_notes,
        detail=detail,
    )


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
