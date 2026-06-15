"""No-live stealth lifecycle execution-contract evidence builders."""

from __future__ import annotations

from core.enums import (
    AdminApiStealthAdmissionContextField,
    StealthCreateLifecycleExecutionBlocker,
    StealthCreateLifecycleExecutionPrerequisite,
)

from .models import StealthCreateLifecycleWriteExecutionContractEvidence


REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS: tuple[str, ...] = (
    AdminApiStealthAdmissionContextField.ROUTE.value,
    AdminApiStealthAdmissionContextField.METHOD.value,
    AdminApiStealthAdmissionContextField.STEALTH_ORDER_ID.value,
    AdminApiStealthAdmissionContextField.ACTOR_ID.value,
    AdminApiStealthAdmissionContextField.IDEMPOTENCY_KEY.value,
    AdminApiStealthAdmissionContextField.OPERATOR_INTENT.value,
    AdminApiStealthAdmissionContextField.PAYLOAD_HASH.value,
)

REQUIRED_CREATE_EXECUTION_PREREQUISITES: tuple[str, ...] = (
    StealthCreateLifecycleExecutionPrerequisite.APPROVAL_SNAPSHOT.value,
    StealthCreateLifecycleExecutionPrerequisite.ADMISSION_AUDIT.value,
    StealthCreateLifecycleExecutionPrerequisite.CAP_GUARD_DECISION.value,
    StealthCreateLifecycleExecutionPrerequisite.RECONCILIATION_PLAN.value,
    StealthCreateLifecycleExecutionPrerequisite.LIFECYCLE_WRITE_GUARD_PROOF.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_SERVICE.value,
    StealthCreateLifecycleExecutionPrerequisite.LIVE_EXECUTION_ADAPTER.value,
    StealthCreateLifecycleExecutionPrerequisite.POST_WRITE_RECONCILIATION.value,
)

BASE_CREATE_EXECUTION_BLOCKERS: tuple[str, ...] = (
    StealthCreateLifecycleExecutionBlocker.EXECUTION_CONTRACT_MISSING.value,
    StealthCreateLifecycleExecutionBlocker.LIVE_EXECUTION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_MANAGER_INVOCATION_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.STEALTH_ROW_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.ORDER_PARENT_WRITE_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.LIFECYCLE_EVENT_DISPATCH_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_ORDER_SUBMIT_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.COINBASE_READ_DISABLED.value,
    StealthCreateLifecycleExecutionBlocker.POST_WRITE_RECONCILIATION_MISSING.value,
)


def build_stealth_create_lifecycle_write_execution_contract(
    *,
    stealth_order_id: str | None,
    exact_command_context_present: bool,
    resolved_prerequisites: list[str] | None = None,
) -> StealthCreateLifecycleWriteExecutionContractEvidence:
    """Build blocked execution-contract evidence for stealth create."""

    resolved = set(resolved_prerequisites or [])
    required_prerequisites = list(REQUIRED_CREATE_EXECUTION_PREREQUISITES)
    missing_prerequisites = [
        prerequisite
        for prerequisite in required_prerequisites
        if prerequisite not in resolved
    ]
    missing_context_fields = (
        []
        if exact_command_context_present
        else list(REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS)
    )
    blockers = list(BASE_CREATE_EXECUTION_BLOCKERS)
    blockers.extend(f"{item}_missing" for item in missing_prerequisites)
    if missing_context_fields:
        blockers.append(
            StealthCreateLifecycleExecutionBlocker.EXACT_COMMAND_CONTEXT_MISSING.value
        )

    return StealthCreateLifecycleWriteExecutionContractEvidence(
        stealth_order_id=stealth_order_id,
        accepted_command_identity_keys=["stealth_order_id"],
        rejected_command_identity_keys=[
            "client_order_id",
            "active_placement_client_order_id",
            "exchange_order_id",
            "order_id",
        ],
        exact_command_context_present=exact_command_context_present,
        required_context_fields=list(REQUIRED_CREATE_EXECUTION_CONTEXT_FIELDS),
        missing_context_fields=missing_context_fields,
        required_prerequisites=required_prerequisites,
        missing_prerequisites=missing_prerequisites,
        blockers=blockers,
        evidence=[
            "Execution-contract evidence is backend-owned and no-live.",
            "The contract boundary does not invoke StealthOrderManager.",
            "The contract boundary does not write stealth rows, order_parent rows, or lifecycle events.",
            "The contract boundary does not read Coinbase, submit Coinbase orders, or execute reconciliation.",
        ],
        detail=(
            "Stealth create execution remains blocked until exact command "
            "context, approval, admission audit, cap/guard, reconciliation "
            "plan, lifecycle-write guard proof, live execution service, live "
            "adapter, and post-write reconciliation evidence are all present."
        ),
    )
