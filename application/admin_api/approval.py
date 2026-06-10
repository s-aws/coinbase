"""Approval snapshot contract helpers for future live Admin API commands."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .idempotency import make_payload_hash


class ApprovalSnapshot(BaseModel):
    """Immutable command evidence an execution request must match."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    actor_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)


def make_approval_snapshot_hash(payload: Any) -> str:
    """Hash the command fields that future approval gates will bind."""

    return make_payload_hash(payload)


def approval_matches_payload(snapshot: ApprovalSnapshot, payload: Any) -> bool:
    """Return whether a command still matches its approved snapshot."""

    return snapshot.payload_hash == make_approval_snapshot_hash(payload)

