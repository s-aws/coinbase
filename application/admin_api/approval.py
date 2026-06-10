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


class LiveExecutionGateDecision(BaseModel):
    """Service-level decision for live HTTP execution readiness."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str
    live_execution_enabled: bool
    approval_snapshot_required: bool
    cap_evaluation_required: bool
    durable_audit_required: bool


def make_approval_snapshot_hash(payload: Any) -> str:
    """Hash the command fields that future approval gates will bind."""

    return make_payload_hash(payload)


def approval_matches_payload(snapshot: ApprovalSnapshot, payload: Any) -> bool:
    """Return whether a command still matches its approved snapshot."""

    return snapshot.payload_hash == make_approval_snapshot_hash(payload)


def evaluate_live_execution_gate(
    *,
    allow_live_execution: bool,
    cap_evaluation_required: bool = True,
) -> LiveExecutionGateDecision:
    """Return the current live-command gate decision.

    The enterprise HTTP surface is intentionally fail-closed until approval
    snapshots, cap evaluation, and audit enforcement are wired end to end.
    """

    if allow_live_execution:
        return LiveExecutionGateDecision(
            allowed=True,
            reason="live execution enabled by trusted compatibility adapter",
            live_execution_enabled=True,
            approval_snapshot_required=False,
            cap_evaluation_required=cap_evaluation_required,
            durable_audit_required=True,
        )
    return LiveExecutionGateDecision(
        allowed=False,
        reason=(
            "live execution disabled until approval snapshot and cap gates "
            "are enforced"
        ),
        live_execution_enabled=False,
        approval_snapshot_required=True,
        cap_evaluation_required=cap_evaluation_required,
        durable_audit_required=True,
    )
