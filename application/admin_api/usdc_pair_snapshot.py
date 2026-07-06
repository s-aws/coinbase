"""Durable M58 USDC pair snapshot evidence for Admin API automation."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from .models import UsdcPairSnapshotOrderPlanRowItem, UsdcPairSnapshotRowItem


class UsdcPairSnapshotRunRecord(BaseModel):
    """Append-only backend dry-run snapshot record."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    side: str = Field(min_length=1)
    max_notional_per_product_usdc: str = Field(min_length=1)
    product_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    portfolio_id: str | None = None
    dry_run: bool = True
    snapshot_rows: list[UsdcPairSnapshotRowItem] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    source: str = "admin_api_usdc_pair_snapshot_log"


class UsdcPairSnapshotOrderPlanRecord(BaseModel):
    """Append-only backend dry-run order-plan evidence record."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    snapshot_run_id: str = Field(min_length=1)
    planned_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    side: str = Field(min_length=1)
    max_notional_per_product_usdc: str = Field(min_length=1)
    max_total_notional_usdc: str = Field(min_length=1)
    planned_total_notional_usdc: str = "0"
    product_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    portfolio_id: str | None = None
    time_in_force: str = Field(min_length=1)
    dry_run: bool = True
    order_plan_rows: list[UsdcPairSnapshotOrderPlanRowItem] = Field(
        default_factory=list
    )
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str | None = None
    operator_notes: str | None = None
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_execution: str = "not_run"
    notional_usdc: str = "0"
    source: str = "admin_api_usdc_pair_snapshot_order_plan_log"


class FileUsdcPairSnapshotRunStore:
    """Append-only JSONL store for M58 dry-run snapshot records."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_LOG_PATH")
            or Path("runtime_state") / "admin_api_usdc_pair_snapshot_runs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotRunRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.run_id

    def read_recent(self, *, limit: int = 100) -> list[UsdcPairSnapshotRunRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotRunRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(UsdcPairSnapshotRunRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_run_id(self, run_id: str) -> UsdcPairSnapshotRunRecord | None:
        """Return the latest record for ``run_id`` if present."""

        with self._lock:
            if not self.path.exists():
                return None
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = UsdcPairSnapshotRunRecord.model_validate_json(line)
            except ValueError:
                continue
            if record.run_id == run_id:
                return record
        return None

    def count_records(self) -> int:
        """Return the number of readable snapshot run records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotRunRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count


class FileUsdcPairSnapshotOrderPlanStore:
    """Append-only JSONL store for M58 dry-run order-plan records."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_USDC_PAIR_SNAPSHOT_ORDER_PLAN_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_usdc_pair_snapshot_order_plans.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: UsdcPairSnapshotOrderPlanRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.plan_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[UsdcPairSnapshotOrderPlanRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[UsdcPairSnapshotOrderPlanRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_plan_id(
        self,
        plan_id: str,
    ) -> UsdcPairSnapshotOrderPlanRecord | None:
        """Return the latest record for ``plan_id`` if present."""

        with self._lock:
            if not self.path.exists():
                return None
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
            except ValueError:
                continue
            if record.plan_id == plan_id:
                return record
        return None

    def count_records(self) -> int:
        """Return the number of readable order-plan records."""

        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                UsdcPairSnapshotOrderPlanRecord.model_validate_json(line)
            except ValueError:
                continue
            count += 1
        return count
