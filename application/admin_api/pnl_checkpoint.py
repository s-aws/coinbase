"""Durable Spot P/L checkpoint helpers for Admin API review evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiGateStatus


class SpotPnlCheckpointRecord(BaseModel):
    """Append-only backend Spot P/L review checkpoint."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope: str = Field(min_length=1)
    product_ids: list[str] = Field(default_factory=list)
    pnl_snapshot: dict
    average_cost_snapshot: dict | None = None
    source_report_route: str = Field(min_length=1)
    review_status: AdminApiGateStatus
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    operator_notes: str = Field(min_length=1)
    source: str = "admin_api_spot_pnl_checkpoint_log"


class FileSpotPnlCheckpointStore:
    """Append-only JSONL Spot P/L checkpoint store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_PNL_CHECKPOINT_LOG_PATH")
            or Path("runtime_state") / "admin_api_spot_pnl_checkpoint.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotPnlCheckpointRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.checkpoint_id

    def read_recent(self, *, limit: int = 100) -> list[SpotPnlCheckpointRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotPnlCheckpointRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(SpotPnlCheckpointRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_checkpoint_id(
        self,
        checkpoint_id: str,
    ) -> SpotPnlCheckpointRecord | None:
        """Return the latest record with the given checkpoint id."""

        for record in self.read_recent(limit=500):
            if record.checkpoint_id == checkpoint_id:
                return record
        return None
