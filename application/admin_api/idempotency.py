"""Idempotency contract helpers for future durable Admin API commands."""

from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiIdempotencyResponseStorage,
)


MAX_INLINE_IDEMPOTENCY_RESPONSE_BYTES = 1_000_000


class IdempotencyRecord(BaseModel):
    """Stored evidence for one idempotent command request."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    status: AdminApiCommandStatus
    response: dict[str, Any] = Field(default_factory=dict)
    response_storage: AdminApiIdempotencyResponseStorage = (
        AdminApiIdempotencyResponseStorage.INLINE
    )
    response_blob_path: str | None = None
    response_blob_sha256: str | None = None
    response_blob_compression: str | None = None
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

    @property
    def _response_blob_dir(self) -> Path:
        return self.path.parent / f"{self.path.stem}_responses"

    def _response_blob_path(self, record: IdempotencyRecord) -> Path:
        if not record.response_blob_path:
            raise ValueError("Missing idempotency response blob path.")
        blob_path = Path(record.response_blob_path)
        if not blob_path.is_absolute():
            blob_path = self.path.parent / blob_path
        resolved_parent = blob_path.parent.resolve()
        allowed_parent = self._response_blob_dir.resolve()
        if resolved_parent != allowed_parent:
            raise ValueError("Idempotency response blob path is outside the store.")
        return blob_path

    def _externalize_large_response(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if (
            not record.response
            or record.response_storage != AdminApiIdempotencyResponseStorage.INLINE
        ):
            return record
        encoded_response = json.dumps(
            record.response,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        if len(encoded_response) <= MAX_INLINE_IDEMPOTENCY_RESPONSE_BYTES:
            return record
        response_sha256 = hashlib.sha256(encoded_response).hexdigest()
        blob_name = (
            hashlib.sha256(
                f"{record.idempotency_key}:{record.payload_hash}".encode("utf-8")
            ).hexdigest()
            + ".json.gz"
        )
        blob_dir = self._response_blob_dir
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / blob_name
        with gzip.open(blob_path, "wb") as handle:
            handle.write(encoded_response)
        return record.model_copy(
            update={
                "response": {},
                "response_storage": AdminApiIdempotencyResponseStorage.GZIP_FILE,
                "response_blob_path": str(blob_path.relative_to(self.path.parent)),
                "response_blob_sha256": response_sha256,
                "response_blob_compression": "gzip",
            }
        )

    def _hydrate_response(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if record.response_storage == AdminApiIdempotencyResponseStorage.INLINE:
            return record
        if record.response_storage != AdminApiIdempotencyResponseStorage.GZIP_FILE:
            raise ValueError(
                f"Unsupported idempotency response storage: {record.response_storage}"
            )
        blob_path = self._response_blob_path(record)
        with gzip.open(blob_path, "rb") as handle:
            encoded_response = handle.read()
        if record.response_blob_sha256:
            observed_sha256 = hashlib.sha256(encoded_response).hexdigest()
            if observed_sha256 != record.response_blob_sha256:
                raise ValueError("Idempotency response blob hash mismatch.")
        response = json.loads(encoded_response.decode("utf-8"))
        return record.model_copy(update={"response": response})

    def _load_latest_by_key(
        self,
        *,
        hydrate_responses: bool = True,
    ) -> dict[str, IdempotencyRecord]:
        records: dict[str, IdempotencyRecord] = {}
        if not self.path.exists():
            return records
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = IdempotencyRecord.model_validate_json(line)
                if hydrate_responses:
                    record = self._hydrate_response(record)
                records[record.idempotency_key] = record
        return records

    def get_record(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._load_latest_by_key().get(idempotency_key)

    def evaluate(self, *, idempotency_key: str, payload_hash: str) -> IdempotencyCheck:
        with self._lock:
            existing = self._load_latest_by_key(hydrate_responses=False).get(
                idempotency_key
            )
            check = evaluate_idempotency(
                existing=existing,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
            )
            if (
                check.decision == AdminApiIdempotencyDecision.REPLAY
                and check.record is not None
            ):
                check.record = self._hydrate_response(check.record)
            return check

    def put_record(self, record: IdempotencyRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = self._externalize_large_response(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
