"""Idempotency contract helpers for future durable Admin API commands."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiCommandStatus, AdminApiIdempotencyDecision


class IdempotencyRecord(BaseModel):
    """Stored evidence for one idempotent command request."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    client_order_id: str | None = None
    status: AdminApiCommandStatus
    response: dict[str, Any] = Field(default_factory=dict)


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

