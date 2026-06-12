"""Approval snapshot contract helpers for future live Admin API commands."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
)

from .idempotency import make_payload_hash
from .models import AdminLiveAdmissionDecisionEvidence


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


def evaluate_command_live_admission(
    *,
    route: str,
    method: str,
    module_id: str,
    identity_key: str,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission | str,
    service_method: str,
    actor_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
) -> AdminLiveAdmissionDecisionEvidence:
    """Return route-bound live admission evidence for one command attempt.

    This is decision evidence only. The function does not call Coinbase and
    does not mutate command state. Current HTTP command routes remain blocked
    until approval store, admission audit, cap/guard, and reconciliation
    contracts are implemented end to end.
    """

    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        action_class=action_class,
        required_permission=required_permission,
        service_method=service_method,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING,
            AdminApiLiveAdmissionBlocker.APPROVAL_STORE_MISSING,
            AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
            AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
            AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=[
            "existing Admin API command route",
            "durable idempotency payload hash",
            "operator intent header",
            "shared command service boundary",
            "missing durable approval store",
            "missing admission audit trail",
            "missing route-specific cap/guard decision",
            "browser authority rejected",
        ],
        detail=(
            "HTTP live execution is blocked until backend-owned approval, "
            "cap/guard, admission-audit, and reconciliation gates admit this "
            "exact route, identity, payload hash, idempotency key, and operator "
            "intent."
        ),
    )
