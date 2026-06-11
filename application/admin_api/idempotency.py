"""Idempotency contract helpers for future durable Admin API commands."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiCommandStatus, AdminApiIdempotencyDecision


class IdempotencyRecord(BaseModel):
    """Stored evidence for one idempotent command request."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    status: AdminApiCommandStatus
    response: dict[str, Any] = Field(default_factory=dict)
    actor_id: str | None = None
    endpoint: str | None = None


class IdempotencyCheck(BaseModel):
    """Decision returned when a command is compared with stored evidence."""

    model_config = ConfigDict(extra="forbid")

    decision: AdminApiIdempotencyDecision
    record: IdempotencyRecord | None = None


def make_payload_hash(payload: Any) -> str:
    """Return a deterministic SHA-256 hash for JSON-compatible payloads."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_idempotency(
    *,
    existing: IdempotencyRecord | None,
    idempotency_key: str,
    payload_hash: str,
) -> IdempotencyCheck:
    """Compare incoming command evidence against an existing record."""

    if existing is None:
        return IdempotencyCheck(decision=AdminApiIdempotencyDecision.NEW)
    if existing.idempotency_key != idempotency_key:
        return IdempotencyCheck(decision=AdminApiIdempotencyDecision.NEW)
    if existing.payload_hash == payload_hash:
        return IdempotencyCheck(
            decision=AdminApiIdempotencyDecision.REPLAY,
            record=existing,
        )
    return IdempotencyCheck(
        decision=AdminApiIdempotencyDecision.CONFLICT,
        record=existing,
    )


class FileIdempotencyStore:
    """Append-only JSONL idempotency store for Admin API command requests.

    This is intentionally dependency-injectable. The route contract depends on
    the store interface, not the file implementation, so a PostgreSQL-backed
    repository can replace it without creating a second command behavior path.
    """

    def __init__(self, path: Path | str = Path("runtime_state") / "admin_api_idempotency.jsonl") -> None:
        self.path = Path(path)
        self._lock = RLock()

    def _load_latest_by_key(self) -> dict[str, IdempotencyRecord]:
        records: dict[str, IdempotencyRecord] = {}
        if not self.path.exists():
            return records
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = IdempotencyRecord.model_validate_json(line)
                records[record.idempotency_key] = record
        return records

    def get_record(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._load_latest_by_key().get(idempotency_key)

    def evaluate(self, *, idempotency_key: str, payload_hash: str) -> IdempotencyCheck:
        with self._lock:
            existing = self._load_latest_by_key().get(idempotency_key)
            return evaluate_idempotency(
                existing=existing,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
            )

    def put_record(self, record: IdempotencyRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
