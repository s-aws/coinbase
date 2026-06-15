"""No-live post-write reconciliation boundary evidence for stealth commands."""

from __future__ import annotations

from core.enums import AdminApiMutationFamilyType

from .live_execution import (
    EXECUTION_BOUNDARY_AUTHORITY,
    POST_WRITE_RECONCILIATION_METHOD,
    POST_WRITE_RECONCILIATION_ROUTE,
    POST_WRITE_RECONCILIATION_SOURCE,
)
from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthPostWriteReconciliationBoundaryEvidence,
)


POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE: tuple[str, ...] = (
    "route_bound_reconciliation_plan",
    "post_write_execution_journal",
    "post_write_completion_proof",
)


def build_stealth_post_write_reconciliation_boundary(
    *,
    mutation_family: AdminApiMutationFamilyType,
    command_route: str,
    service_method: str,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
) -> StealthPostWriteReconciliationBoundaryEvidence:
    """Build fail-closed post-write reconciliation boundary evidence."""

    exact_context_present = admission_decision is not None
    return StealthPostWriteReconciliationBoundaryEvidence(
        mutation_family=mutation_family,
        command_route=command_route,
        service_method=service_method,
        stealth_order_id=stealth_order_id,
        command_context_bound=exact_context_present,
        payload_bound=exact_context_present,
        idempotency_bound=exact_context_present,
        operator_intent_bound=exact_context_present,
        idempotency_key=(
            admission_decision.idempotency_key
            if admission_decision is not None
            else None
        ),
        payload_hash=(
            admission_decision.payload_hash
            if admission_decision is not None
            else None
        ),
        operator_intent=(
            admission_decision.operator_intent
            if admission_decision is not None
            else None
        ),
        post_write_reconciliation_route=POST_WRITE_RECONCILIATION_ROUTE,
        post_write_reconciliation_method=POST_WRITE_RECONCILIATION_METHOD,
        post_write_reconciliation_source=POST_WRITE_RECONCILIATION_SOURCE,
        post_write_reconciliation_missing_reason=(
            "post_write_reconciliation_missing"
        ),
        required_evidence=list(POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE),
        missing_evidence=list(POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE),
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Post-write reconciliation remains a backend-owned route-bound requirement.",
            "The boundary names the reconciliation-plan writer but does not record a plan.",
            "The boundary does not execute reconciliation or mutate order, lifecycle, or exchange state.",
            "Browser and BFF layers may display the boundary but cannot satisfy it.",
        ],
        detail=(
            f"{command_route} must be followed by a backend-owned "
            f"{POST_WRITE_RECONCILIATION_METHOD} "
            f"{POST_WRITE_RECONCILIATION_ROUTE} plan and completion proof before "
            "a future stealth write can be considered complete. This evidence "
            "does not run that plan, execute reconciliation, call Coinbase, or "
            "mutate local state."
        ),
    )
